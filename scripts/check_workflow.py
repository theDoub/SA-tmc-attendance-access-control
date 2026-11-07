"""Validate the CI workflow: parses as YAML, triggers on main, runs the documented commands."""

import sys
from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/ci.yml")
REQUIRED_COMMANDS = (
    'pip install -e ".[dev]"',
    "ruff check .",
    "ruff format --check .",
    "pytest",
    "python scripts/scan_secrets.py",
)


def main() -> int:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = data.get("on", data.get(True))  # PyYAML parses bare `on` as boolean True
    errors = []
    for event in ("push", "pull_request"):
        if "main" not in triggers.get(event, {}).get("branches", []):
            errors.append(f"workflow must trigger on {event} to main")
    steps = [s for job in data["jobs"].values() for s in job["steps"]]
    runs = "\n".join(s.get("run", "") for s in steps)
    errors += [f"missing command: {c}" for c in REQUIRED_COMMANDS if c not in runs]
    if errors:
        print("\n".join(errors))
        return 1
    print("Workflow OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
