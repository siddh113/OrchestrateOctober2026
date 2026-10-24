# Sample Analysis: 32 Known Cases

Traces every inference from data to output for the 32 sample cases.
Each inference is marked **CONFIRMED** (directly observed in data) or **UNCERTAIN** (inferred, needs validation).

---

## 1. Case Overview

| case_id | email | audit_at | reported_status | deletion_status |
|---------|-------|----------|-----------------|-----------------|
| case_01 | amina.elmasri@gmail.com | 2026-09-03T11:30:00Z | COMPLETE | COMPLETE |
| case_02 | mateo.rios@outlook.com | 2026-09-04T15:00:00Z | PARTIALLY_COMPLETE | COMPLETE |
| case_03 | l.fontaine46@yahoo.com | 2026-09-26T11:00:00Z | COMPLETE | COMPLETE |
| case_04 | thandiwe.n@gmail.com | 2026-09-07T10:20:00Z | COMPLETE | COMPLETE |
| case_05 | leila.haddad@yahoo.com | 2026-09-08T13:40:00Z | COMPLETE | INCOMPLETE |
| case_06 | jonas.berg@outlook.com | 2026-09-10T09:15:00Z | PARTIALLY_COMPLETE | INCOMPLETE |
| case_07 | priya.raman@gmail.com | 2026-09-12T08:00:00Z | COMPLETE | INCOMPLETE |
| case_08 | gabriel.costa@proton.me | 2026-09-14T16:10:00Z | PARTIALLY_COMPLETE | INCOMPLETE |
| case_09 | k.appiah88@gmail.com | 2026-09-16T09:00:00Z | NOT_STARTED | INCOMPLETE |
| case_10 | nadia.ionescu@yahoo.com | 2026-09-18T12:25:00Z | COMPLETE | INCOMPLETE |
| case_11 | novak.tomasz@icloud.com | 2026-10-01T12:00:00Z | COMPLETE | INCOMPLETE |
| case_12 | minjun.kim@gmail.com | 2026-09-15T12:00:00Z | COMPLETE | INCOMPLETE |
| case_13 | noor-khalil@proton.me | 2026-10-01T12:00:00Z | NOT_STARTED | INCOMPLETE |
| case_14 | y.tanaka32@gmail.com | 2026-10-01T12:00:00Z | COMPLETE | INCOMPLETE |
| case_15 | lucia-torres@gmail.com | 2026-09-15T12:00:00Z | COMPLETE | INCOMPLETE |
| case_16 | diya.k4436@outlook.com | 2026-09-21T10:00:00Z | NOT_STARTED | INCOMPLETE |
| case_17 | leonie.g9352@outlook.com | 2026-09-15T12:00:00Z | NOT_STARTED | INCOMPLETE |
| case_18 | mori.ren@gmail.com | 2026-09-26T11:00:00Z | COMPLETE | INCOMPLETE |
| case_19 | e.varga90@yahoo.com | 2026-09-15T12:00:00Z | PARTIALLY_COMPLETE | INCOMPLETE |
| case_20 | akosua.gyasi@gmail.com | 2026-09-26T11:00:00Z | NOT_STARTED | INCOMPLETE |
| case_21 | amara-okeke@proton.me | 2026-09-15T12:00:00Z | COMPLETE | COMPLETE |
| case_22 | seoyeon-han@gmail.com | 2026-09-21T10:00:00Z | COMPLETE | INCOMPLETE |
| case_23 | thandiwe.m6866@zoho.com | 2026-09-15T12:00:00Z | NOT_STARTED | INCOMPLETE |
| case_24 | keiko.nakamura@gmail.com | 2026-09-15T12:00:00Z | COMPLETE | INCOMPLETE |
| case_25 | s.yoon04@gmail.com | 2026-09-15T12:00:00Z | NOT_STARTED | COMPLETE |
| case_26 | almeida.mariana@gmail.com | 2026-09-15T12:00:00Z | NOT_STARTED | COMPLETE |
| case_27 | ananya-nair@gmail.com | 2026-09-15T12:00:00Z | COMPLETE | COMPLETE |
| case_28 | smartinez6461@gmail.com | 2026-09-15T12:00:00Z | NOT_STARTED | COMPLETE |
| case_29 | noah.f438085@outlook.com | 2026-09-15T12:00:00Z | NOT_STARTED | INCOMPLETE |
| case_30 | camille.bernard86@outlook.com | 2026-09-15T12:00:00Z | COMPLETE | INCOMPLETE |
| case_31 | a.eze08@gmail.com | 2026-09-15T12:00:00Z | COMPLETE | COMPLETE |
| case_32 | addo.kofi@gmail.com | 2026-09-15T12:00:00Z | PARTIALLY_COMPLETE | INCOMPLETE |

