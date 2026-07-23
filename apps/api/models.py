"""Ingest-API models.

`IngestToken` authenticates service-to-service ingest calls from a sibling
repo (ADR-0006, Role A: The AI Shortcut → Brightbean). `IngestRecord` maps a
sibling's ``external_ref`` back to the created `Post` so re-submissions are
idempotent instead of creating duplicates.

The raw token is never stored — only its SHA-256 hash. Issue a token with
``IngestToken.issue(workspace, ...)`` (or the ``create_ingest_token`` management
command), which returns the raw value exactly once for the caller to place in
the sibling's ``BRIGHTBEAN_API_TOKEN`` env var.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from django.db import models
from django.utils import timezone

_TOKEN_BYTES = 32  # 256 bits of entropy → 43-char urlsafe token.


def hash_token(raw: str) -> str:
    """Return the hex SHA-256 of a raw token (what we persist and compare)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IngestToken(models.Model):
    """A bearer token scoped to a single workspace for draft ingest.

    A token grants exactly one capability: create/update **draft** posts in its
    workspace. It never approves, schedules, or publishes — the human-review
    gate stays in the composer (ADR-0006).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ingest_tokens",
    )
    name = models.CharField(
        max_length=100,
        help_text="Human label for this token, e.g. 'ACC theshortcutsai'.",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "api_ingest_token"
        ordering = ["-created_at"]

    def __str__(self):
        state = "active" if self.is_active else "revoked"
        return f"IngestToken({self.name}, {state})"

    @classmethod
    def issue(cls, workspace, name: str) -> tuple[IngestToken, str]:
        """Create a token and return (instance, raw_token).

        The raw token is returned once and never stored — persist only its hash.
        """
        raw = secrets.token_urlsafe(_TOKEN_BYTES)
        instance = cls.objects.create(
            workspace=workspace,
            name=name,
            token_hash=hash_token(raw),
        )
        return instance, raw

    @classmethod
    def authenticate(cls, raw: str | None) -> IngestToken | None:
        """Return the active token matching ``raw``, or None.

        The lookup is by hash; the final check uses a constant-time compare so a
        stray non-unique hash can never shortcut verification.
        """
        if not raw:
            return None
        candidate = cls.objects.filter(token_hash=hash_token(raw), is_active=True).select_related("workspace").first()
        if candidate is None:
            return None
        if not hmac.compare_digest(candidate.token_hash, hash_token(raw)):
            return None
        return candidate

    def mark_used(self):
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])


class IngestRecord(models.Model):
    """Idempotency + audit link between a sibling's ``external_ref`` and a Post."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_ref = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Sibling-supplied idempotency key, e.g. 'acc:post-31-...:en'.",
    )
    post = models.ForeignKey(
        "composer.Post",
        on_delete=models.CASCADE,
        related_name="ingest_records",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ingest_records",
    )
    token = models.ForeignKey(
        IngestToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ingest_records",
    )
    source = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "api_ingest_record"
        ordering = ["-created_at"]

    def __str__(self):
        return f"IngestRecord({self.external_ref})"
