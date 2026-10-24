# Evaluation Report — Ghost Data Still Exists

## 1. Case-Level Deletion-Status Accuracy

Evaluated against `dataset/sample_output.csv` (32 public cases).

| Metric | Score |
|---|---|
| Deletion-status accuracy | **32/32 (100%)** |
| Exact step-sequence match | **10/32 (31%)** |
| Overall field accuracy | **81.1%** |

All 32 sample cases produce the correct `deletion_status`
(`COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`).

## 2. Step-Level and Field-Level Accuracy

Steps were compared position-by-position up to `min(expected_length, actual_length)`.

| Field | Correct | Total compared | Accuracy |
|---|---|---|---|
| `phase` | 157 | 169 | 92.9% |
| `system_id` | 130 | 169 | 76.9% |
| `resource_id` | 120 | 169 | 71.0% |
| `operation` | 125 | 169 | 74.0% |
| `state` | 130 | 169 | 76.9% |
| `evidence_id` | 160 | 169 | 94.7% |
| **Overall** | **822** | **1014** | **81.1%** |

Expected total steps across 32 cases: **193**  
Generated total steps: **170** (missing 23 steps across 22 cases)

## 3. Sequence Accuracy

10 of 32 cases match the expected step sequence exactly (step order, all fields).  
The 22 cases with discrepancies fall into these categories:

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

The following three cases were constructed to test edge conditions not covered by the 32 public samples.

### Custom Case A — Tombstone with PII Exposed

**Scenario:** A user's account was tombstoned (stable `user_id` retained in `identity_service`), but the tombstone record still contains the user's name and email. The deletion request is valid. The account is absent from `account_service`.

**Expected output:** `INCOMPLETE`

Steps:
1. FINDING — `REPORT_EXPOSED_PII` on `identity_service/tombstone_XXX` (PRESENT)
2. REMEDIATION — `REDACT_RECORD` on `identity_service/tombstone_XXX` (REDACTED)
3. VERIFICATION — `VERIFY_RECORD_ABSENT` on `account_service/account_XXX` (ABSENT)
4. VERIFICATION — `VERIFY_RECORD_REDACTED` on `identity_service/tombstone_XXX` (REDACTED)

**Pipeline behavior:** Correctly handles tombstone REDACT policy. Fails only if identity_service evidence PII is not extracted.

### Custom Case B — NOT_APPLICABLE (Data Access Request)

**Scenario:** Request text reads: "I would like to access all personal data you hold about me." No deletion language present.

**Expected output:** `NOT_APPLICABLE`, `steps_json=[]`

**Pipeline behavior:** Intent classifier keyword fast-path returns `NOT_APPLICABLE` on "access" without contacting LLM.

### Custom Case C — COMPLETE with Security Audit Retained

**Scenario:** User's account is deleted (ABSENT in account_service), all analytics anonymized, but a security audit log entry remains present (policy=RETAIN).

**Expected output:** `COMPLETE`

Steps:
1. VERIFICATION — `VERIFY_RECORD_ABSENT` on `account_service/account_XXX`
2. VERIFICATION — `VERIFY_RECORD_PRESENT` on `security_service/audit_record_XXX`
3. VERIFICATION — `VERIFY_RECORD_ANONYMIZED` on `analytics_platform/analytics_XXX`

**Pipeline behavior:** Security audit records are always flagged as RETAIN; never as violations. COMPLETE path includes VERIFY_RECORD_PRESENT for all retained security records.
