"""Unit tests for models.py — Pydantic data models.

Covers:
- PermissionKeyword enum values
- GroupDefinition validation
- DirectusACConfig length/count validators (Requirements 7.1, 7.2, 7.3)
- DirectusRole, DirectusCollection, DirectusPermission API response models
- Property 3: Valid config round-trip (Requirements 1.2, 1.3, 1.4, 7.1, 7.2, 7.3)
"""
import yaml
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from directus_ac.models import (
    DirectusACConfig,
    DirectusCollection,
    DirectusPermission,
    DirectusRole,
    GroupDefinition,
    PermissionKeyword,
)


# ---------------------------------------------------------------------------
# PermissionKeyword
# ---------------------------------------------------------------------------


class TestPermissionKeyword:
    def test_all_four_values_exist(self):
        assert PermissionKeyword.READ == "READ"
        assert PermissionKeyword.WRITE == "WRITE"
        assert PermissionKeyword.UPDATE == "UPDATE"
        assert PermissionKeyword.DELETE == "DELETE"

    def test_is_str_subclass(self):
        assert isinstance(PermissionKeyword.READ, str)

    def test_exactly_four_members(self):
        assert len(PermissionKeyword) == 4

    def test_invalid_keyword_raises(self):
        with pytest.raises(ValueError):
            PermissionKeyword("INVALID")


# ---------------------------------------------------------------------------
# GroupDefinition
# ---------------------------------------------------------------------------


class TestGroupDefinition:
    def test_valid_group(self):
        g = GroupDefinition(
            collections=["articles", "comments"],
            permissions={"editor": [PermissionKeyword.READ, PermissionKeyword.WRITE]},
        )
        assert g.collections == ["articles", "comments"]
        assert g.permissions["editor"] == [PermissionKeyword.READ, PermissionKeyword.WRITE]

    def test_empty_collections_allowed(self):
        # GroupDefinition itself has no length constraint — that's on DirectusACConfig
        g = GroupDefinition(collections=[], permissions={})
        assert g.collections == []

    def test_permissions_with_all_keywords(self):
        g = GroupDefinition(
            collections=["col"],
            permissions={
                "role1": [
                    PermissionKeyword.READ,
                    PermissionKeyword.WRITE,
                    PermissionKeyword.UPDATE,
                    PermissionKeyword.DELETE,
                ]
            },
        )
        assert len(g.permissions["role1"]) == 4

    def test_invalid_permission_keyword_rejected(self):
        with pytest.raises(ValidationError):
            GroupDefinition(
                collections=["col"],
                permissions={"role": ["INVALID"]},  # type: ignore[list-item]
            )

    def test_missing_collections_field_raises(self):
        with pytest.raises(ValidationError):
            GroupDefinition(permissions={"role": [PermissionKeyword.READ]})  # type: ignore[call-arg]

    def test_missing_permissions_field_raises(self):
        with pytest.raises(ValidationError):
            GroupDefinition(collections=["col"])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# DirectusACConfig — valid construction
# ---------------------------------------------------------------------------


class TestDirectusACConfigValid:
    def _make_config(self, **overrides):
        defaults = dict(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                )
            ],
        )
        defaults.update(overrides)
        return DirectusACConfig(**defaults)

    def test_minimal_valid_config(self):
        cfg = self._make_config()
        assert cfg.collections == ["articles"]
        assert cfg.roles == ["editor"]
        assert len(cfg.groups) == 1

    def test_max_boundary_collections(self):
        cfg = self._make_config(collections=["c"] * 500)
        assert len(cfg.collections) == 500

    def test_max_boundary_roles(self):
        cfg = self._make_config(roles=["r"] * 500)
        assert len(cfg.roles) == 500

    def test_max_boundary_groups(self):
        group = GroupDefinition(
            collections=["col"],
            permissions={"role": [PermissionKeyword.READ]},
        )
        cfg = self._make_config(groups=[group] * 500)
        assert len(cfg.groups) == 500

    def test_name_at_max_length(self):
        long_name = "a" * 255
        cfg = self._make_config(collections=[long_name])
        assert cfg.collections[0] == long_name

    def test_name_at_min_length(self):
        cfg = self._make_config(collections=["x"])
        assert cfg.collections[0] == "x"


# ---------------------------------------------------------------------------
# DirectusACConfig — validation failures (Requirements 7.1, 7.2, 7.3)
# ---------------------------------------------------------------------------


