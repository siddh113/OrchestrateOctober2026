# Deletion-Audit Pipeline Design

## Context

Build `code/main.py` (entry point) and supporting modules to process 518 deletion-audit cases and produce `output.csv`. Both `code/main.py` and `code/evaluation/main.py` are currently empty. The pipeline must: classify intent, resolve identity (current + historical), parse 94 evidence files to reconstruct true resource state at `audit_at`, apply 15 deletion policy rules, and generate deterministically-ordered FINDING → REMEDIATION → VERIFICATION steps.

Key constraint: use LLM only for PDF content, image/screenshot content, and ambiguous/non-English intent classification. Everything else is pure Python.

---

## Approaches (chosen from three)

| Approach | LLM calls | Cost | Determinism | Chosen |
|---|---|---|---|---|
| **A: Deterministic pipeline + LLM at boundaries** | ~30 (cached after first run) | <$1 | Full | ✅ |
| B: LLM reasoner per case | ~518 × 30K tokens | $50–200 | None | ✗ |
| C: Hybrid with LLM per resource | ~3000 | ~$10 | Partial | ✗ |

**Chosen: Approach A.** The user specified exactly this. Structured evidence (SQL, JSON, logs) is unambiguous when parsed by code. LLM adds cost and non-determinism with no accuracy benefit for machine-readable formats.

---

## File Layout

```
code/
├── main.py                          ← orchestrator
├── pipeline/
│   ├── __init__.py                  ← all dataclasses
│   ├── identity_resolver.py
│   ├── intent_classifier.py
│   ├── activity_scanner.py
│   ├── evidence_indexer.py          ← largest module
│   ├── state_reconstructor.py       ← hardest logic
│   ├── policy_engine.py
│   ├── step_planner.py
│   ├── llm_client.py
│   └── output_validator.py
├── evaluation/
│   └── main.py                      ← compare vs sample_output.csv
├── .evidence_cache/                 ← gitignored, one JSON per evidence file
└── .llm_cache/                      ← gitignored, one JSON per LLM call (keyed by sha256)
requirements.txt                     ← anthropic>=0.34.0 only
```

---

## Dataclasses (`pipeline/__init__.py`)

```python
@dataclass
class UserIdentity:
    user_id: str                 # "user_01"
    current_email: str
    all_emails: set[str]         # current + all historical (lowercase)
    all_phones: set[str]         # current + all historical
    name: str
    email_hash: str

@dataclass
class EvidenceRecord:
    file_id: str                 # "evidence_54"
    resource_id: str             # "account_005"
    system_id: str               # "account_service"
    state: str                   # PRESENT/ABSENT/ANONYMIZED/REDACTED/ACTIVE/BLOCKED/DISABLED
    data_category: str           # USER_PROFILE/SEARCH_INDEX_ENTRY/etc.
    captured_at: datetime        # from evidence_files.csv (file-level, not per-record)
    raw_fields: dict             # full parsed row for condition evaluation

@dataclass
class ResourceState:
    resource_id: str
    system_id: str
    state: str
    evidence_file_id: str        # the specific evidence file proving this state
    data_category: str
    raw_fields: dict

@dataclass
class PolicyDecision:
    resource_state: ResourceState
    required_action: str         # DELETE/REDACT/ANONYMIZE/RETAIN/BLOCK_RESTORE
    is_violation: bool
    finding_operation: str       # REPORT_REMAINING_RECORD/REPORT_EXPOSED_PII/etc.
    finding_state: str           # PRESENT or ACTIVE
    remediation_operation: str
    remediation_state: str       # ABSENT/REDACTED/ANONYMIZED/DISABLED/BLOCKED
    verification_operation: str
    verification_state: str

@dataclass
class Step:
    step_no: int
    phase: str                   # FINDING/REMEDIATION/VERIFICATION
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str             # non-empty for FINDING + COMPLETE VERIFY; "" otherwise
```

---

## Module Specifications

### `pipeline/llm_client.py`

Three public functions only. All results cached to `.llm_cache/{sha256}.json`.

```python
def extract_pdf(file_path: str) -> str     # claude-sonnet-4-6 with document block
def extract_image(file_path: str) -> str   # claude-sonnet-4-6 with image block
def classify_intent(request_text: str) -> str  # claude-haiku-4-5, returns "DELETION"|"NOT_APPLICABLE"
```

Cache key: `sha256(f"{function_name}:{file_sha256}")` for files; `sha256(f"intent:{text_sha256}")` for intent.

