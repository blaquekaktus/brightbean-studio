"""Tests for the ADR-0006 draft-ingest endpoint.

Covers token auth, the draft-only guard, workspace binding, platform resolution
(including the no-connected-account case), idempotency by external_ref, and the
freeze-after-human-review rule.
"""

import json

import pytest
from django.urls import reverse

from apps.api.models import IngestRecord, IngestToken, hash_token
from apps.composer.models import ContentCategory, Post
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


@pytest.fixture
def workspace(db, organization):
    return Workspace.objects.create(organization=organization, name="The AI Shortcut")


@pytest.fixture
def token(db, workspace):
    instance, raw = IngestToken.issue(workspace, "ACC theshortcutsai")
    instance.raw = raw  # stash the plaintext for the test to send
    return instance


def _account(workspace, platform):
    return SocialAccount.objects.create(
        workspace=workspace,
        platform=platform,
        account_platform_id=f"{platform}-123",
        account_name=f"{platform} channel",
    )


def _payload(ws, **overrides):
    payload = {
        "source": "automatedcontentcreator",
        "external_ref": "acc:post-31-notebooklm-research-assistant:en",
        "workspace_handle": "theshortcutsai",
        "language": "en",
        "status": "draft",
        "title": "NotebookLM Deep Dive",
        "caption": "I stopped asking a chatbot to read my PDFs.",
        "first_comment": "",
        "internal_notes": "HUMAN REVIEW REQUIRED before publish.",
        "tags": ["notebooklm", "ai research assistant"],
        "category": "tool_spotlights",
        "platform_posts": [
            {"platform": "youtube", "status": "draft"},
            {"platform": "instagram", "status": "draft"},
            {"platform": "tiktok", "status": "draft"},
        ],
    }
    payload.update(overrides)
    return payload


def _post_json(client, payload, raw_token=None):
    headers = {}
    if raw_token is not None:
        headers["HTTP_AUTHORIZATION"] = f"Bearer {raw_token}"
    return client.post(
        reverse("api:ingest_posts"),
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


# --- auth ---------------------------------------------------------------


def test_missing_token_is_401(client, db, workspace):
    resp = _post_json(client, _payload(workspace))
    assert resp.status_code == 401


def test_bad_token_is_401(client, db, workspace):
    resp = _post_json(client, _payload(workspace), raw_token="not-a-real-token")
    assert resp.status_code == 401


def test_revoked_token_is_401(client, token, workspace):
    token.is_active = False
    token.save(update_fields=["is_active"])
    resp = _post_json(client, _payload(workspace), raw_token=token.raw)
    assert resp.status_code == 401


def test_token_hash_only_never_stores_raw(token):
    # The raw token must not be recoverable from the DB.
    assert token.token_hash == hash_token(token.raw)
    assert token.raw not in token.token_hash


# --- happy path ---------------------------------------------------------


def test_creates_draft_post_and_platform_posts(client, token, workspace):
    _account(workspace, "youtube")
    _account(workspace, "instagram")
    resp = _post_json(client, _payload(workspace), raw_token=token.raw)
    assert resp.status_code == 201
    body = resp.json()
    assert body["created"] is True
    assert body["status"] == "draft"
    post = Post.objects.get(id=body["post_id"])
    assert post.workspace_id == workspace.id
    assert post.author_id is None
    assert post.caption.startswith("I stopped asking")
    assert post.tags == ["notebooklm", "ai research assistant"]
    # youtube + instagram connected → 2 platform posts; tiktok skipped.
    platforms = {pp["platform"] for pp in body["platform_posts"]}
    assert platforms == {"youtube", "instagram"}
    assert body["skipped_platforms"] == ["tiktok"]
    assert all(pp["status"] == "draft" for pp in body["platform_posts"])


def test_category_resolved_to_workspace_content_category(client, token, workspace):
    _account(workspace, "youtube")
    resp = _post_json(client, _payload(workspace), raw_token=token.raw)
    post = Post.objects.get(id=resp.json()["post_id"])
    assert post.category is not None
    assert post.category.name == "tool_spotlights"
    assert ContentCategory.objects.filter(workspace=workspace, name="tool_spotlights").exists()


def test_no_connected_accounts_still_creates_draft(client, token, workspace):
    resp = _post_json(client, _payload(workspace), raw_token=token.raw)
    assert resp.status_code == 201
    body = resp.json()
    assert body["platform_posts"] == []
    assert set(body["skipped_platforms"]) == {"youtube", "instagram", "tiktok"}
    # A childless post still derives to "draft".
    assert body["status"] == "draft"


def test_token_last_used_is_stamped(client, token, workspace):
    assert token.last_used_at is None
    _post_json(client, _payload(workspace), raw_token=token.raw)
    token.refresh_from_db()
    assert token.last_used_at is not None


# --- guards -------------------------------------------------------------


def test_non_draft_status_is_rejected(client, token, workspace):
    resp = _post_json(client, _payload(workspace, status="published"), raw_token=token.raw)
    assert resp.status_code == 400
    assert "draft" in resp.json()["error"].lower()


def test_foreign_workspace_uuid_is_rejected(client, token, workspace, organization):
    other = Workspace.objects.create(organization=organization, name="Other")
    resp = _post_json(client, _payload(workspace, workspace=str(other.id)), raw_token=token.raw)
    assert resp.status_code == 400


def test_matching_workspace_uuid_is_accepted(client, token, workspace):
    resp = _post_json(client, _payload(workspace, workspace=str(workspace.id)), raw_token=token.raw)
    assert resp.status_code == 201


def test_unsupported_platform_is_rejected(client, token, workspace):
    payload = _payload(workspace, platform_posts=[{"platform": "myspace"}])
    resp = _post_json(client, payload, raw_token=token.raw)
    assert resp.status_code == 400


def test_bad_json_is_400(client, token):
    resp = client.post(
        reverse("api:ingest_posts"),
        data="{not json",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token.raw}",
    )
    assert resp.status_code == 400


def test_get_is_405(client, token):
    resp = client.get(reverse("api:ingest_posts"))
    assert resp.status_code == 405


# --- idempotency + freeze ----------------------------------------------


def test_resubmit_same_external_ref_updates_not_duplicates(client, token, workspace):
    _account(workspace, "youtube")
    first = _post_json(client, _payload(workspace), raw_token=token.raw)
    second = _post_json(client, _payload(workspace, caption="Edited caption"), raw_token=token.raw)
    assert first.json()["post_id"] == second.json()["post_id"]
    assert second.status_code == 200
    assert second.json()["updated"] is True
    assert Post.objects.filter(workspace=workspace).count() == 1
    assert IngestRecord.objects.filter(workspace=workspace).count() == 1
    Post.objects.get(id=second.json()["post_id"]).refresh_from_db()
    assert Post.objects.get(id=second.json()["post_id"]).caption == "Edited caption"


def test_resubmit_does_not_overwrite_post_advanced_past_draft(client, token, workspace):
    _account(workspace, "youtube")
    resp = _post_json(client, _payload(workspace), raw_token=token.raw)
    post = Post.objects.get(id=resp.json()["post_id"])
    # A human moves the single platform post forward.
    pp = post.platform_posts.first()
    pp.status = "approved"
    pp.save(update_fields=["status"])

    again = _post_json(client, _payload(workspace, caption="Sneaky overwrite"), raw_token=token.raw)
    assert again.status_code == 200
    assert again.json()["frozen"] is True
    post.refresh_from_db()
    assert post.caption.startswith("I stopped asking")  # unchanged
