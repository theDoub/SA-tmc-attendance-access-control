# Component-and-Connector View

| Metadata | Value |
|---|---|
| System | TMC QR-Based Attendance & Access Control System |
| Module | Edge Gate Access Processing (`tmc_access`) |
| Milestone | M2 |
| Owner | Nguyen Tran Tuan Khai |
| Baseline | Assignment 1 (`Assignment1_Group6.pdf`), ADR-001..004 |
| Related contracts | [`docs/contracts/edge-access-contracts.md`](../contracts/edge-access-contracts.md) |
| Related static view | [`module-view.md`](module-view.md) |
| Status | Implemented A2 prototype runtime view; core Edge components are implemented and tested while turnstile hardware and Hub ingestion use simulated adapters |

## 1. Purpose and view boundary

The Module View explains where code is organized. This Component-and-Connector
(C&C) View explains what participates at runtime, how those participants
communicate, and how the access lifecycle progresses through success and
failure states.

The boundary is the **factory gate station**. The components inside the kiosk
process are the Edge module's runtime participants. The scanner, turnstile
controller, Hub, employee phone, NTP service, and HR/Payroll system are
external devices or services. The Hub and HR/Payroll implementation are
outside M2; only the `SyncClient` boundary is represented here.

```mermaid
flowchart LR
    classDef impl fill:#eaf4fc,stroke:#1f5a8a,stroke-width:1.5px,color:#111827
    classDef sim fill:#edf7ed,stroke:#2e6f40,stroke-width:1.5px,stroke-dasharray:4 2,color:#111827
    classDef ext fill:#f3f4f6,stroke:#6b7280,stroke-width:1.2px,stroke-dasharray:4 2,color:#1f2937
    classDef zone fill:#ffffff,stroke:#94a3b8,stroke-width:1.2px,color:#111827

    Phone["Employee Phone"]:::ext -.->|Dynamic signed QR| Scanner["Optical QR Scanner"]:::ext
    Scanner -->|Scan envelope| API["Scan Receiver / API Boundary<br/>(FastAPI /scan)"]:::impl
    subgraph Kiosk["Kiosk Process: tmc_access"]
        API --> COORD["AccessCoordinator"]:::impl
        COORD --> QR["PublicKeyQrValidator +<br/>ReplayGuardStore"]:::impl
        COORD --> POLICY["AccessPolicyEvaluator"]:::impl
        COORD --> DB[("SQLite WAL Repositories<br/>(access_attempts, attendance_records, outbox_events)")]:::impl
        COORD --> GATE["TurnstileAdapter<br/>(Mock implemented; Vendor OD-13)"]:::sim
        SYNC["SyncService + SyncRetryWorker<br/>(SimulatedSyncClient; Http OD-10)"]:::sim --> DB
    end
    GATE <-->|Unlock & passage status| CTRL["Turnstile Controller<br/>(Hardware / Mock)"]:::ext
    SYNC -.->|"Async batch sync<br/>(Simulated / OD-10)"| HUB["Central Hub Ingestion API<br/>(Out of M2 scope)"]:::ext
    HUB -.->|"Policy & key distribution<br/>(Pending OD-09)"| QR
    HUB -.->|"Policy & key distribution<br/>(Pending OD-09)"| POLICY

    class Kiosk zone
```

The diagram is a runtime interaction view, not a deployment guarantee. The
repository does not specify a kiosk service manager or a vendor protocol.
`AccessCoordinator` has no `UserFeedbackPort` or display component in the A2
codebase; `presentation/api` exposes `/health` and `/scan` HTTP JSON responses,
and any physical kiosk display/annunciator is an external presentation concern.
`MockTurnstileAdapter` and `SimulatedSyncClient` / `SimulatedHubReceiver` are
used in tests and simulation mode; `VendorTurnstileAdapter` (OD-13) and
production `HttpSyncClient` (OD-10) remain open.

### Visual notation and semantic legend

- **Boxes** are computational components. The `Kiosk process` border identifies
  components executing inside the kiosk OS process; external devices and
  services are outside that boundary.
- **Solid arrows** represent synchronous control initiation. A bidirectional
  solid arrow represents a request-response or polling handshake.
- **Dashed arrows** represent asynchronous or deferred interactions. The
  phone-to-scanner edge is a physical optical presentation; the SyncService
  and policy/key distribution edges are asynchronous network interactions.
- **Cylinders** represent persistent stores. The SQLite file is not drawn as a
  separate top-level component because it is internal state of the repository
  component.

## 2. Runtime component catalog

