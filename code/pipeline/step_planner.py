from __future__ import annotations
from typing import Optional

from pipeline import PolicyDecision, ResourceState, Step

# Sort keys within each phase
_FINDING_ORDER = {
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,
}
_REMEDIATION_ORDER = {
    "DISABLE_DATA_FLOW": 1,
    "BLOCK_RESTORE": 2,
    "DELETE_RECORD": 3,
    "REDACT_RECORD": 4,
    "ANONYMIZE_RECORD": 5,
}
_VERIFICATION_ORDER = {
    "VERIFY_RECORD_ABSENT": 1,
    "VERIFY_RECORD_PRESENT": 2,
    "VERIFY_RECORD_REDACTED": 3,
    "VERIFY_RECORD_ANONYMIZED": 4,
    "VERIFY_DATA_FLOW_DISABLED": 5,
    "VERIFY_RESTORE_BLOCKED": 6,
}


def _sort_key(operation: str, system_id: str, resource_id: str, order_map: dict) -> tuple:
    return (order_map.get(operation, 99), system_id, resource_id)


def plan(
    violations: list[PolicyDecision],
    compliant_resources: list[ResourceState],
    deletion_status: str,
    security_resources: list[ResourceState],
    user_id: str = "",
) -> list[Step]:
    """Build ordered steps list for a case.

    deletion_status: 'COMPLETE' or 'INCOMPLETE'
    security_resources: list of ResourceState with data_category=SECURITY_AUDIT_LOG
    """
    steps: list[Step] = []
    step_no = 1

    if deletion_status == "COMPLETE":
        # VERIFICATION only; all evidence_ids non-empty
        verify_steps: list[tuple] = []

        # Account service ABSENT verification (from compliant with system_id=account_service)
        acct_compliant = [r for r in compliant_resources if r.system_id == "account_service"]
        for r in acct_compliant:
            verify_steps.append((
                "VERIFY_RECORD_ABSENT", "ABSENT",
                r.system_id, r.resource_id, r.evidence_file_id
            ))

        # Security audit PRESENT (always retain)
        for sec in security_resources:
            verify_steps.append((
                "VERIFY_RECORD_PRESENT", "PRESENT",
                sec.system_id, sec.resource_id, sec.evidence_file_id
            ))

        # Other compliant resources
        verify_op_map = {
            "ABSENT": "VERIFY_RECORD_ABSENT",
            "REDACTED": "VERIFY_RECORD_REDACTED",
            "ANONYMIZED": "VERIFY_RECORD_ANONYMIZED",
            "BLOCKED": "VERIFY_RESTORE_BLOCKED",
            "DISABLED": "VERIFY_DATA_FLOW_DISABLED",
            "PRESENT": "VERIFY_RECORD_PRESENT",
        }
        for r in compliant_resources:
            if r.system_id == "account_service":
                continue  # already added above
            if r.data_category == "SECURITY_AUDIT_LOG":
                continue  # added separately
            op = verify_op_map.get(r.state, "VERIFY_RECORD_ABSENT")
            verify_steps.append((op, r.state, r.system_id, r.resource_id, r.evidence_file_id))

        # Deduplicate (same resource_id + system_id)
        seen = set()
        unique_verify = []
        for vs in verify_steps:
            key = (vs[2], vs[3])  # system_id, resource_id
            if key not in seen:
                seen.add(key)
                unique_verify.append(vs)

        # Sort by VERIFICATION_ORDER then system_id then resource_id
        unique_verify.sort(key=lambda x: _sort_key(x[0], x[2], x[3], _VERIFICATION_ORDER))

        for op, state, sys_id, rid, evidence_id in unique_verify:
            steps.append(Step(
                step_no=step_no, phase="VERIFICATION",
                system_id=sys_id, resource_id=rid,
                operation=op, state=state,
                evidence_id=evidence_id or "",
            ))
            step_no += 1

    else:
        # INCOMPLETE: FINDING → REMEDIATION → VERIFICATION
        # Phase 1: FINDING
        finding_steps = []
        for v in violations:
            rs = v.resource_state
            finding_steps.append((
                v.finding_operation, v.finding_state,
                rs.system_id, rs.resource_id,
                rs.evidence_file_id,
            ))

        # Deduplicate findings
        seen_f = set()
        unique_findings = []
        for fs in finding_steps:
            key = (fs[0], fs[2], fs[3])
            if key not in seen_f:
                seen_f.add(key)
                unique_findings.append(fs)

        unique_findings.sort(key=lambda x: _sort_key(x[0], x[2], x[3], _FINDING_ORDER))

        for op, state, sys_id, rid, evidence_id in unique_findings:
            steps.append(Step(
                step_no=step_no, phase="FINDING",
                system_id=sys_id, resource_id=rid,
                operation=op, state=state,
                evidence_id=evidence_id or "",
            ))
            step_no += 1

        # Phase 2: REMEDIATION (evidence_id always "")
        remediation_steps = []
        for v in violations:
            rs = v.resource_state
            remediation_steps.append((
                v.remediation_operation, v.remediation_state,
                rs.system_id, rs.resource_id,
            ))

        # Deduplicate remediations
        seen_r = set()
        unique_remediations = []
        for rs in remediation_steps:
            key = (rs[0], rs[2], rs[3])
            if key not in seen_r:
                seen_r.add(key)
                unique_remediations.append(rs)

        unique_remediations.sort(key=lambda x: _sort_key(x[0], x[2], x[3], _REMEDIATION_ORDER))

        for op, state, sys_id, rid in unique_remediations:
            steps.append(Step(
                step_no=step_no, phase="REMEDIATION",
                system_id=sys_id, resource_id=rid,
                operation=op, state=state,
                evidence_id="",
            ))
            step_no += 1

        # Phase 3: VERIFICATION (evidence_id always "")
        verify_steps: list[tuple] = []

        # Account service ABSENT — always include for INCOMPLETE
        acct_from_violations = [v.resource_state for v in violations if v.resource_state.system_id == "account_service"]
        acct_from_compliant = [r for r in compliant_resources if r.system_id == "account_service"]
        all_acct = acct_from_violations + acct_from_compliant
        seen_acct = set()
        for r in all_acct:
            if r.resource_id not in seen_acct:
                seen_acct.add(r.resource_id)
                verify_steps.append((
                    "VERIFY_RECORD_ABSENT", "ABSENT",
                    r.system_id, r.resource_id,
                ))

        # Security audit PRESENT
        for sec in security_resources:
            verify_steps.append((
                "VERIFY_RECORD_PRESENT", "PRESENT",
                sec.system_id, sec.resource_id,
            ))

        # One VERIFY per violation
        for v in violations:
            rs = v.resource_state
            verify_steps.append((
                v.verification_operation, v.verification_state,
                rs.system_id, rs.resource_id,
            ))

        # One VERIFY per compliant resource (non-account, non-security)
        verify_op_map = {
            "ABSENT": "VERIFY_RECORD_ABSENT",
            "REDACTED": "VERIFY_RECORD_REDACTED",
            "ANONYMIZED": "VERIFY_RECORD_ANONYMIZED",
            "BLOCKED": "VERIFY_RESTORE_BLOCKED",
            "DISABLED": "VERIFY_DATA_FLOW_DISABLED",
            "PRESENT": "VERIFY_RECORD_PRESENT",
        }
        for r in compliant_resources:
            if r.system_id == "account_service":
                continue
            if r.data_category == "SECURITY_AUDIT_LOG":
                continue
            op = verify_op_map.get(r.state, "VERIFY_RECORD_ABSENT")
            verify_steps.append((op, r.state, r.system_id, r.resource_id))

        # Deduplicate verifications
        seen_v = set()
        unique_verify = []
        for vs in verify_steps:
            key = (vs[0], vs[2], vs[3])
            if key not in seen_v:
                seen_v.add(key)
                unique_verify.append(vs)

        unique_verify.sort(key=lambda x: _sort_key(x[0], x[2], x[3], _VERIFICATION_ORDER))

        for item in unique_verify:
            op, state, sys_id, rid = item
            steps.append(Step(
                step_no=step_no, phase="VERIFICATION",
                system_id=sys_id, resource_id=rid,
                operation=op, state=state,
                evidence_id="",
            ))
            step_no += 1

    # Renumber all steps consecutively
    for i, s in enumerate(steps, 1):
        s.step_no = i

    return steps
