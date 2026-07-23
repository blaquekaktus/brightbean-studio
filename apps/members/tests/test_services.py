"""Tests for the org-membership / invitation lifecycle service layer.

apps/members is the multi-tenant boundary: it decides who joins an org, at
what role, and enforces the invariants that keep tenants isolated and prevent
privilege escalation (email-match on accept, no inviting/promoting to owner,
last-owner protection, workspace-belongs-to-org checks). This layer had no
tests. The invite email is patched out — these assert the security logic, not
template rendering.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.members import services
from apps.members.models import Invitation, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    """Patch the invite email so tests exercise logic, not SMTP/templates."""
    monkeypatch.setattr(services, "_send_invite_email", lambda invitation: None)


@pytest.fixture
def workspace(organization):
    return Workspace.objects.create(organization=organization, name="Main Workspace")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Org")


# ── create_invitation ────────────────────────────────────────────────────
class TestCreateInvitation:
    def test_creates_pending_invitation_and_normalizes_email(self, organization, org_owner):
        inv = services.create_invitation(
            organization, "  New.Person@Example.com ", OrgMembership.OrgRole.MEMBER, [], org_owner
        )
        assert inv.email == "new.person@example.com"
        assert inv.org_role == OrgMembership.OrgRole.MEMBER
        assert inv.expires_at > timezone.now()
        assert inv.accepted_at is None

    def test_rejects_existing_member(self, organization, org_owner):
        # org_owner is already a member (test@example.com)
        with pytest.raises(ValueError, match="already a member"):
            services.create_invitation(organization, "test@example.com", OrgMembership.OrgRole.MEMBER, [], org_owner)

    def test_rejects_duplicate_pending_invite(self, organization, org_owner):
        services.create_invitation(organization, "dup@example.com", OrgMembership.OrgRole.MEMBER, [], org_owner)
        with pytest.raises(ValueError, match="already pending"):
            services.create_invitation(organization, "dup@example.com", OrgMembership.OrgRole.MEMBER, [], org_owner)

    def test_cannot_invite_as_owner(self, organization, org_owner):
        with pytest.raises(ValueError, match="owner"):
            services.create_invitation(organization, "wannabe@example.com", OrgMembership.OrgRole.OWNER, [], org_owner)

    def test_rejects_workspace_from_another_org(self, organization, org_owner, other_org):
        foreign_ws = Workspace.objects.create(organization=other_org, name="Foreign")
        with pytest.raises(ValueError, match="does not belong"):
            services.create_invitation(
                organization,
                "x@example.com",
                OrgMembership.OrgRole.MEMBER,
                [{"workspace_id": str(foreign_ws.id), "role": "editor"}],
                org_owner,
            )


# ── accept_invitation ────────────────────────────────────────────────────
class TestAcceptInvitation:
    def _make_invite(self, organization, org_owner, email, assignments=None):
        return services.create_invitation(
            organization, email, OrgMembership.OrgRole.MEMBER, assignments or [], org_owner
        )

    def test_accept_creates_org_and_workspace_membership(self, organization, org_owner, workspace, django_user_model):
        invitee = django_user_model.objects.create_user(email="invitee@example.com", password="x")
        inv = self._make_invite(
            organization,
            org_owner,
            "invitee@example.com",
            [{"workspace_id": str(workspace.id), "role": WorkspaceMembership.WorkspaceRole.EDITOR}],
        )
        services.accept_invitation(inv, invitee)

        assert OrgMembership.objects.filter(user=invitee, organization=organization).exists()
        wm = WorkspaceMembership.objects.get(user=invitee, workspace=workspace)
        assert wm.workspace_role == WorkspaceMembership.WorkspaceRole.EDITOR
        inv.refresh_from_db()
        assert inv.is_accepted
        invitee.refresh_from_db()
        assert invitee.last_workspace_id == workspace.id

    def test_rejects_email_mismatch(self, organization, org_owner, django_user_model):
        """Security: an invite for one email must not be redeemable by another."""
        inv = self._make_invite(organization, org_owner, "intended@example.com")
        attacker = django_user_model.objects.create_user(email="attacker@example.com", password="x")
        with pytest.raises(ValueError, match="different email"):
            services.accept_invitation(inv, attacker)
        assert not OrgMembership.objects.filter(user=attacker, organization=organization).exists()

    def test_rejects_expired_invitation(self, organization, org_owner, django_user_model):
        inv = self._make_invite(organization, org_owner, "late@example.com")
        Invitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now() - timedelta(days=1))
        inv.refresh_from_db()
        invitee = django_user_model.objects.create_user(email="late@example.com", password="x")
        with pytest.raises(ValueError, match="expired"):
            services.accept_invitation(inv, invitee)

    def test_rejects_already_accepted(self, organization, org_owner, django_user_model):
        inv = self._make_invite(organization, org_owner, "twice@example.com")
        invitee = django_user_model.objects.create_user(email="twice@example.com", password="x")
        services.accept_invitation(inv, invitee)
        with pytest.raises(ValueError, match="already been accepted"):
            services.accept_invitation(inv, invitee)


# ── resend / revoke ──────────────────────────────────────────────────────
class TestResendRevoke:
    def test_resend_rotates_token_and_extends_expiry(self, organization, org_owner):
        inv = services.create_invitation(organization, "r@example.com", OrgMembership.OrgRole.MEMBER, [], org_owner)
        old_token, old_expiry = inv.token, inv.expires_at
        Invitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now() + timedelta(days=1))
        inv.refresh_from_db()
        services.resend_invitation(inv)
        assert inv.token != old_token
        assert inv.expires_at > old_expiry

    def test_revoke_expires_immediately(self, organization, org_owner):
        inv = services.create_invitation(organization, "rev@example.com", OrgMembership.OrgRole.MEMBER, [], org_owner)
        services.revoke_invitation(inv)
        assert inv.expires_at <= timezone.now()
        assert inv.is_expired

    def test_cannot_revoke_accepted(self, organization, org_owner, django_user_model):
        inv = services.create_invitation(organization, "acc@example.com", OrgMembership.OrgRole.MEMBER, [], org_owner)
        invitee = django_user_model.objects.create_user(email="acc@example.com", password="x")
        services.accept_invitation(inv, invitee)
        with pytest.raises(ValueError, match="already accepted"):
            services.revoke_invitation(inv)


# ── remove_member / role changes ─────────────────────────────────────────
class TestMembershipChanges:
    def _add_member(self, organization, django_user_model, email, role=OrgMembership.OrgRole.MEMBER):
        u = django_user_model.objects.create_user(email=email, password="x")
        m = OrgMembership.objects.create(user=u, organization=organization, org_role=role)
        return u, m

    def test_cannot_remove_self(self, organization, org_owner):
        own_membership = OrgMembership.objects.get(user=org_owner, organization=organization)
        with pytest.raises(ValueError, match="cannot remove yourself"):
            services.remove_member(organization, own_membership, org_owner)

    def test_cannot_remove_last_owner(self, organization, org_owner, django_user_model):
        remover, _ = self._add_member(organization, django_user_model, "admin@example.com", OrgMembership.OrgRole.ADMIN)
        owner_membership = OrgMembership.objects.get(user=org_owner, organization=organization)
        with pytest.raises(ValueError, match="last organization owner"):
            services.remove_member(organization, owner_membership, remover)

    def test_remove_member_deletes_workspace_memberships(self, organization, org_owner, workspace, django_user_model):
        member, membership = self._add_member(organization, django_user_model, "m@example.com")
        WorkspaceMembership.objects.create(user=member, workspace=workspace)
        services.remove_member(organization, membership, org_owner)
        assert not OrgMembership.objects.filter(pk=membership.pk).exists()
        assert not WorkspaceMembership.objects.filter(user=member, workspace=workspace).exists()

    def test_cannot_promote_to_owner(self, organization, org_owner, django_user_model):
        _, membership = self._add_member(organization, django_user_model, "m2@example.com")
        with pytest.raises(ValueError, match="Transfer ownership"):
            services.update_member_org_role(organization, membership, OrgMembership.OrgRole.OWNER)

    def test_cannot_demote_last_owner(self, organization, org_owner):
        owner_membership = OrgMembership.objects.get(user=org_owner, organization=organization)
        with pytest.raises(ValueError, match="last organization owner"):
            services.update_member_org_role(organization, owner_membership, OrgMembership.OrgRole.ADMIN)

    def test_update_role_succeeds_for_non_owner(self, organization, org_owner, django_user_model):
        _, membership = self._add_member(organization, django_user_model, "m3@example.com")
        services.update_member_org_role(organization, membership, OrgMembership.OrgRole.ADMIN)
        membership.refresh_from_db()
        assert membership.org_role == OrgMembership.OrgRole.ADMIN


# ── update_workspace_assignments ─────────────────────────────────────────
class TestWorkspaceAssignments:
    def test_rejects_workspace_from_another_org(self, organization, other_org, django_user_model):
        member = django_user_model.objects.create_user(email="wa@example.com", password="x")
        foreign_ws = Workspace.objects.create(organization=other_org, name="Foreign")
        with pytest.raises(ValueError, match="does not belong"):
            services.update_workspace_assignments(
                organization, member, [{"workspace_id": str(foreign_ws.id), "role": "editor"}]
            )

    def test_syncs_add_update_and_remove(self, organization, django_user_model):
        member = django_user_model.objects.create_user(email="sync@example.com", password="x")
        ws_a = Workspace.objects.create(organization=organization, name="A")
        ws_b = Workspace.objects.create(organization=organization, name="B")

        # Start with A=editor
        services.update_workspace_assignments(organization, member, [{"workspace_id": str(ws_a.id), "role": "editor"}])
        assert WorkspaceMembership.objects.get(user=member, workspace=ws_a).workspace_role == "editor"

        # Change A→viewer, add B=manager, (implicitly) A stays; then drop A entirely
        services.update_workspace_assignments(
            organization,
            member,
            [
                {"workspace_id": str(ws_a.id), "role": "viewer"},
                {"workspace_id": str(ws_b.id), "role": "manager"},
            ],
        )
        assert WorkspaceMembership.objects.get(user=member, workspace=ws_a).workspace_role == "viewer"
        assert WorkspaceMembership.objects.get(user=member, workspace=ws_b).workspace_role == "manager"

        # Remove A by omitting it
        services.update_workspace_assignments(organization, member, [{"workspace_id": str(ws_b.id), "role": "manager"}])
        assert not WorkspaceMembership.objects.filter(user=member, workspace=ws_a).exists()
        assert WorkspaceMembership.objects.filter(user=member, workspace=ws_b).exists()


# ── effective_permissions (RBAC mapping) ─────────────────────────────────
class TestEffectivePermissions:
    def test_builtin_role_maps_to_permission_set(self, organization, workspace, django_user_model):
        u = django_user_model.objects.create_user(email="perm@example.com", password="x")
        wm = WorkspaceMembership.objects.create(
            user=u, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.VIEWER
        )
        perms = wm.effective_permissions
        assert perms["view_analytics"] is True
        assert perms["create_posts"] is False
        assert perms["publish_directly"] is False

    def test_custom_role_overrides_builtin(self, organization, workspace, django_user_model):
        from apps.members.models import CustomRole

        role = CustomRole.objects.create(
            organization=organization, name="Auditor", permissions={"view_analytics": True, "create_posts": False}
        )
        u = django_user_model.objects.create_user(email="cr@example.com", password="x")
        wm = WorkspaceMembership.objects.create(
            user=u, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER, custom_role=role
        )
        # custom_role takes precedence over the (otherwise all-True) owner builtin
        assert wm.effective_permissions == {"view_analytics": True, "create_posts": False}
        assert "delete_media" not in wm.effective_permissions