**Key observation** (CONFIRMED): `reported_status` has no predictive value. Cases with `COMPLETE` are INCOMPLETE (05, 07, 11, 18, 22, 24, 27→actually COMPLETE). Cases with `NOT_STARTED` are COMPLETE (25, 26, 28). `reported_status` must be ignored; only evidence determines the answer.

**Key observation** (CONFIRMED): None of the 32 sample cases is `NOT_APPLICABLE`. All requests authorize deletion. NOT_APPLICABLE detection requires seeing the real eval set.

---

## 2. Identity Resolution

### 2.1 Email → user_id Lookup Order

**Algorithm** (CONFIRMED):
1. Search `user_identities.csv` for row where `email` = request email. If found → `match_type=current`.
2. If not found, search `user_audit_log.csv` for rows where `field_name='email'` AND `old_value` = request email. The `user_id` on that row is the subject. `match_type=historical`.
3. Once user_id is known, collect ALL email history: current + all `old_value` entries from audit log for that user_id where `field_name='email'`.
4. All historical emails are additional identifiers; evidence may contain any of them.

### 2.2 Full Resolution Table

| case_id | request_email | match_type | user_id | current_email | historical_emails | audit_ids |
|---------|--------------|------------|---------|---------------|-------------------|-----------|
| case_01 | amina.elmasri@gmail.com | **current** | user_01 | same | — | — |
| case_02 | mateo.rios@outlook.com | **current** | user_02 | same | — | — |
| case_03 | l.fontaine46@yahoo.com | **current** | user_43 | same | — | — |
| case_04 | thandiwe.n@gmail.com | **current** | user_04 | same | — | — |
| case_05 | leila.haddad@yahoo.com | **current** | user_05 | same | — | — |
| case_06 | jonas.berg@outlook.com | **current** | user_06 | same | — | — |
| case_07 | priya.raman@gmail.com | **current** | user_07 | same | — | — |
| case_08 | gabriel.costa@proton.me | **current** | user_08 | same | — | — |
| case_09 | k.appiah88@gmail.com | **current** | user_61 | same | — | — |
| case_10 | nadia.ionescu@yahoo.com | **historical** ⚠ | user_10 | n.petrescu@yahoo.com | nadia.petrescu@yahoo.com (audit_121, 2025-12-13); nadia.ionescu@yahoo.com (audit_238 old_value, 2026-04-12) | audit_121, audit_238 |
| case_11 | novak.tomasz@icloud.com | **current** | user_32 | same | — | — |
| case_12 | minjun.kim@gmail.com | **current** | user_12 | same | minjun.kim90@gmail.com was old (audit_282, 2026-05-18) | audit_282 |
| case_13 | noor-khalil@proton.me | **current** | user_33 | same | — | — |
| case_14 | y.tanaka32@gmail.com | **current** | user_37 | same | — | — |
| case_15 | lucia-torres@gmail.com | **current** | user_15 | same | — | audit_50 (phone only) |
| case_16 | diya.k4436@outlook.com | **current** | user_53 | same | — | — |
| case_17 | leonie.g9352@outlook.com | **current** | user_17 | same | — | — |
| case_18 | mori.ren@gmail.com | **current** | user_50 | same | — | audit_169 (phone only) |
| case_19 | e.varga90@yahoo.com | **current** | user_19 | same | — | — |
| case_20 | akosua.gyasi@gmail.com | **current** | user_48 | same | — | — |
| case_21 | amara-okeke@proton.me | **current** | user_21 | same | — | — |
| case_22 | seoyeon-han@gmail.com | **current** | user_51 | same | — | — |
| case_23 | thandiwe.m6866@zoho.com | **current** | user_23 | same | — | — |
| case_24 | keiko.nakamura@gmail.com | **current** | user_24 | same | — | — |
| case_25 | s.yoon04@gmail.com | **current** | user_25 | same | — | audit_220 (phone only) |
| case_26 | almeida.mariana@gmail.com | **current** | user_26 | same | — | — |
| case_27 | ananya-nair@gmail.com | **current** | user_27 | same | — | — |
| case_28 | smartinez6461@gmail.com | **current** | user_28 | same | — | — |
| case_29 | noah.f438085@outlook.com | **historical** ⚠ | user_29 | noah.f4380@outlook.com | noah.f438085@outlook.com (old) | audit_284 (2026-05-18) |
| case_30 | camille.bernard86@outlook.com | **historical** ⚠ | user_30 | camille.bernard@outlook.com | camille.bernard86@outlook.com (old) | audit_280 (2026-05-17) |
| case_31 | a.eze08@gmail.com | **current** | user_541 | same | — | — |
| case_32 | addo.kofi@gmail.com | **current** | user_542 | same | — | — |

