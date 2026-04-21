# brightbean-studio

> **Ecosystem publishing backend.** Adopted per ADR-0006.

This repository is governed by the universal portfolio rules defined in `ai-brain`.

## Layer 0: Universal Rules

- **UIDs Only:** `[Category][Owner]-[8 hex chars]`. Never commit real names, emails, phones, or postal addresses outside of explicitly allowed paths in `.layer0-allow`.
- **Units Only:** All financial values in units.
- **Reference:** See `ai-brain/README.md` for full ecosystem compliance, accounting, and editing rules.

---

## Local Rules

- **Stack:** Django / HTMX / Postgres / Caddy.
- **Isolation:** This application uses its own Postgres database. It does NOT connect to the portfolio Supabase instance.
- **Role:** It acts as the API endpoint for `automatedcontentcreator` output and provides white-label workspaces for SMB clients.
