from __future__ import annotations
import csv
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline import EvidenceRecord, UserIdentity

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "dataset"
_CACHE_DIR = _REPO_ROOT / ".evidence_cache"

# ─── Table → (system_id, data_category) ────────────────────────────────────
_TABLE_META = {
    "customer_profiles": ("account_service", "USER_PROFILE"),
    "customer_profiles_primary": ("account_service", "USER_PROFILE"),
    "customer_profiles_failover_replica": ("account_service", "USER_PROFILE"),
    "customer_data_primary": ("account_service", "USER_PROFILE"),
    "customer_data_failover_replica": ("account_service", "USER_PROFILE"),
    "customer_data_read_replica": ("account_service", "USER_PROFILE"),
    "customer_data_replica_ap_south": ("account_service", "USER_PROFILE"),
    "customer_data_replica_eu_west": ("account_service", "USER_PROFILE"),
    "customer_data_reporting_replica": ("account_service", "USER_PROFILE"),
    "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
    "search_documents_primary": ("search_service", "SEARCH_INDEX_ENTRY"),
    "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
    "support_records": ("support_platform", "SUPPORT_MESSAGE"),
    "support_conversations": ("support_platform", "SUPPORT_MESSAGE"),
    "customer_exports": ("export_service", "USER_EXPORT"),
    "connector_subscriptions": ("integration_service", "DATA_FLOW"),
    "connector_configurations": ("integration_service", "DATA_FLOW"),
    "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
    "backup_catalog": ("backup_service", "BACKUP_ARCHIVE"),
    "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
    "security_audit_events": ("security_service", "SECURITY_AUDIT_LOG"),
    "deleted_customer_references": ("identity_service", "ACCOUNT_TOMBSTONE"),
}

# Replica tables (for ghost detection)
_REPLICA_TABLES = {
    "customer_profiles_failover_replica",
    "customer_data_failover_replica",
    "customer_data_read_replica",
    "customer_data_replica_ap_south",
    "customer_data_replica_eu_west",
    "customer_data_reporting_replica",
}
_PRIMARY_TABLES = {
    "customer_profiles_primary",
    "customer_data_primary",
    "customer_profiles",  # treat as primary when no explicit primary exists
}

# txt STATUS → state
_TXT_STATUS_MAP = {
    "NOT_FOUND": "ABSENT",
    "FOUND": "PRESENT",
    "IDENTIFIABLE": "PRESENT",
    "ACTIVE": "ACTIVE",
    "DISABLED": "DISABLED",
    "BLOCKED": "BLOCKED",
    "REDACTED": "REDACTED",
    "ANONYMIZED": "ANONYMIZED",
}