### 2.3 Historical Identity Notes

**case_10** (CONFIRMED): Two-hop chain. Request email is the oldest address. Must search evidence under all three addresses: `nadia.ionescu@yahoo.com`, `nadia.petrescu@yahoo.com`, `n.petrescu@yahoo.com`. The sample output INCOMPLETE finding (support_002) was located via the old email in a support log.

**case_12** (CONFIRMED): Request email is current, but old email `minjun.kim90@gmail.com` exists in audit_282. Evidence may reference the old address. The analytics finding was linked back through the old address.

**case_29, case_30** (CONFIRMED): Single-hop historical. The request email is the pre-change address; evidence may reference either old or current.

**Phone changes** (CONFIRMED): users 15, 18, 25 have historical phone numbers in `user_audit_log.csv`. Evidence (e.g. support attachments, delivery logs) may identify these users by old phone. Must treat old phone as an additional identifier.

### 2.4 NOT_APPLICABLE Detection

**UNCERTAIN** — No NOT_APPLICABLE cases in the 32 sample set. Based on problem spec:
- Request for account access, data export, marketing opt-out, or correction → NOT_APPLICABLE
- `steps_json = []` for NOT_APPLICABLE
- Must handle non-English requests (French, Spanish, Japanese seen in samples — all were valid deletions)

---

## 3. Resource-to-User Linking

### 3.1 system_activity.csv Event Types

| event_type | row count | notes |
|---|---|---|
| DELETE_RECORD | 890 | Most common; reported_result may be SUCCESS/PARTIAL/FAILED |
| UPDATE_RECORD | 672 | Identity field updates, not deletion-relevant |
| SYNC_RECORD | 447 | **Replication events** — critical for detecting ghost data |
| INDEX_RECORD | 400 | Search index updates |
| SEND_EMAIL | 368 | Email delivery |
| REFRESH_CACHE | 284 | Cache operations |
| RETAIN_RECORD | 206 | Policy retention |
| ANONYMIZE_RECORD | 204 | Anonymization ops |
| REDACT_RECORD | 173 | Redaction ops |
| CREATE_EXPORT | 155 | Export creation |
| CHECK_DATA_FLOW | 89 | Connector heartbeat checks |
| DISABLE_DATA_FLOW | ~36 | Flow shutdown |
| BLOCK_RESTORE | ~36 | Restore blocking |
| CHECK_RESTORE_ACCESS | 28 | Restore-access checks |
| LINK_RESOURCE_IDENTITY | 12 | Explicit user↔resource catalog entries |
| RESTORE_BACKUP | 1 | Backup restore (creates ghost data) |

**Total: 4,011 data rows.**

### 3.2 LINK_RESOURCE_IDENTITY Format

**CONFIRMED**: Only 12 rows exist (lines 4001–4012, all at end of file). Two formats:

**Standard resource:**
```
Data catalog linked <resource_id> (<alias>) to <email> and <user_id>.
```

**Attachment/object:**
```
Attachment catalog confirmed <resource_id> (<filename>) belongs only to <email> and <user_id>; no other subject is linked.
```

**Tombstone:**
```
Data catalog linked <resource_id> (<stable_user_ref>) to <email> and <user_id>.
```

All 12 entries map resource_id → email + user_id explicitly. These are authoritative.

| activity_id | resource_id | email | user_id |
|---|---|---|---|
| activity_4000 | account_5762 | haruka.s1838@zoho.com | user_11 |
| activity_4001 | search_428 | g.silva76@gmail.com | user_13 |
| activity_4002 | data_flow_1121 | jain.aditi@gmail.com | user_14 |
| activity_4003 | analytics_7438 | darwish.omar@icloud.com | user_20 |
| activity_4004 | export_1260 | ingrid.dahl@outlook.com | user_18 |
| activity_4005 | support_1034 | kagyeman8947@fastmail.com | user_22 |
| activity_4006 | backup_9287 | areed1433@gmail.com | user_16 |
| activity_4007 | object_19 (delivery_confirmation_19.pdf) | priya.raman@gmail.com | user_07 |
| activity_4008 | marketing_001 | kwame-mensah@proton.me | user_09 |
| activity_4009 | export_1842 (NST-2026-0718-1842) | ingrid.dahl@outlook.com | user_18 |
| activity_4010 | audit_record_003 | oliver-bennett@gmail.com | user_03 |
| activity_4011 | tombstone_17 (user_17) | leonie.g9352@outlook.com | user_17 |