| Component | Provided ports | Required ports | Runtime responsibility and key state |
|---|---|---|---|
| **Scan Receiver / API Boundary** (`presentation/api`) | FastAPI `/health`, `/scan` | `AccessCoordinator` | Accepts a scanner `ScanInput`, validates the envelope, redacts the payload from representations, dispatches to the coordinator, and returns `{access_attempt_id, status, reason_code}`. |
| **AccessCoordinator** (`application/access`) | `process_scan` (`AccessCoordinator`) | `QrValidator`, `AccessPolicyEngine`, `GateAdapter`, `AttendanceRepository` | Orchestrates validation, policy, Phase 1 attempt persistence, unlock, passage monitoring, `next_sequence()`, and Phase 2 atomic attendance+outbox persistence. A Phase 1 failure prevents unlock. |
| **PublicKeyQrValidator + ReplayGuardStore** (`infrastructure/qr`) | `QrValidator` | `ReplayGuard` | Verifies Ed25519 two-part prototype QR tokens (`base64url(JSON).base64url(sig)`) with cached public keys (0 s clock skew) and atomically checks/records `jti` in an in-memory `Lock`-guarded store. Private signing keys remain in the Hub; replay restart and multi-scanner behavior remain OD-08. |
| **AccessPolicyEvaluator** (`domain/policies`) | `AccessPolicyEngine` | `PolicySnapshotProvider` | Evaluates station/gate, direction, employee status, and policy freshness (`fresh_for=300s`, `max_stale_for=7200s`). Missing or too-stale policy denies locally and never calls the Hub synchronously. |
| **SQLite persistence managers** (`infrastructure/persistence`) | `AttendanceRepository`, `OutboxRepository` | `sqlite3` connection | Stores `access_attempts`, atomically stores `attendance_records` + `outbox_events` (`PENDING`, `SYNCED`, `REJECTED`, `CONFLICT`), and provides `next_sequence()`. Configured with `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, and `timeout=0.1` s (100 ms). Production sequence scope remains OD-11. |
| **TurnstileAdapter** (`infrastructure/turnstile`) | `GateAdapter` | Vendor hardware (stubbed) or mock | Sends bounded unlock commands and separately queries passage. `ACKNOWLEDGED` is not passage; the configured unlock timeout is 800 ms and the passage window is 15 seconds. `MockTurnstileAdapter` is implemented; `VendorTurnstileAdapter` is OD-13. |
| **SyncService + SyncRetryWorker** (`application/synchronization` + `infrastructure/synchronization`) | `SyncService`, `SyncRetryWorker` | `OutboxRepository`, `SyncClient` | Obtains pending records, sends batches, and marks only Hub-accepted IDs synchronized. Delivery is at least once with configured backoff/jitter (`5, 10, 20, 40, 60` s, jitter `0.8-1.0`). Uses `SimulatedSyncClient` in simulation mode; production `HttpSyncClient` and Hub auth remain OD-10. |

Note: No `UserFeedbackPort` or dedicated kiosk display component exists in the
implemented `tmc_access` codebase; immediate feedback is limited to the HTTP
JSON response returned by `/scan`. Public-key and policy snapshots are local
data owned by the validator and policy evaluator, and their distribution
mechanism is explicitly deferred to OD-09.

## 3. Connector catalog

| Connector | Roles | Nature and mechanism | Concurrency, buffering, guarantees, and failure behavior |
|---|---|---|---|
| **Scanner ingress channel** | `Scanner: Publisher` → `Scan Receiver: Receiver` | External scanner-to-kiosk transport; USB, serial, LAN, or keyboard-wedge mechanism is deployment-specific and unconfirmed by A1. | The API validates and bounds the envelope, rejects malformed input, and never logs raw payloads. Input buffering and scanner framing are deployment concerns, not a domain contract. |
| **In-process method call** | `Caller: required port` → `Callee: provided port` | Synchronous Python calls through domain `Protocol`s; no network serialization. | The ingress coordinator call blocks its request worker while local stages execute; bounded stage timeouts protect the response budget. No unbounded queue is implied. |
| **SQLite local persistence** | `AccessCoordinator/SyncService: repository clients` ↔ `SQLite repositories: persistence service` | SQLite C bindings and file-backed SQL transactions; the database file is internal state of this component. | SQLite serializes writers and permits readers under WAL (`PRAGMA synchronous=FULL`, `PRAGMA foreign_keys=ON`). Connection timeout is `0.1` s (`100` ms): on lock timeout or storage failure, the request fails closed (`StorageError`). |
| **Hardware driver interface** | `TurnstileAdapter: Master/Controller` ↔ `Turnstile controller: Actuator` | Vendor/serial/USB/LAN mechanism hidden behind `GateAdapter`; exact vendor protocol is OD-13. | `unlock` has an 800 ms bound. Unlock acknowledgement and passage polling are separate; uncertain outcomes are not blindly retried. |
| **HTTPS batch channel** | `SyncService: Sender/Publisher` → `Central Hub: Receiver/Collector` | Asynchronous HTTPS/TLS transport (or `SimulatedSyncClient` in simulation mode). | At-least-once delivery; Hub deduplicates by stable `transaction_id`. Transient errors use `5, 10, 20, 40, 60` s backoff with `0.8-1.0` jitter (`TMC_SYNC_BACKOFF_*`). Outbox capacity is not fixed by the architecture; disk-full behavior is an operational/OD-11 decision. |
| **Policy/key distribution (deferred)** | `Central Hub: Publisher` → `Validator/Policy: Snapshot receivers` | Placeholder asynchronous distribution connector; mechanism is OD-09. | No synchronous dependency is allowed on the access path. Until adopted, local snapshots are the only inputs and freshness rules govern denial. |

All connectors use the named roles above; a connector does not imply that
components share mutable in-memory state.

## 4. Dynamic interaction scenarios

### 4.1 Normal success: two-phase persistence

The following reflects the implemented `AccessCoordinator` flow following the
proposed OD-04 ordering (still pending formal ADR confirmation in `decisions.md`).

```mermaid
sequenceDiagram
    participant S as Scanner
    participant A as API Boundary
    participant C as AccessCoordinator
    participant V as QrValidator
    participant P as AccessPolicyEngine
    participant R as AttendanceRepository
    participant G as GateAdapter
    S->>A: ScanInput (payload, station, gate, direction)
    A->>C: handle_scan(scan)
    C->>V: validate(payload, station, received_at)
    V-->>C: QrValidationResult (valid credential)
    C->>P: evaluate(credential, gate, direction, received_at)
    P-->>C: AccessDecision (ALLOW)
    C->>R: save_attempt(ALLOWED_PERSISTED)
    R-->>C: committed (Phase 1)
    C->>G: unlock(command_id, gate, direction, 800 ms)
    G-->>C: GateCommandResult (ACKNOWLEDGED)
    C->>R: update_attempt(UNLOCK_ACKNOWLEDGED)
    C->>G: query_passage(command_id, 15 s)
    G-->>C: PassageStatus (CONFIRMED)
    C->>R: update_attempt(PASSAGE_CONFIRMED)
    C->>R: next_sequence()
    R-->>C: source_sequence
    C->>R: save_record_with_outbox(record)
    R-->>C: atomic commit (Phase 2)
    C-->>A: AccessAttempt (PASSAGE_CONFIRMED)
