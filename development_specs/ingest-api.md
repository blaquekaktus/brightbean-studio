# Ingest API — sibling content handoff (ADR-0006, Role A)

Brightbean's **inbound** side of the ai-brain ADR-0006 contract. The sibling
content engine (The AI Shortcut / `automatedcontentcreator`) POSTs a finished
content package here and it lands as a **draft** post in a workspace. Brightbean
keeps every downstream decision — review, approval, scheduling, per-platform
delivery. Nothing published through this door is ever auto-published.

- **App:** `apps/api/`
- **Endpoint:** `POST /api/v1/ingest/posts/`
- **Tests:** `tests/api/test_ingest.py`

## Auth

Bearer token, per workspace. Issue one with the management command (the raw
token is printed **once** — only its SHA-256 hash is stored):

```bash
python manage.py create_ingest_token --workspace <workspace-uuid> --name "ACC theshortcutsai"
```

Put the printed value in the sibling's `BRIGHTBEAN_API_TOKEN` env var and the
workspace UUID in `BRIGHTBEAN_WORKSPACE_EN` / `BRIGHTBEAN_WORKSPACE_DE`. Requests
send `Authorization: Bearer <token>`. Revoke by setting `is_active=False`
(admin) — no need to touch code.

## Request

JSON body matching the sibling adapter's payload
(`src/publish/brightbean_publisher.py` → `build_payload`):

```json
{
  "source": "automatedcontentcreator",
  "external_ref": "acc:post-31-notebooklm-research-assistant:en",
  "status": "draft",
  "title": "NotebookLM Deep Dive",
  "caption": "…YouTube-description body…",
  "first_comment": "",
  "internal_notes": "HUMAN REVIEW REQUIRED before publish. …",
  "tags": ["notebooklm", "ai research assistant"],
  "category": "tool_spotlights",
  "platform_posts": [
    {"platform": "youtube", "status": "draft"},
    {"platform": "instagram", "status": "draft"},
    {"platform": "tiktok", "status": "draft"}
  ],
  "workspace": "<optional workspace uuid — must match the token's workspace>"
}
```

## Behaviour

- Creates a `composer.Post` (author `None` — machine ingest) plus one
  `composer.PlatformPost` (`status="draft"`) per **connected** social account
  matching each requested platform. Platforms with no connected account are
  returned in `skipped_platforms` rather than dropped silently.
- `category` (the sibling's pillar) resolves to a per-workspace
  `ContentCategory`, created on first use.
- **Idempotent** on `external_ref`: re-POSTing the same ref updates the existing
  draft instead of duplicating.
- **Freeze after review:** once a human advances any platform past `draft`, a
  re-ingest returns `frozen: true` and does not overwrite the post.

## Guardrails

| Rule | Enforcement |
|---|---|
| Draft only | `status != "draft"` → 400. `PlatformPost`s created as `draft`. |
| Token-bound workspace | Workspace comes from the token; a mismatched payload `workspace` → 400. |
| No plaintext secrets | Only the token **hash** is stored; raw shown once at issue. |
| Human-review gate | Post/PlatformPost stay draft; review + publish happen in the composer. |

## Responses

- `201` — new draft created.
- `200` — existing draft updated (or `frozen: true` when past draft).
- `400` — bad JSON, non-draft status, foreign workspace, unsupported platform.
- `401` — missing/invalid/revoked token.

Body includes `post_id`, `workspace`, derived `status`, `external_ref`,
`created`/`updated`/`frozen`, `platform_posts`, and `skipped_platforms`.