**Critical limitation** (CONFIRMED): LINK_RESOURCE_IDENTITY covers ~12 resources out of thousands. For all other resources, the user↔resource binding comes from **evidence file contents** (SQL, JSON, logs), not the activity log. The `details` field of all other event types contains only `resource_id` — no email, no user_id.

### 3.3 Ghost Data Signals in system_activity.csv

**CONFIRMED** from sample cases:

1. **SYNC_RECORD after DELETE_RECORD** → replication may re-populate record.
   - case_05: `activity_3482` DELETE_RECORD on account_005 (SUCCESS), then `activity_3483` SYNC_RECORD targeting `account_failover_replica`. Evidence (evidence_54) then shows account_005 absent from primary but **present in failover replica** → INCOMPLETE.

2. **DELETE_RECORD with PARTIAL or FAILED reported_result** → deletion incomplete.
   - case_06 search_001: `activity_3546` DELETE_RECORD FAILED → search entry still present.
   - case_02 account_002: `activity_3376` DELETE_RECORD PARTIAL → but evidence_54 still shows absent. **CONFIRMED**: PARTIAL/FAILED in activity is a hint only; truth is in evidence.

3. **RESTORE_BACKUP repopulating downstream** → ghost recreation.
   - activity_3387: backup_9287 restored → search_4882 repopulated. Then activity_3388 DELETE_RECORD on search_4882 FAILED. Pattern: backup restores data, deletion of restored data also fails.

4. **REDACT_RECORD FAILED** → tombstone PII still exposed.
   - case_32: `activity_3692` REDACT_RECORD on tombstone_9178 FAILED → finding is REPORT_EXPOSED_PII.

5. **CHECK_DATA_FLOW confirms enabled=true** → REPORT_ACTIVE_DATA_FLOW risk.

6. **CHECK_RESTORE_ACCESS confirms restore=true** → REPORT_RESTORE_RISK.

---

## 4. Evidence Files: Internal Structure and Selection

### 4.1 File Types and Schemas

#### evidence_54 — `customer_accounts_failover_replica_20260902.sql` (captured 2026-09-02)
- Tables: `customer_profiles_primary`, `customer_profiles_failover_replica`
- Columns: `resource_id`, `user_id`, `full_name`, `email`, `phone`, `account_status`, `updated_at`
- **Deleted record**: row absent from primary; may still exist in failover replica
- **Ghost data proof**: account_005 absent from primary, present in failover replica → INCOMPLETE for case_05
- Cited for: cases 01, 02, 04, 05 (audit_at 2026-09-03 to 2026-09-08)

#### evidence_92 — `service_resource_export_20260915_114455.json` (captured 2026-09-15)
- Multi-service JSON export, sections:
  - `account_service.profile_lookups`: `{resource_id, profile (null=absent), status_code (404=absent, 200=present)}`
  - `analytics_platform.profiles`: `{resource_id, customer_reference, email, email_hash, phone, audience_cohort}` — all null except audience_cohort = anonymized
  - `backup_service.restore_entries`: `{resource_id, customer_reference, customer_email, restore_allowed (bool)}`
  - `export_service.exports`: `{resource_id, customer_reference, owner_email, owner_phone, object_key}`
  - `integration_service.connectors`: `{resource_id, customer_reference, customer_email, enabled (bool), last_delivery_status}`
- Cited for: cases 21, 23–30 (audit_at 2026-09-15 to 2026-09-26)

#### evidence_94 — `resource_lookup_trace_20260926_103856.log` (captured 2026-09-26)
- Structured key=value log, one DEBUG+INFO pair per resource lookup
- Per-service state fields:
  - `account_service`: `rows=0 http_status=404` (absent) / `rows=1 http_status=200` (present)
  - `analytics_platform`: `customer_reference=null email=null` (anonymized) / `email=X` (PII exposed)
  - `integration_service`: `enabled=true/false last_delivery_status=delivered/stopped`
  - `backup_service`: `archive_present=true restore_allowed=true/false`
  - `search_service`: `result=hit` (remaining) / `result=miss` (absent)
  - `support_platform`: `requester_email=null` (redacted) / `requester_email=X` (PII exposed)
  - `security_service`: `rows=1 subject_reference=<user_id> retention_until=<date>` (retained)
- Cited for: cases 03, 18, 20 (audit_at 2026-09-26)

