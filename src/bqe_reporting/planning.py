from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .analysis import employee_summary, monthly_trends, project_summary
from .storage import Warehouse


def planning_context(
    warehouse: Warehouse,
    *,
    data_mode: str,
) -> dict[str, Any]:
    """Create a traceable, read-only context package for downstream planning."""
    connection = warehouse.connection
    sync_state = [
        dict(row)
        for row in connection.execute(
            "SELECT resource,high_watermark,synced_at FROM sync_state ORDER BY resource"
        )
    ]
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "system_of_record": "BQE CORE",
            "mode": data_mode,
            "access": "OAuth Authorization Code with PKCE; read:core only",
            "write_access": False,
        },
        "usage": {
            "purpose": "Historical context for human-reviewed workload planning and decision support",
            "limits": [
                "Historical activity does not establish future availability or commitments.",
                "Resource coverage depends on the authorizing user's BQE subscription and permissions.",
                "Financial measures require reconciliation to BQE CORE reports before presentation.",
                "The connector does not make decisions or write changes to BQE CORE.",
            ],
        },
        "coverage": warehouse.row_counts(),
        "sync_state": sync_state,
        "validation": warehouse.validate(),
        "employees": employee_summary(connection),
        "projects": project_summary(connection),
        "monthly_trends": monthly_trends(connection),
    }


def _markdown(context: dict[str, Any]) -> str:
    coverage = context["coverage"]
    checks = "\n".join(
        f"- {item['check']}: **{item['severity']}** — {item['message']}"
        for item in context["validation"]
    )
    sync = "\n".join(
        f"- {item['resource']}: checkpoint `{item['high_watermark'] or 'none'}`"
        for item in context["sync_state"]
    ) or "- No completed resource checkpoints."
    return f"""# BQE CORE AI Planning Context

Generated: {context['generated_at']}

> BQE CORE remains the system of record. This package contains historical context for
> human-reviewed planning; it does not make decisions or write to BQE CORE.

## Coverage

- Employees/resources: {coverage['employees']}
- Projects: {coverage['projects']}
- Time entries: {coverage['time_entries']}
- Expense entries: {coverage['expense_entries']}
- Allocations: {coverage['allocations']}
- Invoices: {coverage['invoices']}
- Payments: {coverage['payments']}
- Deduplicated raw response batches: {coverage['raw_api_response']}

## Resource checkpoints

{sync}

## Warehouse validation

{checks}

## Machine-readable context

See `planning_context.json` in the same folder for employee, project, and monthly
historical summaries with source metadata and safety limits.
"""


def write_planning_context(
    warehouse: Warehouse,
    output_dir: Path,
    *,
    data_mode: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    context = planning_context(warehouse, data_mode=data_mode)
    json_path = output_dir / "planning_context.json"
    markdown_path = output_dir / "planning_context.md"
    json_path.write_text(
        json.dumps(context, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(context), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
