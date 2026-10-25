"""Measure data-derived vs naming-convention account_id splits.

For every case in deletion_requests.csv, resolves identity and calls
resolve_account_id() to classify the account_service resource_id as:
  - data_derived: one of the three evidence-based lookup rules matched
  - naming_convention: fallback account_NNN from user number

Also identifies which INCOMPLETE cases had account_service in their
reconstructed state (evidence-backed) vs synthesized (no evidence link).

Usage (from repo root):
    python -I code/evaluation/measure_account_ids.py
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "dataset"
sys.path.insert(0, str(_REPO_ROOT / "code"))

from pipeline.identity_resolver import IdentityResolver
from pipeline.activity_scanner import ActivityScanner
from pipeline.evidence_indexer import EvidenceIndexer
from pipeline.state_reconstructor import StateReconstructor
from pipeline.intent_classifier import fast_classify
from pipeline.llm_client import UsageTracker
from datetime import datetime, timezone


def _naming_convention(user_id: str) -> str:
    """Return the naming-convention account_id for a user_id like 'user_042'."""
    num = user_id.split("_", 1)[-1] if "_" in user_id else user_id
    try:
        return f"account_{int(num):03d}"
    except ValueError:
        return f"account_{num}"


def parse_audit_at(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def main() -> None:
    print("Loading CSVs...", flush=True)
    with open(_DATASET / "deletion_requests.csv", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    with open(_DATASET / "evidence_files.csv", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))
    with open(_REPO_ROOT / "output.csv", encoding="utf-8") as f:
        output_rows = {r["case_id"]: r for r in csv.DictReader(f)}

    resolver = IdentityResolver()
    scanner = ActivityScanner()
    indexer = EvidenceIndexer()
    reconstructor = StateReconstructor(indexer, scanner)

    print(f"Building evidence index ({len(manifest)} files)...", flush=True)
    indexer.build(manifest)
    print("Index built.", flush=True)

    # Counters — 2x2: (evidence-backed vs synthesized) x (data-derived vs naming-convention)
    total_acct_steps = 0

    backed_data_derived = 0
    backed_naming_conv = 0

    synth_data_derived = 0
    synth_naming_conv = 0

    not_applicable = 0
    errors = 0

    for i, case in enumerate(cases):
        case_id = case["case_id"]
        out_row = output_rows.get(case_id)
        if out_row is None:
            continue

        deletion_status = out_row["deletion_status"]
        steps = json.loads(out_row["steps_json"])

        # Find account_service steps in this case
        acct_steps = [
            s for s in steps
            if s.get("system_id") == "account_service"
        ]

        if deletion_status == "NOT_APPLICABLE":
            not_applicable += 1
            continue

        # Resolve identity
        fast = fast_classify(case["request_text"])
        if fast == "NOT_APPLICABLE":
            not_applicable += 1
            continue

        identity = resolver.resolve(case["email"])
        if identity is None:
            not_applicable += 1
            continue

        audit_at = parse_audit_at(case["audit_at"])

        # Reconstruct states
        try:
            all_states = reconstructor.reconstruct(identity, audit_at)
        except Exception as e:
            errors += 1
            continue

        acct_in_states = any(rs.system_id == "account_service" for rs in all_states)

        # resolve_account_id for this identity
        resolved_id = indexer.resolve_account_id(identity) or ""
        nc_id = _naming_convention(identity.user_id)
        is_naming_conv = (resolved_id == nc_id)

        for s in acct_steps:
            rid = s.get("resource_id", "")
            total_acct_steps += 1

            # Classify this step's resource_id
            step_nc = _naming_convention(identity.user_id)
            step_is_nc = (rid == step_nc)

            # Is this step synthesized?
            if deletion_status == "INCOMPLETE" and not acct_in_states:
                # Synthesized: no evidence-backed account_service resource
                if step_is_nc:
                    synth_naming_conv += 1
                else:
                    synth_data_derived += 1
            else:
                # Evidence-backed: account appeared in reconstructed state
                if step_is_nc:
                    backed_naming_conv += 1
                else:
                    backed_data_derived += 1

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(cases)} cases processed...", flush=True)

    backed_total = backed_data_derived + backed_naming_conv
    synth_total  = synth_data_derived  + synth_naming_conv
    col_derived  = backed_data_derived + synth_data_derived
    col_naming   = backed_naming_conv  + synth_naming_conv
    grand_total  = backed_total + synth_total

    assert grand_total == total_acct_steps, f"Sum mismatch: {grand_total} != {total_acct_steps}"

    guessed_pct_all   = 100 * col_naming  / grand_total if grand_total else 0
    guessed_pct_synth = 100 * synth_naming_conv / synth_total if synth_total else 0

    print("\n" + "=" * 68)
    print("ACCOUNT_SERVICE RESOURCE_ID SPLIT (2x2)")
    print("=" * 68)
    W = 20
    print(f"{'':>{W}} {'Data-derived':>14} {'Naming-conv':>12} {'Total':>8}")
    print("-" * 68)
    print(f"{'Evidence-backed':>{W}} {backed_data_derived:>14} {backed_naming_conv:>12} {backed_total:>8}")
    print(f"{'Synthesized':>{W}} {synth_data_derived:>14} {synth_naming_conv:>12} {synth_total:>8}")
    print("-" * 68)
    print(f"{'Total':>{W}} {col_derived:>14} {col_naming:>12} {grand_total:>8}")
    print()
    print(f"Naming-convention (guessed) % of all steps : {guessed_pct_all:.1f}%  ({col_naming}/{grand_total})")
    print(f"Naming-convention (guessed) % of synthesized: {guessed_pct_synth:.1f}%  ({synth_naming_conv}/{synth_total})")
    print()
    print(f"NOT_APPLICABLE cases (skipped): {not_applicable}")
    if errors:
        print(f"Errors: {errors}")
    print()
    usage = UsageTracker.get().summary()
    if "0 calls" in usage or "No LLM" in usage:
        print("No LLM calls made.")
    else:
        print(f"LLM usage:\n{usage}")


if __name__ == "__main__":
    main()
