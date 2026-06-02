"""Unit tests for serialize_config() edge cases."""
from __future__ import annotations

import tempfile
import os

import yaml

from directus_ac.config import load_config
from directus_ac.generate import serialize_config
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusACConfig,
    GroupDefinition,
    PermissionKeyword,
)


class TestSerializeConfigSingleCollectionSingleRoleSinglePermission:
    """Test single collection with single role and single permission."""

    def test_single_read_permission(self):
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["collections"] == ["articles"]
        assert parsed["roles"] == ["editor"]
        assert len(parsed["groups"]) == 1
        assert parsed["groups"][0]["collections"] == ["articles"]
        assert parsed["groups"][0]["permissions"]["editor"] == "READ"

    def test_single_write_permission(self):
        config = DirectusACConfig(
            collections=["posts"],
            roles=["author"],
            groups=[
                GroupDefinition(
                    collections=["posts"],
                    permissions={"author": [PermissionKeyword.WRITE]},
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["author"] == "WRITE"

    def test_single_delete_permission(self):
        config = DirectusACConfig(
            collections=["logs"],
            roles=["admin"],
            groups=[
                GroupDefinition(
                    collections=["logs"],
                    permissions={"admin": [PermissionKeyword.DELETE]},
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["admin"] == "DELETE"


class TestSerializeConfigMultiplePermissionsCombined:
    """Test multiple permissions combined into space-separated string."""

    def test_two_permissions(self):
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={
                        "editor": [PermissionKeyword.READ, PermissionKeyword.WRITE]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["editor"] == "READ WRITE"

    def test_three_permissions(self):
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={
                        "editor": [
                            PermissionKeyword.READ,
                            PermissionKeyword.WRITE,
                            PermissionKeyword.UPDATE,
                        ]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["editor"] == "READ WRITE UPDATE"

    def test_all_four_permissions(self):
        config = DirectusACConfig(
            collections=["articles"],
            roles=["admin"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={
                        "admin": [
                            PermissionKeyword.READ,
                            PermissionKeyword.WRITE,
                            PermissionKeyword.UPDATE,
                            PermissionKeyword.DELETE,
                        ]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["admin"] == "READ WRITE UPDATE DELETE"

    def test_no_leading_or_trailing_whitespace(self):
        config = DirectusACConfig(
            collections=["data"],
            roles=["viewer"],
            groups=[
                GroupDefinition(
                    collections=["data"],
                    permissions={
                        "viewer": [PermissionKeyword.READ, PermissionKeyword.UPDATE]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        perm_str = parsed["groups"][0]["permissions"]["viewer"]
        assert perm_str == perm_str.strip()


class TestSerializeConfigCanonicalKeywordOrdering:
    """Test canonical keyword ordering (READ before WRITE before UPDATE before DELETE)."""

    def test_keywords_provided_out_of_order_are_serialized_in_canonical_order(self):
        """Even if keywords are provided in non-canonical order, output is canonical."""
        config = DirectusACConfig(
            collections=["items"],
            roles=["manager"],
            groups=[
                GroupDefinition(
                    collections=["items"],
                    permissions={
                        "manager": [
                            PermissionKeyword.DELETE,
                            PermissionKeyword.READ,
                            PermissionKeyword.UPDATE,
                            PermissionKeyword.WRITE,
                        ]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["manager"] == "READ WRITE UPDATE DELETE"

    def test_write_before_read_reordered(self):
        config = DirectusACConfig(
            collections=["docs"],
            roles=["writer"],
            groups=[
                GroupDefinition(
                    collections=["docs"],
                    permissions={
                        "writer": [PermissionKeyword.WRITE, PermissionKeyword.READ]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["writer"] == "READ WRITE"

    def test_delete_and_update_reordered(self):
        config = DirectusACConfig(
            collections=["records"],
            roles=["cleaner"],
            groups=[
                GroupDefinition(
                    collections=["records"],
                    permissions={
                        "cleaner": [PermissionKeyword.DELETE, PermissionKeyword.UPDATE]
                    },
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["cleaner"] == "UPDATE DELETE"


class TestSerializeConfigLoadConfigRoundTrip:
    """Test output is valid YAML parseable by load_config()."""

    def test_simple_config_round_trips(self, tmp_path):
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                )
            ],
        )

        yaml_str = serialize_config(config)
        tmp_file = tmp_path / "directus_ac.yaml"
        tmp_file.write_text(yaml_str, encoding="utf-8")

        parsed = load_config(str(tmp_file))

        assert parsed.collections == config.collections
        assert parsed.roles == config.roles
        assert len(parsed.groups) == len(config.groups)
        assert set(parsed.groups[0].permissions["editor"]) == set(
            config.groups[0].permissions["editor"]
        )

    def test_multi_group_config_round_trips(self, tmp_path):
        config = DirectusACConfig(
            collections=["articles", "comments"],
            roles=["editor", "moderator"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={
                        "editor": [
                            PermissionKeyword.READ,
                            PermissionKeyword.WRITE,
                            PermissionKeyword.UPDATE,
                        ],
                        "moderator": [PermissionKeyword.READ, PermissionKeyword.DELETE],
                    },
                ),
                GroupDefinition(
                    collections=["comments"],
                    permissions={
                        "moderator": [
                            PermissionKeyword.READ,
                            PermissionKeyword.UPDATE,
                            PermissionKeyword.DELETE,
                        ],
                    },
                ),
            ],
        )

        yaml_str = serialize_config(config)
        tmp_file = tmp_path / "directus_ac.yaml"
        tmp_file.write_text(yaml_str, encoding="utf-8")

        parsed = load_config(str(tmp_file))

        assert sorted(parsed.collections) == sorted(config.collections)
        assert sorted(parsed.roles) == sorted(config.roles)
        assert len(parsed.groups) == len(config.groups)

        # Build permission maps for comparison
        def perm_map(cfg):
            result = {}
            for group in cfg.groups:
                for col in group.collections:
                    result[col] = {
                        role: set(kws) for role, kws in group.permissions.items()
                    }
            return result

        assert perm_map(parsed) == perm_map(config)

    def test_all_permissions_round_trip(self, tmp_path):
        """Config with all four permission keywords round-trips correctly."""
        config = DirectusACConfig(
            collections=["everything"],
            roles=["superadmin"],
            groups=[
                GroupDefinition(
                    collections=["everything"],
                    permissions={
                        "superadmin": [
                            PermissionKeyword.READ,
                            PermissionKeyword.WRITE,
                            PermissionKeyword.UPDATE,
                            PermissionKeyword.DELETE,
                        ]
                    },
                )
            ],
        )

        yaml_str = serialize_config(config)
        tmp_file = tmp_path / "directus_ac.yaml"
        tmp_file.write_text(yaml_str, encoding="utf-8")

        parsed = load_config(str(tmp_file))

        assert set(parsed.groups[0].permissions["superadmin"]) == set(
            config.groups[0].permissions["superadmin"]
        )

    def test_top_level_keys_in_correct_order(self):
        """Serialized YAML has top-level keys in order: collections, roles, groups."""
        config = DirectusACConfig(
            collections=["data"],
            roles=["user"],
            groups=[
                GroupDefinition(
                    collections=["data"],
                    permissions={"user": [PermissionKeyword.READ]},
                )
            ],
        )

        yaml_str = serialize_config(config)

        # Check that keys appear in the correct order in the YAML string
        collections_pos = yaml_str.index("collections:")
        roles_pos = yaml_str.index("roles:")
        groups_pos = yaml_str.index("groups:")

        assert collections_pos < roles_pos < groups_pos


class TestSerializeConfigInlineCustomRefs:
    """Test inline C_N references in Permission_Set strings."""

    def test_custom_refs_appended_after_keywords(self):
        """Custom refs appear after standard keywords in Permission_Set."""
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ, PermissionKeyword.WRITE]},
                    custom_permission_refs={"editor": ["UPDATE_C_1", "READ_C_2"]},
                )
            ],
            custom_permissions=[
                CustomPermissionEntry(name="UPDATE_C_1", policy="p", collection="articles", action="update"),
                CustomPermissionEntry(name="READ_C_2", policy="p", collection="articles", action="read"),
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["editor"] == "READ WRITE UPDATE_C_1 READ_C_2"

    def test_custom_refs_only_no_standard_keywords(self):
        """A role with only custom refs and no standard keywords."""
        config = DirectusACConfig(
            collections=["articles"],
            roles=["viewer"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={},
                    custom_permission_refs={"viewer": ["READ_C_1"]},
                )
            ],
            custom_permissions=[
                CustomPermissionEntry(name="READ_C_1", policy="p", collection="articles", action="read"),
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["viewer"] == "READ_C_1"

    def test_multiple_roles_with_different_refs(self):
        """Different roles can have different custom refs."""
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor", "viewer"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={
                        "editor": [PermissionKeyword.READ, PermissionKeyword.WRITE],
                        "viewer": [PermissionKeyword.READ],
                    },
                    custom_permission_refs={
                        "editor": ["UPDATE_C_1"],
                        "viewer": ["READ_C_2"],
                    },
                )
            ],
            custom_permissions=[
                CustomPermissionEntry(name="UPDATE_C_1", policy="p", collection="articles", action="update"),
                CustomPermissionEntry(name="READ_C_2", policy="p", collection="articles", action="read"),
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["editor"] == "READ WRITE UPDATE_C_1"
        assert parsed["groups"][0]["permissions"]["viewer"] == "READ READ_C_2"

    def test_role_in_refs_but_not_in_permissions(self):
        """A role that only appears in custom_permission_refs is still serialized."""
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor", "custom_only"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                    custom_permission_refs={"custom_only": ["READ_C_1"]},
                )
            ],
            custom_permissions=[
                CustomPermissionEntry(name="READ_C_1", policy="p", collection="articles", action="read"),
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["custom_only"] == "READ_C_1"
        assert parsed["groups"][0]["permissions"]["editor"] == "READ"

    def test_no_custom_refs_produces_standard_output(self):
        """When no custom_permission_refs exist, output is standard keywords only."""
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ, PermissionKeyword.WRITE]},
                )
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert parsed["groups"][0]["permissions"]["editor"] == "READ WRITE"

    def test_no_leading_or_trailing_whitespace_with_refs(self):
        """Permission_Set string has no leading/trailing whitespace even with refs."""
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                    custom_permission_refs={"editor": ["READ_C_1"]},
                )
            ],
            custom_permissions=[
                CustomPermissionEntry(name="READ_C_1", policy="p", collection="articles", action="read"),
            ],
        )

        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        perm_str = parsed["groups"][0]["permissions"]["editor"]
        assert perm_str == perm_str.strip()


class TestSerializeConfigCustomPermissions:
    """Test custom_permissions serialization in serialize_config()."""

    def _base_config(self, custom_permissions=None):
        """Helper to create a config with optional custom permissions."""
        return DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                )
            ],
            custom_permissions=custom_permissions or [],
        )

    def test_omits_custom_permissions_key_when_list_is_empty(self):
        """custom_permissions key is omitted entirely when list is empty."""
        config = self._base_config(custom_permissions=[])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        assert "custom_permissions" not in parsed

    def test_includes_custom_permissions_key_when_non_empty(self):
        """custom_permissions key is present when list is non-empty."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        assert "custom_permissions" in parsed
        assert len(parsed["custom_permissions"]) == 1

    def test_serializes_required_fields(self):
        """Each entry has name, policy, collection, action."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="UPDATE_C_1",
                policy="editor policy",
                collection="articles",
                action="update",
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert entry["name"] == "UPDATE_C_1"
        assert entry["policy"] == "editor policy"
        assert entry["collection"] == "articles"
        assert entry["action"] == "update"

    def test_includes_non_null_validation(self):
        """validation is included when non-null and non-empty."""
        validation = {"_and": [{"status": {"_eq": "draft"}}]}
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="UPDATE_C_1",
                policy="editor policy",
                collection="articles",
                action="update",
                validation=validation,
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert entry["validation"] == validation

    def test_includes_non_null_fields(self):
        """fields is included when non-null and non-empty."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="UPDATE_C_1",
                policy="editor policy",
                collection="articles",
                action="update",
                fields=["title", "body"],
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert entry["fields"] == ["title", "body"]

    def test_includes_non_null_permissions(self):
        """permissions (item-level) is included when non-null and non-empty."""
        perms = {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                permissions=perms,
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert entry["permissions"] == perms

    def test_skips_null_optional_attributes(self):
        """Optional attributes that are None are not included in output."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                validation=None,
                fields=None,
                permissions=None,
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert "validation" not in entry
        assert "fields" not in entry
        assert "permissions" not in entry

    def test_skips_empty_dict_validation(self):
        """Empty dict validation is not included in output."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                validation={},
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert "validation" not in entry

    def test_skips_empty_list_fields(self):
        """Empty list fields is not included in output."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                fields=[],
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert "fields" not in entry

    def test_skips_empty_dict_permissions(self):
        """Empty dict permissions is not included in output."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                permissions={},
            )
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)
        entry = parsed["custom_permissions"][0]
        assert "permissions" not in entry

    def test_key_order_collections_roles_groups_custom_permissions(self):
        """Top-level keys appear in order: collections, roles, groups, custom_permissions."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="READ_C_1",
                policy="editor policy",
                collection="articles",
                action="read",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            )
        ])
        result = serialize_config(config)

        collections_pos = result.index("collections:")
        roles_pos = result.index("roles:")
        groups_pos = result.index("groups:")
        custom_pos = result.index("custom_permissions:")

        assert collections_pos < roles_pos < groups_pos < custom_pos

    def test_multiple_entries_serialized(self):
        """Multiple custom permission entries are all serialized."""
        config = self._base_config(custom_permissions=[
            CustomPermissionEntry(
                name="UPDATE_C_1",
                policy="editor policy",
                collection="articles",
                action="update",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
                fields=["title", "body"],
            ),
            CustomPermissionEntry(
                name="READ_C_2",
                policy="editor policy",
                collection="articles",
                action="read",
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ])
        result = serialize_config(config)
        parsed = yaml.safe_load(result)

        assert len(parsed["custom_permissions"]) == 2
        assert parsed["custom_permissions"][0]["name"] == "UPDATE_C_1"
        assert parsed["custom_permissions"][1]["name"] == "READ_C_2"
        assert "validation" in parsed["custom_permissions"][0]
        assert "fields" in parsed["custom_permissions"][0]
        assert "permissions" in parsed["custom_permissions"][1]