**UsageTracker singleton** — accumulates per-call `{model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd}`. Pricing (claude-sonnet-4-6): input $3/1M, output $15/1M, cache_write $3.75/1M, cache_read $0.30/1M. Haiku: $0.80/$4.00 per 1M.

Mark system prompt with `cache_control={"type": "ephemeral"}` for prompt caching.

---

### `pipeline/identity_resolver.py`

```python
class IdentityResolver:
    def resolve(self, email: str) -> UserIdentity
```

**Algorithm:**
1. Normalize email to lowercase.
2. Lookup in `user_identities.csv` by current email → `match_type=current`.
3. If miss: lookup in `user_audit_log.csv` old_value (field_name='email') → find user_id → `match_type=historical`.
4. From audit log, collect all old email values for that user_id (handles two-hop chains naturally).
5. Collect all old phone values similarly.
6. Return `UserIdentity` with `all_emails` = current + all historical, `all_phones` = current + all historical.

**Confirmed:** 3 historical matches in samples — case_10 (two-hop), case_29, case_30 (single-hop each).

---

### `pipeline/intent_classifier.py`

```python
def classify(request_text: str) -> str  # "DELETION" | "NOT_APPLICABLE"
```

**Fast path (keyword regex, handles ~95%):**
- Deletion keywords: `\bdelete\b`, `\berase\b`, `\bclose\s+my\s+account\b`, `\bsupprimer\b`, `\beliminar\b`, `削除`, `消去`, `退会`, etc.
- NOT_APPLICABLE keywords: `\bdata\s+access\b`, `\bopt.out\b`, `\bunsubscribe\b`, `\bcorrection\b`, `\brequest\s+a\s+copy\b`
- Deletion wins if both match.
- LLM fallback only when neither pattern matches.

**LLM prompt:** single-sentence system + `"Classify: {text}"` → returns `DELETION` or `NOT_APPLICABLE`.

---

### `pipeline/activity_scanner.py`

```python
class ActivityScanner:
    def get_linked_resources(self, identity: UserIdentity) -> list[dict]  # LINK_RESOURCE_IDENTITY rows
    def get_ghost_signals(self, resource_id: str, audit_at: datetime) -> list[dict]
```

Load `system_activity.csv` once. Build:
- `_link_by_email`: email → `[{resource_id, user_id, activity_id, target_system}]`
- `_link_by_user_id`: user_id → same
- `_by_resource_id`: resource_id → all rows

**Parse LINK_RESOURCE_IDENTITY details:**
- Standard: `r'to (.+?) and (user_\d+)'` → (email, user_id)
- Attachment: `r'belongs only to (.+?) and (user_\d+)'` → (email, user_id)

**Ghost signal patterns** (for documentation, state comes from evidence):
- SYNC_RECORD after DELETE = replication drift risk
- DELETE with PARTIAL/FAILED = incomplete
- RESTORE_BACKUP = recreation risk
- REDACT with FAILED = tombstone PII exposed

---

### `pipeline/evidence_indexer.py` *(largest module)*

```python
class EvidenceIndexer:
    def build(self, evidence_files_manifest: list[dict])
    def get_records_for_identity(self, identity: UserIdentity, audit_at: datetime) -> list[tuple[str, EvidenceRecord]]
```

**Cache:** `.evidence_cache/{file_id}_{sha256[:8]}.json`. If file unchanged, load from cache. Otherwise parse + write.

**Parser dispatch by extension:**

| Extension | Parser |
|---|---|
| `.sql` | `sqlite3.connect(":memory:")` → query all tables |
| `.json` | `json.load()` → dispatch by filename pattern |
| `.log` | key=value regex OR JSON-per-line OR pipe-delimited |
| `.txt` | pipe-delimited (`timestamp \| system_id \| resource_id \| type \| STATUS \| identifier`) |
| `.pdf` | `llm_client.extract_pdf()` → parse extracted text |
| `.png` | `llm_client.extract_image()` → parse extracted text |

