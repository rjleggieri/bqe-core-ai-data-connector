# Security policy

## Reporting a vulnerability

Do not open a public issue with credentials, tokens, BQE response data, company names,
employee names, project names, or other sensitive business information. Contact the
repository owner privately through GitHub instead.

## Security boundary

- Business-data requests are GET-only. Other HTTP methods are rejected locally.
- OAuth uses Authorization Code with PKCE, a random state value, and a loopback redirect.
- The requested scope must be exactly `read:core`.
- Short-lived access tokens are stored in Windows Credential Manager, not in the repo.
- Live access is disabled unless both local opt-in settings are enabled.
- `.env`, databases, caches, generated exports, logs, and temporary output are ignored.
- The warehouse stores authorized business data locally and should be protected according
  to the organization's data-retention and workstation-security policies.

Before publishing changes, run:

```powershell
.venv\Scripts\python.exe -m pytest
git diff --check
git grep -n -I -E "access[_-]?token|client[_-]?secret|refresh[_-]?token"
```

Treat any accidentally committed credential as compromised: revoke it, remove the
affected data from repository history, and authorize again.