# PII fields for analytics/tombstone
_PII_FIELDS = {"email", "phone", "email_hash", "customer_reference", "user_id",
               "name", "full_name", "requester_email", "requester_phone"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_kv(line: str) -> dict:
    """Parse key=value pairs from a log line."""
    result = {}
    for m in re.finditer(r'(\w+)=(?:"([^"]*)"|(\S+))', line):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        result[key] = val
    return result


def _matches_identity(fields: dict, identity: UserIdentity) -> bool:
    """Check if any identifier in fields belongs to identity."""
    emails_lower = identity.all_emails  # already lowercase
    uid = identity.user_id
    ehash = identity.email_hash

    # Check email fields
    email_field_names = {
        "email", "owner_email", "requester_email", "customer_email",
        "lookup_key", "matched_value", "lookup_email",
    }
    for fn in email_field_names:
        v = fields.get(fn)
        if v and str(v).lower() in emails_lower:
            return True

    # Check user_id / customer_reference / subject_reference
    for fn in ("customer_reference", "user_id", "subject_reference"):
        v = fields.get(fn)
        if v and str(v).strip() == uid:
            return True

    # Check email_hash
    if ehash:
        for fn in ("email_hash",):
            v = fields.get(fn)
            if v and str(v).strip() == ehash:
                return True

    # Check phone
    for p in identity.all_phones:
        if not p:
            continue
        for fn in ("phone", "requester_phone"):
            v = fields.get(fn)
            if v and str(v).strip() == p:
                return True

    return False


def _state_analytics(row: dict) -> str:
    """PRESENT if any PII non-null, else ANONYMIZED."""
    pii = ("email", "phone", "email_hash", "customer_reference", "user_id")
    for f in pii:
        v = row.get(f)
        if v is not None and str(v).strip() not in ("", "null", "None"):
            return "PRESENT"
    return "ANONYMIZED"


def _state_support(row: dict) -> str:
    """PRESENT if requester_email or requester_phone non-null, else REDACTED."""
    for f in ("requester_email", "requester_phone"):
        v = row.get(f)
        if v is not None and str(v).strip() not in ("", "null", "None"):
            return "PRESENT"
    return "REDACTED"


def _state_tombstone(row: dict) -> str:
    """PRESENT (PII exposed) if name/email/phone/email_hash non-null, else REDACTED."""
    for f in ("name", "email", "phone", "email_hash", "full_name"):
        v = row.get(f)
        if v is not None and str(v).strip() not in ("", "null", "None"):
            return "PRESENT"
    return "REDACTED"


def _state_dataflow(row: dict) -> str:
    v = row.get("enabled")
    if v is None:
        return "UNKNOWN"
    if isinstance(v, bool):
        return "ACTIVE" if v else "DISABLED"
    if str(v).lower() in ("true", "1", "yes"):
        return "ACTIVE"
    return "DISABLED"


def _state_backup(row: dict) -> str:
    v = row.get("restore_allowed")
    if v is None:
        return "UNKNOWN"
    if isinstance(v, bool):
        return "ACTIVE" if v else "BLOCKED"
    if str(v).lower() in ("true", "1", "yes"):
        return "ACTIVE"
    return "BLOCKED"


# ─── Parsers ─────────────────────────────────────────────────────────────────

# Collection name → (system_id, data_category)
_COLLECTION_META = {
    "customer_profiles": ("account_service", "USER_PROFILE"),
    "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
    "customer_analytics_reports": ("analytics_platform", "ANALYTICS_PROFILE"),
    "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
    "support_records": ("support_platform", "SUPPORT_MESSAGE"),
    "support_conversations": ("support_platform", "SUPPORT_MESSAGE"),
    "customer_exports": ("export_service", "USER_EXPORT"),
    "connector_subscriptions": ("integration_service", "DATA_FLOW"),
    "connector_configurations": ("integration_service", "DATA_FLOW"),
    "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
    "backup_catalog": ("backup_service", "BACKUP_ARCHIVE"),
    "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
    "security_audit_events": ("security_service", "SECURITY_AUDIT_LOG"),
    "deleted_customer_references": ("identity_service", "ACCOUNT_TOMBSTONE"),
}


def _determine_state(row_dict: dict, data_category: str, is_ghost: bool = False) -> str:
    if is_ghost:
        return "PRESENT"
    if data_category == "USER_PROFILE":
        return "PRESENT"
    elif data_category in ("ANALYTICS_PROFILE",):
        return _state_analytics(row_dict)
    elif data_category == "SUPPORT_MESSAGE":
        return _state_support(row_dict)
    elif data_category == "SUPPORT_ATTACHMENT":
        return "PRESENT"
    elif data_category == "DATA_FLOW":
        return _state_dataflow(row_dict)
    elif data_category == "BACKUP_ARCHIVE":
        return _state_backup(row_dict)
    elif data_category == "SECURITY_AUDIT_LOG":
        return "PRESENT"
    elif data_category == "ACCOUNT_TOMBSTONE":
        return _state_tombstone(row_dict)
    elif data_category == "SEARCH_INDEX_ENTRY":
        return "PRESENT"
    elif data_category == "USER_EXPORT":
        return "PRESENT"
    else:
        return "PRESENT"


def _parse_sql(file_path: Path, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    records = []
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.executescript(content)
    except Exception:
        con.close()
        return records

    try:
        cursor = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
    except Exception:
        con.close()
        return records

    # Detect which tables have record_json column
    def _has_record_json(table: str) -> bool:
        try:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info([{table}])")]
            return "record_json" in cols
        except Exception:
            return False

    # Detect replica tables in this file for ghost detection
    replica_tables_in_file = [t for t in tables if t in _REPLICA_TABLES]
    primary_tables_in_file = [t for t in tables if t in _PRIMARY_TABLES]

    # For record_json tables, ghost detection is per (collection_name, resource_id)
    # Build: primary table's (collection_name, resource_id) set
    primary_collection_rids: set[tuple] = set()
    primary_direct_rids: set[str] = set()
    for pt in primary_tables_in_file:
        try:
            if _has_record_json(pt):
                rows = con.execute(f"SELECT resource_id, collection_name FROM [{pt}]").fetchall()
                for r in rows:
                    primary_collection_rids.add((str(r[1]), str(r[0])))
            else:
                rows = con.execute(f"SELECT resource_id FROM [{pt}]").fetchall()
                for r in rows:
                    primary_direct_rids.add(str(r[0]))
        except Exception:
            pass

    for table in tables:
        try:
            cur3 = con.execute(f"SELECT * FROM [{table}]")
            rows = cur3.fetchall()
        except Exception:
            continue

        if _has_record_json(table):
            # Parse via record_json + collection_name + origin_system
            is_replica_table = table in _REPLICA_TABLES

            for row in rows:
                row_dict = dict(row)
                rid = str(row_dict.get("resource_id", "")).strip()
                collection = str(row_dict.get("collection_name", "")).strip()
                origin_system = str(row_dict.get("origin_system", "")).strip()

                if not rid:
                    continue

                # Parse embedded JSON
                rj_raw = row_dict.get("record_json", "{}")
                try:
                    rj = json.loads(rj_raw) if isinstance(rj_raw, str) else (rj_raw or {})
                except Exception:
                    rj = {}

                # Determine system_id and data_category
                meta = _COLLECTION_META.get(collection)
                if meta:
                    system_id, data_category = meta
                else:
                    system_id = origin_system or "unknown_service"
                    data_category = collection or "UNKNOWN"

                # Ghost detection for record_json tables
                is_ghost = (is_replica_table and
                            primary_tables_in_file and
                            (collection, rid) not in primary_collection_rids)

                state = _determine_state(rj, data_category, is_ghost)

                merged = {**row_dict, **rj, "ghost": is_ghost}
                merged["_identifiers"] = _extract_identifiers(merged)

                records.append(EvidenceRecord(
                    file_id=file_id,
                    resource_id=rid,
                    system_id=system_id,
                    state=state,
                    data_category=data_category,
                    captured_at=captured_at,
                    raw_fields=merged,
                ))
        else:
            meta = _TABLE_META.get(table)
            if not meta:
                continue
            system_id, data_category = meta

            for row in rows:
                row_dict = dict(row)
                rid = str(row_dict.get("resource_id", "")).strip()
                if not rid:
                    continue

                is_ghost = (table in _REPLICA_TABLES and
                            primary_tables_in_file and
                            rid not in primary_direct_rids)

                state = _determine_state(row_dict, data_category, is_ghost)
                row_dict["ghost"] = is_ghost
                row_dict["_identifiers"] = _extract_identifiers(row_dict)

                records.append(EvidenceRecord(
                    file_id=file_id,
                    resource_id=rid,
                    system_id=system_id,
                    state=state,
                    data_category=data_category,
                    captured_at=captured_at,
                    raw_fields=row_dict,
                ))

    con.close()
    return records


_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_USER_RE = re.compile(r'^user_\d+$')
_HASH_RE = re.compile(r'^[0-9a-f]{40,}$')

_JSON_EXTRACT_RE = re.compile(r'\{.*\}')
# bracket format: TIMESTAMP [LEVEL] [service] [trace_id] event_name: key=val ...
_BRACKET_LOG_RE = re.compile(r'^\S+\s+\[\w+\]\s+\[[\w\-]+\]\s+\[([^\]]*)\]\s+([\w]+):\s*(.*)')
# ISO-8601 timestamp at start of log line
_LINE_TS_RE = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?(?:[+-]\d{2}:\d{2})?)')


def _parse_line_to_kv(line: str) -> dict:
    """Multi-format log line parser returning kv dict with at least 'event' when parseable."""
    # Format A: standard key=value  (resource_lookup_trace style)
    kv = _parse_kv(line)
    if kv.get("event"):
        return kv

    # Format C: TIMESTAMP {JSON} (structured_service_events style)
    m = _JSON_EXTRACT_RE.search(line)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict) and parsed.get("event"):
                return {k: str(v) if not isinstance(v, str) else v for k, v in parsed.items()}
        except Exception:
            pass

    # Format B: TIMESTAMP [LEVEL] [service] [trace_id] event_name: key="val" ...
    m2 = _BRACKET_LOG_RE.match(line)
    if m2:
        trace, event, rest = m2.groups()
        inner = _parse_kv(rest)
        inner["event"] = event
        inner.setdefault("trace_id", trace)
        return inner

    # Format D: TIMESTAMP requestId=X ... message="escaped_kv..."
    if kv.get("message"):
        msg = kv["message"].replace('\\"', '"').replace('\\n', ' ')
        inner = _parse_kv(msg)
        if inner.get("event"):
            req_id = kv.get("requestId", "")
            inner.setdefault("trace_id", req_id)
            return inner

    return kv


