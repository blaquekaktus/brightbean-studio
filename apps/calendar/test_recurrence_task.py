"""Tests for the recurring-posts generator (the durable publish cadence).

Covers the generation logic directly (``_generate_recurring_posts``); the
``@background`` wrapper + daily registration is thin glue over it.
"""

from django.test import TestCase
from django.utils import timezone

from apps.calendar.models import RecurrenceRule
from apps.calendar.tasks import _generate_recurring_posts
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class RecurringPostsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.workspace = Workspace.objects.create(organization=self.org, name="Client A")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="ig-1",
            account_name="Client A IG",
        )
        # Source post scheduled today → weekly occurrences land within 90 days.
        self.source = Post.objects.create(
            workspace=self.workspace,
            caption="Weekly carousel tip",
            scheduled_at=timezone.now(),
        )
        PlatformPost.objects.create(
            post=self.source,
            social_account=self.account,
            status=PlatformPost.Status.SCHEDULED,
            scheduled_at=self.source.scheduled_at,
        )
        self.rule = RecurrenceRule.objects.create(
            post=self.source,
            frequency=RecurrenceRule.Frequency.WEEKLY,
            interval=1,
        )

    def _clones(self):
        return Post.objects.filter(workspace=self.workspace, caption="Weekly carousel tip").exclude(id=self.source.id)

    def test_generates_scheduled_occurrences(self):
        count = _generate_recurring_posts()

        clones = self._clones()
        self.assertGreater(count, 0)
        self.assertEqual(clones.count(), count)
        # Weekly for 90 days → roughly a dozen, all in the future.
        self.assertGreaterEqual(clones.count(), 10)
        for clone in clones:
            self.assertGreater(clone.scheduled_at, timezone.now())
            pp = clone.platform_posts.get()
            self.assertEqual(pp.status, "scheduled")
            self.assertEqual(pp.social_account, self.account)

    def test_is_idempotent(self):
        first = _generate_recurring_posts()
        before = self._clones().count()
        second = _generate_recurring_posts()
        self.assertEqual(second, 0)
        self.assertEqual(self._clones().count(), before)
        self.assertEqual(first, before)

    def test_records_last_generated_at(self):
        self.assertIsNone(self.rule.last_generated_at)
        _generate_recurring_posts()
        self.rule.refresh_from_db()
        self.assertIsNotNone(self.rule.last_generated_at)

    def test_skips_inactive_rules(self):
        self.rule.is_active = False
        self.rule.save(update_fields=["is_active"])
        count = _generate_recurring_posts()
        self.assertEqual(count, 0)
        self.assertEqual(self._clones().count(), 0)

    def test_skips_rule_without_scheduled_source(self):
        self.source.scheduled_at = None
        self.source.save(update_fields=["scheduled_at"])
        count = _generate_recurring_posts()
        self.assertEqual(count, 0)
