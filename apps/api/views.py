"""Ingest-API HTTP layer.

A single token-authenticated endpoint, ``POST /api/v1/ingest/posts/``, that the
sibling content engine calls to hand off a finished package as a draft
(ADR-0006, Role A). Plain Django + ``JsonResponse`` — the repo has no DRF and
this one endpoint doesn't justify adding it.
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .ingest import IngestError, ingest_draft
from .models import IngestToken


def _bearer(request) -> str | None:
    """Extract a bearer token from the Authorization header."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    prefix = "Bearer "
    if header.startswith(prefix):
        return header[len(prefix) :].strip()
    return None


@csrf_exempt
@require_POST
def ingest_posts(request):
    """Receive one content package and create/update a draft Post.

    Auth: ``Authorization: Bearer <token>`` (an active `IngestToken`). The
    token's workspace is authoritative — the payload cannot target another.
    """
    token = IngestToken.authenticate(_bearer(request))
    if token is None:
        return JsonResponse({"error": "Invalid or missing ingest token."}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)

    try:
        result = ingest_draft(payload, token)
    except IngestError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    token.mark_used()
    status_code = 201 if result.get("created") else 200
    return JsonResponse(result, status=status_code)
