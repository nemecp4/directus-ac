"""Property-based tests for serialization correctness (Feature: custom-permissions).

Feature: custom-permissions, Property 6: Serialization correctness
Validates: Requirements 4.2, 4.3, 4.4

Property 6: For any DirectusACConfig, the serialized YAML SHALL:
- Include `custom_permissions` key if and only if custom permissions exist
- Maintain key order `collections`, `roles`, `groups`, `custom_permissions`
- Include custom permission references inline in Permission_Set strings
- Each custom permission entry SHALL contain name, policy, collection, action,
  and only non-null/non-empty optional attributes
"""
from __future__ import annotations

import re

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.generate import serialize_config
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusACConfig,
    GroupDefinition,
    PermissionKeyword,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_action = st.sampled_from(["create", "read", "update", "delete"])

# Simple field names: lowercase letters + underscore, 1-20 chars
_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

# Collection names: simple identifiers (no YAML-special chars)
_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)

# Role names: letters, digits, underscore, dash, space
_role_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
)

# Policy names: similar to role names
_policy_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
)


@st.composite
def _validation_dict(draw):
    """Generate a simple validation dict that round-trips cleanly through YAML."""
    field = draw(_field_name)
    operator = draw(st.sampled_from(["_eq", "_neq", "_contains", "_in"]))
    value = draw(st.one_of(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
        st.integers(min_value=0, max_value=100),
        st.booleans(),
    ))
    return {"_and": [{field: {operator: value}}]}


# Optional attributes: either None or a non-empty value
_opt_validation = st.one_of(st.none(), _validation_dict())
_opt_fields = st.one_of(
    st.none(),
    st.lists(_field_name, min_size=1, max_size=5),
)
_opt_permissions = st.one_of(st.none(), _validation_dict())


