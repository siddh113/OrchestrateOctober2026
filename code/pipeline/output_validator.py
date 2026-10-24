from __future__ import annotations
import json
import sys

_VALID_STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
_VALID_PHASES = {"FINDING", "REMEDIATION", "VERIFICATION"}
_VALID_OPERATIONS = {
    "REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK",
    "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD",
    "VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED",
    "VERIFY_RECORD_ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED",
}
_PHASE_ORDER = ["FINDING", "REMEDIATION", "VERIFICATION"]


def validate(rows: list[dict], expected_count: int = 518) -> list[str]:
    """Validate output rows. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    # 1. Row count
    if len(rows) != expected_count:
        errors.append(f"Expected {expected_count} rows, got {len(rows)}")

    # 2. Sorted by case_id numerically
    case_ids = [r["case_id"] for r in rows]
    try:
        numeric_ids = [int(r["case_id"].split("_")[1]) for r in rows]
        if numeric_ids != sorted(numeric_ids):
            errors.append("Rows not sorted by case_id numerically")
    except Exception as e:
        errors.append(f"case_id parse error: {e}")

    # 3. Per-row validation
    for row in rows:
        case_id = row.get("case_id", "?")
        status = row.get("deletion_status", "")
        steps_raw = row.get("steps_json", "")

        if status not in _VALID_STATUSES:
            errors.append(f"{case_id}: invalid deletion_status={status!r}")
            continue

        # Parse steps_json
        try:
            steps = json.loads(steps_raw)
        except Exception as e:
            errors.append(f"{case_id}: invalid steps_json: {e}")
            continue

        if not isinstance(steps, list):
            errors.append(f"{case_id}: steps_json not an array")
            continue

        # 4. NOT_APPLICABLE → steps=[]
        if status == "NOT_APPLICABLE":
            if steps:
                errors.append(f"{case_id}: NOT_APPLICABLE but steps non-empty")
            continue

        # 5. step_no consecutive from 1
        for i, step in enumerate(steps, 1):
            if step.get("step_no") != i:
                errors.append(f"{case_id}: step_no out of order at index {i}")
                break

        # 6. Phase ordering: FINDING before REMEDIATION before VERIFICATION
        phases_seen = []
        for step in steps:
            phase = step.get("phase")
            if not phases_seen or phases_seen[-1] != phase:
                phases_seen.append(phase)
        for i in range(len(phases_seen) - 1):
            p1, p2 = phases_seen[i], phases_seen[i + 1]
            if p1 not in _PHASE_ORDER or p2 not in _PHASE_ORDER:
                continue
            if _PHASE_ORDER.index(p1) > _PHASE_ORDER.index(p2):
                errors.append(f"{case_id}: phases out of order {p1} before {p2}")

        # 7. COMPLETE → all steps VERIFICATION
        if status == "COMPLETE":
            non_v = [s for s in steps if s.get("phase") != "VERIFICATION"]
            if non_v:
                errors.append(f"{case_id}: COMPLETE but has non-VERIFICATION steps")

        # 8. INCOMPLETE → all three phases present
        if status == "INCOMPLETE":
            present_phases = {s.get("phase") for s in steps}
            for ph in ["FINDING", "REMEDIATION", "VERIFICATION"]:
                if ph not in present_phases:
                    errors.append(f"{case_id}: INCOMPLETE missing phase {ph}")

        # 9. evidence_id rules
        for step in steps:
            phase = step.get("phase")
            ev = step.get("evidence_id", "")
            if phase == "REMEDIATION" and ev:
                errors.append(f"{case_id}: step {step.get('step_no')} REMEDIATION has non-empty evidence_id")
            if phase == "FINDING" and not ev:
                errors.append(f"{case_id}: step {step.get('step_no')} FINDING has empty evidence_id")
            if status == "COMPLETE" and phase == "VERIFICATION" and not ev:
                errors.append(f"{case_id}: step {step.get('step_no')} COMPLETE VERIFICATION has empty evidence_id")
            if status == "INCOMPLETE" and phase == "VERIFICATION" and ev:
                errors.append(f"{case_id}: step {step.get('step_no')} INCOMPLETE VERIFICATION has non-empty evidence_id")

        # 10. INCOMPLETE must have VERIFY_RECORD_ABSENT on account_service
        if status == "INCOMPLETE":
            has_absent = any(
                s.get("operation") == "VERIFY_RECORD_ABSENT" and s.get("system_id") == "account_service"
                for s in steps
            )
            if not has_absent:
                errors.append(f"{case_id}: INCOMPLETE missing VERIFY_RECORD_ABSENT on account_service")

        # 11. All operations from allowed set
        for step in steps:
            op = step.get("operation", "")
            if op not in _VALID_OPERATIONS:
                errors.append(f"{case_id}: step {step.get('step_no')} unknown operation {op!r}")

    return errors
