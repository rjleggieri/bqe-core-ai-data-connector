# Local analytical model

SQLite is the connector's local analytical store. CSV, JSON, and Markdown are generated
exports; Parquet remains an optional future format for larger data volumes.

## Layers

1. `raw_api_response` stores page payload, fetch timestamp, request context, and SHA-256
   content hash. Identical resource payloads are stored once.
2. Normalized entity and fact tables provide typed join and calculation columns while
   retaining `raw_json` on parent rows for audit.
3. `sync_state`, `sync_runs`, and `sync_run_resources` preserve checkpoints and run
   outcomes.
4. Derived outputs provide project, employee, monthly trend, management, and AI planning
   views.

## Main tables

| Table | Primary key | Purpose |
|---|---|---|
| `clients` | `id` | Client reference |
| `employees` | `id` | Employee/resource reference |
| `projects` | `id` | Project reference |
| `time_entries` | `id` | Historical effort and billable mix |
| `expense_entries` | `id` | Historical project expenses |
| `invoices` / `invoice_details` | BQE ID / composite | Processed invoice context |
| `payments` / `payment_details` | BQE ID / composite | Payment context |
| `allocations` | `id` | Available forward-work records |
| `raw_api_response` | local integer | Deduplicated source evidence |
| `sync_state` | `resource` | Incremental high-water mark |
| `sync_runs` | UUID | Run-level audit |

Facts do not require project or employee master access. When BQE returns display names
with authorized facts, summaries use those names. Relationship tables create opaque
reference placeholders when a dimension endpoint is unavailable, preserving foreign-key
integrity without inventing business attributes.

## Calculation definitions

- Project hours: sum of `actualHours`.
- Billable/nonbillable hours: `actualHours` partitioned by `billable`.
- Estimated billable value: `COALESCE(clientHours,actualHours) * billRate` for billable,
  non-written-off entries. It is not invoice revenue.
- Estimated labor cost: `actualHours * costRate` where the rate is present.
- Unbilled time value: estimated billable value where `invoiceId` is null.
- Invoice totals: processed, nonvoid invoice details allocated to project.
- Payment totals: payment detail joined to invoice, then invoice detail to project.
- Outstanding balance: invoice header balance allocated to projects in proportion to
  invoice detail amount.
- Historical workload: actual time by employee and project.
- Forward workload: allocation units, supplemented by current commitments, schedule
  uncertainty, standard hours, and approved leave when available.

Accounting-grade currency reporting should use decimal-safe arithmetic or integer minor
units. The current SQLite `REAL` measures are planning estimates and must be reconciled
to BQE reports.