@st.composite
def _config_without_custom_permissions(draw):
    """Generate a valid DirectusACConfig with NO custom permissions."""
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collections = draw(
        st.lists(_collection_name, min_size=num_collections, max_size=num_collections, unique=True)
    )

    num_roles = draw(st.integers(min_value=1, max_value=3))
    roles = draw(
        st.lists(_role_name, min_size=num_roles, max_size=num_roles, unique=True)
    )

    # Build at least one group with standard keywords
    keywords = draw(
        st.lists(
            st.sampled_from(list(PermissionKeyword)),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    group = GroupDefinition(
        collections=collections[:1],
        permissions={roles[0]: keywords},
    )

    return DirectusACConfig(
        collections=collections,
        roles=roles,
        groups=[group],
        custom_permissions=[],
    )


@st.composite
def _config_with_custom_permissions(draw):
    """Generate a valid DirectusACConfig WITH custom permissions and inline refs."""
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collections = draw(
        st.lists(_collection_name, min_size=num_collections, max_size=num_collections, unique=True)
    )

    num_roles = draw(st.integers(min_value=1, max_value=3))
    roles = draw(
        st.lists(_role_name, min_size=num_roles, max_size=num_roles, unique=True)
    )

    # Build at least one group with standard keywords and custom refs
    keywords = draw(
        st.lists(
            st.sampled_from(list(PermissionKeyword)),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )

    # Generate 1-5 custom permission entries
    num_custom = draw(st.integers(min_value=1, max_value=5))
    custom_permissions = []
    custom_refs_for_role: dict[str, list[str]] = {}

    for i in range(1, num_custom + 1):
        policy = draw(_policy_name)
        collection = draw(st.sampled_from(collections))
        action = draw(_action)
        name = f"{action.upper()}_C_{i}"
        validation = draw(_opt_validation)
        fields = draw(_opt_fields)
        permissions = draw(_opt_permissions)

        custom_permissions.append(CustomPermissionEntry(
            name=name,
            policy=policy,
            collection=collection,
            action=action,
            validation=validation,
            fields=fields,
            permissions=permissions,
        ))

        # Assign this ref to a random role
        role = draw(st.sampled_from(roles))
        if role not in custom_refs_for_role:
            custom_refs_for_role[role] = []
        custom_refs_for_role[role].append(name)

    # Build group with both standard keywords and custom refs
    permissions_dict: dict[str, list[PermissionKeyword]] = {}
    if keywords:
        permissions_dict[roles[0]] = keywords

    group = GroupDefinition(
        collections=collections[:1],
        permissions=permissions_dict,
        custom_permission_refs=custom_refs_for_role,
    )

    return DirectusACConfig(
        collections=collections,
        roles=roles,
        groups=[group],
        custom_permissions=custom_permissions,
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 6: Serialization correctness
# Validates: Requirements 4.2, 4.3, 4.4
# ---------------------------------------------------------------------------


@given(config=_config_without_custom_permissions())
@settings(max_examples=100)
def test_custom_permissions_key_absent_when_no_custom_permissions(
    config: DirectusACConfig,
) -> None:
    """Property 6 (part A): custom_permissions key omitted when list is empty.

    For any DirectusACConfig with no custom permissions, the serialized YAML
    SHALL NOT include the `custom_permissions` key.

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    assert "custom_permissions" not in parsed, (
        f"custom_permissions key should be absent when no custom permissions exist, "
        f"but found: {parsed.get('custom_permissions')}"
    )


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_custom_permissions_key_present_when_custom_permissions_exist(
    config: DirectusACConfig,
) -> None:
    """Property 6 (part B): custom_permissions key present when custom permissions exist.

    For any DirectusACConfig with custom permissions, the serialized YAML
    SHALL include the `custom_permissions` key.

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    assert "custom_permissions" in parsed, (
        f"custom_permissions key should be present when custom permissions exist. "
        f"Config has {len(config.custom_permissions)} custom permissions."
    )
    assert len(parsed["custom_permissions"]) == len(config.custom_permissions), (
        f"Expected {len(config.custom_permissions)} entries in custom_permissions, "
        f"got {len(parsed['custom_permissions'])}"
    )


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_yaml_key_order_is_correct(config: DirectusACConfig) -> None:
    """Property 6 (part C): Key order is collections, roles, groups, custom_permissions.

    For any DirectusACConfig with custom permissions, the serialized YAML SHALL
    maintain the key order: collections, roles, groups, custom_permissions.

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    yaml_output = serialize_config(config)

    # Find positions of top-level keys in the raw YAML string
    collections_pos = yaml_output.index("collections:")
    roles_pos = yaml_output.index("roles:")
    groups_pos = yaml_output.index("groups:")
    custom_pos = yaml_output.index("custom_permissions:")

    assert collections_pos < roles_pos, (
        f"'collections:' (pos {collections_pos}) should appear before "
        f"'roles:' (pos {roles_pos})"
    )
    assert roles_pos < groups_pos, (
        f"'roles:' (pos {roles_pos}) should appear before "
        f"'groups:' (pos {groups_pos})"
    )
    assert groups_pos < custom_pos, (
        f"'groups:' (pos {groups_pos}) should appear before "
        f"'custom_permissions:' (pos {custom_pos})"
    )


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_permission_set_strings_contain_inline_c_n_references(
    config: DirectusACConfig,
) -> None:
    """Property 6 (part D): Permission_Set strings contain inline C_N references.

    For any DirectusACConfig with custom permissions, the serialized YAML's
    Permission_Set strings SHALL contain the C_N references from the group's
    custom_permission_refs for each role.

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    for group_idx, group in enumerate(config.groups):
        parsed_group = parsed["groups"][group_idx]
        parsed_permissions = parsed_group["permissions"]

        for role_name, refs in group.custom_permission_refs.items():
            perm_set_str = parsed_permissions.get(role_name, "")
            tokens = perm_set_str.split()

            for ref in refs:
                assert ref in tokens, (
                    f"Group {group_idx}, role '{role_name}': expected C_N reference "
                    f"'{ref}' in Permission_Set '{perm_set_str}', "
                    f"but tokens are: {tokens}"
                )
                # Verify it matches the C_N pattern
                assert re.fullmatch(r"[A-Z]+_C_\d+", ref), (
                    f"Reference '{ref}' does not match C_N pattern"
                )


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_custom_permission_entries_contain_only_non_null_non_empty_optional_attrs(
    config: DirectusACConfig,
) -> None:
    """Property 6 (part E): Each entry contains only non-null/non-empty optional attributes.

    For any DirectusACConfig with custom permissions, each serialized custom
    permission entry SHALL contain name, policy, collection, action, and only
    include validation/fields/permissions when they are non-null and non-empty
    (not {} for dicts, not [] for lists).

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    for i, entry in enumerate(parsed["custom_permissions"]):
        # Required fields must always be present
        assert "name" in entry, f"Entry {i}: missing required field 'name'"
        assert "policy" in entry, f"Entry {i}: missing required field 'policy'"
        assert "collection" in entry, f"Entry {i}: missing required field 'collection'"
        assert "action" in entry, f"Entry {i}: missing required field 'action'"

        # Verify name matches C_N pattern
        assert re.fullmatch(r"[A-Z]+_C_\d+", entry["name"]), (
            f"Entry {i}: name '{entry['name']}' does not match C_N pattern"
        )

        # Optional attributes: if present, must be non-null and non-empty
        if "validation" in entry:
            assert entry["validation"] is not None, (
                f"Entry {i}: 'validation' is present but None"
            )
            assert entry["validation"] != {}, (
                f"Entry {i}: 'validation' is present but empty dict"
            )

        if "fields" in entry:
            assert entry["fields"] is not None, (
                f"Entry {i}: 'fields' is present but None"
            )
            assert entry["fields"] != [], (
                f"Entry {i}: 'fields' is present but empty list"
            )

        if "permissions" in entry:
            assert entry["permissions"] is not None, (
                f"Entry {i}: 'permissions' is present but None"
            )
            assert entry["permissions"] != {}, (
                f"Entry {i}: 'permissions' is present but empty dict"
            )

        # Verify that null/empty optional attrs from the original config are NOT serialized
        original = config.custom_permissions[i]
        if original.validation is None or original.validation == {}:
            assert "validation" not in entry, (
                f"Entry {i}: 'validation' should be omitted (original was "
                f"{original.validation!r}), but it's present as {entry.get('validation')!r}"
            )
        if original.fields is None or original.fields == []:
            assert "fields" not in entry, (
                f"Entry {i}: 'fields' should be omitted (original was "
                f"{original.fields!r}), but it's present as {entry.get('fields')!r}"
            )
        if original.permissions is None or original.permissions == {}:
            assert "permissions" not in entry, (
                f"Entry {i}: 'permissions' should be omitted (original was "
                f"{original.permissions!r}), but it's present as {entry.get('permissions')!r}"
            )


@given(config=_config_without_custom_permissions())
@settings(max_examples=100)
def test_key_order_without_custom_permissions(config: DirectusACConfig) -> None:
    """Property 6 (part F): Key order is collections, roles, groups when no custom perms.

    For any DirectusACConfig without custom permissions, the serialized YAML SHALL
    maintain the key order: collections, roles, groups (no custom_permissions key).

    **Validates: Requirements 4.2, 4.3, 4.4**
    """
    yaml_output = serialize_config(config)

    collections_pos = yaml_output.index("collections:")
    roles_pos = yaml_output.index("roles:")
    groups_pos = yaml_output.index("groups:")

    assert collections_pos < roles_pos < groups_pos, (
        f"Key order should be collections ({collections_pos}) < "
        f"roles ({roles_pos}) < groups ({groups_pos})"
    )

    # custom_permissions should not appear at all
    assert "custom_permissions:" not in yaml_output, (
        "custom_permissions key should not appear when no custom permissions exist"
    )
