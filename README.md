# BQE CORE Read-Only Reporting Proof of Concept

This project explores management reporting, historical billing analysis, and workload analysis from BQE CORE without changing BQE data. Phase one is **mock-first and synthetic-only**. It is a reporting proof of concept, not a production integration.

No BQE authentication or company-data request has been attempted.

## Safety boundary

- The business-data client implements GET only and rejects POST, PUT, PATCH, and DELETE before network I/O.
- Configuration rejects `readwrite:core`.
- Live mode requires two local gates (`BQE_MODE=LIVE` and `BQE_ENABLE_LIVE=YES`), and phase-one `bqe sync --live` still stops before making a request.
- Credentials/tokens, caches, databases, exports, logs, and live data are excluded by `.gitignore`.
- Mock commands print an unmistakable synthetic-data banner.

## What is implemented

- Reusable `httpx` API client with `fields`, `where`, `orderBy`, `page`, and `expand`; documented pagination limits; retry handling for `429`/5xx; and methods for projects, clients, employees, time/expense entries, invoices, payments, activities, allocations, and custom fields.
- Native App OAuth Authorization Code + PKCE with random state, S256 challenge, a `127.0.0.1` loopback callback, strict endpoint validation, and Windows Credential Manager access-token storage.
- SQLite warehouse with raw-response audit storage, normalized tables, foreign keys, hash deduplication, upserts, and per-resource high-water marks.
- Synthetic transformations for project hours, billable/nonbillable hours, estimated billable value, estimated labor cost, invoices, payments, outstanding balance, unbilled time, workload, and monthly trends.
- CSV and Markdown prototype outputs.
- Automated tests for pagination, query construction, write prevention, normalization, duplicates, incremental sync state, nulls, and financial consistency.

## What is not implemented

- General live synchronization. The only enabled live business-data operation is an explicit, five-row, field-minimized connection test.
- Production scheduling, webhook handling, deleted-record sync, encrypted database, multi-company isolation, or monitoring.
- Validated treatment of BQE enums, project phases, joint/manual invoices, retainers, credits, multi-currency, write-ups/write-downs, or accounting revenue.
- Vendor resources and production-grade decimal currency accounting.
- Automatic decisions or any BQE write operation.

See [API capability assessment](docs/BQE_API_CAPABILITY_ASSESSMENT.md), [local model](docs/LOCAL_ANALYTICAL_MODEL.md), and [demo workflows](docs/DEMO_WORKFLOW_OPTIONS.md).

## Install on Windows

In PowerShell from this folder:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, use `.venv\Scripts\python.exe` in place of `python`; changing machine-wide execution policy is not required.

## Run in mock mode

Do not create `.env` for the synthetic workflow. Defaults are safe.

```powershell
bqe sync --from 2026-06-01 --to 2026-07-31
bqe analyze
bqe brief
bqe inspect-schema
pytest
```

Generated local data goes under `data/`; outputs go under `exports/mock/`. Both are Git-ignored. The included prototype copies under `examples/outputs/` are synthetic and safe to review.

The date arguments are accepted for the future live workflow; the fixed synthetic fixture currently includes June and July 2026 and is loaded in full.

## OAuth design to configure later

Proposed application type: **Native App**

Redirect URI: **`http://127.0.0.1:8765/callback`**

Scope: **`read:core`**

BQE's current application-type documentation says Native Apps do not support refresh tokens. Request exactly `read:core`; do not add `offline_access`, `readwrite:core`, `openid`, `profile`, `email`, or `address`. Interactive sign-in is required again after the short-lived access token expires.

The design follows BQE's [Native App PKCE guidance](https://api-explorer.bqecore.com/docs/authentication-authorization) and [Getting Started flow](https://api-explorer.bqecore.com/docs/getting-started). BQE's token response includes the company-specific API `endpoint`; the implementation must validate and use that returned HTTPS URL rather than guessing it.

## Developer Portal steps (do not authenticate yet)

