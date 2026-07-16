"""Draft ingest: map a sibling content payload to a Brightbean draft Post.

Implements the receiving half of ai-brain ADR-0006, Role A. The sibling (The AI
Shortcut / automatedcontentcreator) POSTs a finished content package as a draft;
this module turns it into a `composer.Post` plus one `composer.PlatformPost` per
connected social account, all at ``status="draft"``.

Guardrails enforced here:

- **Draft only.** A payload whose ``status`` is anything but ``"draft"`` is
  rejected — ACC never publishes through this door (ADR-0006; composer keeps the
  human-review gate).
- **Never clobber human edits.** A re-submission (same ``external_ref``) updates
  the post *only while it is still an untouched draft*. Once a reviewer advances
  any platform past draft, the post is frozen against further ingest overwrites.
- **Workspace is bound to the token**, not chosen by the payload. A payload
  ``workspace`` UUID, if present, must match the token's workspace or the call
  is rejected — a token can only ever write to its own workspace.
"""

from __future__ import annotations

from django.db import transaction

from apps.composer.models import ContentCategory, PlatformPost, Post
from apps.social_accounts.models import SocialAccount

_DRAFT = PlatformPost.Status.DRAFT  # "draft"

# Platform strings the sibling may send (a subset of SocialAccount platforms).
# LinkedIn is intentionally absent — it is manual-only on the sibling, forever.
VALID_PLATFORMS = {
    "facebook",
    "instagram",
    "instagram_personal",
    "tiktok",
    "youtube",
    "pinterest",
    "threads",
    "bluesky",
    "google_business",
    "mastodon",
}


class IngestError(ValueError):
    """A payload the caller can fix — surfaced to the client as HTTP 400."""


def _resolve_category(workspace, pillar) -> ContentCategory | None:
    """Map the sibling's pillar string to a per-workspace ContentCategory."""
    name = (pillar or "").strip()
    if not name:
        return None
    category, _ = ContentCategory.objects.get_or_create(workspace=workspace, name=name)
    return category


def _requested_platforms(payload) -> list[str]:
    """Validated, de-duplicated platform names from ``platform_posts``."""
    out: list[str] = []
    for entry in payload.get("platform_posts", []) or []:
        name = (entry or {}).get("platform")
        if not name:
            continue
        if name not in VALID_PLATFORMS:
            raise IngestError(f"Unsupported platform: {name!r}")
        if name not in out:
            out.append(name)
    return out


def _sync_platform_posts(post, workspace, platforms) -> tuple[list[dict], list[str]]:
    """(Re)build draft PlatformPosts for the requested platforms.

    Creates one PlatformPost per *connected* social account matching each
    requested platform. Platforms with no connected account are reported as
    skipped rather than silently dropped. Returns (created_summaries, skipped).
    """
    # Rebuild from scratch so a re-ingest reflects the latest payload exactly.
    post.platform_posts.all().delete()
    created: list[dict] = []
    skipped: list[str] = []
    for platform in platforms:
        accounts = list(SocialAccount.objects.filter(workspace=workspace, platform=platform))
        if not accounts:
            skipped.append(platform)
            continue
        for account in accounts:
            pp = PlatformPost.objects.create(
                post=post,
                social_account=account,
                status=_DRAFT,
            )
            created.append(
                {
                    "platform": platform,
                    "social_account_id": str(account.id),
                    "platform_post_id": str(pp.id),
                    "status": pp.status,
                }
            )
    return created, skipped


def ingest_draft(payload: dict, token) -> dict:
    """Create or idempotently update a draft Post from a sibling payload.

    ``token`` is an authenticated ``IngestToken``; its workspace is authoritative.
    Returns a JSON-serialisable summary. Raises ``IngestError`` for any
    caller-fixable problem (bad status, foreign workspace, unsupported platform).
    """
    from .models import IngestRecord  # local import avoids app-loading cycle

    if not isinstance(payload, dict):
        raise IngestError("Payload must be a JSON object.")

    status = payload.get("status", _DRAFT)
    if status != _DRAFT:
        raise IngestError(
            f"Only draft ingest is permitted (got status={status!r}). Publishing is a human action in Brightbean."
        )

    workspace = token.workspace
    claimed = payload.get("workspace")
    if claimed and str(claimed) != str(workspace.id):
        raise IngestError("Payload workspace does not match this token's workspace.")

    external_ref = (payload.get("external_ref") or "").strip()
    platforms = _requested_platforms(payload)

    fields = {
        "title": payload.get("title", "") or "",
        "caption": payload.get("caption", "") or "",
        "first_comment": payload.get("first_comment", "") or "",
        "internal_notes": payload.get("internal_notes", "") or "",
        "tags": payload.get("tags", []) or [],
    }

    with transaction.atomic():
        record = (
            IngestRecord.objects.select_for_update().filter(external_ref=external_ref).first() if external_ref else None
        )

        if record is not None:
            post = record.post
            # Freeze against overwrite once a human has advanced it past draft.
            if post.status != _DRAFT:
                return {
                    "post_id": str(post.id),
                    "workspace": str(workspace.id),
                    "status": post.status,
                    "external_ref": external_ref,
                    "created": False,
                    "updated": False,
                    "frozen": True,
                    "detail": "Post advanced beyond draft; ingest did not overwrite it.",
                    "platform_posts": [],
                    "skipped_platforms": [],
                }
            for key, value in fields.items():
                setattr(post, key, value)
            post.category = _resolve_category(workspace, payload.get("category"))
            post.save()
            created_flag = False
        else:
            post = Post.objects.create(
                workspace=workspace,
                author=None,  # machine ingest — no human author
                category=_resolve_category(workspace, payload.get("category")),
                **fields,
            )
            created_flag = True

        platform_summaries, skipped = _sync_platform_posts(post, workspace, platforms)

        if external_ref:
            if record is None:
                IngestRecord.objects.create(
                    external_ref=external_ref,
                    post=post,
                    workspace=workspace,
                    token=token,
                    source=payload.get("source", "") or "",
                )
            else:
                record.post = post
                record.token = token
                record.save(update_fields=["post", "token", "updated_at"])

    return {
        "post_id": str(post.id),
        "workspace": str(workspace.id),
        "status": post.status,  # derived aggregate — "draft"
        "external_ref": external_ref,
        "created": created_flag,
        "updated": not created_flag,
        "frozen": False,
        "platform_posts": platform_summaries,
        "skipped_platforms": skipped,
    }
