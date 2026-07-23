from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from typing import Iterable

import httpx

from .client import BQEClient
from .storage import Warehouse


@dataclass(frozen=True)
class ResourceSpec:
    name: str
    endpoint: str
    fields: tuple[str, ...]
    date_field: str | None = None
    expand: str | None = None


RESOURCE_SPECS: dict[str, ResourceSpec] = {
    "clients": ResourceSpec(
        "clients",
        "client",
        ("id", "name", "company", "lastUpdated"),
    ),
    "employees": ResourceSpec(
        "employees",
        "employee",
        (
            "id",
            "displayName",
            "managerId",
            "department",
            "title",
            "weeklyStandardHours",
            "utilizationTarget",
            "status",
            "lastUpdated",
        ),
    ),
    "projects": ResourceSpec(
        "projects",
        "project",
        (
            "id",
            "clientId",
            "managerId",
            "code",
            "name",
            "displayName",
            "contractType",
            "contractAmount",
            "status",
            "lastUpdated",
        ),
    ),
    "time_entries": ResourceSpec(
        "time_entries",
        "timeentry",
        (
            "id",
            "date",
            "projectId",
            "project",
            "resourceId",
            "resource",
            "activityId",
            "activity",
            "actualHours",
            "clientHours",
            "billable",
            "billRate",
            "costRate",
            "billStatus",
            "invoiceId",
            "isWrittenOff",
            "lastUpdated",
        ),
        date_field="date",
    ),
    "expense_entries": ResourceSpec(
        "expense_entries",
        "expenseentry",
        (
            "id",
            "date",
            "projectId",
            "project",
            "resourceId",
            "resource",
            "expenseId",
            "billable",
            "billStatus",
            "chargeAmount",
            "costRate",
            "units",
            "invoiceId",
            "isWrittenOff",
            "lastUpdated",
        ),
        date_field="date",
    ),
    "invoices": ResourceSpec(
        "invoices",
        "invoice",
        (
            "id",
            "date",
            "invoiceNumber",
            "invoiceAmount",
            "balance",
            "serviceAmount",
            "expenseAmount",
            "isDraft",
            "isVoid",
            "lastUpdated",
        ),
        date_field="date",
        expand="invoiceDetails",
    ),
    "payments": ResourceSpec(
        "payments",
        "payment",
        (
            "id",
            "date",
            "clientId",
            "projectId",
            "amount",
            "isRetainer",
            "lastUpdated",
        ),
        date_field="date",
        expand="lineItems",
    ),
    "allocations": ResourceSpec(
        "allocations",
        "allocation",
        (
            "id",
            "projectId",
            "resourceId",
            "itemId",
            "startsOn",
            "endsOn",
            "units",
            "percentComplete",
            "lastUpdated",
        ),
        date_field="startsOn",
    ),
}

DEFAULT_RESOURCES = tuple(RESOURCE_SPECS)


@dataclass(frozen=True)
class ResourceSyncResult:
    resource: str
    status: str
    pages: int
    rows: int
    watermark_before: str | None
    watermark_after: str | None
    error: str | None = None


def _date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc


def build_where(
    spec: ResourceSpec,
    *,
    watermark: str | None,
    date_from: str | None,
    date_to: str | None,
    full: bool,
) -> str | None:
    start = _date(date_from, "--from")
    end = _date(date_to, "--to")
    if bool(start) != bool(end):
        raise ValueError("--from and --to must be supplied together")
    if start and end and end < start:
        raise ValueError("--to must be on or after --from")
    clauses: list[str] = []
    if not full and watermark:
        # Include equal timestamps so a failed page cannot create a high-watermark gap.
        clauses.append(f"lastUpdated>='{watermark}'")
    if start and end:
        if spec.date_field:
            end_exclusive = end + timedelta(days=1)
            clauses.extend(
                (
                    f"{spec.date_field}>='{start.isoformat()}T00:00:00'",
                    f"{spec.date_field}<'{end_exclusive.isoformat()}T00:00:00'",
                )
            )
    elif spec.date_field and not full and not watermark:
        raise ValueError(
            f"{spec.name} has no prior checkpoint; supply --from/--to or explicitly use --full"
        )
    return " AND ".join(clauses) or None


