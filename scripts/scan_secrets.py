"""Targeted secret scan over files Git would track. Exit code 1 if anything suspicious is found.

Deliberately NOT a plain keyword grep: a bare `password` or `token` is fine in docs and code.
Flags: private-key blocks, well-known credential formats, quoted literal values assigned to
secret-like names, and files that must never be committed (keys, local databases).
"""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "private key block": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "quoted secret literal": re.compile(
        r"""(?ix)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)
        \w*\s*[:=]\s*["'](?P<value>[^"'<>\s]{8,})["']"""
    ),
}
PLACEHOLDER = re.compile(r"(?i)example|dummy|changeme|placeholder|synthetic|\*{3,}|x{4,}")
FORBIDDEN_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3")
SELF = Path(__file__).name


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [Path(line) for line in out.splitlines() if line]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name == ".env":
            findings.append(f"{path}: file type must not be committed")
            continue
        if path.name == SELF or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.groupdict().get("value") or match.group(0)
                if PLACEHOLDER.search(value):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path}:{line}: {label}")
    if findings:
        print("Possible secrets found:")
        print("\n".join(f"  {f}" for f in findings))
        return 1
    print("Secret scan: no findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
