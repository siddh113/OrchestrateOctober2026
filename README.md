# Ghost Data Still Exists — Deletion Audit Agent

HackerRank Orchestrate, October 2026.

For each deletion request the agent determines whether deletion was actually requested, resolves the
subject's current and historical identifiers, reconstructs the true state of every relevant data
record at `audit_at` from the supplied evidence, applies the deletion policy, and returns `COMPLETE`,
`INCOMPLETE`, or `NOT_APPLICABLE` with ordered FINDING → REMEDIATION → VERIFICATION steps.

Challenge and submission URL:
https://www.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists

---

## Setup

**Requirements:** Python 3.10 or later. No external packages are needed.

The pipeline uses only the Python standard library: `csv`, `json`, `re`, `sqlite3`, `pathlib`,
`datetime`, `hashlib`, `collections`. There is no `requirements.txt` and nothing to install.

```bash
# Clone and enter the repo
git clone <repo-url>
cd hackerrank-orchestrate-october26
```

---

## Running the Solution

From the **repository root**:

```bash
python -I code/main.py
```

The `-I` flag isolates the interpreter from the working directory (prevents accidental `.pth` or
`sitecustomize` interference). The solution reads all inputs from `dataset/` and writes `output.csv`
to the repository root.

Progress is printed every 50 cases. The run completes in under 60 seconds on a laptop.

**Running the evaluation harness** (32 public sample cases):

```bash
python -I code/evaluation/main.py
```

**Running the three custom evaluation cases:**

```bash
python -I code/evaluation/custom_cases.py
```

---

## Zero Model Calls

**This solution makes zero LLM API calls.** No API key is required. No network access is needed.

All 518 cases are processed by deterministic Python:

| Stage | Implementation |
|---|---|
| Intent classification | Keyword regex fast-path; LLM fallback never triggered |
| Evidence parsing | `sqlite3` for SQL, `json.load` for JSON, regex for logs and text |
| State reconstruction | Timestamp-ordered selection from indexed evidence records |
| Policy application | Rule lookup against `dataset/deletion_rules.csv` |
| Step planning | Deterministic phase/operation/system/resource ordering |

Because the code path for PDF and image parsing (via the `anthropic` SDK) is implemented but was
never reached on the final run, no LLM cache entries exist and no API key is required to reproduce
the results.

---

## Architecture

```
code/
├── main.py                    # Orchestrator: loads data, runs pipeline, writes output.csv
└── pipeline/
    ├── __init__.py            # Dataclasses: UserIdentity, EvidenceRecord, ResourceState,
    │                          #   PolicyDecision, Step
    ├── identity_resolver.py   # Resolves current + historical email/phone from CSV files
    ├── intent_classifier.py   # Keyword regex → DELETION or NOT_APPLICABLE
    ├── activity_scanner.py    # Reads system_activity.csv; resolves linked resource IDs
    ├── evidence_indexer.py    # Parses all 94 evidence files; indexes by identity + resource
    ├── state_reconstructor.py # Selects best evidence per resource at audit_at
    ├── policy_engine.py       # Applies deletion_rules.csv to each ResourceState
    ├── step_planner.py        # Produces ordered FINDING/REMEDIATION/VERIFICATION steps
    ├── output_validator.py    # Validates output rows before writing
    └── llm_client.py          # llm_client.py contains optional LLM fallbacks for PDF, image and ambiguous-intent handling. In the final run none are reached (0 calls); only UsageTracker is used to report usage.
```

**Evidence indexing** (`evidence_indexer.py`) is the largest module. It dispatches by file
extension: `.sql` → `sqlite3`, `.json` → pattern-matched JSON, `.log` → JSON-per-line or key=value
regex, `.txt` → pipe-delimited. The indexer operates in three phases:

- **Phase 1 (on-time):** Only files where `captured_at ≤ audit_at`. Records matched by identity
  identifiers (email, phone, email hash, user_id, account_id).
- **Phase 2 (late-file identity discovery):** Files captured after `audit_at` are used to discover
  resource IDs associated with the user, then the best on-time record for each newly found resource
  is used for state. Late files are never cited as evidence.
- **Phase 3 (batch co-location):** Anonymized analytics records with null PII fields are linked to
  users via consecutive `DELETE_RECORD` + `ANONYMIZE_RECORD` batches in `system_activity.csv`
  (LIFO order).

---

## Design Notes

The initial plan specified separate pipeline modules as the primary deliverable. During development,
all modules were implemented as planned. Tasks 7–12 in the task tracker were cancelled at submission
time not because the modules were skipped, but because all planned modules exist in `code/pipeline/`
and are complete — no further module refactor was needed.

