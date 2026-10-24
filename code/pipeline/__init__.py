from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class UserIdentity:
    user_id: str
    current_email: str
    all_emails: set = field(default_factory=set)        # lowercase current + historical
    all_phones: set = field(default_factory=set)        # current + historical
    name: str = ""
    email_hash: str = ""
    all_email_hashes: set = field(default_factory=set)  # SHA-256 of all emails


@dataclass
class EvidenceRecord:
    file_id: str
    resource_id: str
    system_id: str
    state: str          # PRESENT/ABSENT/ANONYMIZED/REDACTED/ACTIVE/BLOCKED/DISABLED
    data_category: str
    captured_at: datetime
    raw_fields: dict = field(default_factory=dict)


@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    state: str
    evidence_file_id: str
    data_category: str
    raw_fields: dict = field(default_factory=dict)


@dataclass
class PolicyDecision:
    resource_state: ResourceState
    required_action: str
    is_violation: bool
    finding_operation: str = ""
    finding_state: str = ""
    remediation_operation: str = ""
    remediation_state: str = ""
    verification_operation: str = ""
    verification_state: str = ""


@dataclass
class Step:
    step_no: int
    phase: str          # FINDING/REMEDIATION/VERIFICATION
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str    # non-empty for FINDING + COMPLETE VERIFY; "" otherwise

    def to_dict(self) -> dict:
        return {
            "step_no": self.step_no,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": self.state,
            "evidence_id": self.evidence_id,
        }


@dataclass
class LLMUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