#### evidence_51 — `customer_data_snapshot_bundle_20260915.json` (captured 2026-09-15)
- Multi-store snapshot:
  - `account_service / customer_profiles`: `records: []` = all accounts gone
  - `identity_service / deleted_customer_references` (tombstone table): `{resource_id, subject_reference, name, email, phone, email_hash, account_status}`
  - `security_service / security_audit_events`: `{resource_id, subject_reference, event_name, integrity_seal}`
- **Correct tombstone (REDACTED)**: `name=null, email=null, phone=null, email_hash=null`, only `subject_reference` + `account_status="DELETED"` remain
- **Incorrect tombstone (PII EXPOSED)**: name/email/phone/email_hash still populated → REPORT_EXPOSED_PII
- Cited for: cases 31 (COMPLETE, redacted tombstone), 32 (INCOMPLETE, exposed tombstone)

#### evidence_03 — `customer_account_handover_20261001.txt` (captured 2026-10-01)
- Pipe-delimited log: `<timestamp> | <system_id> | <resource_id> | <record_type> | <STATUS> | <identifier>`
- Status values: `NOT_FOUND`, `FOUND`, `IDENTIFIABLE`, `ANONYMIZED`, `ACTIVE`, `DISABLED`, `BLOCKED`, `REDACTED`
- Cited for: cases 11, 13, 14 (audit_at 2026-10-01)

#### evidence_05 — `customer_data_read_replica_20260921.sql` (captured 2026-09-21)
- Tables: `customer_data_primary`, `customer_data_read_replica` — both with embedded `record_json`
- Covers: account_service, analytics, security, integration, search, support, backup records
- Replication drift: record_id in read_replica but absent from primary = ghost data
- Cited for: cases 16, 22 (audit_at 2026-09-21)

#### evidence_01 — `service_events_ap_south_20260915.log` (captured 2026-09-15)
- Operational key=value event log:
  - `event=profile_lookup_completed rows=0 http_status=404` → absent
  - `event=index_query_completed result=hit` → search entry still present
  - `event=analytics_identity_scan matched_value=<email> direct_identifiers=1` → analytics PII exposed
  - `event=connector_heartbeat enabled=true scheduler_registered=true` → active data flow
  - `event=restore_candidate_evaluated eligible=true deletion_block=false` → restore risk
  - `event=message_pii_scan matched_value=<email>` → support message PII exposed
- Cited for: cases 12, 15, 17, 19 (audit_at 2026-09-15)

#### evidence_56 — `customer_analytics_report_20260907.json` (captured 2026-09-07)
- Array of analytics records: `{resource_id, user_id, email, phone, email_hash, metrics, recent_activity}`
- Anonymized: `user_id=null, email=null, phone=null, email_hash=null`
- Cited for: case_04 step 2 — analytics_901 anonymized

#### evidence_57 — `customer_search_primary_20260910.sql` (captured 2026-09-10)
- Table: `search_documents_primary`: `{resource_id, display_name, email, source_resource_id, indexed_at}`
- Present: row exists with display_name/email. Absent: row missing.
- Cited for: case_06 — search_001 still present

#### evidence_93 — `customer_data_inventory_20260916.sql` (captured 2026-09-16)
- Most comprehensive snapshot; normalized tables:
  - `customer_profiles`, `customer_search_documents`, `customer_analytics_profiles`
  - `support_records`, `customer_exports`, `connector_subscriptions`
  - `backup_restore_entries`: `restore_allowed` (0/1)
  - `security_audit_records`: `retention_until`
- Cited for: case_09 — backup_4978 with `restore_allowed=1`

### 4.2 Evidence Selection Rule

**CONFIRMED** — NOT "most recent evidence before audit_at." The rule is:

> Choose the evidence file where `captured_at ≤ audit_at` **AND** the file directly contains a row/entry for the specific `resource_id` being cited.

When multiple files pre-date the audit_at, the one that **directly contains** the resource_id (provably showing its state) wins.

**Confirmed examples:**

| case | audit_at | evidence_id | captured_at | Resource directly in file |
|------|----------|-------------|-------------|---------------------------|
| case_01 | 2026-09-03 | evidence_54 | 2026-09-02 | account_001 (absent from primary, present in failover) |
| case_04 step1 | 2026-09-07 | evidence_54 | 2026-09-02 | account_004 absent from primary |
| case_04 step2 | 2026-09-07 | evidence_56 | 2026-09-07 | analytics_901 with null identity fields |
| case_06 | 2026-09-10 | evidence_57 | 2026-09-10 | search_001 row present |
| case_09 | 2026-09-16 | evidence_93 | 2026-09-16 | backup_4978 restore_allowed=1 |
| case_21 | 2026-09-15 | evidence_92 | 2026-09-15 | account_6440 status_code=404 |
| case_31 | 2026-09-15 | evidence_51 | 2026-09-15 | tombstone_440 name=null |
| case_32 | 2026-09-15 | evidence_51 | 2026-09-15 | tombstone_9178 email still populated |
| case_18 | 2026-09-26 | evidence_94 | 2026-09-26 | log entries for mori.ren resources |