class SyncEngine:
    """Permission-aware, incremental BQE-to-SQLite ingestion."""

    def __init__(self, client: BQEClient, warehouse: Warehouse):
        self.client = client
        self.warehouse = warehouse

    def sync(
        self,
        resources: Iterable[str] = DEFAULT_RESOURCES,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        full: bool = False,
        page_size: int | None = None,
        strict: bool = False,
    ) -> list[ResourceSyncResult]:
        requested = tuple(dict.fromkeys(resources))
        unknown = [name for name in requested if name not in RESOURCE_SPECS]
        if unknown:
            raise ValueError(f"Unknown resources: {', '.join(unknown)}")
        run_id = self.warehouse.begin_sync_run("live-read-only", requested)
        results: list[ResourceSyncResult] = []
        try:
            for name in requested:
                spec = RESOURCE_SPECS[name]
                before = self.warehouse.get_watermark(name)
                try:
                    where = build_where(
                        spec,
                        watermark=before,
                        date_from=date_from,
                        date_to=date_to,
                        full=full,
                    )
                    pages = 0
                    rows_seen = 0
                    context = json.dumps(
                        {
                            "mode": "live-read-only",
                            "endpoint": spec.endpoint,
                            "fields": list(spec.fields),
                            "where": where,
                            "incremental": not full,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    query: dict[str, object] = {
                        "fields": list(spec.fields),
                        "where": where,
                        "order_by": "lastUpdated asc",
                    }
                    if spec.expand:
                        query["expand"] = spec.expand
                    effective_page_size = page_size or (100 if spec.expand else 1000)
                    for page in self.client.iter_pages(
                        spec.endpoint,
                        page_size=effective_page_size,
                        **query,
                    ):
                        pages += 1
                        rows_seen += len(page)
                        self.warehouse.store_raw(name, page, context=context)
                        self.warehouse.normalize(name, page)
                    after = self.warehouse.get_watermark(name)
                    result = ResourceSyncResult(
                        name, "complete", pages, rows_seen, before, after
                    )
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    unavailable = status_code in {403, 404}
                    result = ResourceSyncResult(
                        name,
                        "unavailable" if unavailable else "failed",
                        0,
                        0,
                        before,
                        self.warehouse.get_watermark(name),
                        f"HTTP {status_code}",
                    )
                    if strict or not unavailable:
                        self.warehouse.record_sync_resource(
                            run_id,
                            name,
                            spec.endpoint,
                            status=result.status,
                            watermark_before=before,
                            watermark_after=result.watermark_after,
                            error=result.error,
                        )
                        raise
                except (TypeError, ValueError) as exc:
                    result = ResourceSyncResult(
                        name,
                        "failed",
                        0,
                        0,
                        before,
                        self.warehouse.get_watermark(name),
                        str(exc),
                    )
                    if strict:
                        self.warehouse.record_sync_resource(
                            run_id,
                            name,
                            spec.endpoint,
                            status=result.status,
                            watermark_before=before,
                            watermark_after=result.watermark_after,
                            error=result.error,
                        )
                        raise
                self.warehouse.record_sync_resource(
                    run_id,
                    name,
                    spec.endpoint,
                    status=result.status,
                    page_count=result.pages,
                    row_count=result.rows,
                    watermark_before=result.watermark_before,
                    watermark_after=result.watermark_after,
                    error=result.error,
                )
                results.append(result)
            overall = "complete" if all(r.status == "complete" for r in results) else "partial"
            self.warehouse.finish_sync_run(run_id, overall)
            return results
        except Exception as exc:
            self.warehouse.finish_sync_run(run_id, "failed", type(exc).__name__)
            raise
