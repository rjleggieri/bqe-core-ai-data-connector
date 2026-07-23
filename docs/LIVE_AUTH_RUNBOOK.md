# Live authorization and synchronization runbook

Authorization retrieves a short-lived token but no BQE business records. Capability
probes retrieve at most five minimal rows and do not store or display them. Synchronization
stores authorized records in the local Git-ignored warehouse.

## Application configuration

- Application type: Native App
- Redirect URI: `http://127.0.0.1:8765/callback`
- Requested scope: exactly `read:core`
- Webhooks: disabled
- Client secret: none
- Access token: Windows Credential Manager
- Business-data client: GET-only

Copy `.env.example` to `.env`, enter the client ID, and confirm that `.env` is ignored.
Set:

```dotenv
BQE_MODE=LIVE
BQE_ENABLE_LIVE=YES
```

## Authorize

```powershell
.venv\Scripts\bqe.exe auth --login
```

The command binds to `127.0.0.1:8765`, generates PKCE and state values, opens BQE
Identity, and waits up to three minutes. Confirm that consent requests `read:core` only.
Decline if a write, profile, email, address, or offline permission appears.

The returned API endpoint must use HTTPS under `*.bqecore.com`. The connector rejects a
refresh token or `readwrite:core`. It stores the short-lived token in Windows Credential
Manager and makes no company-data request during authorization.

## Test capabilities

Project capability:

```powershell
.venv\Scripts\bqe.exe test-connection --live
```

Approved resource capabilities:

```powershell
.venv\Scripts\bqe.exe test-access --live timeentry expenseentry allocation
```

Each probe requests only `id,lastUpdated`, limits the response to five rows, and prints
only HTTP status, row count, and rate-limit information.

## First synchronization

Use a bounded date range when only time, expense, and allocation history is approved:

```powershell
.venv\Scripts\bqe.exe sync --live `
  --resources time_entries expense_entries allocations `
  --from YYYY-MM-DD --to YYYY-MM-DD
```

Use `--full` only when a complete first load has been approved:

```powershell
.venv\Scripts\bqe.exe sync --live --full
```

The default run is permission-aware: an HTTP 403 or 404 is recorded as unavailable and
other resources continue. Add `--strict` when missing access must fail the run.

## Validate and export

```powershell
.venv\Scripts\bqe.exe status
.venv\Scripts\bqe.exe validate
.venv\Scripts\bqe.exe analyze
.venv\Scripts\bqe.exe brief
.venv\Scripts\bqe.exe export-context
```

Reconcile time-entry count, actual hours, billable hours, expense-entry count, and charge
amount to the same inclusive date range in BQE CORE. Financial measures must be
reconciled to BQE reports before presentation.

## Routine synchronization

After a resource has a checkpoint, the same command incrementally requests records whose
`lastUpdated` value is at or after that checkpoint. Equal timestamps are intentionally
overlapped; upserts and raw-response hashes make the operation repeatable.

```powershell
.venv\Scripts\bqe.exe sync --live
```

## Close out

Delete the locally stored access token when it is no longer needed:

```powershell
.venv\Scripts\bqe.exe auth --clear
```

Disable the two live gates in `.env`. Apply the organization's approved retention period
to the local database and exports.
