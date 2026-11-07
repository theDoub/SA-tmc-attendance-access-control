# Architecture Decisions

Baseline: `Assignment1_Group6.pdf` §5.1. ADR-001..004 are **Accepted in A1**. The summaries below paraphrase A1 and cite it; the authoritative text is in the report. Owner of refinement: Vu Quoc Viet. Do not edit accepted decisions silently: supersede them with a new ADR.

## ADR index

| ID | Title | A1 status | A1 location | Summary (paraphrase) |
|---|---|---|---|---|
| ADR-001 | Macro & micro architectural style | Accepted | §5.1.2 | Distributed Edge–Hub topology; Modular Monolith for the Central Hub; Edge nodes authorize locally. |
| ADR-002 | Dynamic cryptographically signed QR verification | Accepted | §5.1.3 | Short-lived signed QR; Edge verifies offline with cached public keys; private keys stay in the Hub. *Contains the OD-01/02/03 inconsistencies.* |
| ADR-003 | Offline-first Edge via local cache and transactional outbox | Accepted | §5.1.4 | SQLite WAL; permission cache (fresh 5 min, usable offline ≤ 2 h); outbox written before unlock; store-and-forward with backoff; idempotent ingestion on `transaction_id`. *Contains OD-04.* |
| ADR-004 | Legacy HR/Payroll integration | Accepted | §5.1.5 | Scheduled batch adapter in the Hub (06:00 on the 1st); out of scope for the Edge module. |

Status in this repository: **needs team review** for ADR-002 and ADR-003 wording (see below). No ADR has been re-decided here.

## Open decisions

Classification: **Blocking** = must be decided before the named component can be implemented. **Non-blocking** = may stay pending; the bootstrap and other components proceed with the documented assumption.

### Blocking for implementation

| ID | Question | Evidence in A1 | Blocks | Bootstrap assumption |
|---|---|---|---|---|
| OD-01 | Who signs QR tokens and how does the phone get one? | ADR-002: phone "generates" signed token **and** private keys only in Hub; §4.1.3: phone "retrieves" QR; Fig. 5 labels Hub backend "Modular Monolith / QR Issuance" | Real `PublicKeyQrValidator` and any test-token tooling (Hieu) | Validator is verify-only; no signing code or private keys in the repo |
| OD-02 | QR payload claim set | ADR-002: employee_id, iat, exp, key_version_id, nonce; §3.5.4: opaque subject, issuer, audience, iat, exp, jti, key version | Validator, `VerifiedCredential` | Domain type carries subject, token id, key version, iat, exp (intersection) |
| OD-04 | Order of writes around the unlock | ADR-003: attempt **and attendance event** before unlock; §3.5.2/§4.2.3: event after passage; Fig. 4 4B: attempt + pending outbox before unlock, 7B: attendance on success | Access Coordinator (Kim), repositories (Nhật) | **Proposed:** attempt persisted → unlock → passage → record + outbox atomically |
| OD-05 | May a controller ACK alone create attendance when passage sensors are unavailable? | §3.5.3 allows ACK fallback; LSP bullet and §5.3.2 require an uncertainty flag and passage evidence | Attendance recorder rules | ACK is never passage; `ConfirmationEvidence.CONTROLLER_ACK_ONLY` exists but is unused |
| OD-08 | Replay-state storage (memory/SQLite), restart behaviour, multiple scanners | §3.5.4 only says "short-lived replay cache"; Fig. 4 step 3 reads "replay state" from the local store | `ReplayGuard`, replay tests (Hieu) | Port exists; stub only |
| OD-10 | Edge→Hub authentication | §3.7.1: per-Edge certificate + mTLS; Table 22 / ADR-003: "HTTPS/API" | Real `HttpSyncClient` (Nhật) | Stub only; no schema invented |
| OD-11 | Outbox/attempt schema, sequence numbers (per gate or per kiosk), `synchronous` level | §3.5.5 mentions a source sequence number; Table 30 lists no sequence | Persistence implementation (Nhật) | Contract specifies atomicity and idempotency only |
| OD-13 | Vendor turnstile API | Fig. 5: "Vendor API*"; §4.2.2 "if supported" | Real `VendorTurnstileAdapter` | Mock adapter covers all contract outcomes |

### Non-blocking for bootstrap

| ID | Question | Evidence | Note |
|---|---|---|---|
| OD-03 | QR validity 30–60 s or 60 s | ADR-002 vs Table 20 | Configuration value once decided |
| OD-06 | Identifier naming (`eventId`/`transaction_id`/`accessAttemptId`/`access_request_id`) | §3.5.5, ADR-003, §3.7.1 | Proposed mapping in contracts §3 |
| OD-07 | Central authorization fallback (500 ms) when cache is stale but Hub reachable vs "gate path entirely local" | Table 28 vs §2.2 | Edge module implements local decisions only |
| OD-09 | Policy distribution: push notifications vs 60 s polling | §2.4.3 vs §4.3.2 | Policy distribution client is outside this module |
| OD-12 | Manual reconciliation flow for unresolved attempts after the 15 s window | Table 26 | Attempt retained as `PASSAGE_UNRESOLVED`; workflow undefined |

### A1 figures consulted

Figures 2 (logical topology), 4 (QR scanning sequence) and 5 (physical deployment) were inspected as images, not inferred from extracted text. Figure 4 step labels informed OD-04; Figure 5 informed OD-01 and OD-13. Figures 1, 3, 6 and 7 were **not** inspected as images (Figure 6's text was extracted from the PDF); anything in this repository that depends on them is cited to A1 prose/tables only. Diagrams here redraw only what Figures 2 and 5 show.

## New ADRs

Use the template in `README.md` (section "Architecture Decision Guidelines"). Proposed ADRs for the team to raise: QR issuance and signing (OD-01), write ordering (OD-04).
