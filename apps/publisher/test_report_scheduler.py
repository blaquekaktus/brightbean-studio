"""Tests for monthly report scheduling + delivery."""

from datetime import UTC, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.notifications.models import EventType, Notification
from apps.organizations.models import Organization
from apps.publisher.report_scheduler import (
    deliver_workspace_report,
    previous_month,
    report_recipients,
    run_monthly_reports,
)
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class PreviousMonthTests(TestCase):
    def test_computes_previous_calendar_month(self):
        now = datetime(2026, 7, 15, 9, 30, tzinfo=UTC)
        start, end, period = previous_month(now)
        self.assertEqual(start, datetime(2026, 6, 1, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 7, 1, tzinfo=UTC))
        self.assertEqual(period, "2026-06")

    def test_handles_year_boundary(self):
        now = datetime(2026, 1, 3, tzinfo=UTC)
        start, end, period = previous_month(now)
        self.assertEqual(period, "2025-12")
        self.assertEqual(start, datetime(2025, 12, 1, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 1, 1, tzinfo=UTC))


class MonthlyReportSchedulerTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.workspace = Workspace.objects.create(organization=self.org, name="Client A")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="ig-1",
            account_name="Client A IG",
        )
        # First of the current month → the scheduled task's active day.
        self.run_now = timezone.now().replace(day=1, hour=12, minute=0, second=0, microsecond=0)
        self.start, self.end, self.period = previous_month(self.run_now)
        self.pub_dt = self.start + timedelta(days=3)

        # Two published posts in the previous month.
        for title in ("Launch", "Recap"):
            post = Post.objects.create(workspace=self.workspace, title=title, published_at=self.pub_dt)
            PlatformPost.objects.create(
                post=post,
                social_account=self.account,
                status=PlatformPost.Status.PUBLISHED,
                published_at=self.pub_dt,
            )

        self.owner = self._member("owner@acme.test", WorkspaceMembership.WorkspaceRole.OWNER)
        self.manager = self._member("manager@acme.test", WorkspaceMembership.WorkspaceRole.MANAGER)
        self.editor = self._member("editor@acme.test", WorkspaceMembership.WorkspaceRole.EDITOR)
        self.client_user = self._member("client@acme.test", WorkspaceMembership.WorkspaceRole.CLIENT)

    def _member(self, email, role):
        user = User.objects.create_user(email=email, password="x")
        WorkspaceMembership.objects.create(user=user, workspace=self.workspace, workspace_role=role)
        return user

    def _report_notifs(self, user):
        return Notification.objects.filter(user=user, event_type=EventType.REPORT_GENERATED)

    def test_recipients_are_owner_and_manager_only(self):
        users = report_recipients(self.workspace)
        self.assertCountEqual(users, [self.owner, self.manager])

    def test_delivers_to_operators_on_first_of_month(self):
        summary = run_monthly_reports(now=self.run_now)  # day == 1, no force needed

        self.assertFalse(summary.get("skipped"))
        self.assertEqual(summary["period"], self.period)
        self.assertEqual(summary["notified"], 2)

        for user in (self.owner, self.manager):
            notif = self._report_notifs(user).get()
            self.assertEqual(notif.data["period"], self.period)
            self.assertEqual(notif.data["workspace_id"], str(self.workspace.id))
            self.assertIn("2 posts published", notif.body)
        for user in (self.editor, self.client_user):
            self.assertFalse(self._report_notifs(user).exists())

    def test_is_idempotent_across_reruns(self):
        run_monthly_reports(now=self.run_now)
        second = run_monthly_reports(now=self.run_now)
        self.assertEqual(second["notified"], 0)
        self.assertEqual(self._report_notifs(self.owner).count(), 1)

    def test_skips_when_not_first_of_month(self):
        not_first = self.run_now.replace(day=15)
        summary = run_monthly_reports(now=not_first)
        self.assertTrue(summary["skipped"])
        self.assertEqual(summary["notified"], 0)
        self.assertFalse(self._report_notifs(self.owner).exists())

    def test_force_runs_on_any_day(self):
        not_first = self.run_now.replace(day=15)
        summary = run_monthly_reports(now=not_first, force=True)
        self.assertEqual(summary["notified"], 2)

    def test_skips_workspace_with_no_activity(self):
        quiet = Workspace.objects.create(organization=self.org, name="Quiet")
        quiet_owner = User.objects.create_user(email="q@acme.test", password="x")
        WorkspaceMembership.objects.create(
            user=quiet_owner,
            workspace=quiet,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        sent = deliver_workspace_report(quiet, self.start, self.end, self.period)
        self.assertEqual(sent, 0)
        self.assertFalse(self._report_notifs(quiet_owner).exists())
