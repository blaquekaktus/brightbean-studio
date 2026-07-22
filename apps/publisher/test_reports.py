"""Tests for the white-label workspace publishing report."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.publisher.reports import build_report_data, render_report_html
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class WorkspaceReportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.workspace = Workspace.objects.create(
            organization=self.org,
            name="Client A",
            primary_color="#0EA5E9",
            secondary_color="#F59E0B",
        )
        self.ig = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="ig-1",
            account_name="Client A IG",
        )
        self.li = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="linkedin",
            account_platform_id="li-1",
            account_name="Client A LI",
        )
        self.now = timezone.now()
        self.start = self.now - timedelta(days=30)
        self.end = self.now + timedelta(days=1)

    def _post(self, title, published_at):
        return Post.objects.create(workspace=self.workspace, title=title, published_at=published_at)

    def _platform_post(self, post, account, status, published_at):
        return PlatformPost.objects.create(post=post, social_account=account, status=status, published_at=published_at)

    def test_aggregates_published_in_range_by_platform(self):
        in_range = self.now - timedelta(days=2)
        p1 = self._post("Launch day", in_range)
        self._platform_post(p1, self.ig, PlatformPost.Status.PUBLISHED, in_range)
        self._platform_post(p1, self.li, PlatformPost.Status.PUBLISHED, in_range)
        p2 = self._post("Follow-up", in_range)
        self._platform_post(p2, self.ig, PlatformPost.Status.PUBLISHED, in_range)

        report = build_report_data(self.workspace, self.start, self.end)

        self.assertEqual(report["total_posts"], 2)
        self.assertEqual(report["total_platform_posts"], 3)
        by_platform = {r["platform"]: r["count"] for r in report["by_platform"]}
        self.assertEqual(by_platform, {"instagram": 2, "linkedin": 1})

    def test_excludes_out_of_range_and_unpublished(self):
        old = self.now - timedelta(days=90)
        p_old = self._post("Ancient", old)
        self._platform_post(p_old, self.ig, PlatformPost.Status.PUBLISHED, old)

        draft = self._post("Draft", None)
        self._platform_post(draft, self.ig, PlatformPost.Status.DRAFT, None)

        scheduled = self._post("Scheduled", None)
        self._platform_post(scheduled, self.ig, PlatformPost.Status.SCHEDULED, self.now - timedelta(days=1))

        report = build_report_data(self.workspace, self.start, self.end)
        self.assertEqual(report["total_posts"], 0)
        self.assertEqual(report["by_platform"], [])

    def test_isolated_by_workspace(self):
        other_ws = Workspace.objects.create(organization=self.org, name="Client B")
        other_acct = SocialAccount.objects.create(
            workspace=other_ws,
            platform="instagram",
            account_platform_id="ig-2",
            account_name="B",
        )
        recent = self.now - timedelta(days=1)
        p = Post.objects.create(workspace=other_ws, title="B post", published_at=recent)
        self._platform_post(p, other_acct, PlatformPost.Status.PUBLISHED, recent)

        report = build_report_data(self.workspace, self.start, self.end)
        self.assertEqual(report["total_posts"], 0)

    def test_render_is_white_labeled_and_escapes(self):
        in_range = self.now - timedelta(days=1)
        p = self._post("Q3 <recap> & wins", in_range)
        self._platform_post(p, self.ig, PlatformPost.Status.PUBLISHED, in_range)

        report = build_report_data(self.workspace, self.start, self.end)
        html = render_report_html(report, self.workspace)

        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("Client A", html)  # white-label workspace name
        self.assertIn("#0EA5E9", html)  # workspace primary colour
        self.assertIn("#F59E0B", html)  # workspace secondary colour
        self.assertIn("Q3 &lt;recap&gt; &amp; wins", html)  # escaped title
        self.assertNotIn("<recap>", html)

    def test_render_falls_back_when_colors_blank(self):
        ws = Workspace.objects.create(organization=self.org, name="Naked")
        report = build_report_data(ws, self.start, self.end)
        html = render_report_html(report, ws)
        self.assertIn("#1F2937", html)  # fallback primary
        self.assertIn("No posts published", html)

    def test_render_is_deterministic(self):
        report = build_report_data(self.workspace, self.start, self.end)
        self.assertEqual(
            render_report_html(report, self.workspace),
            render_report_html(report, self.workspace),
        )
