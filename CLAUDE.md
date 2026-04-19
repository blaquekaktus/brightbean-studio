# brightbean-studio — Universal CLAUDE.md Framework

> This repo participates in the Universal CLAUDE.md Framework.
> Universal rules (Layer 0 + Ecosystem + Guardrails) appear first.
> Project-specific rules are below the divider.
>
> Framework version: Patch 2026-04-12-A

---

## Layer 0 — Identity & Privacy Policy (NON-NEGOTIABLE)

### UIDs Only — Never Commit Real Identities

Every person, client, lawyer, or prospect referenced in ANY repo uses a
UID. Real names, emails, phones, and addresses live ONLY in
`~/.claude-private/` — never in any committed file.

**UID format:** `[Category][Owner]-[8 hex chars]`

- Categories: `P` (person), `C` (client), `L` (lawyer individual), `U` (lead/prospect)
- Owners: `S` (Self), `J` (Jason)
- Examples: `CS-3a7f2c1e`, `LJ-a91b4e5d`, `US-f3b8a24e`

Law firm names are public entities and MAY be committed (firm only,
never individual lawyers inside them — those still use `L[S|J]-xxxxxxxx`).

### Units Only — Never Commit Currency Amounts

Financial values are expressed in abstract **units**, never in
USD/EUR/etc. The conversion factor lives ONLY in
`~/.claude-private/units.conf` — never committed, never sent to any
remote system.

Precision: **3 decimal places** (e.g. `0.450 units`).

### Agent Rules (every session in this repo)

**No conversational sign-offs.** Do not add closing lines like "Branches pushed, no PRs opened per your standing rule" or similar acknowledgments at the end of turns. State what's done inside the task output only; the turn ends when the summary ends.

**PR discipline.** One logical change per PR — a feature, a fix, or a refactor, not all three. If a task touches more than ~400 lines or 5 files across unrelated concerns, split it. Prefer merging small PRs fast over one large PR that sits in review. Use `isolation: worktree` when invoking the `experiment` agent for speculative or risky changes.

<important if="you are writing files, committing code, or pushing to remote">

You MUST:

- NEVER commit real names, emails, phones, or postal addresses.
- NEVER commit currency symbols or currency codes.
- If a real identity appears in context, replace with a UID placeholder
  and flag that the user must add the offline mapping entry.
- If a currency figure appears in context, replace with `[X units]`
  and flag for local conversion.
- Screenshots/logs containing PII are never committed or sent to remote
  MCPs without redaction.

</important>

Before any commit, scan the diff for email markers, currency symbols,
digit-heavy phone-like patterns. If found → abort, sanitize with
UIDs/units, re-stage. The canonical pre-commit hook spec lives in
`ai-brain/patterns/precommit-hook.md`.

### Offline Secrets Directory

Location: `~/.claude-private/`
Contents:
- `units.conf` — conversion factor
- `persons.json` / `clients.json` / `lawyers.json` / `leads.json` — UID→identity maps

---

## Ecosystem Context

brightbean-studio is an open-source social media management platform
(Django + React, self-hostable). In this portfolio it serves two roles:

- **(A) ACC output sink** — The AI Shortcut (`automatedcontentcreator`)
  publishes scheduled content through Brightbean's publisher/composer apps.
- **(B) SMB white-label** — bundled with the `websites` service as a
  managed social-media-management offering for KMU clients.

**Status: ADR-0006 proposed.** Full adoption is blocked on:
- ADR-0002 (Lechner Studios entity readiness for platform app registration)
- Hosting target decision (shared VPS vs dedicated)
- ACC→Brightbean handoff contract spec

Do NOT add Brightbean cross-links to other repos' copy or footers until
ADR-0006 is accepted.

### Portfolio Map (brief)

- `websites` — client web builds; potential white-label bundler
- `automatedcontentcreator` — content pipeline; primary Brightbean publisher
- `ai-brain` — knowledge layer; compliance, decisions, patterns

---

## Project-Specific Rules

### Stack

Django 4.x + React + Postgres + Redis. Managed via Docker Compose.
Run locally with `make dev`. Tests: `pytest`. Lint: `ruff`.

### Key invariants

1. **Multi-tenant by design.** Every model with user data must have a
   `workspace` or `organization` FK. Never write cross-tenant queries.
2. **No hardcoded credentials.** All secrets via environment variables;
   `.env` is gitignored. Use `config/` patterns for env var access.
3. **Upstream compatibility.** This is a fork of an open-source project.
   Keep changes minimal and upstream-compatible where possible — prefer
   config over monkey-patching.
4. **ACC integration boundary.** The publisher/composer apps are the
   integration surface. Do not modify upstream social-account auth flows
   without checking for breakage against the ACC webhook contract.
5. **No real social credentials in test fixtures.** Mock all OAuth tokens.
