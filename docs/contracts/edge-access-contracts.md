# Edge Access Contracts

Shared contract for the **Edge Gate Access Processing** module. Source of truth is `Assignment1_Group6.pdf` (A1). Code lives in `src/tmc_access/domain/interfaces/` and `domain/models/`.

**Status tags** used throughout:
- **[A1]**: established by Assignment 1 (section cited).
- **[Proposed]**: proposed for implementation, not stated by A1.
- **[Pending]**: needs team confirmation; see [decisions.md](../architecture/decisions.md) (OD-nn).

Changing a contract requires the owner of every affected component to agree (see `AGENTS.md`).

## 1. Attendance lifecycle

Seven distinct stages. Success at one stage never implies the next.

| # | Stage | Domain type | Produced by | Status |
|---|---|---|---|---|
| 1 | QR validation | `QrValidationResult` | `QrValidator` | [A1] Table 16 `validateQR` |
| 2 | Access authorization | `AccessDecision` | `AccessPolicyEngine` | [A1] Table 16 `evaluateAccess` |
| 3 | Turnstile unlock acknowledgement | `GateCommandResult` (`GateAck`) | `GateAdapter.unlock` | [A1] Fig. 6, Table 16 `unlockGate` |
| 4 | Physical passage confirmation | `PassageStatus` | `GateAdapter.query_passage` | [A1] §3.5.3, Table 25 (15 s window §4.2.3) |
| 5 | Attendance recording | `AttendanceRecord` | Attendance Recorder (Access Coordinator flow) | [A1] §5.3.2; creation rule [Pending] OD-04/OD-05 |
| 6 | Local persistence | `AccessAttempt` row; record + outbox row | `AttendanceRepository` | [A1] ADR-003, Table 32; ordering [Pending] OD-04 |
| 7 | Central synchronization ack | `SyncResult` / `SyncStatus` | `SyncClient` | [A1] §3.5.5, Table 31 |

`AccessAttempt` (every scan, all outcomes, audit) and `AttendanceRecord` (authoritative event) are separate entities linked by `access_attempt_id` [A1 §5.3.2].

**Sequence: Proposed, Pending Team Confirmation (OD-04):**

```text
validate QR -> evaluate policy -> persist AccessAttempt (ALLOWED_PERSISTED)
  -> unlock command (ack) -> query passage
  -> if confirmed: persist AttendanceRecord + outbox entry in ONE atomic local transaction
  -> async sync (separate from the access decision)
```

Rules that are firm because A1 states them:
- ALLOW ≠ attendance [A1 §3.5.3]. Timeout/negative controller responses are stored as failed attempts [A1 §3.5.3, Table 17].
- If the access attempt cannot be durably stored, **do not issue the unlock command** [A1 Table 32].
- `AttendanceRecord` and its outbox entry are persisted atomically [confirmed by the team, consistent with A1 §3.1.3 "one local transaction"].

A1 inconsistency to resolve (OD-04): A1 Figure 4 step 4B writes "attempt + pending outbox" **before** the unlock, and step 7B "creates attendance only on success"; ADR-003 says the "access request and generated attendance event" are written before the unlock pulse. The proposed sequence above reconciles these but is **not** an A1 decision.

## 2. Contracts

### 2.1 QR Validator: `QrValidator` (owner: Hieu)
| | |
|---|---|
| Responsibility | Verify format, signature, audience, expiry, key status and anti-replay state using locally cached **public** keys [A1 Table 10, §3.5.4] |
| Input | raw payload (secret-like, never logged/persisted [A1 Table 15]), `station_id`, `now` [A1 Table 16] |
| Output | `QrValidationResult`: VALID with `VerifiedCredential` (subject, token id, key version, iat, exp) or a reject outcome: `INVALID_SIGNATURE`, `EXPIRED`, `REPLAYED`, `MALFORMED`, `WRONG_AUDIENCE`, `UNKNOWN_KEY`, `CLOCK_UNRELIABLE` [Proposed enum, values derived from A1 Tables 10/17] |
| Errors | `QrError` (infrastructure failure), `StorageError` (replay state unavailable → fail closed) |
| Rejected input | Deny **without** calling the gate [A1 Table 17] |

