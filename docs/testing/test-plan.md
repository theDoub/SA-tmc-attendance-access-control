# Test Plan

Skipped tests are **PENDING functionality**, not passes. `pytest -ra` prints each reason and `conftest.py` prints a PENDING count.

## Implemented scaffold tests (passing)

| Area | File | Verifies |
|---|---|---|
| Architecture boundaries | `tests/unit/test_smoke_architecture.py` | All modules import; layers do not import outer layers; no retry/backoff/cache settings in domain |
| Wiring | `tests/unit/test_wiring.py` | Container builds; unimplemented flows raise `NotImplementedError`; settings match A1 values |
| Mock turnstile | `tests/unit/test_mock_turnstile.py` | Deterministic outcomes; ack ≠ passage; no default scenario |
| SQLite | `tests/unit/test_sqlite_wal.py` | WAL on a **file-backed** DB; in-memory rejected |
| API | `tests/unit/test_api_smoke.py` | `/health` 200; `/scan` 501; payload not echoed/repr'd |
| Models | `tests/unit/test_models.py` | Lifecycle types stay distinct; result invariants |
| Access policy | `tests/unit/access/test_policy_evaluator.py` | Fresh/stale/missing policy, grants and inactive subjects |
| Access flow | `tests/unit/access/test_access_scenarios.py` | Denials, write-before-unlock, gate/passage outcomes and attendance creation |

## Pending scenarios (not implemented)

| # | Scenario | File | Owner | Blocked by |
|---|---|---|---|---|
| 1 | Valid QR | `tests/unit/qr/` | Hieu | OD-01, OD-02 |
| 2 | Invalid signature | `tests/unit/qr/` | Hieu | OD-01 |
| 3 | Expired QR | `tests/unit/qr/` | Hieu | OD-02 |
| 4 | Replay attack | `tests/unit/qr/` | Hieu | OD-08 |
| – | Malformed QR (extra) | `tests/unit/qr/` | Hieu | OD-02 |
| 7 | Network disconnection | `tests/integration/` | Nhật | OD-11 |
| 8 | Local event persistence | `tests/integration/` | Nhật | OD-04, OD-11 |
| 9 | Reconnection and synchronization | `tests/integration/` | Nhật | OD-10, OD-11 |
| 10 | Duplicate event ingestion | `tests/integration/` | Nhật | OD-06, OD-11 |

Test data must be synthetic. Never use real QR tokens, employee data or keys.

## Commands
```text
pytest                     # all
pytest -m unit             # unit only
pytest -m integration      # integration only
pytest -m pending -rs      # list pending placeholders
```
