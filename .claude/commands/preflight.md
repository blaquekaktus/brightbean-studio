# /preflight

Pre-commit checklist for brightbean-studio.

1. **No cross-tenant queries** — every queryset touching user data must filter by `workspace` or `organization`. Grep for raw `Model.objects.all()` in changed files.
2. **No hardcoded credentials** — no API keys, tokens, or passwords in committed files. Secrets via env vars only.
3. **No PII in commits** — UIDs only for users/clients in committed files.
4. **Layer 0 scan** — no currency symbols in internal files, no real emails.
5. **No secrets** — `.env` only, gitignored.
6. **Multi-tenant FK present** — any new model with user-scoped data has a `workspace` or `organization` FK.
7. **Tests pass** — run `pytest` before committing any `apps/` changes.
8. **No real OAuth tokens in fixtures** — all test fixtures use mocked credentials.

Report pass / warn / fail per item.
