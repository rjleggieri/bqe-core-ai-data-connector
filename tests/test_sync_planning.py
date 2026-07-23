from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from bqe_reporting.analysis import employee_summary, project_summary
from bqe_reporting.client import BQEClient
from bqe_reporting.planning import planning_context, write_planning_context
from bqe_reporting.storage import Warehouse
from bqe_reporting.sync import RESOURCE_SPECS, SyncEngine, build_where


def test_incremental_where_and_initial_fact_guard() -> None:
    projects = RESOURCE_SPECS["projects"]
    time_entries = RESOURCE_SPECS["time_entries"]
    assert build_where(
        projects,
        watermark="2026-07-01T12:00:00Z",
        date_from=None,
        date_to=None,
        full=False,
    ) == "lastUpdated>='2026-07-01T12:00:00Z'"
    with pytest.raises(ValueError, match="supply --from/--to"):
        build_where(
            time_entries,
            watermark=None,
            date_from=None,
            date_to=None,
            full=False,
        )
    assert build_where(
        time_entries,
        watermark=None,
        date_from="2026-07-01",
        date_to="2026-07-07",
        full=False,
    ) == (
        "date>='2026-07-01T00:00:00' AND "
        "date<'2026-07-08T00:00:00'"
    )


def test_sync_engine_paginates_audits_and_checkpoints(tmp_path: Path) -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        pages.append(page)
        if page == "1,2":
            return httpx.Response(
                200,
                json=[
                    {"id": "c1", "name": "Example One", "lastUpdated": "2026-07-01T00:00:00Z"},
                    {"id": "c2", "name": "Example Two", "lastUpdated": "2026-07-02T00:00:00Z"},
                ],
            )
        return httpx.Response(
            200,
            json=[
                {"id": "c3", "name": "Example Three", "lastUpdated": "2026-07-03T00:00:00Z"}
            ],
        )

    with Warehouse(tmp_path / "sync.sqlite3") as warehouse:
        with BQEClient(
            "https://example.test/api",
            "synthetic",
            transport=httpx.MockTransport(handler),
        ) as client:
            result = SyncEngine(client, warehouse).sync(["clients"], page_size=2)[0]
        assert result.status == "complete"
        assert result.pages == 2
        assert result.rows == 3
        assert warehouse.row_counts()["clients"] == 3
        assert warehouse.row_counts()["raw_api_response"] == 2
        assert warehouse.get_watermark("clients") == "2026-07-03T00:00:00Z"
        run = warehouse.connection.execute(
            "SELECT status FROM sync_runs"
        ).fetchone()
        assert run["status"] == "complete"
    assert pages == ["1,2", "2,2"]


def test_sync_engine_continues_when_resource_is_not_authorized(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/project"):
            return httpx.Response(403, json={"error": "forbidden"})
        return httpx.Response(
            200,
            json=[{"id": "e1", "displayName": "Example Employee", "lastUpdated": "2026-07-01"}],
        )

    with Warehouse(tmp_path / "partial.sqlite3") as warehouse:
        with BQEClient(
            "https://example.test/api",
            "synthetic",
            transport=httpx.MockTransport(handler),
        ) as client:
            results = SyncEngine(client, warehouse).sync(["projects", "employees"])
        assert [result.status for result in results] == ["unavailable", "complete"]
        assert warehouse.row_counts()["employees"] == 1
        run = warehouse.connection.execute("SELECT status FROM sync_runs").fetchone()
        assert run["status"] == "partial"


def test_fact_names_support_planning_without_dimension_access(tmp_path: Path) -> None:
    with Warehouse(tmp_path / "facts.sqlite3") as warehouse:
        warehouse.store_raw(
            "time_entries",
            [
                {
                    "id": "t1",
                    "projectId": "p1",
                    "project": "1001 Example Project",
                    "resourceId": "e1",
                    "resource": "Example Employee",
                    "actualHours": 8,
                    "billable": True,
                }
            ],
        )
        warehouse.normalize(
            "time_entries",
            [
                {
                    "id": "t1",
                    "projectId": "p1",
                    "project": "1001 Example Project",
                    "resourceId": "e1",
                    "resource": "Example Employee",
                    "actualHours": 8,
                    "billable": True,
                }
            ],
        )
        assert project_summary(warehouse.connection)[0]["project_name"] == "1001 Example Project"
        assert employee_summary(warehouse.connection)[0]["employee_name"] == "Example Employee"
        context = planning_context(warehouse, data_mode="test")
        assert context["source"]["write_access"] is False
        paths = write_planning_context(warehouse, tmp_path / "exports", data_mode="test")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert payload["employees"][0]["employee_name"] == "Example Employee"
        assert paths["markdown"].is_file()


def test_referenced_dimensions_do_not_break_partial_permission_sync(tmp_path: Path) -> None:
    with Warehouse(tmp_path / "partial-relations.sqlite3") as warehouse:
        warehouse.normalize(
            "allocations",
            [
                {
                    "id": "a1",
                    "projectId": "p1",
                    "resourceId": "e1",
                    "units": 12,
                    "lastUpdated": "2026-07-01",
                }
            ],
        )
        assert warehouse.row_counts()["projects"] == 1
        assert warehouse.row_counts()["employees"] == 1
        assert all(check["severity"] != "error" for check in warehouse.validate())