**SQL table → system_id + data_category mapping:**
- `customer_profiles_primary` / `customer_profiles_failover_replica` / `customer_profiles` → `account_service`, `USER_PROFILE`
- `customer_search_documents` / `search_documents_primary` → `search_service`, `SEARCH_INDEX_ENTRY`
- `customer_analytics_profiles` / `customer_analytics_reports` → `analytics_platform`, `ANALYTICS_PROFILE`
- `support_records` / `support_conversations` → `support_platform`, `SUPPORT_MESSAGE`
- `customer_exports` → `export_service`, `USER_EXPORT`
- `connector_subscriptions` / `connector_configurations` → `integration_service`, `DATA_FLOW`
- `backup_restore_entries` / `backup_catalog` → `backup_service`, `BACKUP_ARCHIVE`
- `security_audit_records` / `security_audit_events` → `security_service`, `SECURITY_AUDIT_LOG`
- `deleted_customer_references` → `identity_service`, `ACCOUNT_TOMBSTONE`
- Tables with `record_json` column → parse embedded JSON, re-dispatch by collection_name

**State derivation:**
- Account: row present = PRESENT; absent = ABSENT; `account_status='DELETION_PENDING'` = PRESENT (not done)
- Analytics: any of `email/phone/email_hash/customer_reference` non-null = PRESENT; all null = ANONYMIZED
- Support: `requester_email` or `requester_phone` non-null = PRESENT; all null = REDACTED
- Integration: `enabled=1/true` = ACTIVE; `enabled=0/false` = DISABLED
- Backup: `restore_allowed=1/true` = ACTIVE; `restore_allowed=0/false` = BLOCKED
- Tombstone (`identity_service`): any of `name/email/phone/email_hash` non-null = PRESENT (PII exposed); all null = REDACTED (compliant)
- Security: row present = PRESENT (always)

**Ghost data in multi-table SQL:**
- `customer_profiles_failover_replica` has row BUT `customer_profiles_primary` does NOT → ghost, state=PRESENT, tag `raw_fields["ghost"]=True`
- Same logic for `customer_data_read_replica` vs `customer_data_primary`

**JSON filename patterns:**
- `service_resource_export_*`: multi-service export; `status_code=404`→ABSENT, `status_code=200`→PRESENT, `restore_allowed=false`→BLOCKED, `enabled=false`→DISABLED, null PII fields→ANONYMIZED
- `customer_data_snapshot_bundle_*`: named collections; same state logic
- `customer_analytics_report_*`: records array, null PII = ANONYMIZED
- `security_audit_ledger_*`: records with `subject_reference`, always PRESENT

**Log formats:**
- Format A (key=value): `r'(\w+)=("(?:[^"]*)"|[^\s]+)'` per line. Events: `profile_lookup_completed rows=0`→ABSENT, `index_query_completed result=hit`→PRESENT, `analytics_identity_scan matched_value=X`→PRESENT, `connector_heartbeat enabled=true`→ACTIVE, `restore_candidate_evaluated eligible=true deletion_block=false`→ACTIVE, `message_pii_scan matched_value=X`→PRESENT
- Format B (JSON-per-line): `timestamp {json}` → parse JSON, same event dispatch
- Format C (pipe-delimited): `timestamp | system_id | resource_id | type | STATUS | identifier` → STATUS maps: NOT_FOUND→ABSENT, FOUND→PRESENT, IDENTIFIABLE→PRESENT, ACTIVE→ACTIVE, DISABLED→DISABLED, BLOCKED→BLOCKED, REDACTED→REDACTED, ANONYMIZED→ANONYMIZED

**Identifier extraction:** For each parsed record, collect into `raw_fields["identifiers"]`: any field named `email`, `owner_email`, `requester_email`, `customer_email`, `lookup_key`, `matched_value`, `subject_reference`, `customer_reference` that is an email address or `user_\d+` pattern.

---

### `pipeline/state_reconstructor.py` *(hardest)*

```python
class StateReconstructor:
    def reconstruct(self, identity: UserIdentity, audit_at: datetime) -> list[ResourceState]
```

**Exact algorithm:**

1. Build identity set: `all_emails` (lowercase), `all_phones`, `{user_id, email_hash}`.
2. Build `linked_resource_ids` from `activity_scanner.get_linked_resources(identity)`.
3. For each evidence file where `captured_at <= audit_at`:
   - For each `EvidenceRecord` in file:
     - Check if any `raw_fields["identifiers"]` entry matches the identity set (case-insensitive for emails).
     - OR `record.resource_id` in `linked_resource_ids`.
     - If match: add to `candidates[resource_id].append((captured_at, file_id, record))`.
4. For each resource_id in candidates:
   - Sort entries by `captured_at` descending.
   - **Ghost handling:** If any entry has `raw_fields["ghost"]=True` AND another entry from the same file has state=ABSENT → prefer the ghost (PRESENT) entry.
   - Otherwise: take entry with latest `captured_at` (most authoritative state before audit_at).
   - Emit one `ResourceState` per resource_id.
