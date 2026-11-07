"""Smoke tests: packages import and layer dependency direction holds."""

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

import tmc_access

SRC = Path(tmc_access.__file__).parent
FORBIDDEN = {
    "domain": {"application", "infrastructure", "presentation", "config", "fastapi", "pydantic"},
    "application": {"infrastructure", "presentation", "config", "fastapi"},
    "infrastructure": {"application", "presentation", "config", "fastapi"},
    "presentation": {"infrastructure", "config"},
}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.unit
def test_all_modules_import() -> None:
    names = [m.name for m in pkgutil.walk_packages(tmc_access.__path__, "tmc_access.")]
    assert len(names) > 20
    for name in names:
        importlib.import_module(name)


@pytest.mark.unit
@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_does_not_import_outer_layers(layer: str) -> None:
    violations = []
    for file in (SRC / layer).rglob("*.py"):
        for module in _imports(file):
            parts = module.split(".")
            target = parts[1] if parts[0] == "tmc_access" and len(parts) > 1 else parts[0]
            if target in FORBIDDEN[layer]:
                violations.append(f"{file.relative_to(SRC)} imports {module}")
    assert not violations, violations


@pytest.mark.unit
def test_domain_has_no_sync_retry_settings() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in (SRC / "domain").rglob("*.py"))
    for forbidden in ("backoff_delays", "jitter_min", "max_stale_seconds"):
        assert forbidden not in text
