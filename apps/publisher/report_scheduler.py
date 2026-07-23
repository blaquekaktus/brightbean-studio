"""Monthly scheduling for white-label publishing reports.

Wires the report generator (``apps.publisher.reports``) into a recurring
background job. On the first of each month it builds the *previous* calendar
month's report for every workspace and notifies the workspace's operators
(Owner / Manager) through the existing notifications engine — which respects
each user's channel preferences and quiet hours, so no separate email or
consent path is introduced.

Delivery is idempotent per ``(workspace, month)`` via the notification's
``data`` payload, so a daily-scheduled runner (or a retried task) never double-
sends. Operators are internal to the SMB, not the SMB's client, so this stays
internal comms.

The registered background task (see ``apps.publisher.apps``) runs daily and
no-ops except on the first of the month; ``force=True`` runs it on any day
(used by tests and manual runs).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from apps.publisher.reports import build_report_data


def previous_month(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """Return ``(start, end, period_key)`` for the previous calendar month.

    ``start`` is inclusive (first instant of the previous month), ``end`` is
    exclusive (first instant of the current month), both timezone-aware.
    ``period_key`` is ``"YYYY-MM"`` of the previous month.
    """
    now = now or timezone.now()
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_prev = first_this - timedelta(days=1)
    start = last_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, first_this, f"{start.year:04d}-{start.month:02d}"


def report_recipients(workspace) -> list:
    """Active workspace operators (Owner / Manager) who should receive the report."""
    from apps.members.models import WorkspaceMembership

    roles = [
        WorkspaceMembership.WorkspaceRole.OWNER,
        WorkspaceMembership.WorkspaceRole.MANAGER,
    ]
    users = []
    seen = set()
    for membership in (
        WorkspaceMembership.objects.filter(workspace=workspace, workspace_role__in=roles)
        .select_related("user")
        .order_by("added_at")
    ):
        user = membership.user
        if user and user.is_active and user.pk not in seen:
            seen.add(user.pk)
            users.append(user)
    return users


def deliver_workspace_report(workspace, start, end, period_key: str) -> int:
    """Notify a workspace's operators of its report for the period.

    Skips workspaces with no published activity, and skips any recipient who
    was already notified for this ``(workspace, month)``. Returns the number of
    notifications sent.
    """
    from apps.notifications.engine import notify
    from apps.notifications.models import EventType, Notification

    report = build_report_data(workspace, start, end)
    if report["total_posts"] == 0:
        return 0

    workspace_id = str(workspace.id)
    title = f"{workspace.name}: {period_key} publishing report"
    body = f"{report['total_posts']} posts published across {report['total_platform_posts']} platform destinations."
    data = {
        "workspace_id": workspace_id,
        "period": period_key,
        "total_posts": report["total_posts"],
        "total_platform_posts": report["total_platform_posts"],
    }

    sent = 0
    for user in report_recipients(workspace):
        already = Notification.objects.filter(
            user=user,
            event_type=EventType.REPORT_GENERATED,
            data__workspace_id=workspace_id,
            data__period=period_key,
        ).exists()
        if already:
            continue
        notify(user, EventType.REPORT_GENERATED, title, body, data=data)
        sent += 1
    return sent


def run_monthly_reports(now: datetime | None = None, force: bool = False) -> dict:
    """Generate + deliver the previous month's report for every workspace.

    No-ops unless it is the first of the month, unless ``force`` is set.
    """
    from apps.workspaces.models import Workspace

    now = now or timezone.now()
    if now.day != 1 and not force:
        return {"skipped": True, "reason": "not the first of the month", "notified": 0}

    start, end, period_key = previous_month(now)
    workspaces_seen = 0
    notified = 0
    for workspace in Workspace.objects.all().iterator():
        workspaces_seen += 1
        notified += deliver_workspace_report(workspace, start, end, period_key)
    return {"period": period_key, "workspaces": workspaces_seen, "notified": notified}
