# Evaluation Report — Ghost Data Still Exists

## 1. Case-Level Deletion-Status Accuracy

Evaluated against `dataset/sample_output.csv` (32 public cases).

Run command: `python -I code/evaluation/main.py` from repo root.

| Metric | Score |
|---|---|
| Deletion-status accuracy | **32/32 (100%)** |
| Exact step-sequence match | **17/32 (53.1%)** |
| Overall field accuracy | **95.7%** |

All 32 sample cases produce the correct `deletion_status`
(`COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`).

## 2. Step-Level and Field-Level Accuracy

Steps compared position-by-position up to `min(expected_length, actual_length)`.

| Field | Correct | Total compared | Accuracy |
|---|---|---|---|
| `phase` | 186 | 186 | 100.0% |
| `system_id` | 178 | 186 | 95.7% |
| `resource_id` | 166 | 186 | 89.2% |
| `operation` | 178 | 186 | 95.7% |
| `state` | 178 | 186 | 95.7% |
| `evidence_id` | 182 | 186 | 97.8% |
| **Overall** | **1068** | **1116** | **95.7%** |

## 3. Sequence Accuracy

17 of 32 cases match the expected step sequence exactly (step order, all fields).
The 15 cases with discrepancies fall into these categories:

| Category | Cases affected |
|---|---|
| Wrong account resource_id (naming-convention fallback, no evidence link) | 10 |
| Missing analytics ANONYMIZED step (null-PII analytics, batch heuristic partial) | 4 |
| Wrong analytics data_category (case_12: ANONYMIZE vs DELETE) | 1 |

## 4. Identified Failures and Root Causes

### 4.1 Analytics ANONYMIZED Records Not Linked to Users

**Affected cases:** case_03, case_04, case_27, case_28
**Root cause:** After anonymization, analytics records have all PII fields set to NULL. Identity-based
matching finds nothing. A batch co-location heuristic links these to users via `system_activity.csv`:
consecutive `DELETE_RECORD` account events are matched LIFO to the `ANONYMIZE_RECORD` analytics events
that follow in the global activity stream. This works for some cases but fails when the
LIFO pairing order does not align with the actual user-to-record assignment (case_27 gets
analytics_6077 instead of analytics_4574; case_03 and case_04 have no evidence-based mapping).

### 4.2 Wrong Account Service Resource IDs

**Affected cases:** case_09, case_17, case_18, case_20, case_21, case_22, case_23, case_25, case_28,
case_29, case_30, case_31, case_32
**Root cause:** When no participant-visible evidence links a `user_NNN` to an actual account_service
resource ID, the pipeline falls back to a naming convention: `user_NNN → account_NNN` (zero-padded
to three digits). This is correct for users 01–09 but wrong for users with arbitrary IDs (e.g.,
user_050 → expected account_5037, not account_050). Evidence-based lookups (snapshot bundle
`customer_reference`, SQL search `source_resource_id`, trace-log `profile_lookup_completed` pairing)
resolve some cases but not all.

### 4.3 Wrong Analytics Data Category (case_12)

**Affected case:** case_12 (`analytics_9914`)
**Root cause:** The event_meta dict maps `contact_lookup_completed` log events to `MARKETING_PROFILE`
(DELETE policy). However, analytics_9914's authoritative state record comes from a SQL
`customer_analytics_profiles` table (not a log event), so the table→system mapping applies and the
record is classified as `ANALYTICS_PROFILE` (ANONYMIZE policy) instead. The expected output uses
DELETE, indicating this record should be treated as a marketing contact record.

## 5. Improvements Made During Development

1. **PDF parsing fixed:** Added `pypdf` extraction before LLM fallback. Stale empty LLM caches for
   5 evidence files were deleted. This recovered evidence_58 (support attachment), which fixed case_07
   deletion_status from COMPLETE → INCOMPLETE.

2. **SUPPORT_ATTACHMENT vs SUPPORT_MESSAGE detection:** Added filename-based detection
   (`"attachment"` in stem). Attachment files require DELETE; message files require REDACT. Further
   improved case_07 step accuracy.

3. **Ghost data detection:** SQL files with both a primary and failover-replica table correctly
   identify records present in the replica but absent from the primary as PRESENT (ghost state).
   Correctly handles case_05 and similar.

4. **Account ID lookup tables:** Implemented three evidence-based lookup rules:
   (1) snapshot bundle `customer_reference` links user_id to account_id;
   (2) SQL search table `source_resource_id` links email to account_id;
   (3) trace log `profile_lookup_completed` events pair email with account_id via trace_id.
   Naming-convention fallback (`user_NNN → account_NNN`) used only when no data rule matches.
   Improved resource_id accuracy from ~71% to 89.2%.

5. **`audit_at` strict cutoff:** Evidence files captured after `audit_at` are excluded from Phase 1
   state reconstruction. Late files are used only to discover resource identity (Phase 2), never as
   citable evidence.

6. **Batch co-location heuristic:** Added `_build_batch_analytics_map` in `evidence_indexer.py` that
   parses `system_activity.csv` to find consecutive `DELETE_RECORD` account batches followed by
   `ANONYMIZE_RECORD` analytics events. LIFO pairing links the last-deleted account's analytics first.
   Improved analytics ANONYMIZED coverage for cases 26 and 27 (partial).

7. **Empty evidence_id violation filter:** Violations with no on-time evidence citation
   (`evidence_file_id == ""`) are excluded from the INCOMPLETE findings. This fixed case_70, which
   had a false PRESENT finding based on a stale late-file record while the Sep 16 audit showed
   deletion complete.

