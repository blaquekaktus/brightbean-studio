"""Tests for the client-portal reports surface.

The security boundary under test: a portal session can only read its own
workspace's reports (scoped to ``request.portal_workspace``).
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import WorkspaceMembership
from apps.organizations.models import Organization
from apps.publisher.models import WorkspaceReport
from apps.workspaces.models import Workspace


class PortalReportsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.workspace = Workspace.objects.create(organization=self.org, name="Client A")
        self.user = User.objects.create_user(email="client@acme.test", password="x", tos_accepted_at=timezone.now())
        WorkspaceMembership.objects.create(
            user=self.user,
            workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT,
        )
        self.report = WorkspaceReport.objects.create(
            workspace=self.workspace,
            period="2026-06",
            html="<!DOCTYPE html><html><body>Client A June report</body></html>",
            total_posts=4,
            total_platform_posts=7,
        )
        # A different workspace + report the session must NOT be able to read.
        self.other_ws = Workspace.objects.create(organization=self.org, name="Client B")
        self.other_report = WorkspaceReport.objects.create(
            workspace=self.other_ws,
            period="2026-05",
            html="<!DOCTYPE html><html><body>SECRET Client B report</body></html>",
            total_posts=9,
            total_platform_posts=9,
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["is_portal_session"] = True
        session["portal_workspace_id"] = str(self.workspace.id)
        session.save()

    def test_reports_list_shows_own_workspace_reports(self):
        resp = self.client.get(reverse("client_portal:reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "2026-06")
        self.assertNotContains(resp, "2026-05")  # other workspace's period

    def test_report_detail_serves_own_report_html(self):
        resp = self.client.get(reverse("client_portal:report_detail", args=["2026-06"]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Client A June report", resp.content)

    def test_report_detail_is_scoped_to_session_workspace(self):
        # The period exists, but belongs to another workspace → must 404, never leak.
        resp = self.client.get(reverse("client_portal:report_detail", args=["2026-05"]))
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(WorkspaceReport.objects.none())  # sanity: report does exist elsewhere
        self.assertEqual(WorkspaceReport.objects.get(period="2026-05").workspace, self.other_ws)

    def test_unauthenticated_session_is_redirected(self):
        self.client.logout()
        resp = self.client.get(reverse("client_portal:report_detail", args=["2026-06"]))
        self.assertEqual(resp.status_code, 302)
