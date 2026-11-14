# TMC Factory Gate Control Center — Web Demo Guide

## 1. System Requirements
- Windows 10/11 with PowerShell 5.1+ (or PowerShell 7+)
- Python 3.12+ with the project `.venv` installed (`pip install -e ".[dev]"`)
- Any modern local browser (Edge, Chrome, Firefox)
- No Docker, Node.js, external database, physical QR scanner, or turnstile hardware required.

## 2. Setup Commands (Windows PowerShell)
```powershell
cd C:\GitHub\Workspace\HCMUT\KTPM\A2\SA-tmc-attendance-access-control
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 3. One-Command Startup
```powershell
.\.venv\Scripts\python.exe -m uvicorn tmc_access.config.demo_container:create_demo_app --factory --host 127.0.0.1 --port 8000
```

## 4. Local Web URL
Open in your browser:
- `http://127.0.0.1:8000/`

## 5. Control Overview
- **Top Bar:** Displays Hub status (`ONLINE` / `OFFLINE`), **Presentation Mode** toggle (larger fonts, compact view for projection), **Refresh DB**, and **Reset Demo** (clears only `data/demo/`).
- **A. Factory Gate Simulation:** Select Factory (`BINH_DUONG` / `LONG_AN`), Gate (`GATE_01` / `GATE_02`), Direction (`ENTRY` / `EXIT`), and `MockTurnstileAdapter` outcome (`acked_with_passage`, `acked_no_passage`, `acked_passage_unavailable`, `rejected`, `timeout`, `unavailable`).
- **B. Demo Credential Issuer — Simulated Central Hub:** Demo-only local Ed25519 issuer (never part of the production Edge runtime). Select `Employee A` (authorized everywhere), `Employee B` (authorized at `GATE_02` only), or `Employee C` (inactive) to generate/scan/replay/tamper 2-part tokens.
- **C. Connectivity & Synchronization:** Toggle `SimulatedSyncClient` (`ONLINE`/`OFFLINE`), arm **Simulate Lost ACK**, trigger **Sync Pending Events** or **Simulate Retry**, and inspect live `PENDING`/`SYNCED`/`REJECTED`/`CONFLICT`/Hub counters.
- **D. Live Event Timeline:** Displays the 9 confirmed stages from QR reception through Hub sync without fabricating unexecuted steps.
- **E. Local SQLite WAL Database Viewer:** Queries `access_attempts`, `attendance_records`, and `outbox_events` directly from `data/demo/edge.db`.

## 6. Demonstrating All Seven Scenarios
1. **Scenario 1 — Successful Attendance:** Select `Employee A`, `GATE_01`, `acked_with_passage` → **Generate Signed QR** → **Scan QR** → observe `PASSAGE_CONFIRMED` and `PENDING` outbox → click **Sync Pending Events** → outbox becomes `SYNCED`, Hub Events = `1`.
2. **Scenario 2 — Invalid QR:** Click **Submit Malformed QR** → validator rejects (`QR_MALFORMED`), gate stays `LOCKED`, no attendance created.
3. **Scenario 3 — Replay Attack:** Generate & scan a valid QR for `Employee A`, then click **Replay Same QR** → `ReplayGuardStore` rejects (`QR_REPLAYED`), gate stays `LOCKED`, no duplicate attendance.
4. **Scenario 4 — Policy Denied:** Select `Employee B` at `GATE_01` → **Generate Signed QR** → **Scan QR** → QR valid, Policy denies (`NOT_AUTHORIZED_FOR_GATE`), gate stays `LOCKED`.
5. **Scenario 5 — Turnstile Failure:** With `Employee A`, change Turnstile Mock Scenario to `rejected`, `timeout`, or `acked_no_passage` and scan → observe `UNLOCK_REJECTED`, `UNLOCK_TIMEOUT`, or `PASSAGE_UNRESOLVED` with zero attendance rows created.
6. **Scenario 6 — Offline Operation:** Click **Switch Hub OFFLINE** → scan `Employee A` with `acked_with_passage` → local access succeeds and persists `PENDING` outbox → click **Switch Hub ONLINE** → **Sync Pending Events** → outbox transitions to `SYNCED`.
7. **Scenario 7 — Lost ACK & Idempotent Retry:** Ensure Hub is `ONLINE`, check **Simulate Lost ACK**, scan `Employee A` → click **Simulate Retry** (first push commits to `SimulatedHubReceiver` but raises `SyncError` on lost ACK; Edge stays `PENDING`, Hub Events increments by 1) → click **Switch Hub ONLINE** if disconnected and click **Simulate Retry** → `SimulatedHubReceiver` deduplicates on `transaction_id` (Hub Events does not duplicate) and Edge marks `SYNCED`.

## 7. Expected Outcomes Summary
- Every scan creates an `access_attempts` row (audit trail).
- Only `PASSAGE_CONFIRMED` creates an `attendance_records` + `outbox_events` row atomically.
- Raw signed QR payloads are never stored in SQLite tables.

## 8. Resetting the Demo
Click **Reset Demo** in the top bar (or `POST /demo/reset`). This deletes only `data/demo/edge.db*` and `data/demo/simulated_hub.db*` and resets in-memory `ReplayGuardStore` and `SimulatedSyncClient` state.

## 9. Known Limitations
- **Simulated Hub & Issuer:** `DemoCredentialIssuer` and `SimulatedHubReceiver` are local demo components; production Hub APIs (`OD-10`), policy/key distribution (`OD-09`), and vendor turnstile protocols (`OD-13`) remain out of scope.
- **In-memory Replay Guard:** `ReplayGuardStore` resets if the server process restarts (`OD-08`).

## 10. Troubleshooting
- **Port 8000 in use:** Pass `--port 8080` to `uvicorn`.
- **Database locked or stale state:** Stop the server or click **Reset Demo** to reinitialize `data/demo/`.
