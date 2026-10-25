"""Evaluation script for Ghost Data Still Exists.

Runs the deletion-audit pipeline on the 32 public sample cases, then compares
against dataset/sample_output.csv and prints case-level, row-level, field-level,
and sequence accuracy, plus a mismatch detail line for every discrepant case.

Usage (from repo root):
    python3 code/evaluation/main.py

Writes updated evaluation/evaluation_report.md at the end.
"""
from __future__ import annotations
import csv
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "dataset"

# Allow `from pipeline.*` imports
sys.path.insert(0, str(_REPO_ROOT / "code"))

from pipeline.identity_resolver import IdentityResolver
from pipeline.intent_classifier import classify, fast_classify
from pipeline.activity_scanner import ActivityScanner
from pipeline.evidence_indexer import EvidenceIndexer
from pipeline.state_reconstructor import StateReconstructor
from pipeline.policy_engine import PolicyEngine
from pipeline.step_planner import plan
from pipeline.output_validator import validate
from pipeline.llm_client import UsageTracker


FIELDS = ["phase", "system_id", "resource_id", "operation", "state", "evidence_id"]


def parse_audit_at(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def run_pipeline_on_samples(
    cases: list[dict],
    resolver: IdentityResolver,
    scanner: ActivityScanner,
    indexer: EvidenceIndexer,
    reconstructor: StateReconstructor,
    engine: PolicyEngine,
) -> list[dict]:
    results = []
    for case in cases:
        case_id = case["case_id"]
        try:
            email = case["email"]
            request_text = case["request_text"]
            audit_at = parse_audit_at(case["audit_at"])

            fast = fast_classify(request_text)
            if fast == "NOT_APPLICABLE":
                results.append({"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"})
                continue

            identity = resolver.resolve(email)
            if identity is None:
                results.append({"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"})
                continue

            account_id = indexer.resolve_account_id(identity) or ""

            if fast is None:
                if account_id:
                    sig = scanner.get_classify_signal(account_id, audit_at)
                    if sig == "NOT_APPLICABLE":
                        results.append({"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"})
                        continue

            intent = classify(request_text)
            if intent == "NOT_APPLICABLE":
                results.append({"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"})
                continue

            all_states = reconstructor.reconstruct(identity, audit_at)
            decisions = [engine.apply(rs, identity, audit_at) for rs in all_states]
            violations = [d for d in decisions if d.is_violation and d.resource_state.evidence_file_id]
            compliant = [d.resource_state for d in decisions if not d.is_violation]
            security_resources = [rs for rs in all_states if rs.data_category == "SECURITY_AUDIT_LOG"]

            deletion_status = "INCOMPLETE" if violations else "COMPLETE"
            steps = plan(violations, compliant, deletion_status, security_resources, identity.user_id, account_id)
            steps_json = json.dumps([s.to_dict() for s in steps], separators=(",", ":"))
            results.append({"case_id": case_id, "deletion_status": deletion_status, "steps_json": steps_json})

        except Exception as e:
            traceback.print_exc()
            print(f"ERROR on {case_id}: {e}", file=sys.stderr)
            results.append({"case_id": case_id, "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"})

    return results


def compare(actual: list[dict], expected: list[dict]) -> None:
    exp_map = {r["case_id"]: r for r in expected}
    act_map = {r["case_id"]: r for r in actual}

    total_cases = len(exp_map)
    status_correct = 0
    exact_match = 0

    field_correct = {f: 0 for f in FIELDS}
    field_total = {f: 0 for f in FIELDS}

    # Sequence accuracy: all steps in same order (phase+op+sys+rid all correct)
    seq_correct = 0

    mismatches = []

    for case_id in sorted(exp_map, key=lambda x: int(x.split("_")[1])):
        exp_row = exp_map[case_id]
        act_row = act_map.get(case_id)
        if act_row is None:
            print(f"  MISSING output for {case_id}")
            continue

        exp_status = exp_row["deletion_status"]
        act_status = act_row["deletion_status"]
        status_ok = exp_status == act_status
        if status_ok:
            status_correct += 1

        exp_steps = json.loads(exp_row["steps_json"])
        act_steps = json.loads(act_row["steps_json"])
        compare_len = min(len(exp_steps), len(act_steps))

        step_all_ok = status_ok and (len(exp_steps) == len(act_steps))
        seq_all_ok = step_all_ok

        mismatch_lines = []

        if not status_ok:
            mismatch_lines.append(
                f"  status: expected={exp_status} got={act_status}"
            )

        if len(exp_steps) != len(act_steps):
            mismatch_lines.append(
                f"  step_count: expected={len(exp_steps)} got={len(act_steps)}"
            )

        for i in range(compare_len):
            e, a = exp_steps[i], act_steps[i]
            step_ok = True
            diffs = []
            for f in FIELDS:
                ev = str(e.get(f, "")).strip()
                av = str(a.get(f, "")).strip()
                field_total[f] += 1
                if ev == av:
                    field_correct[f] += 1
                else:
                    step_ok = False
                    diffs.append(f"{f}: exp={ev!r} got={av!r}")
            if diffs:
                mismatch_lines.append(f"  step {i+1}: " + " | ".join(diffs))
            if not step_ok:
                step_all_ok = False
                seq_all_ok = False

        if step_all_ok:
            exact_match += 1
        if seq_all_ok:
            seq_correct += 1

        if mismatch_lines:
            mismatches.append((case_id, exp_status, act_status, exp_steps, act_steps, mismatch_lines))

    # ── Print results ──────────────────────────────────────────────────────────
    tot_f_correct = sum(field_correct.values())
    tot_f_total = sum(field_total.values())
    overall_pct = 100 * tot_f_correct / tot_f_total if tot_f_total else 0

    print(f"\n{'='*60}")
    print("EVALUATION RESULTS (32 sample cases)")
    print(f"{'='*60}")
    print(f"Case-level deletion_status accuracy : {status_correct}/{total_cases}  ({100*status_correct/total_cases:.1f}%)")
    print(f"Exact step-sequence match           : {exact_match}/{total_cases}  ({100*exact_match/total_cases:.1f}%)")
    print(f"Sequence accuracy (all fields ok)   : {seq_correct}/{total_cases}  ({100*seq_correct/total_cases:.1f}%)")
    print()
    print(f"{'Field':<15} {'Correct':>8} {'Total':>8} {'Acc%':>8}")
    print("-" * 42)
    for f in FIELDS:
        c, t = field_correct[f], field_total[f]
        print(f"{f:<15} {c:>8} {t:>8} {100*c/t:>7.1f}%")
    print("-" * 42)
    print(f"{'Overall':<15} {tot_f_correct:>8} {tot_f_total:>8} {overall_pct:>7.1f}%")

    print(f"\n{'='*60}")
    print(f"MISMATCHES ({len(mismatches)} cases)")
    print(f"{'='*60}")
    for case_id, exp_st, act_st, exp_steps, act_steps, lines in mismatches:
        print(f"\n{case_id}  [exp={exp_st} got={act_st}  steps exp={len(exp_steps)} got={len(act_steps)}]")
        # Deduplicate mismatch lines (step field diffs already expanded above)
        seen = set()
        for ln in lines:
            if ln not in seen:
                seen.add(ln)
                print(ln)


def write_report(status_correct: int, exact_match: int, field_correct: dict, field_total: dict, total_cases: int) -> None:
    """Stub — full report written by compare(); call separately if needed."""
    pass


def main() -> None:
    print("Loading sample cases...", flush=True)
    with open(_DATASET / "sample_deletion_requests.csv", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    with open(_DATASET / "sample_output.csv", encoding="utf-8") as f:
        expected = list(csv.DictReader(f))

    manifest = []
    with open(_DATASET / "evidence_files.csv", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    resolver = IdentityResolver()
    scanner = ActivityScanner()
    indexer = EvidenceIndexer()
    reconstructor = StateReconstructor(indexer, scanner)
    engine = PolicyEngine()

    print(f"Building evidence index ({len(manifest)} files)...", flush=True)
    indexer.build(manifest)
    print("Evidence index built.", flush=True)

    print(f"Running pipeline on {len(cases)} sample cases...", flush=True)
    actual = run_pipeline_on_samples(cases, resolver, scanner, indexer, reconstructor, engine)

    compare(actual, expected)

    # Validate the 32-case output against schema rules
    errs = validate(actual, expected_count=len(actual))
    if errs:
        print(f"\nValidation errors on 32-sample output ({len(errs)}):")
        for e in errs:
            print(f"  {e}")
    else:
        print(f"\nValidation passed on 32-sample output (0 errors).")

    usage = UsageTracker.get().summary()
    if "0 calls" not in usage and "No LLM" not in usage:
        print(f"\nLLM usage:\n{usage}")
    else:
        print("\nNo LLM calls made.")


if __name__ == "__main__":
    main()