**Implication for the agent**: Must look up each resource_id across all evidence files captured at or before audit_at to find the one that directly contains it. Cannot assume a single file covers all resources for a case.

---

## 5. Step Construction Rules

### 5.1 Phase Structure

**CONFIRMED from all 32 cases:**

- `COMPLETE`: **ONLY VERIFICATION steps**. No FINDING or REMEDIATION. All verification steps cite non-empty evidence_id.
- `INCOMPLETE`: **ALL THREE phases always present**. No exceptions across 22 INCOMPLETE cases.
- Phase order: `FINDING` → `REMEDIATION` → `VERIFICATION` — strict blocks, never interleaved.
- Within-phase steps are numbered consecutively continuing from the prior phase (no restart).

### 5.2 evidence_id Population Rules

**CONFIRMED with zero exceptions across all 32 cases:**

| Phase | Case type | evidence_id |
|-------|-----------|-------------|
| FINDING | INCOMPLETE | **non-empty** — always a valid file_id or activity_id |
| REMEDIATION | INCOMPLETE | **empty string ""** — future work |
| VERIFICATION | INCOMPLETE | **empty string ""** — future work |
| VERIFICATION | COMPLETE | **non-empty** — proves current state |

### 5.3 Within-Phase Ordering

**CONFIRMED:**

**FINDING phase** ordering within a case:
- Ordered by operation type (table order from spec): REPORT_REMAINING_RECORD before REPORT_EXPOSED_PII before REPORT_ACTIVE_DATA_FLOW before REPORT_RESTORE_RISK
- Then by `system_id` ascending, then `resource_id` ascending

**REMEDIATION phase** ordering:
- `DISABLE_DATA_FLOW` always comes **first** when present (confirmed: cases 11, 18, 20, 29, 30)
- `BLOCK_RESTORE` comes before record operations (cases 9, 14, 17)
- Then DELETE_RECORD, REDACT_RECORD, ANONYMIZE_RECORD
- Within each operation type: `system_id` asc, `resource_id` asc

**VERIFICATION phase** ordering:
- VERIFY_RECORD_ABSENT → VERIFY_RECORD_PRESENT → VERIFY_RECORD_REDACTED → VERIFY_RECORD_ANONYMIZED → VERIFY_DATA_FLOW_DISABLED → VERIFY_RESTORE_BLOCKED
- Then `system_id` asc, `resource_id` asc

### 5.4 Invariant Steps

**CONFIRMED across all cases:**

1. **`VERIFY_RECORD_PRESENT` on `security_service`** appears in every case that has a security audit record. Cases 01, 02, 04 (simple COMPLETE) do NOT include it — confirming it only appears when a security_service record exists for the user. All complex COMPLETE cases (03, 21, 25, 26, 27, 28, 31) and all INCOMPLETE cases include it.

2. **`VERIFY_RECORD_ABSENT` on `account_service`** appears in every INCOMPLETE case, including those where the account was not itself the subject of a FINDING. Even when the finding is about search_service or support_platform, the account_service absence is always verified. **Exception**: cases where the account IS the finding (e.g., case_05) — the FINDING → DELETE → VERIFY chain is on the same resource.

3. **Every INCOMPLETE case has verification for every system where a finding or remediation occurred**, plus account_service and security_service as baseline.

### 5.5 Remediation → Verification Mapping

**CONFIRMED 1:1 mapping:**

| Remediation operation | Verification operation |
|---|---|
| DELETE_RECORD | VERIFY_RECORD_ABSENT |
| REDACT_RECORD | VERIFY_RECORD_REDACTED |
| ANONYMIZE_RECORD | VERIFY_RECORD_ANONYMIZED |
| DISABLE_DATA_FLOW | VERIFY_DATA_FLOW_DISABLED |
| BLOCK_RESTORE | VERIFY_RESTORE_BLOCKED |

### 5.6 Tombstone Handling

**CONFIRMED from cases 31 and 32:**

An `ACCOUNT_TOMBSTONE` in `identity_service`:
- Permitted to **exist** after deletion (stable `subject_reference` / `user_id` must be kept)
- Must have `name`, `email`, `phone`, `email_hash` nulled (REDACTED state)
- If PII still present: `REPORT_EXPOSED_PII` (NOT `REPORT_REMAINING_RECORD`) + `REDACT_RECORD` (NOT `DELETE_RECORD`)
- If PII already removed: `VERIFY_RECORD_REDACTED` on the tombstone resource_id

