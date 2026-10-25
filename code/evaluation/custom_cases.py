"""Custom evaluation cases for Ghost Data Still Exists.

Three hand-crafted cases testing edge conditions beyond the 32 public samples:

  A: Non-deletion request (NOT_APPLICABLE via keyword fast-path)
  B: Historical-email-only match (identity resolved via old email)
  C: COMPLETE case with restore risk BLOCKED and data flow DISABLED

Run from repo root:
    python -I code/evaluation/custom_cases.py
"""
from __future__ import annotations
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "code"))

from pipeline.identity_resolver import IdentityResolver
from pipeline.intent_classifier import classify, fast_classify
from pipeline.activity_scanner import ActivityScanner
from pipeline.evidence_indexer import EvidenceIndexer
from pipeline.state_reconstructor import StateReconstructor
from pipeline.policy_engine import PolicyEngine
from pipeline.step_planner import plan
import csv


CUSTOM_CASES = [
    {
        "case_id": "custom_A",
        "description": "Non-deletion request — data copy/access, NOT_APPLICABLE via keyword fast-path",
        "email": "o.walker66@yahoo.com",   # user_523, current email
        "request_text": (
            "I would like to receive a copy of all personal data you hold about me "
            "in a portable format. Please send it to my registered email address."
        ),
        "audit_at": "2026-10-01T12:00:00Z",
        "expected_status": "NOT_APPLICABLE",
        "expected_ops": [],
        "rationale": (
            "Request contains 'copy', 'data', 'portable format' — NOT_APPLICABLE keywords. "
            "No deletion language present. Intent classifier fast-path must return NOT_APPLICABLE "
            "without an LLM call."
        ),
    },
    {
        "case_id": "custom_B",
        "description": "Historical-email-only match — identity resolved via old email in user_audit_log",
        "email": "o.walker6695@yahoo.com",  # user_523 OLD email, no longer current
        "request_text": (
            "Please delete my account and all associated personal data immediately. "
            "I no longer use this service."
        ),
        "audit_at": "2026-10-01T12:00:00Z",
        "expected_status": None,  # same output as current-email run (checked dynamically)
        "expected_ops": None,
        "rationale": (
            "The request email is historical (changed in user_audit_log). "
            "identity_resolver must find user_523 via old_value lookup, "
            "then reconstruct identical state as if current email were used."
        ),
    },
    {
        "case_id": "custom_C",
        "description": "COMPLETE: account absent, backup BLOCKED, data flow DISABLED, security audit PRESENT",
        "email": "lucas-souza95@gmail.com",
        "request_text": (
            "Please erase the account linked to this email address. "
            "Please handle any copies that fall within the scope of your deletion policy."
        ),
        "audit_at": "2026-10-01T12:00:00Z",
        "expected_status": "COMPLETE",
        "expected_ops": {
            "VERIFY_RECORD_ABSENT",
            "VERIFY_RESTORE_BLOCKED",
            "VERIFY_DATA_FLOW_DISABLED",
        },
        "rationale": (
            "At audit_at all records are compliant: account absent, backup BLOCKED, "
            "data flow DISABLED. Policy engine must find zero violations → COMPLETE. "
            "VERIFY steps must include both VERIFY_RESTORE_BLOCKED and VERIFY_DATA_FLOW_DISABLED."
        ),
    },
]


