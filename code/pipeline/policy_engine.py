from __future__ import annotations
from datetime import datetime, timezone

from pipeline import ResourceState, PolicyDecision

# data_category → required_action
_POLICY = {
    "USER_PROFILE": "DELETE",
    "SECONDARY_IDENTIFIER": "DELETE",
    "SEARCH_INDEX_ENTRY": "DELETE",
    "CACHE_ENTRY": "DELETE",
    "SUPPORT_MESSAGE": "REDACT",
    "SUPPORT_ATTACHMENT": "DELETE",
    "ANALYTICS_PROFILE": "ANONYMIZE",
    "PRODUCT_TELEMETRY": "ANONYMIZE",
    "USER_EXPORT": "DELETE",
    "MARKETING_PROFILE": "DELETE",
    "EMAIL_DELIVERY_LOG": "REDACT",
    "SECURITY_AUDIT_LOG": "RETAIN",
    "LEGAL_HOLD_RECORD": "RETAIN",
    "BACKUP_ARCHIVE": "RETAIN",      # action = block restore
    "ACCOUNT_TOMBSTONE": "REDACT",
    "DATA_FLOW": "DISABLE",          # synthetic for integration connectors
}

# Maps required_action → (finding_op, finding_state, remediation_op, remediation_state, verification_op, verification_state)
_ACTION_OPS = {
    "DELETE": (
        "REPORT_REMAINING_RECORD", "PRESENT",
        "DELETE_RECORD", "ABSENT",
        "VERIFY_RECORD_ABSENT", "ABSENT",
    ),
    "REDACT": (
        "REPORT_EXPOSED_PII", "PRESENT",
        "REDACT_RECORD", "REDACTED",
        "VERIFY_RECORD_REDACTED", "REDACTED",
    ),
    "ANONYMIZE": (
        "REPORT_EXPOSED_PII", "PRESENT",
        "ANONYMIZE_RECORD", "ANONYMIZED",
        "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED",
    ),
    "RETAIN": (
        None, None,
        None, None,
        "VERIFY_RECORD_PRESENT", "PRESENT",
    ),
    "RETAIN_BLOCKED": (
        "REPORT_RESTORE_RISK", "ACTIVE",
        "BLOCK_RESTORE", "BLOCKED",
        "VERIFY_RESTORE_BLOCKED", "BLOCKED",
    ),
    "DISABLE": (
        "REPORT_ACTIVE_DATA_FLOW", "ACTIVE",
        "DISABLE_DATA_FLOW", "DISABLED",
        "VERIFY_DATA_FLOW_DISABLED", "DISABLED",
    ),
    "ACCOUNT_TOMBSTONE_REDACT": (
        "REPORT_EXPOSED_PII", "PRESENT",
        "REDACT_RECORD", "REDACTED",
        "VERIFY_RECORD_REDACTED", "REDACTED",
    ),
}

# Compliant state per required_action
_COMPLIANT_STATES = {
    "DELETE": {"ABSENT"},
    "REDACT": {"REDACTED"},
    "ANONYMIZE": {"ANONYMIZED"},
    "RETAIN": {"PRESENT"},
    "RETAIN_BLOCKED": {"BLOCKED"},
    "DISABLE": {"DISABLED"},
    "ACCOUNT_TOMBSTONE_REDACT": {"REDACTED"},
}

_PII_FIELDS = ("email", "phone", "email_hash", "customer_reference", "user_id",
               "name", "full_name", "requester_email", "requester_phone")


def _is_pii_exposed(raw: dict, data_category: str) -> bool:
    if data_category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
        for f in ("email", "phone", "email_hash", "customer_reference", "user_id"):
            v = raw.get(f)
            if v is not None and str(v).strip() not in ("", "null", "None"):
                return True
        return False
    if data_category in ("SUPPORT_MESSAGE",):
        for f in ("requester_email", "requester_phone", "email", "matched_value"):
            v = raw.get(f)
            if v is not None and str(v).strip() not in ("", "null", "None"):
                return True
        return False
    if data_category == "ACCOUNT_TOMBSTONE":
        for f in ("name", "email", "phone", "email_hash", "full_name"):
            v = raw.get(f)
            if v is not None and str(v).strip() not in ("", "null", "None"):
                return True
        return False
    return True


class PolicyEngine:
    def apply(self, rs: ResourceState, identity, audit_at: datetime) -> PolicyDecision:
        """Apply deletion policy to a ResourceState. Returns PolicyDecision."""
        data_category = rs.data_category
        state = rs.state
        raw = rs.raw_fields

        # Determine effective policy action
        base_action = _POLICY.get(data_category, "DELETE")

        # Special case: BACKUP_ARCHIVE
        if data_category == "BACKUP_ARCHIVE":
            if state == "ACTIVE":
                # Restore path open — violation
                effective_action = "RETAIN_BLOCKED"
            else:
                # Already BLOCKED or ABSENT → compliant
                effective_action = "RETAIN_BLOCKED"
        elif data_category == "DATA_FLOW":
            effective_action = "DISABLE"
        elif data_category == "ACCOUNT_TOMBSTONE":
            effective_action = "ACCOUNT_TOMBSTONE_REDACT"
        else:
            effective_action = base_action

        ops = _ACTION_OPS[effective_action]
        finding_op, finding_state, remediation_op, remediation_state, verification_op, verification_state = ops

        # Determine violation
        if effective_action == "RETAIN":
            # Security/Legal: never a violation
            is_violation = False
        elif effective_action in ("DELETE",):
            # Violation if record is PRESENT
            is_violation = (state == "PRESENT")
        elif effective_action in ("REDACT",):
            # Violation if PII still exposed (state=PRESENT)
            is_violation = (state == "PRESENT") and _is_pii_exposed(raw, data_category)
        elif effective_action in ("ANONYMIZE",):
            # Violation if state=PRESENT (PII not yet anonymized)
            is_violation = (state == "PRESENT") and _is_pii_exposed(raw, data_category)
        elif effective_action == "RETAIN_BLOCKED":
            # Violation if restore is still ACTIVE
            is_violation = (state == "ACTIVE")
        elif effective_action == "DISABLE":
            # Violation if data flow still ACTIVE
            is_violation = (state == "ACTIVE")
        elif effective_action == "ACCOUNT_TOMBSTONE_REDACT":
            # Violation if PII exposed
            is_violation = (state == "PRESENT") and _is_pii_exposed(raw, data_category)
        else:
            is_violation = False

        return PolicyDecision(
            resource_state=rs,
            required_action=effective_action,
            is_violation=is_violation,
            finding_operation=finding_op or "",
            finding_state=finding_state or "",
            remediation_operation=remediation_op or "",
            remediation_state=remediation_state or "",
            verification_operation=verification_op or "",
            verification_state=verification_state or "",
        )