```

1. The scanner sends an envelope containing request, station, gate, direction,
   reception time, and raw payload. The API boundary redacts the payload in
   logs and representations.
2. The coordinator validates signature, claims, expiry, key status, and replay
   locally, then evaluates the cached policy.
3. If both checks allow access, it commits an `AccessAttempt` with
   `ALLOWED_PERSISTED`. The coordinator does not issue a gate command before
   this durable commit.
4. It calls `GateAdapter.unlock`. Only `GateAck.ACKNOWLEDGED` enters the
   passage-monitoring window. The kiosk may provide immediate visual/audio
   feedback at this point; acknowledgement is not attendance.
5. During the separate 15-second window, `query_passage` waits for physical
   evidence. Only `PassageStatus.CONFIRMED` advances the attempt.
6. The coordinator calls `save_record_with_outbox`. The authoritative
   `AttendanceRecord` and its outbox row commit in one local transaction.
7. `SyncService` later uploads the outbox item. The item becomes synchronized
   only when the Hub includes its stable identifier in `accepted_record_ids`.

### 4.2 Rejection and policy denial: fail closed

For malformed, invalid, expired, or replayed QR input, the validator returns a
non-valid result. For missing, corrupt, inactive, or stale policy, the policy
component returns a normal `DENY` decision. The coordinator persists a denied
`AccessAttempt` with a reason such as `QR_REJECTED`, `POLICY_MISSING`, or
`POLICY_STALE`, returns denial feedback, and **does not call the gate**.

If the denial audit write fails, the request is still fail-closed: no unlock is
issued and no success is reported. No attendance record or outbox row is
created for any denial.

### 4.3 Hardware failure and passage uncertainty

After a successful Phase 1 commit:

1. `REJECTED` updates the attempt to `UNLOCK_REJECTED`; no attendance is
   created.
2. `TIMEOUT` updates it to `UNLOCK_TIMEOUT`; the controller outcome is
   uncertain, so the unlock is not blindly retried and no attendance is
   created.
3. `UNAVAILABLE` is retained as a failed/uncertain attempt; no attendance is
   created.
4. `ACKNOWLEDGED` followed by `NOT_CONFIRMED`, `UNKNOWN`, or `UNAVAILABLE`
   updates the attempt to `PASSAGE_UNRESOLVED`. The kiosk must not claim
   attendance, and no Phase 2 outbox row is created.
5. `CONFIRMED` updates the attempt to `PASSAGE_CONFIRMED` and enables the
   atomic Phase 2 write. If that write fails, neither attendance nor outbox is
   reported as committed.

The controller acknowledgement fallback described in the A1 baseline is not
silently adopted: whether `ACKNOWLEDGED` can ever count as attendance is OD-05
and outside the confirmed C&C behavior.

### 4.4 Offline operation and store-and-forward

The scan-to-unlock sequence uses only the local public-key/policy state, gate
adapter, and SQLite. A WAN outage therefore does not block local authorization
while the policy remains within its configured usable-staleness rules. Confirmed
attendance records accumulate as `PENDING` outbox items.

The background loop obtains the oldest pending batch and sends it through the
Hub connector. Accepted IDs are marked synchronized. Network errors and HTTP
429/503 leave items pending and schedule capped exponential backoff with
jitter. Permanent item errors are quarantined so one poison item does not
stall unrelated records. A duplicate with identical content is idempotently
accepted; a conflicting duplicate remains a conflict for investigation.

## 5. Kiosk response-time budget

This budget is the allocation in
[`edge-access-contracts.md`](../contracts/edge-access-contracts.md), not a
benchmark result. It covers scan reception through immediate unlock feedback;
the 15-second passage monitor and synchronization are deliberately decoupled.

| Stage | Runtime component | Target | Hard bound / fallback |
|---|---|---:|---|
| Scan capture and envelope parsing | Scan Receiver / API Boundary | ≤ 30 ms | 100 ms; reject malformed envelope |
| Cryptographic verification and replay check | PublicKeyQrValidator + ReplayGuardStore | ≤ 20 ms | 50 ms; deny invalid, expired, or replayed input |
| Local policy evaluation | AccessPolicyEvaluator | ≤ 10 ms | 50 ms; deny missing or stale policy |
| Phase 1 attempt persistence | SQLite repository | ≤ 30 ms | 200 ms; fail closed and do not unlock |
| Turnstile unlock pulse | TurnstileAdapter | ≤ 200 ms | 800 ms; record timeout and fail closed |
| Immediate API response | `presentation/api` | ≤ 50 ms | 300 ms; return bounded HTTP JSON response |
| **Ingress authorization total** | **All above** | **≤ 340 ms** | **≤ 1,500 ms** |
| Passage monitoring | Gate sensor query (`query_passage`) | Asynchronous target | Separate 15-second window |

The remaining allowance to the hard 2,000 ms requirement is reserved for
operating-system scheduling and jitter. No synchronous Hub request is allowed
on this path. Meeting these targets under the 2–5 TPS factory burst target
requires performance testing; the current A2 prototype has not been
benchmarked for latency or throughput.

## 6. Invariants and open-decision boundaries

- **OD-04 — write ordering:** the target C&C sequence is Phase 1
  `AccessAttempt` commit → unlock → passage → atomic Phase 2
  `AttendanceRecord` plus outbox commit. It remains a proposed repository
  resolution until the decision register is formally updated.
- **OD-08 — replay state:** this view requires an atomic replay check and
  record, but does not decide persistence across restart or behavior with
  multiple scanners.
- **OD-10 — Edge-to-Hub authentication:** this view requires an asynchronous
  `SyncClient` and accepted-ID acknowledgement, but does not declare mTLS,
  application authentication, or a final endpoint as adopted.
- **OD-13 — vendor turnstile API:** this view specifies only the stable
  `GateAdapter` port and its timeout/result semantics. The vendor protocol is
  external and unresolved; the mock adapter is the test implementation.

Other lifecycle boundaries are normative: `AccessAttempt` is an audit entity
and is not an `AttendanceRecord`; unlock acknowledgement is not passage;
local persistence is not synchronization acknowledgement; and no stage may
report success for a later stage that has not committed.

## 7. Traceability and implementation status

The runtime participants map to `domain/interfaces`, `application`, and
`infrastructure` as described by [`module-view.md`](module-view.md). The
integrated A2 prototype implements and tests `PublicKeyQrValidator`,
`ReplayGuardStore`, `AccessPolicyEvaluator`, `AccessCoordinator`,
`SqliteAttendanceRepository`, `SqliteOutboxRepository`, `SyncService`,
`SyncRetryWorker`, `MockTurnstileAdapter`, `SimulatedSyncClient`, and the
FastAPI `/health` and `/scan` boundaries. `VendorTurnstileAdapter` (OD-13) and
production `HttpSyncClient` (OD-10) remain unimplemented/stubbed.
