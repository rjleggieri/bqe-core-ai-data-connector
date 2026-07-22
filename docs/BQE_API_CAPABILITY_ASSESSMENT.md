# BQE CORE API Capability Assessment

Status: documentation-based phase-one assessment, reviewed 2026-07-21 against BQE CORE API documentation version 2026.07.1.0. No authentication or company-data retrieval was performed.

This is a read-only reporting proof of concept, not a production integration. BQE explicitly notes that not every CORE web-app module is available through the public API, and the authorizing user's subscription and security permissions further restrict results.

## Official sources inspected

- [BQE CORE API overview](https://api-explorer.bqecore.com/)
- [Getting Started and OAuth flow](https://api-explorer.bqecore.com/docs/getting-started)
- [Authentication and application types](https://api-explorer.bqecore.com/docs/authentication-authorization)
- [Parameters, filtering, pagination, and expansion](https://api-explorer.bqecore.com/docs/filtering)
- [Rate limits, custom fields, timezones, and permissions](https://api-explorer.bqecore.com/docs/rules)
- [Official Python sample](https://github.com/BQEDeveloper/CoreApiPythonSample)
- Resource references: [Project](https://api-explorer.bqecore.com/docs/api/apis/project), [Client](https://api-explorer.bqecore.com/docs/api/apis/client), [Employee](https://api-explorer.bqecore.com/docs/api/apis/employee), [Time Entry](https://api-explorer.bqecore.com/docs/api/apis/timeentry), [Expense Entry](https://api-explorer.bqecore.com/docs/api/apis/expenseentry), [Invoice](https://api-explorer.bqecore.com/docs/api/apis/invoice), [Payment](https://api-explorer.bqecore.com/docs/api/apis/payment), [Activity](https://api-explorer.bqecore.com/docs/api/apis/activity), [Allocation](https://api-explorer.bqecore.com/docs/api/apis/allocation), [Resource Schedule](https://api-explorer.bqecore.com/docs/api/apis/resourceschedule), [Project Assignment](https://api-explorer.bqecore.com/docs/api/apis/projectassignment), [Custom Field](https://api-explorer.bqecore.com/docs/api/apis/customfield), and [Custom Field Value](https://api-explorer.bqecore.com/docs/api/apis/customfieldvalue)

The official Python sample demonstrates OAuth and query parameters, but it is based on Python 3.7/Flask and stores OAuth responses in an INI file. This project adopts its documented endpoint patterns while replacing its credential-storage approach with PKCE, environment-based non-secret configuration, and a recommendation to use Windows Credential Manager.

## Useful read-only endpoints and fields

All list endpoints below are `GET`, require authentication, and document `read:core` unless noted. Actual access also depends on the consenting user's CORE subscription and permissions.

| Resource | Endpoint | Important documented fields | Analytical use |
|---|---|---|---|
| Projects | `/project`, `/project/{id}` | `id`, `clientId`, `managerId`, `code`, `name`, `displayName`, `type`, `contractType`, `contractAmount`, `expenseContract`, `fixedFee`, `budgetId`, `completedOn`, `dueDate`, `lastUpdated`, `customFields` | Central project/client/manager join; contract and inactivity analysis |
| Project billing schedules | `/project/{id}/billingschedules`; `/billingschedule` | Project relationship plus schedule dates/amount/status fields returned by the tenant | Planned versus actual billing; verify schema and permissions live |
| Clients | `/client`, `/client/{id}` | `id`, `name`, `company`, `clientSince`, `currencyId`, `currencyName`, `feeScheduleId`, `lastUpdated`, `customFields` | Client rollups and currency/fee context |
| Employees | `/employee`, `/employee/{id}` | `id`, `displayName`, `firstName`, `lastName`, `managerId`, `manager`, `department`, `title`, `status`, `billRate`, `costRate`, `dailyStandardHours`, `weeklyStandardHours`, `utilizationTarget`, `lastUpdated`, `customFields` | Employee, supervisor, capacity, cost, and utilization analysis |
| Time entries | `/timeentry`, `/timeentry/{id}` | `id`, `date`, `projectId`, `resourceId`, `activityId`, `actualHours`, `clientHours`, `billable`, `billRate`, `costRate`, `billStatus`, `invoiceId`, `isWrittenOff`, `classification`, `lastUpdated` | Hours, utilization, estimated bill value/cost, unbilled work, and trends |
| Expense entries | `/expenseentry`, `/expenseentry/{id}` | `id`, `date`, `expenseId`, `projectId`, `resourceId`, `billable`, `billStatus`, `chargeAmount`, `costRate`, `invoiceId`, `isWrittenOff`, `currencyName`, `lastUpdated` | Project cost/billing completeness and unbilled expense analysis |
| Invoices | `/invoice`, `/invoice/{id}` | `id`, `date`, `accountingDate`, `invoiceNumber`, `invoiceAmount`, `balance`, `dueDate`, `serviceAmount`, `expenseAmount`, `invoiceFrom`, `invoiceTo`, `isDraft`, `isVoid`, `isManualInvoice`, `isJointInvoice`, `lastUpdated`, nested `invoiceDetails` | Historical billing, aging, outstanding, draft/void treatment |
| Invoice details | Nested `invoiceDetails` via `expand=invoiceDetails` | `invoiceId`, `projectId`, `clientId`, `amount`, `class`, `classId` | Allocates an invoice—including joint invoices—to projects/clients |
| Manual invoice lines | Nested `lineItems` via `expand=lineItems` | Documented manual-invoice service/expense line items | Detail reconciliation; interpretation must be tested across invoice types |
| Payments | `/payment`, `/payment/{id}` | `id`, `date`, `accountingDate`, `clientId`, `projectId`, `amount`, `isRetainer`, `retainerType`, `method`, `reference`, `lastUpdated`, nested `lineItems` | Cash received, retainers, client and invoice settlement |
| Payment details | Nested `lineItems` via `expand=lineItems` | `invoiceId`, `invoiceDetailId`, `amount`, `balance`, `clientId`, `dueDate` | Payment-to-invoice reconciliation; then invoice detail to project |
| Activities | `/activity`, `/activity/{id}` | `id`, `code`, `description`, `billable`, `billRate`, `costRate`, `isActive`, `lastUpdated`, `customFields` | Service/task category and fallback rate analysis |
| Allocations | `/allocation`, `/allocation/{id}` | `id`, `projectId`, `resourceId`, `resourceGroupId`, `itemId`, `itemType`, `startsOn`, `endsOn`, `units`, `percentComplete`, `priority`, `lastUpdated` | Forward-looking workload and allocation changes |
| Resource schedules | `/resourceschedule`, `/resourceschedule/week` | `id`, `allocationId`, `weekId`, `units`; week `id`, `startDate`, `endDate` | Weekly allocation distribution; weeks always begin Monday per docs |
| Project assignments | `/projectassignment/resource` and related list routes | `id`, `projectId`, `resourceId`, `resourceType`, `classification`, `lastUpdated` | Who may work on which project; assignment is not proof of planned workload |
| Custom fields | `/customfield`, `/customfieldvalue` | Definition: `id`, `definitionId`, `label`, `module`, `type`; value: `customFieldId`, `entityId`, `entityType`, `value` | Tenant-specific portfolio tags, sectors, offices, or management groupings |
| Budgets/estimates/fee schedules | `/budget`, `/estimate`, `/feeschedule` | Project/budget identifiers, names, detailed amounts/rates depending on resource | Contract/budget variance and rate-source reconciliation after schema validation |

Fields marked filterable/sortable vary by resource. Only use `where` or `orderBy` on fields the resource page marks accordingly.

## Join model

| From | To | Join |
|---|---|---|
| `projects` | `clients` | `project.clientId = client.id` |
| `projects` | project manager (`employees`) | `project.managerId = employee.id` |
| `employees` | supervisor (`employees`) | `employee.managerId = manager.id` |
| `time_entries` | `projects`, employee/vendor, `activities`, `invoices` | `projectId`, `resourceId`, `activityId`, `invoiceId` |
| `expense_entries` | `projects`, employee/vendor, `invoices` | `projectId`, `resourceId`, `invoiceId` |
| `invoice_details` | `invoices`, `projects`, `clients` | `invoiceId`, `projectId`, `clientId` |
| `payment_details` | `payments`, `invoices` | parent payment ID and `invoiceId`; invoice details then allocate to projects |
| `allocations` | `projects`, employees/vendors, activities/expenses | `projectId`, `resourceId`, `itemId` |
| `resource_schedules` | `allocations`, schedule weeks | `allocationId`, `weekId` |
| `custom_field_values` | definition and entity | `customFieldId`; `entityId` interpreted with `entityType` |

Do not join on display names. A resource may be an employee or vendor; preserve resource type where exposed. Joint invoices and multi-project payments require detail-level allocation and must never be attributed solely from a header-level project field.

## Management questions

### Appears answerable after a limited live schema test

- Historical invoice totals, payments, and outstanding invoice balance by month/client/project.
- Billable and nonbillable actual hours by employee, project, manager, client, activity, and period.
- Estimated billable value from time-entry client hours/rates, clearly labeled as an estimate rather than revenue.
- Estimated labor cost where `costRate` is visible to the authorized user.
- Unbilled time using billable, not written-off entries without `invoiceId`, subject to enum/approval validation.
- Contract amount versus time-value, invoicing, payments, and outstanding balance.
- Actual workload distribution and month-over-month changes.
- Forward workload if allocations/resource schedules are used consistently.
- Heuristic flags for inactivity, high unbilled value, contract pressure, low utilization, and workload concentration.
- A weekly narrative brief generated from reconciled aggregates.

### Not fully answerable yet

- True profitability when cost-rate access is restricted, overhead treatment is unknown, or vendor/payroll costs are incomplete.
- Exact recognized revenue, WIP, percent-complete revenue, or accounting-basis reporting without validating the relevant accounting endpoints and company policy.
- “Underbilled” as an authoritative conclusion. The API can identify signals, but contracts, billing holds, write-ups/write-downs, retainers, taxes, and billing judgment require context.
- Reliable future capacity if allocations/resource schedules are not maintained in CORE.
- Staff availability after PTO/holidays without adding and validating PTO/calendar data.
- Full invoice-line-to-individual-time-entry reconciliation for every invoice type until `invoiceDetails`, `lineItems`, and time/expense `invoiceId` behavior are tested.
- Natural-language answers are only as reliable as the synchronized data, definitions, permissions, and reconciliation controls.

## Live-data uncertainties to verify

1. Exact enum values and tenant usage for project status, contract type, bill status, employee status, and resource type.
2. Whether `billRate`, `costRate`, contract amounts, custom fields, and employee capacity fields are visible to the chosen service user.
3. Whether time entries use `clientHours` differently from `actualHours`, and whether write-up/write-down multipliers change the value Finance expects.
4. Behavior of draft, void, joint, manual, late-fee, retainer, credit, and multi-currency transactions.
5. Whether invoice `balance` agrees with payment details at the chosen as-of date; late adjustments may cause timing differences.
6. Whether missing `invoiceId` reliably means unbilled for approved billable entries, and how `billStatus`, workflow approval, and write-offs interact.
7. Project hierarchy/phase rollups (`type`, parent relationships) and whether management wants phase or top-project totals.
8. Tenant timezone, daylight-saving handling, accounting date versus transaction date, and inclusivity at date boundaries.
9. Completeness and historical retention of allocations/resource schedules.
10. Currency multipliers and whether all monetary values are home currency, transaction currency, or mixed.

## Parameters, pagination, rate limiting, and time

- Lists support `fields`, `where`, `orderBy`, `page`, and usually `expand`; nested objects are omitted unless expanded.
- `page=N,S`: default size is 25, maximum 1,000 without `expand`, and maximum 100 with `expand`. A page beyond the end returns `204 No Content`.
- `fields=count(*)` returns a count and cannot be combined with `orderBy` or `page`; it can be combined with `where`.
- `where` supports expressions only on fields marked Filterable. String/date-time values are single-quoted and clauses should be URL encoded. Complex clauses can time out.
- `orderBy` works only on Sortable fields. Use deterministic ordering (`lastUpdated asc,id asc` where supported) for incremental work.
- Rate-limit quotas are per-minute, but the numeric quota depends on application configuration. Responses expose `X-Rate-Limit-*`; `429` includes `Retry-After`. The client honors `Retry-After` and retries transient 5xx responses with bounded backoff.
- CORE uses ISO 8601 timestamps and documents `createdOn` as UTC. The `X-UTC-Offset` header exists, but a fixed offset does not represent DST year-round. Preserve source timestamps, store UTC when an offset is present, record company timezone separately, and use half-open reporting windows (`>= start`, `< next_day`).
- Incremental sync should filter on `lastUpdated` with a safety overlap and deduplicate by `id`; periodically run a full reconciliation because deletion behavior needs validation. Investigate `/deletedhistory` before relying on it.

## Authentication recommendation

Recommended Developer Portal application type: **Native App**.

Recommended redirect URI: **`http://127.0.0.1:8765/callback`**, registered and sent exactly as written.

The official application-type table identifies Native App for mobile/desktop, no client secret, required PKCE, and no PAR. Use Authorization Code with PKCE (`S256`), launch the system browser, accept only a loopback callback on `127.0.0.1`, validate a cryptographically random `state`, exchange the single-use code, and immediately stop the listener. Do not bind the callback server to all interfaces.

Exact scope:

- `read:core` — required read-only company-data scope.

Do **not** request `offline_access` or `readwrite:core`. BQE's current application-type guidance says only Regular Web App and Web App (FAPI/PAR) support refresh tokens. `openid`, `profile`, `email`, and `address` are also unnecessary for phase-one reporting.

The token response supplies an `endpoint` value that is the company-specific API base URL. Validate it as HTTPS and against the expected BQE domain/data-center pattern before using it; do not construct or guess it.

## Security risks and safeguards

| Risk | Safeguard |
|---|---|
| Excess permissions or accidental mutation | Native App requests only `read:core`; business client rejects every method except GET before network I/O; no write methods exist |
| Token theft | Never paste tokens into chat; use Windows Credential Manager/DPAPI; never log Authorization headers; restrict local user access; support token revocation |
| Access-token persistence | Store the short-lived access token only in Windows Credential Manager; reject unexpected refresh tokens; require interactive reauthorization after expiry |
| CSRF/code interception | Random `state`, PKCE S256, exact loopback URI, single callback, short timeout, bind only `127.0.0.1`, discard code/verifier after exchange |
| Hostile or incorrect API endpoint | Accept only HTTPS; validate token-response endpoint host against an approved BQE allowlist before first request |
| Sensitive cached company data | Separate restricted data directory; `.gitignore` caches/exports/logs/databases; optional encrypted volume; retention/deletion policy; no cloud sync without approval |
| Employee privacy | Select only needed fields; avoid DOB, SSN, bank, address, salary, email, and memos; role-based access to exports; aggregate where possible |
| Misleading management conclusions | Label estimates; reconcile to CORE; record extraction time/filters; retain raw evidence; require Finance/PM review; show data-quality warnings |
| Prompt injection/data exfiltration | Treat BQE text/memos as untrusted data; do not give the reporting agent tools to send messages or mutate external systems; minimize fields supplied to an LLM |
| Logs leaking data | Log counts, resource names, page numbers, and request IDs—not payloads, query values containing names, tokens, or financial records |

## Phase-one implementation boundary

The package implements mock synchronization, raw/normalized SQLite storage, analysis, CSV/Markdown outputs, reusable GET-only client methods, a loopback OAuth PKCE flow, Windows Credential Manager access-token storage, strict endpoint/scope validation, and one explicit five-row connection test. General live synchronization remains disabled.
