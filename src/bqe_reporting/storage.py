from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS raw_api_response (
    id INTEGER PRIMARY KEY,
    resource TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    request_context TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
    resource TEXT PRIMARY KEY,
    high_watermark TEXT,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL,
    requested_resources_json TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS sync_run_resources (
    run_id TEXT NOT NULL REFERENCES sync_runs(id),
    resource TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    watermark_before TEXT,
    watermark_after TEXT,
    error TEXT,
    PRIMARY KEY (run_id, resource)
);
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT,
    company TEXT,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    display_name TEXT,
    manager_id TEXT REFERENCES employees(id),
    department TEXT,
    title TEXT,
    weekly_standard_hours REAL,
    utilization_target REAL,
    status TEXT,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    client_id TEXT REFERENCES clients(id),
    manager_id TEXT REFERENCES employees(id),
    code TEXT,
    name TEXT,
    display_name TEXT,
    contract_type TEXT,
    contract_amount REAL,
    status TEXT,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS time_entries (
    id TEXT PRIMARY KEY,
    date TEXT,
    project_id TEXT,
    project_display TEXT,
    resource_id TEXT,
    resource_name TEXT,
    activity_id TEXT,
    activity_name TEXT,
    actual_hours REAL,
    client_hours REAL,
    billable INTEGER,
    bill_rate REAL,
    cost_rate REAL,
    bill_status TEXT,
    invoice_id TEXT,
    is_written_off INTEGER,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expense_entries (
    id TEXT PRIMARY KEY,
    date TEXT,
    project_id TEXT,
    project_display TEXT,
    resource_id TEXT,
    resource_name TEXT,
    expense_id TEXT,
    billable INTEGER,
    bill_status TEXT,
    charge_amount REAL,
    cost_rate REAL,
    units REAL,
    invoice_id TEXT,
    is_written_off INTEGER,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    date TEXT,
    invoice_number TEXT,
    invoice_amount REAL,
    balance REAL,
    service_amount REAL,
    expense_amount REAL,
    is_draft INTEGER,
    is_void INTEGER,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_details (
    invoice_id TEXT NOT NULL REFERENCES invoices(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    client_id TEXT REFERENCES clients(id),
    amount REAL,
    PRIMARY KEY (invoice_id, project_id)
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    date TEXT,
    client_id TEXT REFERENCES clients(id),
    project_id TEXT REFERENCES projects(id),
    amount REAL,
    is_retainer INTEGER,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_details (
    payment_id TEXT NOT NULL REFERENCES payments(id),
    invoice_id TEXT NOT NULL REFERENCES invoices(id),
    amount REAL,
    PRIMARY KEY (payment_id, invoice_id)
);
CREATE TABLE IF NOT EXISTS allocations (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    resource_id TEXT REFERENCES employees(id),
    item_id TEXT,
    starts_on TEXT,
    ends_on TEXT,
    units REAL,
    percent_complete REAL,
    last_updated TEXT,
    raw_json TEXT NOT NULL
);
"""


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _bool(value: Any) -> int:
    return int(bool(value))


class Warehouse:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        additions = {
            "time_entries": {
                "project_display": "TEXT",
                "resource_name": "TEXT",
                "activity_name": "TEXT",
            },
            "expense_entries": {
                "project_display": "TEXT",
                "resource_name": "TEXT",
            },
        }
        with self.connection:
            for table, columns in additions.items():
                existing = {
                    row[1]
                    for row in self.connection.execute(f"PRAGMA table_info({table})")
                }
                for name, sql_type in columns.items():
                    if name not in existing:
                        self.connection.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"
                        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def store_raw(self, resource: str, rows: list[Mapping[str, Any]], context: str = "mock") -> bool:
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(f"{resource}\0{payload}".encode()).hexdigest()
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO raw_api_response "
            "(resource,fetched_at,request_context,content_hash,payload_json) VALUES (?,?,?,?,?)",
            (resource, datetime.now(timezone.utc).isoformat(), context, digest, payload),
        )
        return cursor.rowcount == 1

    def normalize(self, resource: str, rows: Iterable[Mapping[str, Any]]) -> int:
        handlers = {
            "clients": self._client,
            "employees": self._employee,
            "projects": self._project,
            "time_entries": self._time_entry,
            "expense_entries": self._expense_entry,
            "invoices": self._invoice,
            "payments": self._payment,
            "allocations": self._allocation,
        }
        if resource not in handlers:
            raise KeyError(f"Unsupported normalized resource: {resource}")
        materialized = list(rows)
        if not materialized:
            return 0
        count = 0
        with self.connection:
            for row in materialized:
                handlers[resource](row)
                count += 1
            watermark = self.connection.execute(
                f"SELECT MAX(last_updated) FROM {resource}"
            ).fetchone()[0]
            self.connection.execute(
                "INSERT INTO sync_state(resource,high_watermark,synced_at) VALUES (?,?,?) "
                "ON CONFLICT(resource) DO UPDATE SET high_watermark=excluded.high_watermark, "
                "synced_at=excluded.synced_at",
                (resource, watermark, datetime.now(timezone.utc).isoformat()),
            )
        return count

    def get_watermark(self, resource: str) -> str | None:
        row = self.connection.execute(
            "SELECT high_watermark FROM sync_state WHERE resource=?", (resource,)
        ).fetchone()
        return None if row is None else row[0]

    def begin_sync_run(self, mode: str, resources: Iterable[str]) -> str:
        run_id = str(uuid4())
        with self.connection:
            self.connection.execute(
                "INSERT INTO sync_runs "
                "(id,started_at,mode,requested_resources_json,status) VALUES (?,?,?,?,?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    mode,
                    json.dumps(list(resources), separators=(",", ":")),
                    "running",
                ),
            )
        return run_id

    def record_sync_resource(
        self,
        run_id: str,
        resource: str,
        endpoint: str,
        *,
        status: str,
        page_count: int = 0,
        row_count: int = 0,
        watermark_before: str | None = None,
        watermark_after: str | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                "INSERT INTO sync_run_resources "
                "(run_id,resource,endpoint,started_at,finished_at,status,page_count,row_count,"
                "watermark_before,watermark_after,error) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id,resource) DO UPDATE SET "
                "finished_at=excluded.finished_at,status=excluded.status,"
                "page_count=excluded.page_count,row_count=excluded.row_count,"
                "watermark_before=excluded.watermark_before,"
                "watermark_after=excluded.watermark_after,error=excluded.error",
                (
                    run_id,
                    resource,
                    endpoint,
                    now,
                    now,
                    status,
                    page_count,
                    row_count,
                    watermark_before,
                    watermark_after,
                    error,
                ),
            )

    def finish_sync_run(self, run_id: str, status: str, error: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE sync_runs SET finished_at=?,status=?,error=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), status, error, run_id),
            )

    def row_counts(self) -> dict[str, int]:
        resources = (
            "clients",
            "employees",
            "projects",
            "time_entries",
            "expense_entries",
            "invoices",
            "payments",
            "allocations",
            "raw_api_response",
        )
        return {
            resource: int(
                self.connection.execute(f"SELECT COUNT(*) FROM {resource}").fetchone()[0]
            )
            for resource in resources
        }

    def validate(self) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []
        integrity = str(self.connection.execute("PRAGMA integrity_check").fetchone()[0])
        checks.append(
            {
                "severity": "ok" if integrity == "ok" else "error",
                "check": "sqlite_integrity",
                "message": integrity,
            }
        )
        foreign_keys = self.connection.execute("PRAGMA foreign_key_check").fetchall()
        checks.append(
            {
                "severity": "ok" if not foreign_keys else "error",
                "check": "foreign_keys",
                "message": "no violations" if not foreign_keys else f"{len(foreign_keys)} violations",
            }
        )
        counts = self.row_counts()
        normalized = sum(
            counts[name]
            for name in counts
            if name not in {"raw_api_response"}
        )
        checks.append(
            {
                "severity": "ok" if not normalized or counts["raw_api_response"] else "warning",
                "check": "raw_audit_evidence",
                "message": (
                    f"{counts['raw_api_response']} deduplicated raw response batches for "
                    f"{normalized} normalized rows"
                ),
            }
        )
        negative_hours = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM time_entries WHERE actual_hours < 0"
            ).fetchone()[0]
        )
        checks.append(
            {
                "severity": "warning" if negative_hours else "ok",
                "check": "negative_time",
                "message": f"{negative_hours} negative time entries",
            }
        )
        return checks

    def _upsert(self, table: str, values: dict[str, Any], keys: tuple[str, ...] = ("id",)) -> None:
        columns = list(values)
        updates = [name for name in columns if name not in keys]
        sql = (
            f"INSERT INTO {table} ({','.join(columns)}) VALUES "
            f"({','.join('?' for _ in columns)}) ON CONFLICT({','.join(keys)}) DO UPDATE SET "
            + ",".join(f"{name}=excluded.{name}" for name in updates)
        )
        self.connection.execute(sql, [values[name] for name in columns])

    @staticmethod
    def _raw(row: Mapping[str, Any]) -> str:
        return json.dumps(row, sort_keys=True, default=str)

    def _ensure_project(self, project_id: str | None) -> None:
        if project_id and not self.connection.execute(
            "SELECT 1 FROM projects WHERE id=?", (project_id,)
        ).fetchone():
            placeholder = {"id": project_id, "_source": "referenced fact"}
            self._upsert(
                "projects",
                {
                    "id": project_id,
                    "client_id": None,
                    "manager_id": None,
                    "code": None,
                    "name": None,
                    "display_name": None,
                    "contract_type": None,
                    "contract_amount": None,
                    "status": None,
                    "last_updated": None,
                    "raw_json": self._raw(placeholder),
                },
            )

    def _ensure_employee(self, employee_id: str | None) -> None:
        if employee_id and not self.connection.execute(
            "SELECT 1 FROM employees WHERE id=?", (employee_id,)
        ).fetchone():
            placeholder = {"id": employee_id, "_source": "referenced fact"}
            self._upsert(
                "employees",
                {
                    "id": employee_id,
                    "display_name": None,
                    "manager_id": None,
                    "department": None,
                    "title": None,
                    "weekly_standard_hours": None,
                    "utilization_target": None,
                    "status": None,
                    "last_updated": None,
                    "raw_json": self._raw(placeholder),
                },
            )

    def _client(self, row: Mapping[str, Any]) -> None:
        self._upsert("clients", {"id": row["id"], "name": _text(row.get("name")), "company": _text(row.get("company")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})

    def _employee(self, row: Mapping[str, Any]) -> None:
        self._upsert("employees", {"id": row["id"], "display_name": _text(row.get("displayName")), "manager_id": _text(row.get("managerId")), "department": _text(row.get("department")), "title": _text(row.get("title")), "weekly_standard_hours": _num(row.get("weeklyStandardHours")), "utilization_target": _num(row.get("utilizationTarget")), "status": _text(row.get("status")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})

    def _project(self, row: Mapping[str, Any]) -> None:
        self._upsert("projects", {"id": row["id"], "client_id": _text(row.get("clientId")), "manager_id": _text(row.get("managerId")), "code": _text(row.get("code")), "name": _text(row.get("name")), "display_name": _text(row.get("displayName")), "contract_type": _text(row.get("contractType")), "contract_amount": _num(row.get("contractAmount")), "status": _text(row.get("status")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})

    def _time_entry(self, row: Mapping[str, Any]) -> None:
        self._upsert("time_entries", {"id": row["id"], "date": _text(row.get("date")), "project_id": _text(row.get("projectId")), "project_display": _text(row.get("project")), "resource_id": _text(row.get("resourceId")), "resource_name": _text(row.get("resource")), "activity_id": _text(row.get("activityId")), "activity_name": _text(row.get("activity")), "actual_hours": _num(row.get("actualHours")) or 0.0, "client_hours": _num(row.get("clientHours")), "billable": _bool(row.get("billable")), "bill_rate": _num(row.get("billRate")), "cost_rate": _num(row.get("costRate")), "bill_status": _text(row.get("billStatus")), "invoice_id": _text(row.get("invoiceId")), "is_written_off": _bool(row.get("isWrittenOff")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})

    def _expense_entry(self, row: Mapping[str, Any]) -> None:
        self._upsert("expense_entries", {"id": row["id"], "date": _text(row.get("date")), "project_id": _text(row.get("projectId")), "project_display": _text(row.get("project")), "resource_id": _text(row.get("resourceId")), "resource_name": _text(row.get("resource")), "expense_id": _text(row.get("expenseId")), "billable": _bool(row.get("billable")), "bill_status": _text(row.get("billStatus")), "charge_amount": _num(row.get("chargeAmount")), "cost_rate": _num(row.get("costRate")), "units": _num(row.get("units")), "invoice_id": _text(row.get("invoiceId")), "is_written_off": _bool(row.get("isWrittenOff")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})

    def _invoice(self, row: Mapping[str, Any]) -> None:
        self._upsert("invoices", {"id": row["id"], "date": _text(row.get("date")), "invoice_number": _text(row.get("invoiceNumber")), "invoice_amount": _num(row.get("invoiceAmount")) or 0.0, "balance": _num(row.get("balance")) or 0.0, "service_amount": _num(row.get("serviceAmount")), "expense_amount": _num(row.get("expenseAmount")), "is_draft": _bool(row.get("isDraft")), "is_void": _bool(row.get("isVoid")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})
        for detail in row.get("invoiceDetails") or []:
            if detail.get("projectId"):
                self._ensure_project(_text(detail.get("projectId")))
                client_id = _text(detail.get("clientId"))
                if client_id and not self.connection.execute(
                    "SELECT 1 FROM clients WHERE id=?", (client_id,)
                ).fetchone():
                    client_id = None
                self._upsert("invoice_details", {"invoice_id": row["id"], "project_id": detail["projectId"], "client_id": client_id, "amount": _num(detail.get("amount")) or 0.0}, ("invoice_id", "project_id"))

    def _payment(self, row: Mapping[str, Any]) -> None:
        project_id = _text(row.get("projectId"))
        self._ensure_project(project_id)
        client_id = _text(row.get("clientId"))
        if client_id and not self.connection.execute(
            "SELECT 1 FROM clients WHERE id=?", (client_id,)
        ).fetchone():
            client_id = None
        self._upsert("payments", {"id": row["id"], "date": _text(row.get("date")), "client_id": client_id, "project_id": project_id, "amount": _num(row.get("amount")) or 0.0, "is_retainer": _bool(row.get("isRetainer")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})
        for detail in row.get("lineItems") or []:
            if detail.get("invoiceId") and self.connection.execute(
                "SELECT 1 FROM invoices WHERE id=?", (detail["invoiceId"],)
            ).fetchone():
                self._upsert("payment_details", {"payment_id": row["id"], "invoice_id": detail["invoiceId"], "amount": _num(detail.get("amount")) or 0.0}, ("payment_id", "invoice_id"))

    def _allocation(self, row: Mapping[str, Any]) -> None:
        self._ensure_project(_text(row.get("projectId")))
        self._ensure_employee(_text(row.get("resourceId")))
        self._upsert("allocations", {"id": row["id"], "project_id": _text(row.get("projectId")), "resource_id": _text(row.get("resourceId")), "item_id": _text(row.get("itemId")), "starts_on": _text(row.get("startsOn")), "ends_on": _text(row.get("endsOn")), "units": _num(row.get("units")) or 0.0, "percent_complete": _num(row.get("percentComplete")), "last_updated": _text(row.get("lastUpdated")), "raw_json": self._raw(row)})
