from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_bqe.json"


def load_fixture(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    with (path or fixture_path()).open(encoding="utf-8") as handle:
        return json.load(handle)


def sync_mock(warehouse: Any, path: Path | None = None) -> dict[str, int]:
    fixture = load_fixture(path)
    counts: dict[str, int] = {}
    for resource in ("clients", "employees", "projects", "time_entries", "expense_entries", "invoices", "payments", "allocations"):
        rows = fixture.get(resource, [])
        warehouse.store_raw(resource, rows, context="synthetic fixture; no company data")
        counts[resource] = warehouse.normalize(resource, rows)
    return counts
