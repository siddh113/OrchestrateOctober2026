from __future__ import annotations
import csv
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline import UserIdentity

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "dataset"

# Parse "linked X ... to EMAIL and USER_ID"
_STANDARD_RE = re.compile(
    r'linked\s+(\S+)\s+\([^)]+\)\s+to\s+([^\s]+@[^\s]+)\s+and\s+(user_\d+)',
    re.IGNORECASE
)
# Parse "belongs only to EMAIL and USER_ID"
_ATTACHMENT_RE = re.compile(
    r'belongs only to\s+([^\s]+@[^\s]+)\s+and\s+(user_\d+)',
    re.IGNORECASE
)

# Ghost signal event types that indicate incomplete deletion or recreation risk
_GHOST_EVENTS = {
    "SYNC_RECORD", "RESTORE_BACKUP", "REPLICATE_DATA",
    "IMPORT_DATA", "BACKUP_RESTORE",
}
_DELETION_EVENTS = {
    "DELETE_ACCOUNT", "DELETE_DATA", "DELETE_RECORD", "PURGE_DATA",
    "REDACT_DATA", "ANONYMIZE_DATA",
}


class ActivityScanner:
    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._link_by_email: dict[str, list[dict]] = defaultdict(list)
        self._link_by_user_id: dict[str, list[dict]] = defaultdict(list)
        self._by_resource_id: dict[str, list[dict]] = defaultdict(list)
        # account_id → list of (event_time, is_deletion bool)
        self._classify_by_account: dict[str, list[tuple[datetime, bool]]] = defaultdict(list)
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        with open(_DATASET / "system_activity.csv", encoding="utf-8") as f:
            self._rows = list(csv.DictReader(f))

        for row in self._rows:
            rid = (row.get("resource_id") or "").strip()
            if rid:
                self._by_resource_id[rid].append(row)

            if row.get("event_type") == "LINK_RESOURCE_IDENTITY":
                details = row.get("details", "")
                # Standard pattern
                m = _STANDARD_RE.search(details)
                if m:
                    resource_id, email, user_id = m.group(1), m.group(2).lower(), m.group(3)
                    entry = {
                        "resource_id": resource_id,
                        "email": email,
                        "user_id": user_id,
                        "activity_id": row["activity_id"],
                        "target_system": row.get("target_system", ""),
                        "event_time": row.get("event_time", ""),
                    }
                    self._link_by_email[email].append(entry)
                    self._link_by_user_id[user_id].append(entry)
                    continue

                # Attachment pattern
                m2 = _ATTACHMENT_RE.search(details)
                if m2:
                    email, user_id = m2.group(1).lower(), m2.group(2)
                    # Extract resource_id from resource_id column
                    resource_id = (row.get("resource_id") or "").strip()
                    entry = {
                        "resource_id": resource_id,
                        "email": email,
                        "user_id": user_id,
                        "activity_id": row["activity_id"],
                        "target_system": row.get("target_system", ""),
                        "event_time": row.get("event_time", ""),
                    }
                    self._link_by_email[email].append(entry)
                    self._link_by_user_id[user_id].append(entry)

            elif row.get("event_type") == "CLASSIFY_REQUEST":
                account_id = (row.get("resource_id") or "").strip()
                details = row.get("details", "").lower()
                is_deletion = "non-deletion" not in details
                try:
                    et = datetime.fromisoformat(
                        row["event_time"].replace("Z", "+00:00")
                    ).replace(tzinfo=timezone.utc)
                except Exception:
                    et = datetime.min.replace(tzinfo=timezone.utc)
                if account_id:
                    self._classify_by_account[account_id].append((et, is_deletion))

        self._loaded = True

    def get_linked_resources(self, identity: UserIdentity) -> list[dict]:
        """Return all LINK_RESOURCE_IDENTITY entries matching this identity."""
        self._load()
        seen = set()
        result = []
        for email in identity.all_emails:
            for entry in self._link_by_email.get(email, []):
                key = (entry["resource_id"], entry["activity_id"])
                if key not in seen:
                    seen.add(key)
                    result.append(entry)
        for entry in self._link_by_user_id.get(identity.user_id, []):
            key = (entry["resource_id"], entry["activity_id"])
            if key not in seen:
                seen.add(key)
                result.append(entry)
        return result

    def get_ghost_signals(self, resource_id: str, audit_at: datetime) -> list[dict]:
        """Return activity rows for resource_id at or before audit_at that indicate ghost risk."""
        self._load()
        result = []
        for row in self._by_resource_id.get(resource_id, []):
            try:
                event_time = datetime.fromisoformat(
                    row["event_time"].replace("Z", "+00:00")
                )
            except Exception:
                continue
            if event_time <= audit_at:
                result.append(row)
        return result

    def get_classify_signal(self, account_id: str, audit_at: datetime) -> Optional[str]:
        """Return 'NOT_APPLICABLE' if account had a non-deletion CLASSIFY_REQUEST.

        audit_at is not checked here: intent classification is not state proof,
        so a CLASSIFY_REQUEST recorded after audit_at is still valid intent evidence.
        """
        self._load()
        entries = self._classify_by_account.get(account_id, [])
        for _et, is_deletion in entries:
            if not is_deletion:
                return "NOT_APPLICABLE"
        return None

    def get_all_rows_for_identity(self, identity: UserIdentity, audit_at: datetime) -> list[dict]:
        """Return all activity rows at or before audit_at that reference this identity."""
        self._load()
        result = []
        id_set = identity.all_emails | {identity.user_id}
        if identity.email_hash:
            id_set.add(identity.email_hash)

        for row in self._rows:
            try:
                event_time = datetime.fromisoformat(
                    row["event_time"].replace("Z", "+00:00")
                )
            except Exception:
                continue
            if event_time > audit_at:
                continue
            # Check details for any identifier match
            details = (row.get("details") or "").lower()
            matched = any(
                (ident.lower() in details)
                for ident in id_set
                if ident
            )
            if matched:
                result.append(row)
        return result