5. **`captured_at` tie-breaking:** When two files have same `captured_at`, prefer the one that explicitly shows the resource_id in a structured lookup (e.g., `service_resource_export` > generic `snapshot_bundle`).
6. Return deduplicated `list[ResourceState]`.

**Evidence selection rule (CONFIRMED from 32 samples):** The citation is NOT "most recent file before audit_at" globally — it is the specific file that **directly contains** that resource_id, from the latest eligible captured_at. A case may cite different evidence files for different systems.

---

### `pipeline/policy_engine.py`

```python
class PolicyEngine:
    def apply(self, rs: ResourceState, identity: UserIdentity, audit_at: datetime) -> PolicyDecision
```

**Decision table:**

| data_category | required_action | Violation when | finding_op | remediation_op | verification_op |
|---|---|---|---|---|---|
| USER_PROFILE | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| SECONDARY_IDENTIFIER | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| SEARCH_INDEX_ENTRY | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| CACHE_ENTRY | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| SUPPORT_MESSAGE | REDACT | state=PRESENT (PII exposed) | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| SUPPORT_ATTACHMENT | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| ANALYTICS_PROFILE | ANONYMIZE | state=PRESENT (PII exposed) | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| PRODUCT_TELEMETRY | ANONYMIZE | state=PRESENT (PII exposed) | REPORT_EXPOSED_PII | ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| USER_EXPORT | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| MARKETING_PROFILE | DELETE | state=PRESENT | REPORT_REMAINING_RECORD | DELETE_RECORD | VERIFY_RECORD_ABSENT |
| EMAIL_DELIVERY_LOG | REDACT | state=PRESENT | REPORT_REMAINING_RECORD | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| SECURITY_AUDIT_LOG | RETAIN | never | — | — | VERIFY_RECORD_PRESENT |
| LEGAL_HOLD_RECORD | RETAIN | never | — | — | VERIFY_RECORD_PRESENT |
| BACKUP_ARCHIVE | BLOCK | state=ACTIVE | REPORT_RESTORE_RISK | BLOCK_RESTORE | VERIFY_RESTORE_BLOCKED |
| ACCOUNT_TOMBSTONE | REDACT | state=PRESENT (PII exposed) | REPORT_EXPOSED_PII | REDACT_RECORD | VERIFY_RECORD_REDACTED |
| DATA_FLOW | DISABLE | state=ACTIVE | REPORT_ACTIVE_DATA_FLOW | DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED |

**Condition evaluation shortcuts (from sample analysis):**
- ANALYTICS/TELEMETRY: `is_violation = any(raw_fields[f] not in (None,"") for f in ("email","phone","email_hash","customer_reference","user_id"))`
- TOMBSTONE: same check for `name, email, phone, email_hash`
- SECURITY_AUDIT_LOG: always RETAIN; check `retention_until > audit_at` if field present
- BACKUP_ARCHIVE: `is_violation = (state == "ACTIVE")` i.e., `restore_allowed=True`
- DATA_FLOW: `is_violation = (state == "ACTIVE")` i.e., `enabled=True`

Compliant states (no violation): ABSENT, ANONYMIZED, REDACTED, BLOCKED, DISABLED → no finding/remediation needed, but generate a VERIFY step.

---

### `pipeline/step_planner.py`

```python
def plan(
    violations: list[PolicyDecision],
    compliant_resources: list[ResourceState],
    deletion_status: str,
    account_resource: ResourceState,      # the account_service record (state=ABSENT)
    security_resource: Optional[ResourceState],  # security_service audit record, if any
) -> list[Step]
```

**Ordering constants:**
```python
FINDING_ORDER = {"REPORT_REMAINING_RECORD":1, "REPORT_EXPOSED_PII":2, "REPORT_ACTIVE_DATA_FLOW":3, "REPORT_RESTORE_RISK":4}
REMEDIATION_ORDER = {"DISABLE_DATA_FLOW":1, "BLOCK_RESTORE":2, "DELETE_RECORD":3, "REDACT_RECORD":4, "ANONYMIZE_RECORD":5}
VERIFICATION_ORDER = {"VERIFY_RECORD_ABSENT":1, "VERIFY_RECORD_PRESENT":2, "VERIFY_RECORD_REDACTED":3, "VERIFY_RECORD_ANONYMIZED":4, "VERIFY_DATA_FLOW_DISABLED":5, "VERIFY_RESTORE_BLOCKED":6}
```
Sort key for all phases: `(operation_priority, system_id, resource_id)` — `system_id` is alphabetical (plain string sort gives correct order).

