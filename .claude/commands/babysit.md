# /babysit

Shepherd one open PR toward merge without supervision. Each run is a single
pass: assess state, take the smallest corrective action, report, and stop.
Designed to run on `/loop` — e.g. `/loop 5m /babysit`.

Usage: `/babysit` (current branch's PR) · `/babysit 1234` (a specific PR).

## Step 1 — Identify the target PR
The current branch's PR, or a passed number. If none is open, report and stop —
do not open one. Capture CI status, mergeable state, unresolved review threads.

## Step 2 — Triage (one action per pass, highest priority first)
CI runs `ruff check .`, `ruff format --check .`, `mypy apps/ config/ providers/
tests/ --ignore-missing-imports`, `pytest --cov=apps`, and a Docker build.
Reproduce locally before pushing.

1. **Failing CI** → read the failing job's logs, apply the minimal fix, push:
   - **ruff check** → fix the lint (or a scoped, justified `# noqa`). Run `ruff check .`.
   - **ruff format** → run `ruff format .` and commit.
   - **mypy** → fix the type; never blanket-`# type: ignore` to pass.
   - **pytest** → reproduce with `pytest`; fix code or test, never delete/skip a test.
   - **Docker build** → fix the Dockerfile/deps as the log indicates.
2. **Conflict / behind base** → rebase onto the base branch, resolve conservatively, push.
3. **Review comments** → apply each actionable change; reply only where it adds info; resolve addressed threads.
4. **All green, no open comments** → report ready-to-merge (never merge a critical change).

## Step 3 — Guardrails
- Stay on the designated branch; smallest footprint; one logical change per push.
- **Sensitive surfaces are human-review-only** — this is the ecosystem publishing
  backend: its API endpoints/auth, the client-workspace boundary, and any DB
  migration stay human-review. Apply only mechanical lint/type/format fixes there.
- **Layer 0** — never commit real names/emails/phones/addresses (UIDs) or currency
  (units); respect `.layer0-allow`. Scan the diff before every push.
- Ambiguous or architecturally significant fix → ASK, don't guess.
- Verify against the real CI result before reporting green.

## Step 4 — Report
`PR #<n> · <state>  (CI: <pass/fail> · conflicts: <y/n> · open comments: <n>)`
`Action this pass: <what changed, or "none — waiting on CI / human review">`
Stay silent on no-op passes. Stop when the PR is merged or closed.

Canonical spec: `ai-brain/patterns/babysit.md`.

In a web/remote session, subscribing to the PR's activity is the event-driven
equivalent — CI and review events wake the session instead of polling.