def parse_audit_at(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def run_case(case: dict, resolver, scanner, indexer, reconstructor, engine) -> dict:
    email = case["email"]
    request_text = case["request_text"]
    audit_at = parse_audit_at(case["audit_at"])

    fast = fast_classify(request_text)
    if fast == "NOT_APPLICABLE":
        return {"deletion_status": "NOT_APPLICABLE", "steps": [], "fast_path": True}

    identity = resolver.resolve(email)
    if identity is None:
        return {"deletion_status": "NOT_APPLICABLE", "steps": [], "fast_path": False, "error": "identity not resolved"}

    if fast is None:
        account_id = indexer.resolve_account_id(identity)
        if account_id:
            from pipeline.activity_scanner import ActivityScanner as AS
            sig = scanner.get_classify_signal(account_id, audit_at)
            if sig == "NOT_APPLICABLE":
                return {"deletion_status": "NOT_APPLICABLE", "steps": [], "fast_path": False}

    intent = classify(request_text)
    if intent == "NOT_APPLICABLE":
        return {"deletion_status": "NOT_APPLICABLE", "steps": [], "fast_path": False}

    all_states = reconstructor.reconstruct(identity, audit_at)
    decisions = [engine.apply(rs, identity, audit_at) for rs in all_states]
    violations = [d for d in decisions if d.is_violation]
    compliant = [d.resource_state for d in decisions if not d.is_violation]
    security = [rs for rs in all_states if rs.data_category == "SECURITY_AUDIT_LOG"]

    deletion_status = "INCOMPLETE" if violations else "COMPLETE"
    steps = plan(violations, compliant, deletion_status, security, identity.user_id)
    return {
        "deletion_status": deletion_status,
        "steps": [s.to_dict() for s in steps],
        "user_id": identity.user_id,
        "fast_path": False,
    }


def validate(result: dict, case: dict, current_email_result: dict | None = None) -> tuple[bool, list[str]]:
    failures = []

    exp_status = case["expected_status"]
    if exp_status is not None and result["deletion_status"] != exp_status:
        failures.append(f"deletion_status: expected={exp_status} got={result['deletion_status']}")

    exp_ops = case["expected_ops"]
    if exp_ops is not None and isinstance(exp_ops, set):
        actual_ops = {s["operation"] for s in result["steps"]}
        missing = exp_ops - actual_ops
        if missing:
            failures.append(f"missing expected operations: {sorted(missing)}")

    # Case B: check same output as current email
    if case["case_id"] == "custom_B" and current_email_result is not None:
        if result["deletion_status"] != current_email_result["deletion_status"]:
            failures.append(
                f"historical-email status differs from current-email: "
                f"{result['deletion_status']} vs {current_email_result['deletion_status']}"
            )
        act_ops = {(s["system_id"], s["resource_id"], s["operation"]) for s in result["steps"]}
        exp_ops2 = {(s["system_id"], s["resource_id"], s["operation"]) for s in current_email_result["steps"]}
        if act_ops != exp_ops2:
            failures.append(
                f"historical-email steps differ from current-email steps.\n"
                f"  historical: {sorted(act_ops)}\n"
                f"  current:    {sorted(exp_ops2)}"
            )

    return len(failures) == 0, failures


def main() -> None:
    import csv as _csv
    with open(_REPO_ROOT / "dataset" / "evidence_files.csv", encoding="utf-8") as f:
        manifest = list(_csv.DictReader(f))

    resolver = IdentityResolver()
    scanner = ActivityScanner()
    indexer = EvidenceIndexer()
    reconstructor = StateReconstructor(indexer, scanner)
    engine = PolicyEngine()

    print("Building evidence index...", flush=True)
    indexer.build(manifest)
    print("Done.\n", flush=True)

    # Run current-email version for case B comparison
    current_email_case = {**CUSTOM_CASES[1], "email": "o.walker66@yahoo.com"}
    current_result = run_case(current_email_case, resolver, scanner, indexer, reconstructor, engine)

    results = []
    for case in CUSTOM_CASES:
        try:
            r = run_case(case, resolver, scanner, indexer, reconstructor, engine)
        except Exception as e:
            traceback.print_exc()
            r = {"deletion_status": "ERROR", "steps": [], "error": str(e), "fast_path": False}

        cur = current_result if case["case_id"] == "custom_B" else None
        ok, failures = validate(r, case, cur)
        results.append((case, r, ok, failures))

    # Print summary
    print("=" * 60)
    print("CUSTOM CASE RESULTS")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for _, _, ok, _ in results if ok)
    print(f"Passed: {passed}/{total}\n")

    for case, r, ok, failures in results:
        status_icon = "PASS" if ok else "FAIL"
        print(f"[{status_icon}] {case['case_id']} — {case['description']}")
        print(f"  deletion_status : {r['deletion_status']}")
        if r.get("fast_path"):
            print(f"  fast_path       : True (no LLM called)")
        if r.get("user_id"):
            print(f"  user_id         : {r['user_id']}")
        print(f"  steps ({len(r['steps'])}):")
        for s in r["steps"]:
            print(f"    {s['step_no']:>2}. [{s['phase']}] {s['system_id']}/{s['resource_id']} "
                  f"{s['operation']} ({s['state']}) evidence={s['evidence_id']!r}")
        if failures:
            print(f"  FAILURES:")
            for f in failures:
                print(f"    - {f}")
        print()

    return results


if __name__ == "__main__":
    main()
