"""Unit tests for the Generator class with a mocked DirectusClient.

Tests cover:
- Basic generation with known collections, roles, policies, permissions
- System collection filtering (exclude directus_* by default)
- Orphan permission handling (unknown policy IDs skipped)
- Empty permissions list produces empty config
- All-system-collections with include_system=False produces empty config
- Action mapping for all 4 Directus actions

Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1–4.9
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from directus_ac.generate import Generator, REVERSE_ACTION_MAP
from directus_ac.models import (
    DirectusACConfig,
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
    PermissionKeyword,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(
    collections: list[DirectusCollection],
    roles: list[DirectusRole],
    permissions: list[DirectusPermission],
    policies: list[DirectusPolicy] | None = None,
) -> MagicMock:
    """Create a mock DirectusClient with configured return values.

    If policies is None, auto-generates a policy for each role (1:1 mapping).
    """
    if policies is None:
        # Auto-generate policies: one policy per role, linked to that role
        policies = [
            DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
            for role in roles
        ]
    client = MagicMock()
    client.get_collections.return_value = collections
    client.get_roles.return_value = roles
    client.get_permissions.return_value = permissions
    client.get_policies.return_value = policies
    return client


def _perm(id: int, role_id: str, collection: str, action: str) -> DirectusPermission:
    """Create a DirectusPermission with policy derived from role_id.

    In v11, permissions reference policies, not roles directly.
    This helper uses the convention policy_id = "policy-{role_id}".
    """
    return DirectusPermission(id=id, policy=f"policy-{role_id}", collection=collection, action=action)


# ---------------------------------------------------------------------------
# Test: Basic generation with known collections, roles, permissions
# ---------------------------------------------------------------------------


class TestBasicGeneration:
    """Test basic generation with known collections, roles, and permissions."""

    def test_single_collection_single_role_single_permission(self):
        """A single permission produces a config with one collection, one role, one group."""
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="role-1", name="Editor")]
        permissions = [
            _perm(1, "role-1", "articles", "read")
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == ["articles"]
        assert config.roles == ["Editor"]
        assert len(config.groups) == 1
        assert config.groups[0].collections == ["articles"]
        assert config.groups[0].permissions == {"Editor": [PermissionKeyword.READ]}

    def test_multiple_collections_multiple_roles(self):
        """Multiple collections and roles produce correct grouping."""
        collections = [
            DirectusCollection(collection="articles"),
            DirectusCollection(collection="comments"),
        ]
        roles = [
            DirectusRole(id="role-1", name="Editor"),
            DirectusRole(id="role-2", name="Viewer"),
        ]
        permissions = [
            _perm(1, "role-1", "articles", "read"),
            _perm(2, "role-1", "articles", "create"),
            _perm(3, "role-2", "articles", "read"),
            _perm(4, "role-1", "comments", "read"),
            _perm(5, "role-2", "comments", "read"),
            _perm(6, "role-2", "comments", "delete"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert sorted(config.collections) == ["articles", "comments"]
        assert sorted(config.roles) == ["Editor", "Viewer"]
        assert len(config.groups) == 2

        # Find groups by collection name
        groups_by_col = {g.collections[0]: g for g in config.groups}

        # articles group: Editor has READ+WRITE, Viewer has READ
        articles_group = groups_by_col["articles"]
        assert set(articles_group.permissions["Editor"]) == {
            PermissionKeyword.READ,
            PermissionKeyword.WRITE,
        }
        assert articles_group.permissions["Viewer"] == [PermissionKeyword.READ]

        # comments group: Editor has READ, Viewer has READ+DELETE
        comments_group = groups_by_col["comments"]
        assert comments_group.permissions["Editor"] == [PermissionKeyword.READ]
        assert set(comments_group.permissions["Viewer"]) == {
            PermissionKeyword.READ,
            PermissionKeyword.DELETE,
        }

    def test_all_four_actions_combined(self):
        """A role with all 4 actions on a collection gets all keywords."""
        collections = [DirectusCollection(collection="products")]
        roles = [DirectusRole(id="role-1", name="Admin")]
        permissions = [
            _perm(1, "role-1", "products", "read"),
            _perm(2, "role-1", "products", "create"),
            _perm(3, "role-1", "products", "update"),
            _perm(4, "role-1", "products", "delete"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == ["products"]
        assert config.roles == ["Admin"]
        assert len(config.groups) == 1
        assert set(config.groups[0].permissions["Admin"]) == {
            PermissionKeyword.READ,
            PermissionKeyword.WRITE,
            PermissionKeyword.UPDATE,
            PermissionKeyword.DELETE,
        }

    def test_client_methods_called(self):
        """Generator calls get_collections, get_roles, get_policies, get_permissions on the client."""
        client = _mock_client([], [], [])
        generator = Generator(client, include_system=False)
        generator.generate()

        client.get_collections.assert_called_once()
        client.get_roles.assert_called_once()
        client.get_policies.assert_called_once()
        client.get_permissions.assert_called_once()


# ---------------------------------------------------------------------------
# Test: System collection filtering
# ---------------------------------------------------------------------------


class TestSystemCollectionFiltering:
    """Test that system collections (directus_*) are excluded by default."""

    def test_exclude_system_collections_by_default(self):
        """With include_system=False, directus_* collections are excluded."""
        collections = [
            DirectusCollection(collection="articles"),
            DirectusCollection(collection="directus_users"),
            DirectusCollection(collection="directus_files"),
        ]
        roles = [DirectusRole(id="role-1", name="Editor")]
        permissions = [
            _perm(1, "role-1", "articles", "read"),
            _perm(2, "role-1", "directus_users", "read"),
            _perm(3, "role-1", "directus_files", "read"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == ["articles"]
        assert "directus_users" not in config.collections
        assert "directus_files" not in config.collections
        # Only one group for "articles"
        assert len(config.groups) == 1
        assert config.groups[0].collections == ["articles"]

    def test_include_system_collections_when_flag_set(self):
        """With include_system=True, directus_* collections are included."""
        collections = [
            DirectusCollection(collection="articles"),
            DirectusCollection(collection="directus_users"),
        ]
        roles = [DirectusRole(id="role-1", name="Editor")]
        permissions = [
            _perm(1, "role-1", "articles", "read"),
            _perm(2, "role-1", "directus_users", "read"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=True)
        config = generator.generate()

        assert sorted(config.collections) == ["articles", "directus_users"]
        assert len(config.groups) == 2

    def test_permissions_on_excluded_system_collections_skipped(self):
        """Permissions referencing excluded system collections are not in output."""
        collections = [
            DirectusCollection(collection="articles"),
            DirectusCollection(collection="directus_activity"),
        ]
        roles = [DirectusRole(id="role-1", name="Admin")]
        permissions = [
            _perm(1, "role-1", "articles", "read"),
            _perm(2, "role-1", "directus_activity", "read"),
            _perm(3, "role-1", "directus_activity", "create"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        # Only articles should appear
        assert config.collections == ["articles"]
        for group in config.groups:
            for col in group.collections:
                assert not col.startswith("directus_")


# ---------------------------------------------------------------------------
# Test: Orphan permission handling (unknown policy IDs)
# ---------------------------------------------------------------------------


class TestOrphanPermissionHandling:
    """Test that permissions referencing unknown policy IDs are skipped."""

    def test_orphan_permissions_skipped(self):
        """Permissions with policy IDs not linked to any known role are excluded."""
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="role-1", name="Editor")]
        policies = [
            DirectusPolicy(id="policy-role-1", name="Editor Policy", roles=["role-1"]),
        ]
        permissions = [
            DirectusPermission(id=1, policy="policy-role-1", collection="articles", action="read"),
            DirectusPermission(id=2, policy="unknown-policy", collection="articles", action="create"),
            DirectusPermission(id=3, policy="another-unknown", collection="articles", action="delete"),
        ]

        client = _mock_client(collections, roles, permissions, policies=policies)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        # Only the valid permission should be in the output
        assert config.collections == ["articles"]
        assert config.roles == ["Editor"]
        assert len(config.groups) == 1
        assert config.groups[0].permissions == {"Editor": [PermissionKeyword.READ]}

    def test_all_orphan_permissions_produces_empty_config(self):
        """If all permissions reference unknown policies, the config is empty."""
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="role-1", name="Editor")]
        policies = [
            DirectusPolicy(id="policy-role-1", name="Editor Policy", roles=["role-1"]),
        ]
        permissions = [
            DirectusPermission(id=1, policy="unknown-1", collection="articles", action="read"),
            DirectusPermission(id=2, policy="unknown-2", collection="articles", action="create"),
        ]

        client = _mock_client(collections, roles, permissions, policies=policies)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == []
        assert config.roles == []
        assert config.groups == []

    def test_orphan_policy_ids_not_in_output(self):
        """Orphan policy IDs do not appear anywhere in the generated config."""
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="role-1", name="Editor")]
        policies = [
            DirectusPolicy(id="policy-role-1", name="Editor Policy", roles=["role-1"]),
        ]
        permissions = [
            DirectusPermission(id=1, policy="policy-role-1", collection="articles", action="read"),
            DirectusPermission(id=2, policy="orphan-policy", collection="articles", action="create"),
        ]

        client = _mock_client(collections, roles, permissions, policies=policies)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        # orphan-policy should not appear in roles or group permissions
        assert "orphan-policy" not in config.roles
        for group in config.groups:
            assert "orphan-policy" not in group.permissions


# ---------------------------------------------------------------------------
# Test: Empty permissions list produces empty config
# ---------------------------------------------------------------------------


class TestEmptyPermissions:
    """Test that an empty permissions list produces an empty config."""

    def test_no_permissions_produces_empty_config(self):
        """With no permissions, the config has empty collections, roles, and groups."""
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="role-1", name="Editor")]
        permissions: list[DirectusPermission] = []

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == []
        assert config.roles == []
        assert config.groups == []

    def test_no_collections_no_roles_no_permissions(self):
        """Completely empty Directus state produces empty config."""
        client = _mock_client([], [], [], policies=[])
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == []
        assert config.roles == []
        assert config.groups == []


# ---------------------------------------------------------------------------
# Test: All system collections with include_system=False produces empty config
# ---------------------------------------------------------------------------


class TestAllSystemCollections:
    """Test that all-system-collections with include_system=False produces empty config."""

    def test_only_system_collections_produces_empty_config(self):
        """When all collections are system collections and include_system=False, config is empty."""
        collections = [
            DirectusCollection(collection="directus_users"),
            DirectusCollection(collection="directus_files"),
            DirectusCollection(collection="directus_activity"),
        ]
        roles = [DirectusRole(id="role-1", name="Admin")]
        permissions = [
            _perm(1, "role-1", "directus_users", "read"),
            _perm(2, "role-1", "directus_files", "create"),
            _perm(3, "role-1", "directus_activity", "update"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=False)
        config = generator.generate()

        assert config.collections == []
        assert config.roles == []
        assert config.groups == []

    def test_system_collections_included_when_flag_set(self):
        """When all collections are system and include_system=True, they appear in output."""
        collections = [
            DirectusCollection(collection="directus_users"),
            DirectusCollection(collection="directus_files"),
        ]
        roles = [DirectusRole(id="role-1", name="Admin")]
        permissions = [
            _perm(1, "role-1", "directus_users", "read"),
            _perm(2, "role-1", "directus_files", "create"),
        ]

        client = _mock_client(collections, roles, permissions)
        generator = Generator(client, include_system=True)
        config = generator.generate()

        assert sorted(config.collections) == ["directus_files", "directus_users"]
        assert config.roles == ["Admin"]
        assert len(config.groups) == 2


# ---------------------------------------------------------------------------
# Test: Action mapping for all 4 Directus actions
# ---------------------------------------------------------------------------


class TestActionMapping:
    """Test that all 4 Directus actions map to the correct PermissionKeyword."""

    def test_read_maps_to_READ(self):
        """Directus 'read' action maps to PermissionKeyword.READ."""
        collections = [DirectusCollection(collection="items")]
        roles = [DirectusRole(id="r1", name="Role")]
        permissions = [_perm(1, "r1", "items", "read")]

        client = _mock_client(collections, roles, permissions)
        config = Generator(client, include_system=False).generate()

        assert config.groups[0].permissions["Role"] == [PermissionKeyword.READ]

    def test_create_maps_to_WRITE(self):
        """Directus 'create' action maps to PermissionKeyword.WRITE."""
        collections = [DirectusCollection(collection="items")]
        roles = [DirectusRole(id="r1", name="Role")]
        permissions = [_perm(1, "r1", "items", "create")]

        client = _mock_client(collections, roles, permissions)
        config = Generator(client, include_system=False).generate()

        assert config.groups[0].permissions["Role"] == [PermissionKeyword.WRITE]

    def test_update_maps_to_UPDATE(self):
        """Directus 'update' action maps to PermissionKeyword.UPDATE."""
        collections = [DirectusCollection(collection="items")]
        roles = [DirectusRole(id="r1", name="Role")]
        permissions = [_perm(1, "r1", "items", "update")]

        client = _mock_client(collections, roles, permissions)
        config = Generator(client, include_system=False).generate()

        assert config.groups[0].permissions["Role"] == [PermissionKeyword.UPDATE]

    def test_delete_maps_to_DELETE(self):
        """Directus 'delete' action maps to PermissionKeyword.DELETE."""
        collections = [DirectusCollection(collection="items")]
        roles = [DirectusRole(id="r1", name="Role")]
        permissions = [_perm(1, "r1", "items", "delete")]

        client = _mock_client(collections, roles, permissions)
        config = Generator(client, include_system=False).generate()

        assert config.groups[0].permissions["Role"] == [PermissionKeyword.DELETE]

    def test_unknown_action_skipped(self):
        """Permissions with unknown action strings are silently skipped."""
        collections = [DirectusCollection(collection="items")]
        roles = [DirectusRole(id="r1", name="Role")]
        permissions = [
            _perm(1, "r1", "items", "read"),
            DirectusPermission(id=2, policy="policy-r1", collection="items", action="unknown_action"),
        ]

        client = _mock_client(collections, roles, permissions)
        config = Generator(client, include_system=False).generate()

        # Only the valid "read" action should be present
        assert config.groups[0].permissions["Role"] == [PermissionKeyword.READ]

    def test_reverse_action_map_completeness(self):
        """REVERSE_ACTION_MAP covers all 4 expected Directus actions."""
        assert set(REVERSE_ACTION_MAP.keys()) == {"read", "create", "update", "delete"}
        assert REVERSE_ACTION_MAP["read"] == PermissionKeyword.READ
        assert REVERSE_ACTION_MAP["create"] == PermissionKeyword.WRITE
        assert REVERSE_ACTION_MAP["update"] == PermissionKeyword.UPDATE
        assert REVERSE_ACTION_MAP["delete"] == PermissionKeyword.DELETE
