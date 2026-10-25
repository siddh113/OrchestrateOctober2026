"""Deletion-audit pipeline main entry point.

Usage (from repo root):
    python3 code/main.py
    python3 code/main.py --sample   # run only on sample_deletion_requests.csv
"""
from __future__ import annotations
import csv
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Allow `from pipeline.*` imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATASET = _REPO_ROOT / "dataset"

from pipeline.identity_resolver import IdentityResolver
from pipeline.intent_classifier import classify, fast_classify
from pipeline.activity_scanner import ActivityScanner
from pipeline.evidence_indexer import EvidenceIndexer
from pipeline.state_reconstructor import StateReconstructor
from pipeline.policy_engine import PolicyEngine
from pipeline.step_planner import plan
from pipeline.output_validator import validate
from pipeline.llm_client import UsageTracker


def parse_audit_at(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def load_manifest() -> list[dict]:
    with open(_DATASET / "evidence_files.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def process_case(
    case: dict,
    resolver: IdentityResolver,
    scanner: ActivityScanner,
    indexer: EvidenceIndexer,
    reconstructor: StateReconstructor,
    engine: PolicyEngine,
) -> dict:
    case_id = case["case_id"]
    email = case["email"]
    request_text = case["request_text"]
    audit_at = parse_audit_at(case["audit_at"])

    # 1. Keyword intent classification (fast path — highest priority signal)
    fast = fast_classify(request_text)
    if fast == "NOT_APPLICABLE":
        return {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}

    # 2. Identity resolution
    identity = resolver.resolve(email)
    if identity is None:
        return {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}

    # 2b. CLASSIFY_REQUEST is a tiebreaker only when request_text was ambiguous (fast=None).
    #     It must never override clear deletion wording in request_text.
    if fast is None:
        account_id = indexer.resolve_account_id(identity)
        if account_id:
            classify_signal = scanner.get_classify_signal(account_id, audit_at)
            if classify_signal == "NOT_APPLICABLE":
                return {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}

    # 2c. Full classify (handles ambiguous cases via LLM if needed)
    intent = classify(request_text)
    if intent == "NOT_APPLICABLE":
        return {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}

    # 3. Account ID (data-derived or naming-convention fallback)
    account_id = indexer.resolve_account_id(identity) or ""

    # 4. State reconstruction
    all_states = reconstructor.reconstruct(identity, audit_at)

    # 5. Policy application
    decisions = [engine.apply(rs, identity, audit_at) for rs in all_states]

    # 6. Split violations vs compliant
    # Require non-empty evidence_file_id for violations: FINDING steps must cite evidence.
    # Records with empty evidence_file_id have no on-time citation and cannot be reported.
    violations = [d for d in decisions if d.is_violation and d.resource_state.evidence_file_id]
    compliant = [d.resource_state for d in decisions if not d.is_violation]

    # Security audit resources (always retain)
    security_resources = [
        rs for rs in all_states if rs.data_category == "SECURITY_AUDIT_LOG"
    ]

    # 6. Determine deletion_status
    if violations:
        deletion_status = "INCOMPLETE"
    else:
        deletion_status = "COMPLETE"

    # 7. Plan steps
    steps = plan(violations, compliant, deletion_status, security_resources, identity.user_id, account_id)

    # 8. Serialize
    steps_json = json.dumps([s.to_dict() for s in steps], separators=(",", ":"))
    return {"case_id": case_id, "deletion_status": deletion_status, "steps_json": steps_json}


def main(sample_only: bool = False) -> None:
    # Load CSVs
    if sample_only:
        requests_path = _DATASET / "sample_deletion_requests.csv"
        output_path = _REPO_ROOT / "sample_output_run.csv"
        expected_count = None
    else:
        requests_path = _DATASET / "deletion_requests.csv"
        output_path = _REPO_ROOT / "output.csv"
        expected_count = 518

    with open(requests_path, encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    manifest = load_manifest()

    # Initialize modules
    resolver = IdentityResolver()
    scanner = ActivityScanner()
    indexer = EvidenceIndexer()
    reconstructor = StateReconstructor(indexer, scanner)
    engine = PolicyEngine()

    print(f"Building evidence index ({len(manifest)} files)...", flush=True)
    indexer.build(manifest)
    print("Evidence index built.", flush=True)

    output_rows = []
    errors = 0

    for i, case in enumerate(cases):
        case_id = case["case_id"]
        try:
            row = process_case(case, resolver, scanner, indexer, reconstructor, engine)
        except Exception as e:
            traceback.print_exc()
            print(f"ERROR on {case_id}: {e}", file=sys.stderr)
            row = {"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}
            errors += 1
        output_rows.append(row)
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(cases)} cases...", flush=True)

    # Sort by case_id numerically
    output_rows.sort(key=lambda r: int(r["case_id"].split("_")[1]))

    # Validate — always print result; exit nonzero if errors remain
    validation_errors = 0
    if expected_count:
        errs = validate(output_rows, expected_count)
        validation_errors = len(errs)
        if errs:
            print(f"\nValidation errors ({validation_errors}):", file=sys.stderr)
            for e in errs[:40]:
                print(f"  {e}", file=sys.stderr)
        else:
            print(f"Validation passed (0 errors).")

    # Write output
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["case_id", "deletion_status", "steps_json"])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nWrote {len(output_rows)} rows to {output_path}")
    if errors:
        print(f"Cases with errors: {errors}", file=sys.stderr)
    print("\n" + UsageTracker.get().summary())

    if validation_errors:
        sys.exit(1)


if __name__ == "__main__":
    sample_only = "--sample" in sys.argv
    main(sample_only=sample_only)
