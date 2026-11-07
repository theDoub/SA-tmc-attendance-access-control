# Contributing

## Workflow
1. **Synchronize with `main`:** `git switch main` then `git pull origin main`.
2. **Create a feature branch:** `git switch -c feature/<topic>`.
3. **Implement your assigned component** (ownership: `README.md` section 10).
4. **Add or update tests.**
5. **Run linting and tests:** `scripts/validate.ps1` (Windows) or `scripts/validate.sh`. They stop at the first failing command.
6. **Update documentation** (contracts, test plan, decisions) if behaviour or interfaces changed.
7. **Commit** using Conventional Commits.
8. **Push the branch:** `git push -u origin <branch>`.
9. **Open a Pull Request** to `main` using the template.
10. **Resolve CI failures**, get review from the component owner(s) affected, then merge.

## Branch names
`feature/qr-validation`, `feature/access-core`, `feature/offline-outbox`, `docs/architecture-views`, `docs/adr-solid-reflection`.

## Commit format
`<type>: <summary>` with `feat`, `fix`, `test`, `docs`, `refactor`, `chore`. Example: `test: add expired-token scenario for QR validator`.

## Rules
- **Do not commit directly to `main`** during normal teamwork. *Exception:* the initial authorized bootstrap commit.
- Do not force-push or rewrite shared history.
- Do not change another member's contract without agreement; note it in the PR.
- Do not commit `.env`, keys, databases, logs or real employee data. `python scripts/scan_secrets.py` checks for this.
- Skipped `PENDING` tests are not completed work. Replace a placeholder with a real test only together with the real behaviour.
- Unresolved architectural questions go into `docs/architecture/decisions.md` as OD entries.
- Repository branch protection is configured by the repository owner on GitHub; do not attempt to change it from tooling.