**COMPLETE case:** Build VERIFICATION steps only (evidence_id = non-empty):
- `VERIFY_RECORD_ABSENT` for account_service (from account_resource)
- `VERIFY_RECORD_PRESENT` for security_service (if exists)
- One `VERIFY_*` step per compliant resource (ANONYMIZED→ANONYMIZED, REDACTED→REDACTED, BLOCKED→RESTORE_BLOCKED, DISABLED→FLOW_DISABLED)
- Each step cites the specific `evidence_file_id` that proves it

**INCOMPLETE case:**
- Phase 1 FINDING: one step per violation, sorted by `FINDING_ORDER`, evidence_id = `violation.resource_state.evidence_file_id` (non-empty)
- Phase 2 REMEDIATION: one step per violation, sorted by `REMEDIATION_ORDER`, evidence_id = `""` always
- Phase 3 VERIFICATION: union of (account_service ABSENT) + (security PRESENT if exists) + (one per violation's verification_op) + (one per compliant resource's verify_op), all evidence_id = `""`, sorted by `VERIFICATION_ORDER`

**Invariants (ALL CONFIRMED from 32 samples):**
- `VERIFY_RECORD_ABSENT` on account_service appears in every case's VERIFICATION phase
- `VERIFY_RECORD_PRESENT` on security_service appears whenever a security audit record exists
- `DISABLE_DATA_FLOW` is always first in REMEDIATION block
- `BLOCK_RESTORE` is always before DELETE/REDACT/ANONYMIZE
- INCOMPLETE: all three phases always present, no exceptions
- COMPLETE: VERIFICATION only, no exceptions
- evidence_id rules: FINDING=non-empty, REMEDIATION="", INCOMPLETE VERIFY="", COMPLETE VERIFY=non-empty

---

### `pipeline/output_validator.py`

Validates before writing. Checks:
1. Exactly 518 rows
2. Sorted by case_id numerically (`int(case_id.split("_")[1])`)
3. `deletion_status` ∈ {COMPLETE, INCOMPLETE, NOT_APPLICABLE}
4. NOT_APPLICABLE → `steps_json = "[]"`
5. step_no consecutive from 1
6. Phase order: FINDING before REMEDIATION before VERIFICATION (no interleaving)
7. COMPLETE → all steps are VERIFICATION
8. INCOMPLETE → all three phases present
9. evidence_id empty for REMEDIATION; empty for INCOMPLETE VERIFICATION; non-empty for FINDING; non-empty for COMPLETE VERIFICATION
10. INCOMPLETE has at least one `VERIFY_RECORD_ABSENT` on account_service
11. All operation names are from the allowed set of 15

---

### `code/main.py` (orchestrator)

```python
def main():
    # Load CSVs once (deletion_requests, evidence_files manifest)
    # Initialize: IdentityResolver, ActivityScanner, EvidenceIndexer, IntentClassifier,
    #             StateReconstructor, PolicyEngine, StepPlanner, OutputValidator
    # EvidenceIndexer.build() — load/parse all 94 files (uses cache)
    # For each case:
    #   1. classify(request_text) → NOT_APPLICABLE shortcut
    #   2. resolve(email) → UserIdentity
    #   3. reconstruct(identity, audit_at) → list[ResourceState]
    #   4. apply(rs) for each → list[PolicyDecision]
    #   5. split violations vs compliant
    #   6. plan(violations, compliant, status, account_resource, security_resource) → list[Step]
    #   7. serialize to dict row
    # Sort output rows by case_id (numeric)
    # validate(output_rows)
    # Write output.csv
    # Print UsageTracker.get().summary()
```

Error handling: wrap each case in try/except; log error to stderr; fallback row = `NOT_APPLICABLE, []` so the run always produces 518 rows.

---

### `code/evaluation/main.py`

Compare output.csv against dataset/sample_output.csv for the 32 known cases:
- Case-level accuracy: `correct_status / 32`
- Step count match per case
- Field-level accuracy: per step field (phase, system_id, resource_id, operation, state, evidence_id)
- Sequence accuracy: steps in correct phase-then-operation-then-system-then-resource order
- Write `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md` at runtime

---

## Dependencies

```
# requirements.txt
anthropic>=0.34.0
```

