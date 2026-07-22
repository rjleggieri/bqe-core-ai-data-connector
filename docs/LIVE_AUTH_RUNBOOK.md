# Live Authorization and First Read-Only Test

This runbook contains two distinct actions. Authorization obtains a short-lived token but retrieves no company business data. The connection test makes one limited GET request. Stop between them unless both have been approved.

## Already completed

- BQE Developer Portal application type: Native App
- Client ID stored locally in Git-ignored `.env`
- Redirect URI: `http://127.0.0.1:8765/callback`
- Requested scope: exactly `read:core`
- Webhooks: disabled
- Windows credential backend: available
- Non-GET business requests: blocked in code

## Before authorization

Confirm:

1. The portal's edit view still shows the exact redirect URI above.
2. You will sign in with the intended CORE company/user.
3. That user's permissions are limited to the reporting modules needed for the proof of concept.
4. You approve opening the BQE login page and obtaining a short-lived read-only access token.

Then change these two local `.env` values:

```dotenv
BQE_MODE=LIVE
BQE_ENABLE_LIVE=YES
```

Run:

```powershell
.venv\Scripts\bqe.exe auth --login
```

The CLI binds only to `127.0.0.1:8765`, generates PKCE and `state`, opens the BQE login page, and waits up to three minutes. On the consent page, verify that the requested permission is **read:core only**. If any write, profile, email, address, or offline permission appears, decline and stop.

After consent, the authorization code is exchanged once. The code and PKCE verifier are discarded. The returned API endpoint must be HTTPS under `*.bqecore.com`; a token with `readwrite:core`, a refresh token, or an unexpected endpoint is rejected. The short-lived access token is stored in Windows Credential Manager. No BQE business-data endpoint is called.

Check status without a network request:

```powershell
.venv\Scripts\bqe.exe auth
```

## First business-data test

Only after separately approving the first data request, run:

```powershell
.venv\Scripts\bqe.exe test-connection --live
```

This makes exactly one business-data request equivalent to:

```http
GET {validated-endpoint}/project?fields=id,lastUpdated&orderBy=lastUpdated%20desc&page=1,5
```

It prints only HTTP status, row count, and the remaining rate-limit value. It does not print identifiers or field values, cache the response, or synchronize other resources.

## After the test

Remove the local access token when desired:

```powershell
.venv\Scripts\bqe.exe auth --clear
```

Return `.env` to:

```dotenv
BQE_MODE=MOCK
BQE_ENABLE_LIVE=NO
```

Before broader retrieval, agree on the company timezone, reporting currency, approved test date range, local retention, and the BQE report/screen used for reconciliation.

## Limited time/expense pilot

For an explicitly approved date range, the constrained pilot command writes to a separate Git-ignored database and requests no names, memos, descriptions, custom fields, or attachments:

```powershell
.venv\Scripts\bqe.exe pilot-sync --live --from YYYY-MM-DD --to YYYY-MM-DD --output-db data\live_pilot.sqlite3
```

Verify against **Time & Expenses > Time Entries** and **Time & Expenses > Expense Entries**. On each screen select a Custom Period matching the inclusive dates, clear status restrictions, and select all accessible employees/resources. Compare entry count and actual hours for time; compare entry count and charge amount for expenses. The API extract may contain only the records allowed by the consenting user's Security Profile.
