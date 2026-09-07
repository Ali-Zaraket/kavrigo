"""Role and permission matrix, and the MFA gate on high-impact actions."""

from __future__ import annotations

import pytest

from kavrigo_api.auth.principal import (
    MFA_REQUIRED_PERMISSIONS,
    ROLE_PERMISSIONS,
    Permission,
    Principal,
    Role,
    WorkspaceContext,
)


def _context(role: Role, *, mfa: bool = False) -> WorkspaceContext:
    return WorkspaceContext(
        principal=Principal(user_id=f"usr_{0:032x}", external_id="user_ext_1", mfa_verified=mfa),
        workspace_id=f"ws_{0:032x}",
        role=role,
    )


class TestRoleHierarchy:
    def test_permissions_are_strictly_nested(self) -> None:
        """A more privileged role can do everything a less privileged one can."""
        assert ROLE_PERMISSIONS[Role.VIEWER] < ROLE_PERMISSIONS[Role.MEMBER]
        assert ROLE_PERMISSIONS[Role.MEMBER] < ROLE_PERMISSIONS[Role.ADMIN]
        assert ROLE_PERMISSIONS[Role.ADMIN] < ROLE_PERMISSIONS[Role.OWNER]

    def test_every_role_is_in_the_matrix(self) -> None:
        assert set(ROLE_PERMISSIONS) == set(Role)

    def test_viewers_cannot_write_anything(self) -> None:
        viewer = _context(Role.VIEWER, mfa=True)
        for permission in Permission:
            if permission.value.split(":")[1] in {"read"}:
                continue
            assert not viewer.has(permission), f"viewer should not have {permission}"

    def test_members_can_manage_agents_but_not_the_workspace(self) -> None:
        member = _context(Role.MEMBER, mfa=True)
        assert member.has(Permission.AGENT_CREATE)
        assert member.has(Permission.AGENT_UPDATE)
        assert not member.has(Permission.MEMBER_INVITE)
        assert not member.has(Permission.WORKSPACE_UPDATE)
        assert not member.has(Permission.RISK_POLICY_WRITE)

    def test_only_owners_can_delete_a_workspace(self) -> None:
        assert _context(Role.OWNER, mfa=True).has(Permission.WORKSPACE_DELETE)
        assert not _context(Role.ADMIN, mfa=True).has(Permission.WORKSPACE_DELETE)


class TestMfaGate:
    """``MASTER_BUILD_SPEC.md`` §21: role alone is not enough for high-impact actions."""

    @pytest.mark.parametrize("permission", sorted(MFA_REQUIRED_PERMISSIONS))
    def test_high_impact_actions_need_a_second_factor(self, permission: Permission) -> None:
        without = _context(Role.OWNER, mfa=False)
        assert not without.has(permission)
        assert without.missing_mfa_for(permission)

        with_mfa = _context(Role.OWNER, mfa=True)
        assert with_mfa.has(permission)
        assert not with_mfa.missing_mfa_for(permission)

    def test_exchange_credential_writes_are_mfa_gated(self) -> None:
        """A stolen session must not be able to attach an exchange account."""
        assert Permission.EXCHANGE_CONNECTION_WRITE in MFA_REQUIRED_PERMISSIONS

    def test_risk_policy_writes_are_mfa_gated(self) -> None:
        """Relaxing risk limits is as sensitive as adding a credential."""
        assert Permission.RISK_POLICY_WRITE in MFA_REQUIRED_PERMISSIONS

    def test_missing_mfa_is_distinguished_from_a_plain_denial(self) -> None:
        """A viewer is denied because of role, not MFA — the client must not prompt to re-auth."""
        viewer = _context(Role.VIEWER, mfa=False)
        assert not viewer.has(Permission.RISK_POLICY_WRITE)
        assert not viewer.missing_mfa_for(Permission.RISK_POLICY_WRITE)

    def test_mfa_does_not_grant_permissions_the_role_lacks(self) -> None:
        viewer = _context(Role.VIEWER, mfa=True)
        assert not viewer.has(Permission.AGENT_CREATE)


def test_ordinary_reads_are_not_mfa_gated() -> None:
    """Requiring a second factor to read would push users to disable MFA, not adopt it."""
    for permission in (Permission.AGENT_READ, Permission.WORKSPACE_READ, Permission.RUN_READ):
        assert permission not in MFA_REQUIRED_PERMISSIONS