**QR security boundaries**
- Edge holds **public verification keys only**; private signing keys stay in the Hub key-management module [A1 ADR-002 item 5]. The scaffold contains no signing, issuing or private-key handling, and none may be added to Edge code or phones without an architecture review.
- **[Pending] OD-01:** A1 says the mobile app "generates" the signed token (ADR-002 item 1) and also that the phone "retrieves" a 60 s QR from the central server (§4.1.3; Fig. 5 labels the Hub backend "QR Issuance"). Who signs, and how the phone obtains a token, is undecided.
- **[Pending] OD-02:** payload claims differ between ADR-002 and §3.5.4. The `VerifiedCredential` fields are the intersection plus `jti`, **[Proposed]**.
- **[Pending] OD-03:** validity 30–60 s (ADR-002) vs 60 s (§4.1.3).

**Anti-replay responsibilities** [A1 §3.5.4 states the cache exists; the rest is Proposed]
| Concern | Owner |
|---|---|
| Decide REPLAYED vs VALID | `QrValidator` |
| Remember token ids until expiry; atomic check-and-record | `ReplayGuard` (`check_and_record`) |
| If replay state is unreadable | Fail closed: treat as not verifiable; surface `StorageError` |
| Retention window | Token expiry + configured clock skew (skew value unset, OD-02/OD-08) |
| Persistence across restart / multiple scanners | [Pending] OD-08 |
| Rate limiting / alerting on repeated failures | [A1 Table 17]: out of scaffold scope |

### 2.2 Access Policy Engine: `AccessPolicyEngine` (owner: Kim)
| | |
|---|---|
| Responsibility | Decide ALLOW/DENY from verified subject, gate, direction, time and the active local policy snapshot [A1 Table 10] |
| Input | `VerifiedCredential`, `gate_id`, `Direction`, `now` |
| Output | `AccessDecision` (ALLOW, or DENY + `DenyReason`, `policy_version`, `stale_cache_used`) |
| Offline rules | fresh ≤ 5 min; stale usable ≤ 2 h when backend unreachable, record that stale data was used; > 2 h or missing/corrupt cache → deny and refer to guard [A1 Table 28]. Values are configuration (`TMC_CACHE_*`), not domain constants |
| Errors | `PolicyError` (corrupt/unreadable). A DENY is a result, never an exception |
| Pending | OD-07: central-authorization fallback within 500 ms when stale and reachable |

### 2.3 Gate/Turnstile Adapter: `GateAdapter` (owner: Nhật; reviewed by Kim)
| | |
|---|---|
| `unlock(command_id, gate_id, direction, timeout_ms)` | Returns `GateCommandResult` with `GateAck`: `ACKNOWLEDGED`, `REJECTED`, `TIMEOUT`, `UNAVAILABLE`. Must return within the timeout (A1: 800 ms) [A1 LSP bullet, Table 29]. TIMEOUT = uncertain outcome; query status before retrying [A1 Table 26] |
| `query_passage(command_id, window_seconds)` | Returns `PassageStatus`: `CONFIRMED`, `NOT_CONFIRMED`, `UNKNOWN`, `UNAVAILABLE`. 15 s window [A1 §4.2.3] |
| Invariant | An acknowledgement is **never** reported as passage [A1 LSP bullet]. `GateCommandResult` has no passage field |
| Errors | `GateError` (misuse, unknown command id). Gate failures are returned as results where A1 defines them |
| Pending | OD-05: whether "ack only" may create attendance when sensors are not exposed. OD-13: vendor API unspecified. `MockTurnstileAdapter` is deterministic and covers all outcomes; the vendor adapter is a stub |