def _extract_identifiers(row: dict) -> list[str]:
    """Extract email-like, user_id-like, and hash-like values from a row."""
    ids = []
    hash_fields = {"email_hash", "correlation_key"}
    for k, v in row.items():
        if not v or not isinstance(v, str):
            continue
        v = v.strip()
        if _EMAIL_RE.match(v):
            ids.append(v.lower())
        elif _USER_RE.match(v):
            ids.append(v)
        elif k in hash_fields and _HASH_RE.match(v):
            ids.append(v)
    return ids


def _parse_json(file_path: Path, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    records = []
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return records

    if not isinstance(data, dict):
        return records

    fname = file_path.stem

    # service_resource_export_* format
    if "service_exports" in data:
        records.extend(_parse_service_resource_export(data, file_id, captured_at))

    # customer_data_snapshot_bundle_* format
    elif "snapshots" in data:
        records.extend(_parse_snapshot_bundle(data, file_id, captured_at))

    # collection/records format (analytics_report, export_jobs, etc.)
    elif "collection" in data and "records" in data:
        records.extend(_parse_collection_records(data, file_id, captured_at, fname))

    # Generic records with system/result fields (connector_configurations, security_audit_ledger, export_manifest)
    elif "records" in data:
        records.extend(_parse_generic_records(data["records"], file_id, captured_at))

    return records


def _parse_service_resource_export(data: dict, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    records = []
    service_exports = data.get("service_exports", {})

    svc_meta = {
        "account_service": ("account_service", "USER_PROFILE"),
        "analytics_platform": ("analytics_platform", "ANALYTICS_PROFILE"),
        "backup_service": ("backup_service", "BACKUP_ARCHIVE"),
        "export_service": ("export_service", "USER_EXPORT"),
        "integration_service": ("integration_service", "DATA_FLOW"),
        "search_service": ("search_service", "SEARCH_INDEX_ENTRY"),
        "security_service": ("security_service", "SECURITY_AUDIT_LOG"),
        "support_platform": ("support_platform", "SUPPORT_MESSAGE"),
    }

    for svc, svc_data in service_exports.items():
        meta = svc_meta.get(svc)
        if not meta or not isinstance(svc_data, dict):
            continue
        system_id, data_category = meta

        for key, items in svc_data.items():
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                rid = str(item.get("resource_id", "")).strip()

                # search: hits->documents
                if svc == "search_service" and "hits" in item:
                    hits = item.get("hits", {})
                    docs = hits.get("documents", []) if isinstance(hits, dict) else []
                    if docs:
                        for doc in docs:
                            doc_rid = str(doc.get("resource_id", rid)).strip()
                            if not doc_rid:
                                continue
                            pii = any(
                                doc.get(f) is not None and str(doc.get(f)).strip() not in ("", "null")
                                for f in ("email", "phone", "email_hash", "display_name")
                            )
                            state = "PRESENT" if pii else "ABSENT"
                            doc["_identifiers"] = _extract_identifiers(doc)
                            records.append(EvidenceRecord(
                                file_id=file_id,
                                resource_id=doc_rid,
                                system_id=system_id,
                                state=state,
                                data_category=data_category,
                                captured_at=captured_at,
                                raw_fields=dict(doc),
                            ))
                    else:
                        # No documents = absent
                        if rid:
                            item["_identifiers"] = _extract_identifiers(item)
                            records.append(EvidenceRecord(
                                file_id=file_id, resource_id=rid,
                                system_id=system_id, state="ABSENT",
                                data_category=data_category, captured_at=captured_at,
                                raw_fields=dict(item),
                            ))
                    continue

                if not rid:
                    continue

                # Determine state
                if svc == "account_service":
                    sc = item.get("status_code")
                    state = "ABSENT" if sc == 404 else "PRESENT"
                elif svc == "analytics_platform":
                    state = _state_analytics(item)
                elif svc == "backup_service":
                    state = _state_backup(item)
                elif svc == "export_service":
                    pii = any(
                        item.get(f) is not None and str(item.get(f)).strip() not in ("", "null")
                        for f in ("owner_email", "owner_phone", "customer_reference")
                    )
                    state = "PRESENT" if pii else "ABSENT"
                elif svc == "integration_service":
                    state = _state_dataflow(item)
                elif svc == "security_service":
                    state = "PRESENT"
                elif svc == "support_platform":
                    state = _state_support(item)
                else:
                    state = "PRESENT"

                item["_identifiers"] = _extract_identifiers(item)
                records.append(EvidenceRecord(
                    file_id=file_id, resource_id=rid,
                    system_id=system_id, state=state,
                    data_category=data_category, captured_at=captured_at,
                    raw_fields=dict(item),
                ))

    return records


def _parse_snapshot_bundle(data: dict, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    records = []
    snapshots = data.get("snapshots", [])

    collection_meta = {
        "customer_profiles": ("account_service", "USER_PROFILE"),
        "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
        "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
        "customer_analytics_reports": ("analytics_platform", "ANALYTICS_PROFILE"),
        "support_records": ("support_platform", "SUPPORT_MESSAGE"),
        "customer_exports": ("export_service", "USER_EXPORT"),
        "connector_subscriptions": ("integration_service", "DATA_FLOW"),
        "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
        "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
        "security_audit_events": ("security_service", "SECURITY_AUDIT_LOG"),
        "deleted_customer_references": ("identity_service", "ACCOUNT_TOMBSTONE"),
    }

    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        collection = snap.get("collection", "")
        data_store = snap.get("data_store", "")
        meta = collection_meta.get(collection) or collection_meta.get(data_store)
        snap_records = snap.get("records", [])
        if not isinstance(snap_records, list):
            continue

        if not meta:
            # Try to infer from data_store
            if "account" in data_store:
                meta = ("account_service", "USER_PROFILE")
            elif "identity" in data_store:
                meta = ("identity_service", "ACCOUNT_TOMBSTONE")
            elif "security" in data_store:
                meta = ("security_service", "SECURITY_AUDIT_LOG")
            else:
                continue

        system_id, data_category = meta

        for item in snap_records:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("resource_id", "")).strip()
            if not rid:
                continue

            if data_category == "USER_PROFILE":
                state = "PRESENT"
            elif data_category == "ANALYTICS_PROFILE":
                state = _state_analytics(item)
            elif data_category == "SUPPORT_MESSAGE":
                state = _state_support(item)
            elif data_category == "DATA_FLOW":
                state = _state_dataflow(item)
            elif data_category == "BACKUP_ARCHIVE":
                state = _state_backup(item)
            elif data_category == "SECURITY_AUDIT_LOG":
                state = "PRESENT"
            elif data_category == "ACCOUNT_TOMBSTONE":
                state = _state_tombstone(item)
            else:
                state = "PRESENT"

            item["_identifiers"] = _extract_identifiers(item)
            records.append(EvidenceRecord(
                file_id=file_id, resource_id=rid,
                system_id=system_id, state=state,
                data_category=data_category, captured_at=captured_at,
                raw_fields=dict(item),
            ))

    return records


def _parse_collection_records(data: dict, file_id: str, captured_at: datetime, fname: str) -> list[EvidenceRecord]:
    records = []
    collection = data.get("collection", fname)
    items = data.get("records", [])

    coll_meta = {
        "customer_analytics_reports": ("analytics_platform", "ANALYTICS_PROFILE"),
        "user_export_jobs": ("export_service", "USER_EXPORT"),
        "export_jobs": ("export_service", "USER_EXPORT"),
    }
    meta = coll_meta.get(collection)
    if not meta:
        if "analytics" in collection.lower():
            meta = ("analytics_platform", "ANALYTICS_PROFILE")
        elif "export" in collection.lower():
            meta = ("export_service", "USER_EXPORT")
        else:
            meta = ("account_service", "USER_PROFILE")

    system_id, data_category = meta

    for item in items:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("resource_id", "")).strip()
        if not rid:
            continue

        if data_category == "ANALYTICS_PROFILE":
            state = _state_analytics(item)
        elif data_category == "USER_EXPORT":
            pii = any(
                item.get(f) is not None and str(item.get(f)).strip() not in ("", "null")
                for f in ("owner_email", "owner_phone", "customer_reference")
            )
            state = "PRESENT" if pii else "ABSENT"
        else:
            state = "PRESENT"

        item["_identifiers"] = _extract_identifiers(item)
        records.append(EvidenceRecord(
            file_id=file_id, resource_id=rid,
            system_id=system_id, state=state,
            data_category=data_category, captured_at=captured_at,
            raw_fields=dict(item),
        ))

    return records


def _parse_generic_records(items: list, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    """Parse result-log format: {system, resource_id, record_type, result, subject_reference}"""
    records = []

    type_meta = {
        "USER_PROFILE": ("account_service", "USER_PROFILE"),
        "SEARCH_INDEX_ENTRY": ("search_service", "SEARCH_INDEX_ENTRY"),
        "ANALYTICS_PROFILE": ("analytics_platform", "ANALYTICS_PROFILE"),
        "SUPPORT_MESSAGE": ("support_platform", "SUPPORT_MESSAGE"),
        "USER_EXPORT": ("export_service", "USER_EXPORT"),
        "DATA_FLOW": ("integration_service", "DATA_FLOW"),
        "BACKUP_ARCHIVE": ("backup_service", "BACKUP_ARCHIVE"),
        "SECURITY_AUDIT_LOG": ("security_service", "SECURITY_AUDIT_LOG"),
        "ACCOUNT_TOMBSTONE": ("identity_service", "ACCOUNT_TOMBSTONE"),
    }

    result_state = {
        "NOT_FOUND": "ABSENT",
        "FOUND": "PRESENT",
        "ANONYMIZED": "ANONYMIZED",
        "REDACTED": "REDACTED",
        "ACTIVE": "ACTIVE",
        "DISABLED": "DISABLED",
        "BLOCKED": "BLOCKED",
    }

    for item in items:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("resource_id", "")).strip()
        if not rid:
            continue

        record_type = str(item.get("record_type", "USER_PROFILE")).strip()
        system = str(item.get("system", "account_service")).strip()
        meta = type_meta.get(record_type, (system, record_type))
        system_id, data_category = meta

        result = str(item.get("result", "FOUND")).strip().upper()
        state = result_state.get(result, "PRESENT")

        item["_identifiers"] = _extract_identifiers(item)
        records.append(EvidenceRecord(
            file_id=file_id, resource_id=rid,
            system_id=system_id, state=state,
            data_category=data_category, captured_at=captured_at,
            raw_fields=dict(item),
        ))

    return records


def _parse_log(file_path: Path, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    records = []

    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return records

    # Pass 1: collect trace context and deletion markers
    trace_context: dict[str, dict] = {}   # trace_id → {email, user_id}
    deletion_marker_rids: set[str] = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        kv = _parse_line_to_kv(line)
        tid = kv.get("trace_id", "")
        event = kv.get("event", "")

        # Collect identity from started/query events
        if tid:
            ctx = trace_context.setdefault(tid, {})
            for field in ("subject_key", "lookup_key", "subject_ref", "correlation_key",
                          "match_key", "lookup_email"):
                val = kv.get(field, "")
                if not val or val in ("null", "None"):
                    continue
                if "@" in val:
                    ctx.setdefault("email", val.lower())
                elif re.match(r"user_\d+$", val):
                    ctx.setdefault("user_id", val)

        # Track deletion marker absences
        if event == "deletion_marker_check" and kv.get("marker_found") == "false":
            rid = kv.get("resource_id", "").strip()
            if rid:
                deletion_marker_rids.add(rid)

    # Pass 2: emit records for result events
    event_meta = {
        "profile_lookup_completed": ("account_service", "USER_PROFILE"),
        "index_query_completed": ("search_service", "SEARCH_INDEX_ENTRY"),
        "analytics_profile_read_completed": ("analytics_platform", "ANALYTICS_PROFILE"),
        "analytics_identity_scan": ("analytics_platform", "ANALYTICS_PROFILE"),
        "contact_lookup_completed": ("analytics_platform", "ANALYTICS_PROFILE"),
        "connector_config_read_completed": ("integration_service", "DATA_FLOW"),
        "connector_heartbeat": ("integration_service", "DATA_FLOW"),
        "restore_policy_read_completed": ("backup_service", "BACKUP_ARCHIVE"),
        "restore_candidate_evaluated": ("backup_service", "BACKUP_ARCHIVE"),
        "support_ticket_read_completed": ("support_platform", "SUPPORT_MESSAGE"),
        "contact_query_completed": ("support_platform", "SUPPORT_ATTACHMENT"),
        "audit_record_read_completed": ("security_service", "SECURITY_AUDIT_LOG"),
        "tombstone_read_completed": ("identity_service", "ACCOUNT_TOMBSTONE"),
        "export_lookup_completed": ("export_service", "USER_EXPORT"),
    }

    for line in lines:
        line = line.strip()
        if not line:
            continue

        kv = _parse_line_to_kv(line)
        event = kv.get("event", "")
        meta = event_meta.get(event)
        if not meta:
            continue

        system_id, data_category = meta
        rid = kv.get("resource_id", "").strip()
        if not rid:
            continue

        # Use per-event timestamp if available (more precise than file-level captured_at)
        line_captured_at = captured_at
        ts_match = _LINE_TS_RE.match(line)
        if ts_match:
            try:
                ts_str = ts_match.group(1)
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                line_captured_at = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Merge trace context into kv for identity matching
        tid = kv.get("trace_id", "")
        ctx = trace_context.get(tid, {})
        if ctx.get("email") and "email" not in kv:
            kv["email"] = ctx["email"]
        if ctx.get("user_id") and "customer_reference" not in kv:
            kv["customer_reference"] = ctx["user_id"]
            kv["subject_reference"] = ctx["user_id"]

        # Determine state
        if event == "profile_lookup_completed":
            row_count = kv.get("rows", "0")
            http = kv.get("http_status", "")
            state = "ABSENT" if row_count == "0" or http == "404" else "PRESENT"

        elif event == "index_query_completed":
            result = kv.get("result", "miss")
            state = "PRESENT" if result == "hit" else "ABSENT"

        elif event in ("analytics_profile_read_completed", "analytics_identity_scan"):
            state = _state_analytics(kv)

        elif event == "contact_lookup_completed":
            row_count = kv.get("rows", "0")
            state = "ABSENT" if row_count == "0" else "PRESENT"
            # correlation_key is an email hash → mark as email_hash for PII detection
            ck = kv.get("correlation_key", "")
            if ck and len(ck) >= 40 and state == "PRESENT":
                kv["email_hash"] = ck

        elif event in ("connector_config_read_completed", "connector_heartbeat"):
            state = _state_dataflow(kv)

        elif event in ("restore_policy_read_completed",):
            state = _state_backup(kv)

        elif event == "restore_candidate_evaluated":
            eligible = kv.get("eligible", "false")
            deletion_block = kv.get("deletion_block", "true")
            state = "ACTIVE" if (eligible == "true" and deletion_block == "false") else "BLOCKED"

        elif event == "support_ticket_read_completed":
            state = _state_support(kv)
            cr = kv.get("customer_reference", "null")
            if cr == "null":
                kv["customer_reference"] = None

        elif event == "contact_query_completed":
            row_count = kv.get("rows", "0")
            if row_count == "0":
                state = "ABSENT"
            else:
                # If deletion marker is absent, it's an attachment that needs DELETE
                state = "PRESENT"
            # Override data_category based on deletion_marker
            if rid in deletion_marker_rids:
                data_category = "SUPPORT_ATTACHMENT"
            else:
                # May be SUPPORT_MESSAGE if PII fields are present
                data_category = "SUPPORT_ATTACHMENT"  # default for contact_query

        elif event == "audit_record_read_completed":
            row_count = kv.get("rows", "0")
            state = "ABSENT" if row_count == "0" else "PRESENT"

        elif event == "tombstone_read_completed":
            state = _state_tombstone(kv)

        elif event == "export_lookup_completed":
            row_count = kv.get("rows", "0")
            state = "ABSENT" if row_count == "0" else "PRESENT"

        else:
            continue

        kv["_identifiers"] = _extract_identifiers(kv)

        records.append(EvidenceRecord(
            file_id=file_id, resource_id=rid,
            system_id=system_id, state=state,
            data_category=data_category, captured_at=line_captured_at,
            raw_fields=dict(kv),
        ))

    return records


def _parse_txt(file_path: Path, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    records = []
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return records

    for line in lines:
        line = line.strip()
        if not line.startswith("-"):
            continue
        parts = [p.strip() for p in line.lstrip("- ").split(" | ")]
        if len(parts) < 5:
            continue
        # Format: timestamp | system_id | resource_id | data_category | STATUS | identifier
        system_id = parts[1]
        resource_id = parts[2]
        data_category = parts[3]
        status = parts[4].upper()
        identifier = parts[5] if len(parts) > 5 else ""

        state = _TXT_STATUS_MAP.get(status, "PRESENT")
        raw = {
            "system_id": system_id,
            "resource_id": resource_id,
            "data_category": data_category,
            "status": status,
            "identifier": identifier,
        }
        # Normalize identifier into searchable fields
        if "@" in identifier:
            raw["email"] = identifier.lower()
        elif re.match(r"user_\d+", identifier):
            raw["customer_reference"] = identifier
            raw["subject_reference"] = identifier
        raw["_identifiers"] = _extract_identifiers(raw)

        records.append(EvidenceRecord(
            file_id=file_id, resource_id=resource_id,
            system_id=system_id, state=state,
            data_category=data_category, captured_at=captured_at,
            raw_fields=raw,
        ))

    return records


def _parse_pdf(file_path: Path, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    # Try pypdf first (deterministic, no API key needed)
    text = ""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(file_path))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        pass
    # Fall back to LLM if pypdf gave nothing
    if not text.strip():
        try:
            from pipeline.llm_client import extract_pdf
            text = extract_pdf(str(file_path))
        except Exception:
            return []
    return _parse_extracted_text(text, file_id, captured_at, str(file_path))


def _parse_image(file_path: Path, file_id: str, captured_at: datetime) -> list[EvidenceRecord]:
    try:
        from pipeline.llm_client import extract_image
        text = extract_image(str(file_path))
    except Exception:
        return []
    return _parse_extracted_text(text, file_id, captured_at, str(file_path))


def _parse_extracted_text(text: str, file_id: str, captured_at: datetime, file_path: str = "") -> list[EvidenceRecord]:
    """Parse LLM-extracted text for resource IDs and state."""
    records = []
    _is_attachment = "attachment" in Path(file_path).stem.lower() if file_path else False
    # Look for resource_id patterns
    rid_re = re.compile(
        r'\b(account_\w+|search_\w+|analytics_\w+|support_\w+|export_\w+|backup_\w+|'
        r'data_flow_\w+|audit_record_\w+|tombstone_\w+|object_\w+|marketing_\w+)\b'
    )
    email_re = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    user_re = re.compile(r'\buser_\d+\b')

    emails = set(m.lower() for m in email_re.findall(text))
    users = set(user_re.findall(text))
    resource_ids = set(rid_re.findall(text))

    for rid in resource_ids:
        # Determine system from resource_id prefix
        prefix_meta = {
            "account_": ("account_service", "USER_PROFILE"),
            "search_": ("search_service", "SEARCH_INDEX_ENTRY"),
            "analytics_": ("analytics_platform", "ANALYTICS_PROFILE"),
            "support_": ("support_platform", "SUPPORT_ATTACHMENT" if _is_attachment else "SUPPORT_MESSAGE"),
            "export_": ("export_service", "USER_EXPORT"),
            "backup_": ("backup_service", "BACKUP_ARCHIVE"),
            "data_flow_": ("integration_service", "DATA_FLOW"),
            "audit_record_": ("security_service", "SECURITY_AUDIT_LOG"),
            "tombstone_": ("identity_service", "ACCOUNT_TOMBSTONE"),
            "marketing_": ("marketing_service", "MARKETING_PROFILE"),
            "object_": ("support_platform", "SUPPORT_ATTACHMENT"),
        }
        meta = None
        for prefix, m in prefix_meta.items():
            if rid.startswith(prefix):
                meta = m
                break
        if not meta:
            continue

        system_id, data_category = meta
        raw = {
            "resource_id": rid,
            "extracted_text": text[:500],
        }
        for e in emails:
            raw["email"] = e
        for u in users:
            raw["customer_reference"] = u
            raw["subject_reference"] = u
        raw["_identifiers"] = list(emails) + list(users)

        records.append(EvidenceRecord(
            file_id=file_id, resource_id=rid,
            system_id=system_id, state="PRESENT",
            data_category=data_category, captured_at=captured_at,
            raw_fields=raw,
        ))

    return records


# ─── Main Indexer ─────────────────────────────────────────────────────────────

class EvidenceIndexer:
    def __init__(self) -> None:
        self._all_records: list[EvidenceRecord] = []
        self._by_resource_id: dict[str, list[EvidenceRecord]] = {}
        # user_id → account_id, from snapshot bundle customer_reference (any timestamp)
        self._account_by_uid: dict[str, str] = {}
        # email (lowercase) → account_id, from SQL search table source_resource_id
        self._account_by_email: dict[str, str] = {}
        # file_id → (captured_at, {user_id: resource_id}), for fallback citation only
        self._account_sql_uid_maps: dict[str, tuple] = {}
        # file_id → file-level captured_at (from evidence_files.csv)
        self._file_captured_at: dict[str, datetime] = {}
        self._built = False

    def build(self, evidence_files_manifest: list[dict]) -> None:
        _CACHE_DIR.mkdir(exist_ok=True)
        all_records = []

        for entry in evidence_files_manifest:
            file_id = entry["file_id"]
            file_path = _DATASET / entry["file_path"]
            captured_at_str = entry.get("captured_at", "")
            try:
                captured_at = datetime.fromisoformat(
                    captured_at_str.replace("Z", "+00:00")
                ).replace(tzinfo=timezone.utc)
            except Exception:
                captured_at = datetime.min.replace(tzinfo=timezone.utc)

            if not file_path.exists():
                continue

            self._file_captured_at[file_id] = captured_at

            # Check disk cache
            file_sha = _sha256_file(file_path)
            cache_path = _CACHE_DIR / f"{file_id}_{file_sha[:8]}.json"
            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    for r in cached:
                        all_records.append(_record_from_dict(r, captured_at))
                    continue
                except Exception:
                    pass

            # Parse file
            ext = file_path.suffix.lower()
            if ext == ".sql":
                recs = _parse_sql(file_path, file_id, captured_at)
            elif ext == ".json":
                recs = _parse_json(file_path, file_id, captured_at)
            elif ext == ".log":
                recs = _parse_log(file_path, file_id, captured_at)
            elif ext == ".txt":
                recs = _parse_txt(file_path, file_id, captured_at)
            elif ext == ".pdf":
                recs = _parse_pdf(file_path, file_id, captured_at)
            elif ext in (".png", ".jpg", ".jpeg"):
                recs = _parse_image(file_path, file_id, captured_at)
            else:
                recs = []

            # Write cache
            try:
                cache_path.write_text(
                    json.dumps([_record_to_dict(r) for r in recs]),
                    encoding="utf-8"
                )
            except Exception:
                pass

            all_records.extend(recs)

        self._all_records = all_records

        # Index by resource_id
        idx: dict[str, list[EvidenceRecord]] = {}
        for r in all_records:
            idx.setdefault(r.resource_id, []).append(r)
        self._by_resource_id = idx

        # Build account lookup tables
        account_by_uid: dict[str, str] = {}
        account_by_email: dict[str, str] = {}
        uid_maps: dict[str, tuple] = {}

        for r in all_records:
            if r.system_id == "account_service":
                rid = r.resource_id
                if not rid:
                    continue
                # customer_reference links user_id → account_id (snapshot bundles, any time)
                cr = r.raw_fields.get("customer_reference", "")
                if cr and re.match(r"user_\d+$", str(cr)):
                    account_by_uid.setdefault(str(cr), rid)
                # user_id column (SQL tables) — also keep for citation map
                uid = r.raw_fields.get("user_id", "")
                if uid:
                    account_by_uid.setdefault(str(uid), rid)
                    fid = r.file_id
                    if fid not in uid_maps:
                        uid_maps[fid] = (r.captured_at, {})
                    uid_maps[fid][1][uid] = rid

            if r.system_id == "search_service":
                src = str(r.raw_fields.get("source_resource_id", "")).strip()
                if src.startswith("account_"):
                    for eid in r.raw_fields.get("_identifiers", []):
                        if "@" in str(eid):
                            account_by_email.setdefault(str(eid).lower(), src)

        self._account_by_uid = account_by_uid
        self._account_by_email = account_by_email
        self._account_sql_uid_maps = uid_maps

        self._built = True

    def get_records_for_identity(
        self, identity: UserIdentity, audit_at: datetime
    ) -> list[tuple[str, EvidenceRecord]]:
        """Return (file_id, record) for all records matching identity at or before audit_at."""
        if not self._built:
            raise RuntimeError("build() not called")

        result = []
        for rec in self._all_records:
            # File must have been available at audit_at (file-level check)
            file_cat = self._file_captured_at.get(rec.file_id, datetime.min.replace(tzinfo=timezone.utc))
            if file_cat > audit_at:
                continue
            # Per-event timestamp must also be at or before audit_at
            if rec.captured_at > audit_at:
                continue
            if _record_matches_identity(rec, identity):
                result.append((rec.file_id, rec))

        # If no account_service record found, resolve via lookup tables
        if not any(r.system_id == "account_service" for _, r in result):
            account_id = self._resolve_account_id(identity)
            if account_id:
                state_recs = self.get_records_for_resource(account_id, audit_at)
                if state_recs:
                    for r in state_recs:
                        result.append((r.file_id, r))
                else:
                    synth = self._synthesize_absent(account_id, identity, audit_at)
                    if synth:
                        result.append(synth)

        return result

    def resolve_account_id(self, identity: UserIdentity) -> Optional[str]:
        """Public: find account_id for identity via lookup tables, then naming convention."""
        if not self._built:
            raise RuntimeError("build() not called")
        return self._resolve_account_id(identity)

    def _resolve_account_id(self, identity: UserIdentity) -> Optional[str]:
        """Find account_id for identity via lookup tables, then naming convention fallback."""
        # Rule 1: snapshot bundle customer_reference (any timestamp)
        aid = self._account_by_uid.get(identity.user_id)
        if aid:
            return aid
        # Rule 2: SQL search table source_resource_id linked via email
        for email in identity.all_emails:
            aid = self._account_by_email.get(email.lower())
            if aid:
                return aid
        # Rule 3 (last resort): user_NNN → account_NNN naming convention.
        # This is only correct for early users whose account_id happens to match
        # the zero-padded user_id suffix. No evidence supports this for other users.
        suffix = identity.user_id.replace("user_", "")
        return "account_" + suffix.zfill(3)

    def _synthesize_absent(
        self, account_id: str, identity: UserIdentity, audit_at: datetime
    ) -> Optional[tuple[str, EvidenceRecord]]:
        """Create synthetic ABSENT account record using best eligible SQL citation file."""
        eligible = {
            fid: (cat, uid_map)
            for fid, (cat, uid_map) in self._account_sql_uid_maps.items()
            if cat <= audit_at
        }
        if not eligible:
            return None
        best_fid = max(eligible, key=lambda k: eligible[k][0])
        best_cat = eligible[best_fid][0]
        rec = EvidenceRecord(
            file_id=best_fid,
            resource_id=account_id,
            system_id="account_service",
            state="ABSENT",
            data_category="USER_PROFILE",
            captured_at=best_cat,
            raw_fields={"user_id": identity.user_id, "synthetic_absent": True,
                        "_identifiers": [identity.user_id]},
        )
        return (best_fid, rec)

    def get_records_for_resource(
        self, resource_id: str, audit_at: datetime
    ) -> list[EvidenceRecord]:
        recs = self._by_resource_id.get(resource_id, [])
        result = []
        for r in recs:
            file_cat = self._file_captured_at.get(r.file_id, datetime.min.replace(tzinfo=timezone.utc))
            if file_cat <= audit_at and r.captured_at <= audit_at:
                result.append(r)
        return result


def _record_matches_identity(rec: EvidenceRecord, identity: UserIdentity) -> bool:
    """Check if this record belongs to the identity."""
    ids = rec.raw_fields.get("_identifiers", [])
    emails_lower = identity.all_emails
    uid = identity.user_id
    ehash = identity.email_hash
    all_ehashes = getattr(identity, "all_email_hashes", set())

    for ident in ids:
        if isinstance(ident, str):
            ident_lower = ident.lower()
            if ident_lower in emails_lower:
                return True
            if ident == uid:
                return True
            if ehash and ident == ehash:
                return True
            if ident in all_ehashes:
                return True

    # Also check correlation_key against all email hashes
    ck = rec.raw_fields.get("correlation_key", "")
    if ck and all_ehashes and ck in all_ehashes:
        return True
    if ck and ck == uid:
        return True

    # Also check raw fields directly for phones
    for p in identity.all_phones:
        if not p:
            continue
        for fn in ("phone", "requester_phone"):
            v = rec.raw_fields.get(fn)
            if v and str(v).strip() == p:
                return True

    return False


def _record_to_dict(r: EvidenceRecord) -> dict:
    return {
        "file_id": r.file_id,
        "resource_id": r.resource_id,
        "system_id": r.system_id,
        "state": r.state,
        "data_category": r.data_category,
        "captured_at": r.captured_at.isoformat(),
        "raw_fields": r.raw_fields,
    }


def _record_from_dict(d: dict, captured_at: datetime) -> EvidenceRecord:
    # Use per-event captured_at stored in cache; fall back to file-level timestamp
    stored_ts = d.get("captured_at")
    if stored_ts:
        try:
            captured_at = datetime.fromisoformat(
                stored_ts.replace("Z", "+00:00")
            ).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return EvidenceRecord(
        file_id=d["file_id"],
        resource_id=d["resource_id"],
        system_id=d["system_id"],
        state=d["state"],
        data_category=d["data_category"],
        captured_at=captured_at,
        raw_fields=d.get("raw_fields", {}),
    )