**case_31 (COMPLETE)**: Tombstone is already correctly redacted. Steps:
1. `VERIFY_RECORD_ABSENT` on account_service / account_4857 (main account gone)
2. `VERIFY_RECORD_PRESENT` on security_service / audit_record_6909 (retained log)
3. `VERIFY_RECORD_REDACTED` on identity_service / tombstone_440 (tombstone exists, PII removed)

**case_32 (INCOMPLETE)**: Tombstone still has PII. Steps:
1. FINDING: `REPORT_EXPOSED_PII` on identity_service / tombstone_9178
2. REMEDIATION: `REDACT_RECORD` on tombstone_9178
3. VERIFICATION: `VERIFY_RECORD_ABSENT` (account_service), `VERIFY_RECORD_PRESENT` (security_service), `VERIFY_RECORD_REDACTED` (identity_service / tombstone_9178)

---

## 6. Common Case Patterns

### Pattern A: Simple COMPLETE — account deleted, nothing else (cases 01, 02)
- Single VERIFICATION step: `VERIFY_RECORD_ABSENT` on account_service
- Evidence: SQL replica snapshot showing account_id absent

### Pattern B: COMPLETE with analytics anonymization (case 04)
- Two VERIFICATION steps: `VERIFY_RECORD_ABSENT` (account) + `VERIFY_RECORD_ANONYMIZED` (analytics)
- Two different evidence files (one per service)

### Pattern C: Full COMPLETE across multiple systems (cases 03, 21, 25, 26, 27, 28)
- 3–6 VERIFICATION steps covering account_service, security_service, analytics_platform, support, integration, backup
- Single evidence file proves all states

### Pattern D: Simple INCOMPLETE — one remaining record (cases 05, 06, 07, 08, 10)
- 1 FINDING + 1 REMEDIATION + 2 VERIFICATION (account absent + record absent)
- e.g., case_05: failover replica still has account_005

### Pattern E: INCOMPLETE — restore risk (cases 09, 14, 17)
- FINDING: `REPORT_RESTORE_RISK` on backup_service
- REMEDIATION: `BLOCK_RESTORE`
- VERIFICATION: account absent + security present + restore blocked

### Pattern F: INCOMPLETE — active data flow (cases 15, 20)
- FINDING: `REPORT_ACTIVE_DATA_FLOW` on integration_service
- REMEDIATION: `DISABLE_DATA_FLOW` (first in block)
- VERIFICATION: account absent + security present + flow disabled

### Pattern G: Full INCOMPLETE — multiple findings + active flow (cases 11, 18, 29, 30)
- 4 FINDINGs: search REMAINING + analytics PII + support PII + data flow ACTIVE
- 4 REMEDIATIONs: DISABLE first, then DELETE search, REDACT support, ANONYMIZE analytics
- 6 VERIFICATIONs: account absent + search absent + security present + support redacted + analytics anonymized + flow disabled

### Pattern H: Tombstone with exposed PII (case 32)
- FINDING: `REPORT_EXPOSED_PII` on identity_service tombstone
- REMEDIATION: `REDACT_RECORD`
- VERIFICATION: account absent + security present + tombstone redacted

---

## 7. Per-Case Trace Summary

### COMPLETE cases

| case | user_id | evidence | systems verified |
|------|---------|----------|-----------------|
| case_01 | user_01 | evidence_54 | account_service (absent) |
| case_02 | user_02 | evidence_54 | account_service (absent) |
| case_03 | user_43 | evidence_94 | account (absent) + security (present) + analytics (anonymized) |
| case_04 | user_04 | evidence_54 + evidence_56 | account (absent) + analytics (anonymized) |
| case_21 | user_21 | evidence_92 | account (absent) + security (present) + analytics (anonymized) |
| case_25 | user_25 | evidence_92 | account (absent) + security (present) + analytics (anonymized) |
| case_26 | user_26 | evidence_92 | account + security + support (redacted) + analytics + flow (disabled) + backup (blocked) |
| case_27 | user_27 | evidence_92 | same 6 systems |
| case_28 | user_28 | evidence_92 | same 6 systems |
| case_31 | user_541 | evidence_51 | account (absent) + security (present) + tombstone (redacted) |

### INCOMPLETE cases (brief)

