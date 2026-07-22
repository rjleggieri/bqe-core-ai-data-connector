from __future__ import annotations

from pathlib import Path

import pytest

from bqe_reporting.analysis import employee_summary, monthly_trends, project_summary
from bqe_reporting.mock import load_fixture, sync_mock
from bqe_reporting.storage import Warehouse


@pytest.fixture
def warehouse(tmp_path: Path):
    with Warehouse(tmp_path / "test.sqlite3") as value:
        sync_mock(value)
        yield value


def test_normalization_and_duplicate_handling(tmp_path: Path) -> None:
    fixture = load_fixture()
    with Warehouse(tmp_path / "test.sqlite3") as wh:
        assert wh.store_raw("clients", fixture["clients"])
        assert not wh.store_raw("clients", fixture["clients"])
        wh.normalize("clients", fixture["clients"])
        wh.normalize("clients", fixture["clients"])
        assert wh.connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 2
        assert wh.connection.execute("SELECT COUNT(*) FROM raw_api_response").fetchone()[0] == 1


def test_incremental_sync_updates_row_and_watermark(tmp_path: Path) -> None:
    with Warehouse(tmp_path / "test.sqlite3") as wh:
        first = {"id": "client-1", "name": "Before", "lastUpdated": "2026-01-01T00:00:00Z"}
        later = {"id": "client-1", "name": "After", "lastUpdated": "2026-02-01T00:00:00Z"}
        wh.normalize("clients", [first])
        wh.normalize("clients", [later])
        row = wh.connection.execute("SELECT name,last_updated FROM clients").fetchone()
        state = wh.connection.execute("SELECT high_watermark FROM sync_state WHERE resource='clients'").fetchone()
        assert tuple(row) == ("After", "2026-02-01T00:00:00Z")
        assert state[0] == "2026-02-01T00:00:00Z"


def test_missing_and_null_fields_are_safe(tmp_path: Path) -> None:
    with Warehouse(tmp_path / "test.sqlite3") as wh:
        wh.normalize("clients", [{"id": "c1", "name": None}])
        wh.normalize("employees", [{"id": "e1", "displayName": "Null Fields", "managerId": None}])
        wh.normalize("projects", [{"id": "p1", "clientId": "c1", "managerId": "e1", "name": "Sparse"}])
        wh.normalize("time_entries", [{"id": "t1", "projectId": "p1", "resourceId": "e1", "actualHours": None, "billable": True}])
        row = wh.connection.execute("SELECT actual_hours,bill_rate,cost_rate FROM time_entries").fetchone()
        assert tuple(row) == (0.0, None, None)


def test_limited_fact_sync_does_not_require_project_or_employee_dimensions(tmp_path: Path) -> None:
    with Warehouse(tmp_path / "pilot.sqlite3") as wh:
        wh.normalize(
            "time_entries",
            [{"id": "t1", "projectId": "opaque-project", "resourceId": "opaque-resource", "actualHours": 1}],
        )
        assert wh.connection.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 1


def test_financial_aggregation_consistency(warehouse: Warehouse) -> None:
    rows = project_summary(warehouse.connection)
    assert sum(row["invoice_total"] for row in rows) == pytest.approx(34200)
    assert sum(row["payment_total"] for row in rows) == pytest.approx(20000)
    assert sum(row["outstanding_balance"] for row in rows) == pytest.approx(14200)
    assert sum(row["unbilled_time_value"] for row in rows) == pytest.approx(21700)
    assert sum(row["estimated_billable_value"] for row in rows) == pytest.approx(54700)


def test_workload_and_monthly_trends(warehouse: Warehouse) -> None:
    employees = employee_summary(warehouse.connection)
    trends = monthly_trends(warehouse.connection)
    alex = next(row for row in employees if row["employee_name"] == "Alex Rivera")
    assert alex["hours"] == pytest.approx(143)
    assert [row["month"] for row in trends] == ["2026-06", "2026-07"]
    assert trends[0]["hours"] == pytest.approx(195)
    assert trends[1]["hours"] == pytest.approx(144)
