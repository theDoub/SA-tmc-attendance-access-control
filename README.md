# TMC QR-based Attendance and Access Control: Edge Gate Access Processing

> **Status: Edge access core implemented; other components remain scaffolded.** Contracts,
> structure, tooling, access policy evaluation, access-flow orchestration, a deterministic mock
> turnstile and unit tests exist. QR verification, SQLite repositories, outbox and synchronization
> are not implemented yet. Their unfinished paths raise `NotImplementedError`; pending scenarios
> are skipped and are not passes.

## 1. Project Title
TMC QR-based Attendance and Access Control System: Assignment 2 (Edge Gate Access Processing module).

## 2. Course and Group Information
- Course: Software Architecture (CO3017), Ho Chi Minh City University of Technology (HCMUT), VNU-HCM. Advisor: Truong Thi Thai Minh.
- Group 6: Nguyen Ngoc Kim (2352661), Nguyen Nhat Hieu (2352230), Bui Doan Minh Nhat (2352855), Nguyen Tran Tuan Khai (2452514), Vu Quoc Viet (2353326).

## 3. Project Overview
TMC Manufacturing Joint Stock Company (Binh Duong ≈800 employees, Long An ≈600) needs QR-based access control and attendance, integrated with the existing HR/Payroll and Turnstile Control systems. Assignment 2 implements one module: **Edge Gate Access Processing**:

QR scan → QR validation → access policy evaluation → gate command → access outcome / attendance recording → offline event storage → asynchronous synchronization.

## 4. Assignment 1 → Assignment 2 Relationship
The Assignment 1 report (`Assignment1_Group6.pdf`, not stored in this repo) is the architectural baseline: ADR-001..004 are Accepted there. A2 implements the Edge half of that design and addresses two issues: connectivity loss during transaction processing and the security risk of static QR codes. Where A1 is inconsistent, this repo records an **open decision** instead of choosing silently: [docs/architecture/decisions.md](docs/architecture/decisions.md).

## 5. System Context
Employee phone shows a QR → gate scanner → kiosk (Edge) → existing turnstile controller. The kiosk syncs attendance asynchronously to the central Hub, which integrates with HR/Payroll monthly. Diagrams: [component-connector view](docs/architecture/component-connector-view.md), [allocation view](docs/architecture/allocation-view.md).

## 6. Architecture Overview
Distributed Edge–Hub topology; Modular Monolith Hub; layered structure; dynamic signed QR credentials (public-key verification at the Edge); offline-first Edge with local cache, Transactional Outbox, Store-and-Forward and idempotent ingestion. See [overview](docs/architecture/overview.md).

Attendance lifecycle (each stage is a separate concept): QR validation → access authorization → unlock acknowledgement → passage confirmation → attendance record → local persistence → central sync acknowledgement. Details: [contracts](docs/contracts/edge-access-contracts.md).

## 7. Scope and Out-of-Scope
| In scope (A2) | Out of scope |
|---|---|
| Edge QR verification contract and tests | Hub modules, Hub ingestion API implementation |
| Access policy evaluation | Mobile app, QR issuance/signing (OD-01) |
| Turnstile adapter contract + mock | Real turnstile hardware / vendor API (OD-13) |
| Attendance recording, SQLite WAL, outbox, sync client | HR/Payroll export, reporting, administration UI |
| Unit and integration tests | Microservices, Kubernetes, Kafka, Redis, Celery, Docker |

## 8. Selected Technology Stack
Python 3.12, FastAPI (API/simulation boundary only), Pydantic and pydantic-settings, SQLite with WAL, `cryptography` (public-key verification), pytest, Ruff, `pyproject.toml` packaging, GitHub Actions. Docker is intentionally omitted.

