# Demo Workflow Options

Every demo should begin with a visible “read-only, reconciled as of…” banner and use synthetic or approved sanitized data until Finance signs off on definitions.

## Immediately feasible with read-only API access

- Ask “How did billable hours change by client, manager, project, or employee?” over a reconciled local snapshot.
- Produce historical invoice, payment, and outstanding-balance summaries with drill-through to source IDs.
- Show unbilled-time candidates by project, age, employee, and estimated value, labeled for review rather than as billing instructions.
- Create a weekly management brief covering hours, billable mix, invoices, payments, balances, month-over-month movement, and data-quality warnings.
- Flag projects with no recent time, unusually high hours, contract pressure, large unbilled time, or concentrated staffing.
- Compare actual employee workload and billable ratio across recent periods.

## Feasible after additional development

- Forward-capacity dashboard from allocations, resource schedules, standard hours, and approved leave.
- Project/phase hierarchy rollups with joint-invoice and multi-currency handling.
- Scheduled incremental synchronization with deletion detection, overlap windows, encrypted token storage, monitoring, and reconciliation controls.
- Natural-language Q&A with citations to local record IDs, saved query definitions, and row-level authorization.
- Budget/estimate/fee-schedule variance analysis after relevant API schemas and tenant usage are validated.
- Anomaly baselines that account for seasonality, project type, contract type, and employee role.

## Not recommended or too risky

- Giving an LLM a broad access token, refresh token, browser session, or permission to call arbitrary BQE endpoints.
- Requesting `readwrite:core` for a reporting demo.
- Allowing an agent to create invoices, change time, write off entries, contact clients, approve work, or update project status.
- Presenting estimated billable value, cost, profitability, “underbilling,” or anomaly flags as audited facts.
- Uploading raw employee/client data, memos, attachments, credentials, or unrestricted exports to a general chat.
- Browser-click automation when the official REST API supplies the data.

## Dependent on data that may not be available through the public API

- Exact recognized revenue/WIP and accounting-basis profitability.
- Complete payroll burden, overhead, benefits, and vendor cost.
- Reliable future capacity when allocations/resource schedules or leave data are incomplete.
- Contract terms or billing judgment stored only in attachments, notes, or external systems.
- Every standard/custom CORE report calculation; public APIs do not expose every web-app module.
- Cross-company benchmarks or business-development context that exists outside CORE.

## Suggested management demo sequence

1. Show a read-only architecture and non-GET rejection test.
2. Reconcile a small approved date range to CORE standard reports.
3. Ask one historical billing question and drill from a summary to source IDs.
4. Show workload change and one clearly explained heuristic flag.
5. Generate the weekly brief, with uncertainties and reconciliation status visible.
6. End with the boundary: suggestions for human review, never automatic changes to CORE.