---

## Known Limitations

### 1. Unresolved Account ID Cases

For ~13 of the 32 sample cases the pipeline uses a naming-convention fallback
(`user_NNN → account_NNN`, zero-padded to three digits) because no participant-visible evidence
directly links the `user_id` to a real account_service resource ID. The three evidence-based lookup
rules (snapshot bundle `customer_reference`, SQL search `source_resource_id`, trace-log
`profile_lookup_completed` trace pairing) resolve many but not all cases.

Cases still affected: 03, 09, 17, 18, 21, 22, 23, 25, 28, 29, 30, 31, 32.

### 2. Naming-Convention Fallback

When no evidence-based account ID lookup succeeds, the pipeline derives
`account_id = "account_" + user_number.zfill(3)` (e.g., `user_050 → account_050`). This is
correct for early users but wrong for users with arbitrary assigned account IDs. A code comment
in `evidence_indexer.py` (`resolve_account_id`) marks this as last-resort only.

### 3. File-Level `captured_at` Interpretation

Evidence files are timestamped with a single `captured_at` field in `evidence_files.csv`. This
timestamp is treated as the capture time for the entire file. Records within a file may have their
own event timestamps (log entries, SQL row timestamps), which are also checked. When a file arrives
late (captured after `audit_at`) it is excluded from Phase 1 entirely; individual records within it
that pre-date `audit_at` are accessible only via Phase 2 identity discovery.

### 4. Late-Captured Files Used for Identity Linking but Never Cited as Evidence

A late file (captured after `audit_at`) may contain records that establish which resource IDs belong
to the user. The pipeline uses this identity signal (Phase 2) to discover the resource, then looks
for an on-time record to determine state. If no on-time record exists, the resource is included with
`evidence_file_id = ""`. Such resources cannot be cited as FINDING evidence and are filtered from
violations (`d.resource_state.evidence_file_id` guard in `main.py`). This is semantically correct
but means some real violations are missed when the only evidence is in late files.

### 5. Batch Co-location Heuristic for Anonymous Analytics

Anonymized analytics records have all PII fields set to NULL. The pipeline links them to users by
matching consecutive `DELETE_RECORD` account events to the `ANONYMIZE_RECORD` analytics events that
immediately follow in `system_activity.csv`, using LIFO (last-deleted account gets first analytics).
This heuristic works for cases 26 and some of 27/28 but is imprecise when the activity stream order
does not reflect actual per-user assignment.

**case_27 still mismatches:** The pipeline assigns analytics_6077 to user_27 but the expected answer
is analytics_4574. The LIFO order from `system_activity.csv` does not match the actual assignment.

**case_12 still mismatches:** analytics_9914 is classified as `ANALYTICS_PROFILE` (ANONYMIZE policy)
because its state record comes from a SQL `customer_analytics_profiles` table. The expected output
treats it as a marketing contact record requiring DELETE. The `contact_lookup_completed` log-event
fix (which maps to `MARKETING_PROFILE`) only applies to log-parsed records, not SQL-table records.

---

## Output

`output.csv` is written to the repository root with the exact header:

```
case_id,deletion_status,steps_json
```

518 data rows, sorted numerically by `case_id`. All `steps_json` values are valid JSON arrays with
consecutive `step_no` values starting at 1. All cited `evidence_id` values exist in
`dataset/evidence_files.csv` and were captured at or before the case's `audit_at`. Every
`NOT_APPLICABLE` case has `steps_json=[]`.

Final status distribution: **COMPLETE 206 / INCOMPLETE 302 / NOT_APPLICABLE 10**.

---

## Packaging

To rebuild `code.zip` from the repository root:

```bash
# macOS / Linux
zip -r code.zip README.md code \
  --exclude "*/__pycache__/*" \
  --exclude "*/.evidence_cache/*" \
  --exclude "*/.llm_cache/*" \
  --exclude "*/.pytest_cache/*" \
  --exclude "*/*.pyc" \
  --exclude "*/.venv/*" \
  --exclude "*/venv/*" \
  --exclude "*/.env" \
  --exclude "*/.env.*" \
  --exclude "*/.git/*" \
  --exclude "*/.claude/*"
```

```powershell
# Windows PowerShell (run from repo root)
$exclude = @('__pycache__', '.evidence_cache', '.llm_cache', '.pytest_cache', '.venv', 'venv', '.git', '.claude')
# Use 7-Zip or the zip command via Git Bash for reliable exclusion
```

Do **not** include `dataset/`, virtual environments, caches, `__pycache__`, secrets, or nested archives.