8. **Support PII detection gaps fixed:** Three general parsing gaps corrected:
   - `message_pii_scan` log event added to `event_meta` → support records found via PII scans now indexed
   - `_is_pii_exposed` for SUPPORT_MESSAGE extended to check `email` and `matched_value` fields
     (txt parser stores email as `raw["email"]`; log events use `matched_value`)
   - `ticket_attachments` and `support_conversations` collections added to `collection_meta` in
     `_parse_snapshot_bundle`
   Fixed case_11 and case_19. Field accuracy improved from 90.0% to 95.7%.

9. **INCOMPLETE VERIFY_RECORD_ABSENT on account_service synthesized:** Every INCOMPLETE case now
   emits a `VERIFY_RECORD_ABSENT` step on `account_service`, even when no evidence file directly
   references the account. Resource ID uses data-derived lookup (Rules 1–2) then naming-convention
   fallback. evidence_id is always `""` for the synthesized step (no on-time proof). This was
   confirmed by sample_output.csv (22/22 INCOMPLETE cases include this step). Fixed 212 validation
   errors. Field accuracy and status accuracy unchanged.

## 6. Validation

The full 518-case run passes all validator checks with **0 errors**. Checks include:
- Exact 518 rows, sorted numerically by case_id
- Valid `deletion_status` values
- `NOT_APPLICABLE` → empty steps
- `step_no` consecutive from 1
- Phase ordering (FINDING → REMEDIATION → VERIFICATION)
- COMPLETE → all steps VERIFICATION
- INCOMPLETE → all three phases present
- evidence_id rules (FINDING non-empty, REMEDIATION empty, INCOMPLETE VERIFY empty, COMPLETE VERIFY non-empty)
- INCOMPLETE has at least one `VERIFY_RECORD_ABSENT` on `account_service`
- All operations from the allowed set of 15

Note: All prior runs (from the first complete pipeline commit) produced 178–215 validation errors
for check 10, printed to stderr. The errors were not surfaced in earlier console summaries because
`main.py` now calls `sys.exit(1)` when errors remain — previously errors printed to stderr only.

## 7. Additional Evaluation Cases

Three custom cases test edge conditions not covered by the 32 public samples.
Run via `python -I code/evaluation/custom_cases.py`. Result: **3/3 PASS**.

---

### Custom Case A — Non-Deletion Request (NOT_APPLICABLE)

**Subject:** `o.walker66@yahoo.com` (user_523)
**Request text:** `"I would like to receive a copy of all personal data you hold about me in a portable format."`
**audit_at:** 2026-10-01T12:00:00Z

**Rationale:** Contains `copy`, `portable format`, `data` — NOT_APPLICABLE keywords. No deletion
language. Intent classifier fast-path must return NOT_APPLICABLE without an LLM call.

**Expected:** `NOT_APPLICABLE`, `steps_json=[]`

**Actual output:**

| Field | Value |
|---|---|
| `deletion_status` | `NOT_APPLICABLE` |
| `steps_json` | `[]` |
| Fast-path hit | Yes (no LLM call) |

**Result: PASS** — Fast-path correctly short-circuits. No evidence lookup performed.

---

### Custom Case B — Historical-Email-Only Resolution

**Subject:** `o.walker6695@yahoo.com` — old email of user_523 (current: `o.walker66@yahoo.com`)
**Request text:** `"Please delete my account and all associated personal data immediately."`
**audit_at:** 2026-10-01T12:00:00Z

**Rationale:** Email in request no longer exists as current identity. `identity_resolver` must find
user_523 via `user_audit_log` `old_value` lookup and produce identical state to current-email run.

**Actual output:** `INCOMPLETE`, user_id=user_523 resolved. Steps identical to current-email run.

Steps:

| # | Phase | system_id | resource_id | operation | state | evidence_id |
|---|---|---|---|---|---|---|
| 1 | FINDING | account_service | account_4974 | REPORT_REMAINING_RECORD | PRESENT | evidence_49 |
| 2 | REMEDIATION | account_service | account_4974 | DELETE_RECORD | ABSENT | `` |
| 3 | VERIFICATION | account_service | account_4974 | VERIFY_RECORD_ABSENT | ABSENT | `` |
| 4 | VERIFICATION | security_service | audit_record_3803 | VERIFY_RECORD_PRESENT | PRESENT | `` |

**Result: PASS** — Historical-email resolution works correctly via `user_audit_log`.

---

### Custom Case C — COMPLETE: Restore Risk Blocked, Data Flow Disabled

**Subject:** `lucas-souza95@gmail.com` (user_39)
**Request text:** `"Please erase the account linked to this email address."`
**audit_at:** 2026-10-01T12:00:00Z

**Rationale:** At audit_at: account absent, backup BLOCKED, data flow DISABLED, support REDACTED,
security audit PRESENT. Zero violations → COMPLETE. Both `VERIFY_RESTORE_BLOCKED` and
`VERIFY_DATA_FLOW_DISABLED` must appear.

**Actual output:** `COMPLETE`, 5 VERIFICATION steps.

| # | Phase | system_id | resource_id | operation | state | evidence_id |
|---|---|---|---|---|---|---|
| 1 | VERIFICATION | account_service | account_4051 | VERIFY_RECORD_ABSENT | ABSENT | evidence_03 |
| 2 | VERIFICATION | security_service | audit_record_7814 | VERIFY_RECORD_PRESENT | PRESENT | evidence_03 |
| 3 | VERIFICATION | support_platform | support_2667 | VERIFY_RECORD_REDACTED | REDACTED | evidence_03 |
| 4 | VERIFICATION | integration_service | data_flow_2901 | VERIFY_DATA_FLOW_DISABLED | DISABLED | evidence_03 |
| 5 | VERIFICATION | backup_service | backup_706 | VERIFY_RESTORE_BLOCKED | BLOCKED | evidence_03 |

**Result: PASS** — COMPLETE path emits all required verification ops with real evidence citations.