## 9. Repository Structure
```text
src/tmc_access/
  domain/            models/ interfaces/ policies/   (pure; no outer-layer imports)
  application/       access/ synchronization/        (use cases)
  infrastructure/    qr/ turnstile/ persistence/ synchronization/
  presentation/api/                                  (FastAPI)
  config/                                            (settings + composition root)
tests/               unit/ (qr, access) integration/ conftest.py
docs/                architecture/ contracts/ testing/
scripts/             validate.ps1 validate.sh scan_secrets.py check_workflow.py
.github/             workflows/ci.yml pull_request_template.md
```

## 10. Team Responsibilities
| Member | Responsibility | Owned areas |
|---|---|---|
| Nguyen Nhat Hieu | M2 issue analysis, QR verification & tests | `infrastructure/qr`, `tests/unit/qr`, QR security docs |
| Nguyen Tran Tuan Khai | Architecture views & integration contracts | `docs/architecture/*view*.md`, `overview.md`, `docs/contracts/`, integration verification |
| Nguyen Ngoc Kim | Edge access core | `application/access`, `domain/policies`, `domain/models`, `tests/unit/access` |
| Bui Doan Minh Nhat | Gate/outbox adapters, offline processing | `infrastructure/turnstile` (mock + vendor), `persistence`, `synchronization`, `application/synchronization`, `tests/integration`, demo scripts |
| Vu Quoc Viet | ADRs, SOLID reflection, report integration, final QA | `docs/architecture/decisions.md`, traceability, SOLID review, QA |

SOLID reflection and report text are **not** written yet; they must be based on the implemented and tested code.

## 11. Prerequisites
- Python **3.12** (`python --version` must show 3.12.x)
- Git
- No other services are needed.

## 12. Installation and Environment Setup

**Windows PowerShell**
```powershell
git clone https://github.com/theDoub/SA-tmc-attendance-access-control.git
Set-Location SA-tmc-attendance-access-control
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "install failed" }
Copy-Item .env.example .env
```
If scripts are blocked, run `powershell -ExecutionPolicy Bypass -File scripts/validate.ps1` instead of activating the venv.

**macOS / Linux**
```bash
git clone https://github.com/theDoub/SA-tmc-attendance-access-control.git
cd SA-tmc-attendance-access-control
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

### Environment variables (all prefixed `TMC_`, dummy values in `.env.example`)
| Variable | Default | Source |
|---|---|---|
| `TMC_EDGE_ID`, `TMC_STATION_ID`, `TMC_FACTORY_ID` | required | dummy ids |
| `TMC_SQLITE_PATH` | `data/edge.db` | file-backed (WAL) |
| `TMC_HUB_BASE_URL` | `https://hub.example.invalid` | placeholder |
| `TMC_QR_PUBLIC_KEY_DIR` | `keys/public` | public keys only (git-ignored) |
| `TMC_QR_CLOCK_SKEW_SECONDS` | unset | no A1 value (OD-02/08) |
| `TMC_CACHE_FRESH_SECONDS` / `TMC_CACHE_MAX_STALE_SECONDS` | 300 / 7200 | A1 Table 28 |
| `TMC_CENTRAL_AUTH_TIMEOUT_MS` | 500 | A1 Table 28 |
| `TMC_TURNSTILE_TIMEOUT_MS` / `TMC_PASSAGE_WINDOW_SECONDS` | 800 / 15 | A1 Table 29, §4.2.3 |
| `TMC_TURNSTILE_MODE` | `vendor` (stub) | `vendor` or `mock` |
| `TMC_TURNSTILE_MOCK_SCENARIO` | none; **required** when mode is `mock` | `acked_with_passage`, `acked_no_passage`, `acked_passage_unavailable`, `rejected`, `timeout`, `unavailable` |
| `TMC_SYNC_BACKOFF_DELAYS_SECONDS` | `[5,10,20,40,60]` (JSON) | A1 §4.3.5 |
| `TMC_SYNC_BACKOFF_JITTER_MIN` / `_MAX` | 0.8 / 1.0 | A1 §4.3.5 |

## 13. Running the Project
Only the health endpoint and a `/scan` endpoint that answers **501 Not Implemented** exist.

