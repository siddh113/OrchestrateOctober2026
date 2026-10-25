# Evaluation Report — Ghost Data Still Exists

## 1. Case-Level Deletion-Status Accuracy

Evaluated against `dataset/sample_output.csv` (32 public cases).

| Metric | Score |
|---|---|
| Deletion-status accuracy | **32/32 (100%)** |
| Exact step-sequence match | **15/32 (46.9%)** |
| Overall field accuracy | **90.0%** |

All 32 sample cases produce the correct `deletion_status`
(`COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`).

## 2. Step-Level and Field-Level Accuracy

Steps were compared position-by-position up to `min(expected_length, actual_length)`.

| Field | Correct | Total compared | Accuracy |
|---|---|---|---|
| `phase` | 175 | 181 | 96.7% |
| `system_id` | 160 | 181 | 88.4% |
| `resource_id` | 148 | 181 | 81.8% |
| `operation` | 159 | 181 | 87.8% |
| `state` | 160 | 181 | 88.4% |
| `evidence_id` | 175 | 181 | 96.7% |
| **Overall** | **977** | **1086** | **90.0%** |

Expected total steps across 32 cases: **193**  
Generated total steps: **181** (missing 12 steps across 17 cases)

## 3. Sequence Accuracy

15 of 32 cases match the expected step sequence exactly (step order, all fields).  
The 17 cases with discrepancies fall into these categories:

| Category | Cases affected |
|---|---|
| Missing analytics ANONYMIZED step (null-PII analytics record not linked to user) | 7 |
| Wrong account resource_id (synthetic `account_NNN` vs real ID from evidence) | 6 |
| Missing search index entry (search evidence not indexed for user) | 4 |
| Missing support record (support evidence not linked to user) | 4 |
| Wrong analytics data_category (ANONYMIZE vs DELETE) | 1 |

## 4. Identified Failures and Root Causes

### 4.1 Analytics ANONYMIZED Records Not Linked to Users

**Affected cases:** case_03, case_04, case_21, case_25, case_26, case_27, case_28  
**Root cause:** Some analytics records (e.g., `analytics_9406`, `analytics_1895`) have all PII fields set to `NULL` in the evidence. These records cannot be matched to a specific user through identifier-based matching because there are no email/phone/user_id fields. The expected output assigns these null-PII records to specific users, suggesting a contextual or temporal assignment mechanism not available from evidence alone.  
**Impact:** COMPLETE cases missing 1 VERIFY_RECORD_ANONYMIZED step; INCOMPLETE cases missing the corresponding FINDING + REMEDIATION + VERIFICATION triple.

### 4.2 Wrong Account Service Resource IDs

**Affected cases:** case_18, case_20, case_21, case_22, case_23, case_25, case_28, case_29, case_30, case_31, case_32  
**Root cause:** When no explicit account evidence maps a `user_NNN` to a real account ID, the pipeline falls back to a naming-convention derivation (`user_NNN` → `account_NNN` zero-padded). This is correct for early users (user_01–user_10) but wrong for users with arbitrary account IDs (e.g., user_050 → expected account_5037, got account_050). Cases 24, 26, 27 were fixed by implementing snapshot bundle `customer_reference` lookups and SQL `source_resource_id` lookups. Remaining 11 cases have no participant-visible evidence linking user_id to account_id.  
**Impact:** VERIFY_RECORD_ABSENT (or FINDING) step cites wrong resource_id and wrong evidence_id.

### 4.3 Missing Search Index Entries

**Affected cases:** case_19, case_22, case_24  
**Root cause:** Search index evidence for certain users does not include any email, user_id, or email_hash field that matches the user identity. Evidence is present but matching fails.  
**Impact:** Missing FINDING + REMEDIATION + VERIFICATION triple for `search_service`.

### 4.4 Missing Support Records

**Affected cases:** case_11, case_16, case_29, case_30  
**Root cause:** Support message or attachment evidence exists but is associated via a support ticket ID rather than directly via email/phone, causing the identity matcher to skip it.  
**Impact:** Missing 1–3 steps in the FINDING/REMEDIATION/VERIFICATION phases.

### 4.5 Wrong Analytics Data Category (case_12)

**Affected case:** case_12 (`analytics_9914`)  
**Root cause:** The pipeline classifies this analytics record as `ANALYTICS_PROFILE` (requiring ANONYMIZE), but the expected output applies a DELETE action (`REPORT_REMAINING_RECORD` + `DELETE_RECORD`), indicating the record should be treated as a different data category.  
**Impact:** 3 steps have wrong operation/state values.

## 5. Improvements Made During Development

1. **PDF parsing fixed:** Added `pypdf` extraction before LLM fallback. Stale empty LLM caches for 5 evidence files were deleted. This recovered evidence_58 (support attachment), which fixed case_07 deletion_status from COMPLETE → INCOMPLETE.

2. **SUPPORT_ATTACHMENT vs SUPPORT_MESSAGE detection:** Added filename-based detection (`"attachment"` in stem). Attachment files require DELETE; message files require REDACT. This further improved case_07 step accuracy.

3. **Ghost data detection:** SQL files with both a primary and failover-replica table correctly identify records present in the replica but absent from the primary as PRESENT (ghost state). This correctly handles case_05 and similar.

