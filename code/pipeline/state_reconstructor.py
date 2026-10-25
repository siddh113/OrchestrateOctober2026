from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline import UserIdentity, EvidenceRecord, ResourceState

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "dataset"

# Priority for evidence sources: higher = more authoritative
_SOURCE_PRIORITY = {
    "service_resource_export": 3,
    "customer_data_snapshot_bundle": 2,
    "customer_account_handover": 2,
    "connector_configurations": 2,
    "security_audit_ledger": 2,
    "customer_export_manifest": 2,
    "customer_analytics_report": 2,
    "customer_export_jobs": 2,
    "default": 1,
}


def _file_priority(file_id: str) -> int:
    """Higher priority sources take precedence in tie-breaking."""
    return _SOURCE_PRIORITY.get(file_id, _SOURCE_PRIORITY["default"])


def _source_priority_from_path(file_path: str) -> int:
    p = Path(file_path)
    fname = p.stem
    ext = p.suffix.lower()
    for key in _SOURCE_PRIORITY:
        if key != "default" and fname.startswith(key):
            return _SOURCE_PRIORITY[key]
    # Extension-based fallback: SQL/JSON structured data > log files
    if ext in (".sql", ".json"):
        return 2
    if ext in (".txt", ".pdf", ".png"):
        return 2
    # .log files: lowest priority for tie-breaking with structured data
    return _SOURCE_PRIORITY["default"]


class StateReconstructor:
    def __init__(self, evidence_indexer, activity_scanner) -> None:
        self._indexer = evidence_indexer
        self._scanner = activity_scanner
        self._manifest: dict[str, dict] = {}
        self._loaded = False

    def _load_manifest(self) -> None:
        if self._loaded:
            return
        with open(_DATASET / "evidence_files.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self._manifest[row["file_id"]] = row
        self._loaded = True

    def _file_source_priority(self, file_id: str) -> int:
        row = self._manifest.get(file_id, {})
        file_path = row.get("file_path", "")
        return _source_priority_from_path(file_path)

    def reconstruct(self, identity: UserIdentity, audit_at: datetime) -> list[ResourceState]:
        """Reconstruct the true state of all resources for identity at audit_at."""
        self._load_manifest()

        # Get all linked resource_ids from activity scanner
        linked_entries = self._scanner.get_linked_resources(identity)
        linked_resource_ids: set[str] = {e["resource_id"] for e in linked_entries if e.get("resource_id")}

        # Get all evidence records matching identity at/before audit_at
        identity_records = self._indexer.get_records_for_identity(identity, audit_at)

        # Also fetch records for linked resource_ids not already covered
        covered_resource_ids = {rec.resource_id for _, rec in identity_records}
        for rid in linked_resource_ids:
            if rid not in covered_resource_ids:
                extra = self._indexer.get_records_for_resource(rid, audit_at)
                for rec in extra:
                    identity_records.append((rec.file_id, rec))

        # Group by (resource_id, system_id, data_category) → best candidate
        # Key: (resource_id, system_id, data_category)
        candidates: dict[tuple, list[tuple[datetime, int, str, EvidenceRecord]]] = {}

        for file_id, rec in identity_records:
            key = (rec.resource_id, rec.system_id, rec.data_category)
            priority = self._file_source_priority(file_id)
            candidates.setdefault(key, []).append(
                (rec.captured_at, priority, file_id, rec)
            )

        result: list[ResourceState] = []

        for key, entries in candidates.items():
            resource_id, system_id, data_category = key

            # Ghost handling: if any entry is ghost (replica with absent in primary),
            # that is the definitive finding — ghost state = PRESENT
            ghost_entries = [e for e in entries if e[3].raw_fields.get("ghost")]
            if ghost_entries:
                # Use the ghost entry with latest captured_at
                ghost_entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
                _, _, file_id, rec = ghost_entries[0]
                result.append(ResourceState(
                    resource_id=resource_id,
                    system_id=system_id,
                    state="PRESENT",
                    evidence_file_id=file_id,
                    data_category=data_category,
                    raw_fields={**rec.raw_fields, "ghost": True},
                ))
                continue

            # Prefer on-time emit_file_id (non-empty) over late-file entry (empty).
            # Within same has-evidence tier: latest captured_at, then source priority.
            entries.sort(key=lambda e: (0 if e[2] == "" else 1, e[0], e[1]), reverse=True)
            _, _, file_id, rec = entries[0]

            result.append(ResourceState(
                resource_id=resource_id,
                system_id=system_id,
                state=rec.state,
                evidence_file_id=file_id,
                data_category=data_category,
                raw_fields=rec.raw_fields,
            ))

        return result