Stdlib only otherwise: `csv`, `json`, `re`, `os`, `sys`, `sqlite3`, `hashlib`, `pathlib`, `datetime`, `dataclasses`, `collections`, `typing`, `base64`.

---

## LLM Usage Estimate

| Function | Files | Tokens/call | Total | Cost |
|---|---|---|---|---|
| extract_pdf | 4 PDFs | ~2K in + ~1K out | ~12K | ~$0.05 |
| extract_image | 11 PNGs | ~3K in + ~1K out | ~44K | ~$0.18 |
| classify_intent (ambiguous only) | ~20 cases | ~300 in + 10 out | ~6K | ~$0.01 |
| **Total first run** | | | **~62K** | **~$0.24** |
| **Subsequent runs (all cached)** | | | **0** | **$0.00** |

---

## Implementation Order

Build and test against `dataset/sample_output.csv` after each module:

1. `pipeline/__init__.py` — dataclasses
2. `pipeline/llm_client.py` — test: call extract_pdf on one PDF, verify cache written
3. `pipeline/identity_resolver.py` — test: all 32 sample emails resolve to correct user_ids (see `docs/sample_analysis.md §2.2`)
4. `pipeline/intent_classifier.py` — test: all 32 sample request texts → DELETION
5. `pipeline/activity_scanner.py` — test: `user_07` → `object_19`; `user_18` → `export_1260, export_1842`
6. `pipeline/evidence_indexer.py` — test incrementally:
   - evidence_54: account_005 in failover replica → PRESENT (ghost)
   - evidence_92: account_6440 status_code=404 → ABSENT
   - evidence_01: search_1874 result=hit → PRESENT
   - evidence_03: search_052 FOUND → PRESENT
7. `pipeline/state_reconstructor.py` — test: all 32 sample cases produce expected resource_ids and states
8. `pipeline/policy_engine.py` — test: violations match expected findings from sample_analysis.md
9. `pipeline/step_planner.py` — test: steps for 32 cases match sample_output.csv exactly
10. `pipeline/output_validator.py` — test: sample_output.csv itself passes validation
11. `code/main.py` — wire all together, run 32 sample cases, then all 518
12. `code/evaluation/main.py` — produce accuracy reports

---

## Critical Edge Cases

1. **Case-insensitive email matching** — normalize all emails to lowercase everywhere; some evidence stores uppercase emails
2. **`audit_at` strict upper bound** — `captured_at <= audit_at` (not `<`); millisecond precision; parse with `datetime.fromisoformat(...).replace(tzinfo=timezone.utc)`
3. **Ghost data in replica SQL** — record in failover/read_replica but absent from primary → emit as PRESENT ghost; this IS the finding
4. **Security audit records never violated** — `audit_record_*` always RETAIN; VERIFY_RECORD_PRESENT, never REPORT_REMAINING_RECORD
5. **Tombstone** — `REPORT_EXPOSED_PII` not `REPORT_REMAINING_RECORD`; `REDACT_RECORD` not `DELETE_RECORD`
6. **case_id numeric sort** — `int("33")` from `"case_33"`; not alphabetical
7. **Multiple evidence files per case** — COMPLETE case may cite different file_ids for different systems (case_04: evidence_54 for account, evidence_56 for analytics)
8. **NOT_APPLICABLE → `steps_json = "[]"`** — empty JSON array string
9. **ALL step fields present** — `evidence_id` key must exist in every step object even when value is `""`

---

## Critical Files

- `dataset/sample_output.csv` — ground truth for 32 cases
- `dataset/deletion_requests.csv` — 518 cases to process
- `dataset/evidence_files.csv` — manifest of 94 evidence files
- `dataset/system_activity.csv` — 4011 activity rows
- `dataset/deletion_rules.csv` — 15 policy rules
- `docs/sample_analysis.md` — confirmed patterns from tracing all 32 samples

---

## Verification

1. Run `python3 code/main.py` from repo root — should complete without errors and write `output.csv`
2. Check: `wc -l output.csv` = 519 (header + 518 rows)
3. Run `python3 code/evaluation/main.py` — should report >90% case accuracy on 32 samples
4. Spot-check case_05: `deletion_status=INCOMPLETE`, finding on account_005 with evidence_54
5. Spot-check case_31: `deletion_status=COMPLETE`, VERIFY_RECORD_REDACTED on identity_service/tombstone_440 with evidence_51
6. Run output_validator directly on output.csv — must pass all 11 checks with zero errors
