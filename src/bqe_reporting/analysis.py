from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import sqlite3
from typing import Any


PROJECT_SQL = """
WITH time_rollup AS (
  SELECT project_id,
    SUM(COALESCE(actual_hours,0)) hours,
    SUM(CASE WHEN billable=1 THEN COALESCE(actual_hours,0) ELSE 0 END) billable_hours,
    SUM(CASE WHEN billable=0 THEN COALESCE(actual_hours,0) ELSE 0 END) nonbillable_hours,
    SUM(CASE WHEN billable=1 AND is_written_off=0 THEN COALESCE(client_hours,actual_hours,0)*COALESCE(bill_rate,0) ELSE 0 END) estimated_billable_value,
    SUM(COALESCE(actual_hours,0)*COALESCE(cost_rate,0)) estimated_labor_cost,
    SUM(CASE WHEN billable=1 AND is_written_off=0 AND invoice_id IS NULL THEN COALESCE(client_hours,actual_hours,0)*COALESCE(bill_rate,0) ELSE 0 END) unbilled_time_value,
    MAX(date) last_time_date
  FROM time_entries GROUP BY project_id
), invoice_rollup AS (
  SELECT d.project_id,
    SUM(CASE WHEN i.is_void=0 AND i.is_draft=0 THEN d.amount ELSE 0 END) invoice_total,
    SUM(CASE WHEN i.is_void=0 AND i.is_draft=0 THEN d.amount * CASE WHEN i.invoice_amount=0 THEN 0 ELSE i.balance/i.invoice_amount END ELSE 0 END) outstanding_balance
  FROM invoice_details d JOIN invoices i ON i.id=d.invoice_id GROUP BY d.project_id
), payment_rollup AS (
  SELECT d.project_id, SUM(pd.amount) payment_total
  FROM payment_details pd JOIN invoices i ON i.id=pd.invoice_id
  JOIN invoice_details d ON d.invoice_id=i.id GROUP BY d.project_id
)
SELECT p.id project_id, p.code project_code, p.name project_name, c.name client_name,
  m.display_name manager_name, p.contract_type, COALESCE(p.contract_amount,0) contract_amount,
  COALESCE(t.hours,0) hours, COALESCE(t.billable_hours,0) billable_hours,
  COALESCE(t.nonbillable_hours,0) nonbillable_hours,
  COALESCE(t.estimated_billable_value,0) estimated_billable_value,
  COALESCE(t.estimated_labor_cost,0) estimated_labor_cost,
  COALESCE(i.invoice_total,0) invoice_total, COALESCE(pay.payment_total,0) payment_total,
  COALESCE(i.outstanding_balance,0) outstanding_balance,
  COALESCE(t.unbilled_time_value,0) unbilled_time_value, t.last_time_date
FROM projects p LEFT JOIN clients c ON c.id=p.client_id
LEFT JOIN employees m ON m.id=p.manager_id LEFT JOIN time_rollup t ON t.project_id=p.id
LEFT JOIN invoice_rollup i ON i.project_id=p.id LEFT JOIN payment_rollup pay ON pay.project_id=p.id
ORDER BY p.code
"""
EMPLOYEE_SQL = """
SELECT e.id employee_id, e.display_name employee_name, e.department, e.title,
  m.display_name manager_name, e.weekly_standard_hours, e.utilization_target,
  COALESCE(SUM(t.actual_hours),0) hours,
  COALESCE(SUM(CASE WHEN t.billable=1 THEN t.actual_hours ELSE 0 END),0) billable_hours,
  COALESCE(SUM(CASE WHEN t.billable=0 THEN t.actual_hours ELSE 0 END),0) nonbillable_hours,
  CASE WHEN SUM(t.actual_hours)>0 THEN SUM(CASE WHEN t.billable=1 THEN t.actual_hours ELSE 0 END)/SUM(t.actual_hours) ELSE 0 END billable_ratio,
  COUNT(DISTINCT t.project_id) active_project_count,
  COALESCE((SELECT SUM(a.units) FROM allocations a WHERE a.resource_id=e.id),0) allocated_units
FROM employees e LEFT JOIN employees m ON m.id=e.manager_id
LEFT JOIN time_entries t ON t.resource_id=e.id
GROUP BY e.id ORDER BY e.display_name
"""