PowerShell: `.\.venv\Scripts\python.exe -m uvicorn tmc_access.config.container:create_default_app --factory`
bash: `.venv/bin/python -m uvicorn tmc_access.config.container:create_default_app --factory`

Then open `http://127.0.0.1:8000/health` (expected `{"status":"ok","mode":"scaffold-only"}`).

## 14. Running Tests
```powershell
.\.venv\Scripts\python.exe -m pytest              # PowerShell
```
```bash
.venv/bin/python -m pytest                        # bash
```
Skipped tests marked `PENDING` are unimplemented scenarios. They are **not** successes. Use `-m pending -rs` to list them. See [test plan](docs/testing/test-plan.md).

## 15. Code Quality Checks
Full local validation (fails on the first failing command):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/validate.ps1
```
```bash
bash scripts/validate.sh
```
Individual commands (CI runs exactly these): `ruff check .`, `ruff format --check .`, `python scripts/scan_secrets.py`, `pytest`. Apply formatting with `ruff format .`. Validate the workflow with `python scripts/check_workflow.py`.

## 16. Development Workflow
Sync `main` → feature branch → implement your component → tests → `scripts/validate.*` → docs → Conventional Commit → push → PR → review → merge. See [CONTRIBUTING.md](CONTRIBUTING.md).

## 17. Component Integration Rules
1. Depend on interfaces in `domain/interfaces`; never on a sibling's concrete class.
2. Do not change another member's contract without their agreement and a docs update.
3. Dependency direction: presentation → application → domain ← infrastructure; only `config/container.py` wires concrete classes. A test enforces it.
4. Never merge lifecycle stages: unlock ack ≠ passage ≠ attendance.
5. Retry/backoff and cache windows are configuration, not domain.

## 18. Coding Conventions
Type hints everywhere; Ruff (line length 100); small focused classes; constructor injection; no secrets or personal data in source; structured error categories from `domain/errors.py`; never log raw QR payloads. Unimplemented behaviour: `NotImplementedError("TODO(owner): ...")`, never fake success.

## 19. Git Branching and Pull Request Rules
Branches: `feature/qr-validation`, `feature/access-core`, `feature/offline-outbox`, `docs/architecture-views`, `docs/adr-solid-reflection`. Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`). No direct commits to `main` in normal work (the initial bootstrap was the one authorized exception). No force pushes. Branch protection is configured on GitHub by the repository owner, not by this repo's tooling.

## 20. Architecture Decision Guidelines
Do not reverse an accepted ADR silently. New decision → new ADR in `docs/architecture/decisions.md`:
```text
ADR-00N: Title | Status (Proposed/Accepted/Superseded) | Context | Decision | Consequences | Supersedes
```
Resolve open decisions (OD-nn) by recording the outcome and updating affected contracts and tests in the same PR.

## 21. Known Limitations / Open Decisions
The Edge access core follows the documented OD-04/OD-05 bootstrap assumptions; the default app
still depends on unfinished QR and persistence components. Blocking decisions: OD-01 QR
signing/issuance, OD-02 payload claims, OD-04 write ordering around unlock, OD-05 ack-only
attendance, OD-08 replay-state storage, OD-10 Edge→Hub authentication, OD-11 persistence schema,
OD-13 vendor turnstile API. Non-blocking: OD-03, 06, 07, 09, 12. Details:
[decisions.md](docs/architecture/decisions.md#open-decisions).

## 22. Assignment Submission Checklist
- [ ] Components implemented by owners; no `NotImplementedError` left in delivered paths
- [ ] Pending tests converted to real tests (or documented as out of scope)
- [ ] Open decisions resolved and recorded
- [ ] Module, C&C and Allocation views completed (Khai)
- [ ] SOLID reflection written from real code and tests (Viet)
- [ ] Architecture-to-code traceability and report integration checklist (Viet)
- [ ] `scripts/validate.*` passes on a clean clone; CI is green
- [ ] No secrets, keys, real employee data or databases committed