### 2.4 Attendance Repository: `AttendanceRepository` (owner: Nhật)
| | |
|---|---|
| Responsibility | Durable local storage of attempts and records [A1 Table 10 Local Store & Outbox] |
| Operations | `save_attempt`, `update_attempt`, `save_record_with_outbox` (atomic; idempotent on `transaction_id`), `next_sequence` |
| Record fields | `transaction_id`, `access_attempt_id`, employee, factory/station/gate, direction, event time, confirmation evidence, `controller_ack`, `source_sequence`, `policy_version`, sync status, time quality [A1 Table 30, §3.5.5] |
| Errors | `StorageError`: no unlock after a failed attempt write; never claim attendance success after a failed write; neither row may exist after a failed atomic write [A1 Tables 16/32] |
| Pending | OD-11: sequence numbers are currently monotonic per kiosk SQLite DB (`next_sequence`); per-gate vs per-kiosk scope remains open for production confirmation |

### 2.5 Outbox Repository: `OutboxRepository` (owner: Nhật)
`get_pending(batch_size)` (oldest first), `mark_synchronized(ids)` (only Hub-accepted ids), `mark_rejected(id, reason)` (quarantine, stop retries for that record only), `mark_conflict(id)` (never SYNCED) [A1 Table 31]. Retention (30 days after ack; pending never deleted), capacity alerts (70%/85%) [A1 §4.3.6] are operational and out of scaffold scope.

### 2.6 Synchronization Client: `SyncClient` (owner: Nhật)
| | |
|---|---|
| Responsibility | Push a batch to the Hub, at-least-once [A1 §3.5.5] |
| Output | `SyncResult(accepted_ids, rejected, conflict_ids)` |
| Errors | `SyncError`: transient; records stay PENDING |
| Retry | Backoff 5/10/20/40/60 s with 80–100% jitter [A1 §4.3.5] is **configuration** (`TMC_SYNC_BACKOFF_*`, `infrastructure/synchronization/backoff.py`), deliberately outside the domain |
| Not defined | Hub API schema, endpoint paths; transport auth (OD-10) |

## 3. Idempotency

- Stable event id: `AttendanceRecord.transaction_id`, UUIDv4, generated **once** when the record is created and reused on every resend [A1 ADR-003]. The Hub enforces a unique constraint on it.
- Identifier naming differs across A1 (`eventId`, `transaction_id`, `accessAttemptId`, `access_request_id`). **[Proposed]** mapping: event = `transaction_id`, attempt = `access_attempt_id` (OD-06).
- Duplicate semantics [A1 Table 31]: same id + identical content → success ack, no new record; same id + conflicting content → conflict, keep record, do not mark synced. ACK lost → resend with the original id [A1 Table 32].

## 4. Offline processing

Local access decisions never wait on a Hub call [A1 §2.2, Table 13]. Synchronization is a separate asynchronous concern: nothing in stages 1–6 depends on stage 7. OD-07 notes one A1 exception (500 ms central fallback) which is not adopted here.

## 5. Failure taxonomy

| Category | Examples | Domain signal | Expected behaviour [A1] |
|---|---|---|---|
| QR failure | invalid/expired/replayed/malformed | `QrValidationResult` (reject outcome) | Deny; do not call gate; audit reason code (Table 17) |
| Policy denial | not authorized, stale > 2 h, missing | `AccessDecision` DENY + `DenyReason` | Deny; refer to guard (Table 28) |
| Gate failure | rejected, timeout, unavailable | `GateAck` ≠ ACKNOWLEDGED | Not attendance; retain attempt; alert guard (Tables 17, 26) |
| Passage uncertainty | no sensor, no passage within 15 s | `PassageStatus` NOT_CONFIRMED/UNKNOWN/UNAVAILABLE | Retain unresolved attempt for manual reconciliation (Table 26; OD-12) |
| Storage failure | disk full, write error | `StorageError` | No unlock if attempt not stored; no success claim; critical alert (Tables 17, 32) |
| Sync failure | network, 5xx, auth, rejection | `SyncError` / `SyncResult` | Keep PENDING; backoff; quarantine only invalid records (Table 31) |

## 6. Open questions

Tracked, with blocking classification, in [decisions.md](../architecture/decisions.md#open-decisions).
