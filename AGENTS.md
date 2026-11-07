# AGENTS.md: Instructions for Coding Agents

Applies to any AI/coding agent working in this repository.

1. **Inspect first.** Read `README.md`, `docs/contracts/edge-access-contracts.md`, `docs/architecture/decisions.md` and the relevant package before editing.
2. **Follow existing interfaces and module boundaries** (`domain/interfaces`, layer rules in `docs/architecture/module-view.md`). `tests/unit/test_smoke_architecture.py` enforces them.
3. **Never silently modify another member's component contract.** Ownership is in `README.md` section 10. Change a contract only with the owner's agreement and update the contracts doc in the same change.
4. **Prefer small, targeted changes.** No unrelated refactoring.
5. **No new architecture styles** (microservices, message brokers, caches, etc.) without a written ADR.
6. **Follow SOLID**; depend on abstractions; wire concrete classes only in `config/container.py`.
7. **Write or update tests** for implemented behaviour; update docs when behaviour or interfaces change.
8. **Do not fake implementations to satisfy tests.** Unfinished code raises `NotImplementedError("TODO(owner): ...")`. Never write a validator that accepts arbitrary credentials, never report success for an unlock, passage or sync that did not happen, and never convert a skipped PENDING test into a pass without real behaviour.
9. **Keep lifecycle stages distinct:** QR validation, authorization, unlock acknowledgement, passage confirmation, attendance record, local persistence, sync acknowledgement. `AccessAttempt` ≠ `AttendanceRecord`.
10. **Security:** no credentials, private keys, tokens or personal data in source, tests, docs or logs; synthetic data only. Do not put private signing keys on Edge or phones; QR issuance is an open decision (OD-01). Never log raw QR payloads.
11. **Keep operational settings out of the domain layer** (retry, backoff, cache windows → config/infrastructure).
12. **Do not rewrite Git history** (no force-push, no amend of pushed commits, no rebase of shared branches).
13. **Report unresolved architectural questions** (add or update an OD entry) instead of guessing. Do not present unconfirmed details as decisions.
14. Run `scripts/validate.ps1` (Windows) or `scripts/validate.sh` before declaring work done, and report skipped/pending tests honestly.