class TestDirectusACConfigInvalid:
    def _base_groups(self):
        return [
            GroupDefinition(
                collections=["col"],
                permissions={"role": [PermissionKeyword.READ]},
            )
        ]

    def test_empty_collections_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(collections=[], roles=["r"], groups=self._base_groups())

    def test_too_many_collections_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=["c"] * 501,
                roles=["r"],
                groups=self._base_groups(),
            )

    def test_empty_roles_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(collections=["c"], roles=[], groups=self._base_groups())

    def test_too_many_roles_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=["c"],
                roles=["r"] * 501,
                groups=self._base_groups(),
            )

    def test_empty_groups_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(collections=["c"], roles=["r"], groups=[])

    def test_too_many_groups_raises(self):
        group = GroupDefinition(
            collections=["col"],
            permissions={"role": [PermissionKeyword.READ]},
        )
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=["c"],
                roles=["r"],
                groups=[group] * 501,
            )

    def test_collection_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=["a" * 256],
                roles=["r"],
                groups=self._base_groups(),
            )

    def test_collection_name_empty_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=[""],
                roles=["r"],
                groups=self._base_groups(),
            )

    def test_role_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=["c"],
                roles=["a" * 256],
                groups=self._base_groups(),
            )

    def test_role_name_empty_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(
                collections=["c"],
                roles=[""],
                groups=self._base_groups(),
            )

    def test_missing_collections_key_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(roles=["r"], groups=self._base_groups())  # type: ignore[call-arg]

    def test_missing_roles_key_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(collections=["c"], groups=self._base_groups())  # type: ignore[call-arg]

    def test_missing_groups_key_raises(self):
        with pytest.raises(ValidationError):
            DirectusACConfig(collections=["c"], roles=["r"])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# DirectusRole
# ---------------------------------------------------------------------------


class TestDirectusRole:
    def test_valid_role(self):
        role = DirectusRole(id="uuid-1234", name="editor")
        assert role.id == "uuid-1234"
        assert role.name == "editor"

    def test_missing_id_raises(self):
        with pytest.raises(ValidationError):
            DirectusRole(name="editor")  # type: ignore[call-arg]

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            DirectusRole(id="uuid-1234")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# DirectusCollection
# ---------------------------------------------------------------------------


class TestDirectusCollection:
    def test_valid_collection(self):
        col = DirectusCollection(collection="articles")
        assert col.collection == "articles"

    def test_missing_collection_field_raises(self):
        with pytest.raises(ValidationError):
            DirectusCollection()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# DirectusPermission
# ---------------------------------------------------------------------------


class TestDirectusPermission:
    def test_valid_permission(self):
        perm = DirectusPermission(
            id=42,
            policy="policy-uuid",
            collection="articles",
            action="read",
        )
        assert perm.id == 42
        assert perm.policy == "policy-uuid"
        assert perm.collection == "articles"
        assert perm.action == "read"

    def test_id_must_be_int(self):
        with pytest.raises(ValidationError):
            DirectusPermission(
                id="not-an-int",  # type: ignore[arg-type]
                policy="policy-uuid",
                collection="articles",
                action="read",
            )

    def test_missing_fields_raise(self):
        with pytest.raises(ValidationError):
            DirectusPermission(id=1, policy="p")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Property 3: Valid config round-trip
# Feature: directus-access-control, Property 3: Valid config round-trip
# ---------------------------------------------------------------------------

# Strategy for valid permission keywords
_permission_keywords = st.sampled_from(["READ", "WRITE", "UPDATE", "DELETE"])

# Characters that YAML (1.1, as used by PyYAML) does not preserve faithfully:
# - C0/C1 control characters (categories Cc) except tab (\x09)
# - Unicode line/paragraph separators (\x85 NEL, \u2028 LS, \u2029 PS)
# - Lone surrogates (category Cs)
# We use printable + tab characters to ensure round-trip fidelity.
_yaml_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cc", "Cs"),
        blacklist_characters="\x85\u2028\u2029",
        whitelist_characters="\t",  # allow tab explicitly
    ),
    min_size=1,
    max_size=255,
)

# Strategy for a single GroupDefinition dict (as raw data, for YAML round-trip)
_st_group = st.fixed_dictionaries({
    "collections": st.lists(
        _yaml_safe_text,
        min_size=1,
        max_size=10,
    ),
    "permissions": st.dictionaries(
        keys=_yaml_safe_text,
        values=st.lists(_permission_keywords, min_size=1, max_size=4, unique=True),
        min_size=1,
        max_size=5,
    ),
})


@settings(max_examples=100, deadline=None)
@given(
    collections=st.lists(
        _yaml_safe_text,
        min_size=1,
        max_size=500,
    ),
    roles=st.lists(
        _yaml_safe_text,
        min_size=1,
        max_size=500,
    ),
    groups=st.lists(
        _st_group,
        min_size=1,
        max_size=500,
    ),
)
def test_directus_ac_config_round_trip(collections, roles, groups):
    """**Validates: Requirements 1.2, 1.3, 1.4, 7.1, 7.2, 7.3**

    For any valid DirectusACConfig, serializing to YAML and parsing back
    should produce an equivalent config object.
    """
    # Build the original config from raw data
    original = DirectusACConfig.model_validate(
        {"collections": collections, "roles": roles, "groups": groups}
    )

    # Serialize to YAML via model_dump (use mode="json" to get native Python
    # types; enum values become their string values via the str mixin)
    raw_dict = original.model_dump(mode="json")
    yaml_str = yaml.dump(raw_dict, allow_unicode=True)

    # Parse back from YAML
    parsed_dict = yaml.safe_load(yaml_str)
    restored = DirectusACConfig.model_validate(parsed_dict)

    assert restored == original