1. Sign in to the BQE CORE Developer Portal with the separate developer account.
2. Add a new application with a clearly limited name such as `Management Reporting POC - Read Only`.
3. Select application type **Native App**.
4. Register exactly `http://127.0.0.1:8765/callback` as a redirect URI, including scheme, host, port, path, case, and lack of trailing slash.
5. The portal lists supported scopes, but this app requests exactly `read:core`. Never request `offline_access` or `readwrite:core` for this Native App.
6. Do not create webhooks for phase one.
7. Copy only the Client ID into a local `.env` created from `.env.example`; a Native App should not use a client secret.
8. Choose a dedicated CORE user with the minimum read subscriptions/security permissions required for the small test. Exclude HR/payroll/banking/private employee fields.
9. Review the portal entry, selected CORE user, redirect URI, and scopes with the project owner before any consent.
10. Stop and provide the non-secret configuration items listed below. Do not paste tokens, passwords, client secrets, or company records into chat.

## Information needed before the first authenticated call

Provide or confirm only:

- The non-secret Native App Client ID (preferably enter it locally rather than in chat).
- Confirmation that the registered application type is Native App.
- Confirmation that the exact redirect URI is registered.
- Confirmation that the consent screen requests only `read:core`.
- The intended dedicated CORE user's role/subscription categories—describe permissions, not credentials.
- The company timezone and reporting currency.
- An approved minimal test date range and whether project/client names may be cached locally.
- The expected BQE report/screen and totals that Finance will use for reconciliation.
- Approval of the local retention location and period for the first extract.

Never provide a password, authorization code, access token, refresh token, client secret, or live data in chat.

## Recommended first limited read-only test

After explicit approval:

1. Complete one interactive Native App PKCE consent locally with `bqe auth --login`.
2. Validate the returned API endpoint as an approved HTTPS BQE host.
3. Call only:

   `GET {endpoint}/project?fields=id,lastUpdated&page=1,5&orderBy=lastUpdated%20desc`

4. Log only status, response headers, elapsed time, and row count—not IDs or payload values.
5. Confirm no more than five rows, inspect field shape locally, then revoke/delete local tokens if the test ends.

This verifies authorization, endpoint selection, field projection, sorting, pagination, rate-limit headers, and project permission while minimizing exposed content. The next test should use a tiny approved time-entry window and reconcile counts/hours to CORE.

## Verification before presenting results

For every reporting period and currency:

1. Record the extraction timestamp, user/permission profile, filters, timezone, and API field list.
2. Reconcile counts and sums for invoices, voids/drafts, payments, balances, time hours, billable hours, and unbilled entries to named BQE screens/reports.
3. Investigate differences at source-ID level; do not “plug” unexplained variances.
4. Confirm project phases, joint invoices, retainers/credits, write-offs, rate overrides, taxes, and multi-currency treatment.
5. Have Finance approve billing/payment definitions and a project leader approve workload definitions.
6. Label calculated bill value, labor cost, outstanding allocations, and anomaly flags as estimates where applicable.
7. Preserve raw API evidence and transformation version for audit, subject to approved retention.

## Key risks before real data

- Read access may expose sensitive financial, client, employee, cost-rate, or memo data beyond the demo's needs.
- The consenting user's subscription/permissions can silently make extracts incomplete.
- BQE public API fields and CORE standard reports may implement different business logic.
- Fixed-fee, joint/manual invoices, retainers, credits, multi-currency, project hierarchy, and write-up/down rules can distort naive joins.
- Allocation data may not reflect actual capacity if teams do not maintain it.
- Local SQLite/CSV exports are unencrypted by default; keep them on an approved restricted drive and delete them on schedule.
- LLM-generated narratives can overstate heuristics. Every brief must show reconciliation and data-quality caveats.

## Secure token handling recommendation

The CLI stores only the short-lived access token and validated company endpoint in Windows Credential Manager, keyed by the Native App Client ID. It rejects refresh tokens, write-scoped tokens, and non-BQE endpoints. Tokens are never printed or logged and can be removed with `bqe auth --clear`. Plaintext token files are not used.

## Live authorization runbook

See [docs/LIVE_AUTH_RUNBOOK.md](docs/LIVE_AUTH_RUNBOOK.md) for the exact interactive steps and stop points.