4. **Account ID lookup tables:** Implemented three evidence-based lookup rules for account_service resource IDs: (1) snapshot bundle `customer_reference` field links user_id to account_id without time restriction; (2) SQL search table `source_resource_id` column links email to account_id; (3) trace log `profile_lookup_completed` events pair email with account_id. A naming-convention fallback (`user_NNN` → `account_NNN`) is used only when no data rule matches, with a code comment explaining its limitations. This improved resource_id accuracy from 66.9% to 71.0% (+4.1pp) and overall field accuracy from 78.8% to 81.1% (+2.3pp).

5. **audit_at strict cutoff:** Evidence files captured after `audit_at` are excluded from state reconstruction. This prevents future evidence from changing the verdict for a given case.

## 6. Additional Evaluation Cases

Three custom cases test edge conditions not covered by the 32 public samples. All ran via `code/evaluation/custom_cases.py`. Result: **3/3 PASS**.

---

### Custom Case A — Non-Deletion Request (NOT_APPLICABLE)

**Subject:** `o.walker66@yahoo.com` (user_523)  
**Request text:** `"I would like to receive a copy of all personal data you hold about me in a portable format. Please send it to my registered email address."`  
**audit_at:** 2026-10-01T12:00:00Z

**Rationale:** Request contains `copy`, `portable format`, and `data` — NOT_APPLICABLE keywords. No deletion language present. Intent classifier fast-path must return NOT_APPLICABLE without an LLM call.

**Expected:** `NOT_APPLICABLE`, `steps_json=[]`

**Actual output:**

| Field | Value |
|---|---|
| `deletion_status` | `NOT_APPLICABLE` |
| `steps_json` | `[]` |
| Fast-path hit | Yes (no LLM call) |

**Result: PASS** — Keyword fast-path correctly short-circuits on `"copy"` + `"portable format"` pattern. No evidence lookup performed.

---

### Custom Case B — Historical-Email-Only Resolution

**Subject:** `o.walker6695@yahoo.com` — the **old** email of user_523 (current: `o.walker66@yahoo.com`)  
**Request text:** `"Please delete my account and all associated personal data immediately. I no longer use this service."`  
**audit_at:** 2026-10-01T12:00:00Z

**Rationale:** The email in the request no longer exists as a current identity. `identity_resolver` must find user_523 via `user_audit_log` `old_value` lookup and reconstruct identical state to a current-email request.

**Expected:** Same `deletion_status` and step set as running with current email `o.walker66@yahoo.com`.

**Actual output:**

| Field | Value |
|---|---|
| `deletion_status` | `INCOMPLETE` |
| `user_id` resolved | `user_523` |

Steps:

| # | Phase | system_id | resource_id | operation | state | evidence_id |
|---|---|---|---|---|---|---|
| 1 | FINDING | account_service | account_4974 | REPORT_REMAINING_RECORD | PRESENT | evidence_49 |
| 2 | REMEDIATION | account_service | account_4974 | DELETE_RECORD | ABSENT | `` |
| 3 | VERIFICATION | account_service | account_4974 | VERIFY_RECORD_ABSENT | ABSENT | `` |
| 4 | VERIFICATION | security_service | audit_record_3803 | VERIFY_RECORD_PRESENT | PRESENT | `` |

Historical-email run produced identical output to current-email run (same user_id, same steps).

**Result: PASS** — `identity_resolver` correctly resolves old email via `user_audit_log` without requiring the current email.

---

### Custom Case C — COMPLETE: Restore Risk Blocked, Data Flow Disabled

**Subject:** `lucas-souza95@gmail.com` (user_39)  
**Request text:** `"Please erase the account linked to this email address. Please handle any copies that fall within the scope of your deletion policy."`  
**audit_at:** 2026-10-01T12:00:00Z

**Rationale:** At audit_at, account is absent, backup restore is blocked, data flow is disabled, support record is redacted, and security audit is retained. All records are compliant → COMPLETE. Verification must include both `VERIFY_RESTORE_BLOCKED` and `VERIFY_DATA_FLOW_DISABLED`.

**Expected:** `COMPLETE` with `VERIFY_RESTORE_BLOCKED` and `VERIFY_DATA_FLOW_DISABLED` in step set.

**Actual output:**

| Field | Value |
|---|---|
| `deletion_status` | `COMPLETE` |
| `user_id` resolved | `user_39` |

Steps:

| # | Phase | system_id | resource_id | operation | state | evidence_id |
|---|---|---|---|---|---|---|
| 1 | VERIFICATION | account_service | account_4051 | VERIFY_RECORD_ABSENT | ABSENT | evidence_03 |
| 2 | VERIFICATION | security_service | audit_record_7814 | VERIFY_RECORD_PRESENT | PRESENT | evidence_03 |
| 3 | VERIFICATION | support_platform | support_2667 | VERIFY_RECORD_REDACTED | REDACTED | evidence_03 |
| 4 | VERIFICATION | integration_service | data_flow_2901 | VERIFY_DATA_FLOW_DISABLED | DISABLED | evidence_03 |
| 5 | VERIFICATION | backup_service | backup_706 | VERIFY_RESTORE_BLOCKED | BLOCKED | evidence_03 |

**Result: PASS** — COMPLETE path correctly includes both `VERIFY_RESTORE_BLOCKED` and `VERIFY_DATA_FLOW_DISABLED`. Security audit retained (VERIFY_RECORD_PRESENT). No FINDING or REMEDIATION phases present.