TREND_SQL = """
SELECT substr(date,1,7) month,
  ROUND(SUM(actual_hours),2) hours,
  ROUND(SUM(CASE WHEN billable=1 THEN actual_hours ELSE 0 END),2) billable_hours,
  ROUND(SUM(CASE WHEN billable=1 THEN COALESCE(client_hours,actual_hours)*COALESCE(bill_rate,0) ELSE 0 END),2) estimated_billable_value
FROM time_entries GROUP BY substr(date,1,7) ORDER BY month
"""


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(sql)]


def project_summary(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, PROJECT_SQL)


def employee_summary(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, EMPLOYEE_SQL)


def monthly_trends(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, TREND_SQL)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(connection: sqlite3.Connection, output_dir: Path) -> dict[str, Path]:
    projects = project_summary(connection)
    employees = employee_summary(connection)
    trends = monthly_trends(connection)
    paths = {
        "projects": output_dir / "project_financial_workload_summary.csv",
        "employees": output_dir / "employee_workload_summary.csv",
        "trends": output_dir / "monthly_trends.csv",
    }
    write_csv(paths["projects"], projects)
    write_csv(paths["employees"], employees)
    write_csv(paths["trends"], trends)
    return paths


def management_brief(connection: sqlite3.Connection) -> str:
    projects = project_summary(connection)
    employees = employee_summary(connection)
    trends = monthly_trends(connection)
    total_hours = sum(float(row["hours"]) for row in projects)
    billable_hours = sum(float(row["billable_hours"]) for row in projects)
    invoices = sum(float(row["invoice_total"]) for row in projects)
    outstanding = sum(float(row["outstanding_balance"]) for row in projects)
    unbilled = sum(float(row["unbilled_time_value"]) for row in projects)
    utilization = billable_hours / total_hours if total_hours else 0
    flags: list[str] = []
    for row in projects:
        if float(row["unbilled_time_value"]) > 5000:
            flags.append(f"{row['project_code']} has estimated unbilled time of ${row['unbilled_time_value']:,.2f}.")
        if float(row["contract_amount"]) and float(row["estimated_billable_value"]) > float(row["contract_amount"]):
            flags.append(f"{row['project_code']} estimated billable time exceeds its contract amount.")
    if employees:
        busiest = max(employees, key=lambda row: float(row["hours"]))
        flags.append(f"{busiest['employee_name']} logged the most fixture hours ({busiest['hours']:.1f}).")
    trend_text = "No monthly trend data."
    if len(trends) >= 2:
        prior, latest = trends[-2], trends[-1]
        delta = float(latest["hours"]) - float(prior["hours"])
        trend_text = f"Hours changed by {delta:+.1f} from {prior['month']} to {latest['month']}."
    bullets = "\n".join(f"- {flag}" for flag in flags) or "- No synthetic-data flags."
    return f"""# Weekly Management Brief — Synthetic Demonstration

> This output uses synthetic fixtures only. It is not company data and must not be used for decisions.

Generated: {date.today().isoformat()}

## Snapshot

- Total hours: {total_hours:,.1f}
- Billable hours: {billable_hours:,.1f} ({utilization:.1%} of logged hours)
- Invoiced: ${invoices:,.2f}
- Outstanding balance (allocated estimate): ${outstanding:,.2f}
- Estimated unbilled time value: ${unbilled:,.2f}
- Trend: {trend_text}

## Items for management review

{bullets}

## Required validation

Reconcile invoice, payment, outstanding, and unbilled totals to BQE CORE reports before presentation. Confirm enum meanings, currency treatment, project hierarchy, permissions, void/draft handling, and the definition of billable value with Finance.
"""
