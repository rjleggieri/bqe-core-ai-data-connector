# Local Analytical Model

SQLite is the phase-one system of record. CSV is used only for synthetic prototype outputs; Parquet is a future optional export for larger data volumes.

## Layers

1. `raw_api_response`: immutable fetched payload, fetch timestamp, request context, and SHA-256 content hash. Identical payloads are stored once.
2. Normalized entity/fact tables: typed columns for joins and calculations plus `raw_json` on each parent row for audit.
3. Derived outputs: project summary, employee workload, monthly trends, and management brief.

## Tables and keys

| Table | Primary key | Important foreign keys |
|---|---|---|
| `clients` | `id` | — |
| `employees` | `id` | `manager_id -> employees.id` |
| `projects` | `id` | `client_id -> clients.id`; `manager_id -> employees.id` |
| `time_entries` | `id` | `project_id -> projects.id`; `resource_id -> employees.id` in the current employee-only mock; `invoice_id` logical join |
| `expense_entries` | `id` | project/resource; invoice logical join |
| `invoices` | `id` | — |
| `invoice_details` | (`invoice_id`,`project_id`) | invoice, project, client |
| `payments` | `id` | client/project where present |
| `payment_details` | (`payment_id`,`invoice_id`) | payment and invoice |
| `allocations` | `id` | project and resource |
| `sync_state` | `resource` | high-water mark for `lastUpdated` |

The live model must add a generic `resources` dimension or separate vendors before vendor time is loaded; the synthetic fixtures intentionally contain employees only. Invoice/payment detail natural keys must be revisited if live data can contain multiple details for the same project/invoice or payment/invoice pair. If so, use the documented detail `id`/`invoiceDetailId` instead of the phase-one composite key.

## Calculation definitions

- Project hours: sum of `actualHours`.
- Billable/nonbillable hours: `actualHours` partitioned by `billable`.
- Estimated billable value: `COALESCE(clientHours,actualHours) * billRate` for billable, non-written-off entries. It is not invoice revenue.
- Estimated labor cost: `actualHours * costRate` when rate is present. Missing rates are not imputed.
- Unbilled time value: estimated billable value where `invoiceId` is null. Live use additionally requires approved/bill-status validation.
- Invoice totals: processed, nonvoid invoice details allocated to project.
- Payment totals: payment detail amount joined to invoice, then invoice detail to project. Multi-project allocation policy needs live validation.
- Outstanding balance: phase-one allocates invoice header balance to projects in proportion to invoice detail amount. Live output must show this is allocated when an invoice spans projects.
- Workload: actual time by employee/project; forward workload uses allocation/resource schedule units separately.
- Month-over-month: transaction `date` grouped by calendar month after timezone policy is agreed.

Use decimal-safe arithmetic or integer minor currency units before production. SQLite `REAL` is acceptable only for this synthetic proof of concept.