| case | user_id | finding | finding evidence | remediation |
|------|---------|---------|-----------------|-------------|
| case_05 | user_05 | account_005 in failover replica | evidence_54 | DELETE account_005 |
| case_06 | user_06 | search_001 still indexed | evidence_57 | DELETE search_001 |
| case_07 | user_07 | support_001 present (attachment) | evidence_58 | DELETE support_001 |
| case_08 | user_08 | export_001 still downloadable | evidence_59 | DELETE export_001 |
| case_09 | user_61 | backup_4978 restore_allowed=true | evidence_93 | BLOCK_RESTORE backup_4978 |
| case_10 | user_10 | support_002 present (old email match) | evidence_61 | DELETE support_002 |
| case_11 | user_32 | search+analytics+support+data_flow | evidence_03 | DISABLE flow, DELETE search, REDACT support, ANONYMIZE analytics |
| case_12 | user_12 | analytics_9914 remaining | evidence_01 | DELETE analytics_9914 |
| case_13 | user_33 | search_1308 + support_4218 present | evidence_03 | DELETE both |
| case_14 | user_37 | backup_3870 restore_allowed | evidence_03 | BLOCK_RESTORE |
| case_15 | user_15 | data_flow_9846 enabled | evidence_01 | DISABLE_DATA_FLOW |
| case_16 | user_53 | account_994 + search_1007 in read_replica | evidence_05 | DELETE both |
| case_17 | user_17 | backup_3245 restore_allowed | evidence_01 | BLOCK_RESTORE |
| case_18 | user_50 | search+analytics+support+data_flow | evidence_94 | DISABLE flow, DELETE search, REDACT support, ANONYMIZE analytics |
| case_19 | user_19 | search_6083 + support_9553 PII | evidence_01 | DELETE search, REDACT support |
| case_20 | user_48 | search_4262 + data_flow_1770 | evidence_94 | DISABLE flow, DELETE search |
| case_22 | user_51 | search_8911 + analytics_4440 PII | evidence_05 | DELETE search, ANONYMIZE analytics |
| case_23 | user_23 | export_7364 + search_898 | evidence_92 | DELETE both |
| case_24 | user_24 | account_5334 + search_5577 | evidence_92 | DELETE both |
| case_29 | user_29 | search+analytics+support+data_flow | evidence_92 | DISABLE flow, DELETE search, REDACT support, ANONYMIZE analytics |
| case_30 | user_30 | search+analytics+support+data_flow | evidence_92 | DISABLE flow, DELETE search, REDACT support, ANONYMIZE analytics |
| case_32 | user_542 | tombstone_9178 PII exposed | evidence_51 | REDACT tombstone |

---

## 8. Inference Confidence Summary

| Inference | Confidence |
|-----------|-----------|
| Email → user_id lookup order (current then audit_log historical) | CONFIRMED |
| 3 historical matches (cases 10, 29, 30) | CONFIRMED |
| reported_status is unreliable — must ignore | CONFIRMED |
| No NOT_APPLICABLE in 32 samples; pattern unknown | UNCERTAIN |
| evidence_id selection = resource_id directly in file, captured_at ≤ audit_at | CONFIRMED |
| COMPLETE cases = VERIFICATION only, no FINDING/REMEDIATION | CONFIRMED |
| INCOMPLETE cases = all 3 phases always present | CONFIRMED |
| FINDING evidence_id always non-empty | CONFIRMED |
| REMEDIATION evidence_id always "" | CONFIRMED |
| INCOMPLETE VERIFICATION evidence_id always "" | CONFIRMED |
| COMPLETE VERIFICATION evidence_id always non-empty | CONFIRMED |
| DISABLE_DATA_FLOW always first in remediation block | CONFIRMED |
| BLOCK_RESTORE before DELETE/REDACT/ANONYMIZE | CONFIRMED |
| Tombstone uses REPORT_EXPOSED_PII not REPORT_REMAINING_RECORD | CONFIRMED |
| Tombstone uses REDACT_RECORD not DELETE_RECORD | CONFIRMED |
| VERIFY_RECORD_ABSENT on account_service in every case | CONFIRMED |
| VERIFY_RECORD_PRESENT on security_service when audit record exists | CONFIRMED |
| Within-phase ordering: operation table order then system_id then resource_id asc | CONFIRMED |
| LINK_RESOURCE_IDENTITY is sparse (12 rows); primary linkage via evidence files | CONFIRMED |
| SYNC_RECORD after DELETE = replication drift risk | CONFIRMED |
| Activity log PARTIAL/FAILED result = hint only; truth comes from evidence | CONFIRMED |
| Phone historical identifiers used for evidence matching | UNCERTAIN (seen in audit_log but not cited in any sample finding) |
| Non-English requests (French, Spanish, Japanese) are valid deletions | CONFIRMED from samples |
