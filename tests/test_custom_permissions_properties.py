"""Property-based tests for custom permissions (Feature: custom-permissions).

Tests cover correctness properties defined in the design document for the
custom permissions feature.
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.config import _parse_custom_permissions
from directus_ac.exceptions import ConfigError
from directus_ac.generate import Generator, generate_permission_name, serialize_config
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    collections: list[DirectusCollection],
    roles: list[DirectusRole],
    permissions: list[DirectusPermission],
    policies: list[DirectusPolicy],
) -> MagicMock:
    """Create a mock DirectusClient with configured return values."""
    client = MagicMock()
    client.get_collections.return_value = collections
    client.get_roles.return_value = roles
    client.get_permissions.return_value = permissions
    client.get_policies.return_value = policies
    return client


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Policy names: non-empty strings with varied characters to stress sanitization
_policy_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=30,
)

# Collection names: non-empty, no directus_ prefix (user collections)
_collection_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: not s.startswith("directus_"))

_action = st.sampled_from(["create", "read", "update", "delete"])


@st.composite
def _custom_permissions_state(draw):
    """Generate a Directus state that produces custom permissions.

    Creates multiple policies and collections, then generates permissions
    that will be classified as custom (via non-null validation, fields, or
    permissions attributes, or duplicate triples).

    Returns (collections, roles, policies, permissions).
    """
    # Generate 1-4 policies with distinct names
    num_policies = draw(st.integers(min_value=1, max_value=4))
    policy_names = draw(
        st.lists(
            _policy_name,
            min_size=num_policies,
            max_size=num_policies,
            unique=True,
        )
    )
    policies = []
    roles = []
    for i, pname in enumerate(policy_names):
        policy_id = f"policy-{i}"
        role_id = f"role-{i}"
        policies.append(
            DirectusPolicy(id=policy_id, name=pname, roles=[role_id])
        )
        roles.append(
            DirectusRole(id=role_id, name=f"Role {i}", policies=[policy_id])
        )

    # Generate 1-4 collections
    num_collections = draw(st.integers(min_value=1, max_value=4))
    collection_names = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )
    collections = [DirectusCollection(collection=c) for c in collection_names]

    # Generate custom permissions: for each policy+collection pair, generate
    # 1-3 permissions that will be classified as custom
    permissions: list[DirectusPermission] = []
    perm_id = 1

    for policy in policies:
        for col_name in collection_names:
            num_perms = draw(st.integers(min_value=1, max_value=3))
            for _ in range(num_perms):
                action = draw(_action)
                # Make it custom by adding at least one non-default attribute
                make_custom_via = draw(
                    st.sampled_from(["validation", "fields", "permissions"])
                )
                validation = None
                fields = None
                item_permissions = None

                if make_custom_via == "validation":
                    validation = {"_and": [{"status": {"_eq": "draft"}}]}
                elif make_custom_via == "fields":
                    fields = draw(
                        st.lists(
                            st.text(
                                alphabet=st.characters(
                                    whitelist_categories=("L",),
                                ),
                                min_size=1,
                                max_size=10,
                            ),
                            min_size=1,
                            max_size=5,
                        )
                    )
                else:
                    item_permissions = {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}

                permissions.append(
                    DirectusPermission(
                        id=perm_id,
                        policy=policy.id,
                        collection=col_name,
                        action=action,
                        validation=validation,
                        fields=fields,
                        permissions=item_permissions,
                    )
                )
                perm_id += 1

    return collections, roles, policies, permissions


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 3: Name format correctness
# Validates: Requirements 2.1, 2.3
# ---------------------------------------------------------------------------


@given(
    action=st.sampled_from(["create", "read", "update", "delete"]),
    counter=st.integers(min_value=1, max_value=10000),
)
@settings(max_examples=100)
def test_generate_permission_name_c_n_format(
    action: str,
    counter: int,
) -> None:
    """Property 3: Permission name follows {ACTION}_C_N pattern.

    For any positive integer counter and valid action, generate_permission_name
    SHALL return a string matching the pattern {ACTION}_C_{counter}.

    **Validates: Requirements 2.1, 2.3**
    """
    import re

    result = generate_permission_name(action, counter)

    # Must match ACTION_C_N pattern
    assert re.fullmatch(r"[A-Z]+_C_\d+", result), (
        f"Generated name '{result}' does not match ACTION_C_N pattern "
        f"(action={action}, counter={counter})"
    )

    # Must be exactly {ACTION}_C_{counter}
    assert result == f"{action.upper()}_C_{counter}", (
        f"Generated name '{result}' does not equal expected '{action.upper()}_C_{counter}'"
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 4: Permission name uniqueness
# Validates: Requirements 2.5, 2.6
# ---------------------------------------------------------------------------


@given(state=_custom_permissions_state())
@settings(max_examples=100)
def test_permission_name_uniqueness(state) -> None:
    """Property 4: Permission name uniqueness.

    For any set of custom permissions within a single generated config, all
    generated Permission_Name values SHALL be distinct, guaranteed by the
    global counter sequence.

    **Validates: Requirements 2.5, 2.6**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Collect all generated permission names
    names = [entry.name for entry in config.custom_permissions]

    # All names must be unique — global counter guarantees this
    assert len(names) == len(set(names)), (
        f"Duplicate permission names found: "
        f"{[n for n in names if names.count(n) > 1]}"
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 5: Counter assignment determinism
# Validates: Requirements 2.2
# ---------------------------------------------------------------------------


@st.composite
def _custom_permissions_sharing_policy_collection(draw):
    """Generate a set of custom permissions with multiple policies and collections.

    Returns (collections, roles, policies, permissions) where all permissions
    are marked as custom (via non-null validation attribute) and have unique IDs.
    """
    # Generate 1-3 policies
    num_policies = draw(st.integers(min_value=1, max_value=3))
    policy_names = draw(
        st.lists(
            _policy_name,
            min_size=num_policies,
            max_size=num_policies,
            unique=True,
        )
    )
    policies = []
    roles = []
    for i, pname in enumerate(policy_names):
        policy_id = f"policy-{i}"
        role_id = f"role-{i}"
        policies.append(
            DirectusPolicy(id=policy_id, name=pname, roles=[role_id])
        )
        roles.append(
            DirectusRole(id=role_id, name=f"Role {i}", policies=[policy_id])
        )

    # Generate 1-3 collections
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collection_names = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )
    collections = [DirectusCollection(collection=c) for c in collection_names]

    # Generate 2-10 custom permissions with unique IDs
    num_perms = draw(st.integers(min_value=2, max_value=10))
    perm_ids = draw(
        st.lists(
            st.integers(min_value=1, max_value=100000),
            min_size=num_perms,
            max_size=num_perms,
            unique=True,
        )
    )

    actions = ["read", "create", "update", "delete"]
    permissions = []
    for perm_id in perm_ids:
        policy = draw(st.sampled_from(policies))
        col_name = draw(st.sampled_from(collection_names))
        action = draw(st.sampled_from(actions))
        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy.id,
                collection=col_name,
                action=action,
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            )
        )

    return collections, roles, policies, permissions


@given(state=_custom_permissions_sharing_policy_collection())
@settings(max_examples=100)
def test_counter_assignment_determinism(state) -> None:
    """Property 5: Counter assignment determinism.

    For any set of custom permissions, the counter values SHALL be assigned as
    a single global sequence starting at 1, where all custom permissions are
    sorted by their Directus permission `id` (ascending) and assigned
    consecutive counter values regardless of which policy or collection they
    belong to.

    **Validates: Requirements 2.2**
    """
    collections, roles, policies, permissions = state

    # Build policy_id -> name mapping
    policy_id_to_name = {p.id: p.name for p in policies}

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    # Sort all permissions by id ascending — this is the expected global counter order
    sorted_perms = sorted(permissions, key=lambda p: p.id)

    # Filter out permissions whose policy can't be resolved (they get skipped)
    resolvable_perms = [p for p in sorted_perms if p.policy in policy_id_to_name]

    assert len(config.custom_permissions) == len(resolvable_perms), (
        f"Expected {len(resolvable_perms)} custom permissions, got {len(config.custom_permissions)}"
    )

    # Verify global counter assignment: perm with lowest id gets counter 1, etc.
    for global_counter, perm in enumerate(resolvable_perms, start=1):
        policy_name = policy_id_to_name[perm.policy]
        expected_name = generate_permission_name(perm.action, global_counter)

        # The entry at position (global_counter - 1) should have this name
        entry = config.custom_permissions[global_counter - 1]
        assert entry.name == expected_name, (
            f"Counter {global_counter} (perm id={perm.id}) should have name "
            f"'{expected_name}', got '{entry.name}'. "
            f"All names: {[e.name for e in config.custom_permissions]}"
        )
        assert entry.action == perm.action, (
            f"Counter {global_counter} (perm id={perm.id}) should have action "
            f"'{perm.action}', got '{entry.action}'"
        )
        assert entry.policy == policy_name, (
            f"Counter {global_counter} should have policy '{policy_name}', "
            f"got '{entry.policy}'"
        )
        assert entry.collection == perm.collection, (
            f"Counter {global_counter} should have collection '{perm.collection}', "
            f"got '{entry.collection}'"
        )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 8: Custom permissions section presence
# Validates: Requirements 4.1, 4.3
# ---------------------------------------------------------------------------


@st.composite
def _standard_only_permissions_state(draw):
    """Generate a Directus state with ONLY standard permissions (no custom).

    Standard permissions have:
    - validation = None
    - fields = None or ["*"]
    - permissions = None
    - No duplicate (policy, collection, action) triples

    Returns (collections, roles, policies, permissions).
    """
    # Generate 1-3 policies with distinct names
    num_policies = draw(st.integers(min_value=1, max_value=3))
    policy_names = draw(
        st.lists(
            _policy_name,
            min_size=num_policies,
            max_size=num_policies,
            unique=True,
        )
    )
    policies = []
    roles = []
    for i, pname in enumerate(policy_names):
        policy_id = f"policy-{i}"
        role_id = f"role-{i}"
        policies.append(
            DirectusPolicy(id=policy_id, name=pname, roles=[role_id])
        )
        roles.append(
            DirectusRole(id=role_id, name=f"Role {i}", policies=[policy_id])
        )

    # Generate 1-3 collections (no directus_ prefix)
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collection_names = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )
    collections = [DirectusCollection(collection=c) for c in collection_names]

    # Generate standard permissions: unique (policy, collection, action) triples
    # with no non-default attributes
    actions = ["read", "create", "update", "delete"]
    permissions: list[DirectusPermission] = []
    used_triples: set[tuple[str, str, str]] = set()
    perm_id = 1

    for policy in policies:
        for col_name in collection_names:
            # Pick 1-4 unique actions for this policy+collection
            num_actions = draw(st.integers(min_value=1, max_value=4))
            chosen_actions = draw(
                st.lists(
                    st.sampled_from(actions),
                    min_size=num_actions,
                    max_size=num_actions,
                    unique=True,
                )
            )
            for action in chosen_actions:
                triple = (policy.id, col_name, action)
                if triple in used_triples:
                    continue  # Avoid duplicates which would trigger custom detection
                used_triples.add(triple)

                # Standard permission: fields is None or ["*"], no validation, no permissions
                fields_value = draw(st.sampled_from([None, ["*"]]))
                permissions.append(
                    DirectusPermission(
                        id=perm_id,
                        policy=policy.id,
                        collection=col_name,
                        action=action,
                        validation=None,
                        fields=fields_value,
                        permissions=None,
                    )
                )
                perm_id += 1

    return collections, roles, policies, permissions


@given(state=_custom_permissions_state())
@settings(max_examples=100)
def test_custom_permissions_section_present_when_custom_exist(state) -> None:
    """Property 8: Custom permissions section presence (present case).

    For any Directus state where at least one permission is classified as
    custom, the generated config SHALL include a non-empty `custom_permissions`
    section in the serialized YAML.

    **Validates: Requirements 4.1, 4.3**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # The config should have custom permissions
    assert len(config.custom_permissions) > 0, (
        "Expected custom permissions in the generated config but got none"
    )

    # Serialize and verify the YAML contains the custom_permissions key
    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    assert "custom_permissions" in parsed, (
        f"Expected 'custom_permissions' key in serialized YAML but it was absent. "
        f"Config has {len(config.custom_permissions)} custom permissions."
    )
    assert isinstance(parsed["custom_permissions"], list), (
        "Expected 'custom_permissions' to be a list in serialized YAML"
    )
    assert len(parsed["custom_permissions"]) > 0, (
        "Expected 'custom_permissions' to be non-empty in serialized YAML"
    )


@given(state=_standard_only_permissions_state())
@settings(max_examples=100)
def test_custom_permissions_section_absent_when_none_exist(state) -> None:
    """Property 8: Custom permissions section presence (absent case).

    For any Directus state where no permission is classified as custom,
    the generated config SHALL omit the `custom_permissions` key entirely
    from the serialized YAML.

    **Validates: Requirements 4.1, 4.3**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # The config should have NO custom permissions
    assert len(config.custom_permissions) == 0, (
        f"Expected no custom permissions but got {len(config.custom_permissions)}"
    )

    # Serialize and verify the YAML does NOT contain the custom_permissions key
    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    assert "custom_permissions" not in parsed, (
        f"Expected 'custom_permissions' key to be absent from serialized YAML "
        f"when no custom permissions exist, but it was present with value: "
        f"{parsed.get('custom_permissions')}"
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 9: Serialization key order and content
# Validates: Requirements 4.2, 4.4
# ---------------------------------------------------------------------------


@st.composite
def _config_with_custom_permissions(draw):
    """Generate a DirectusACConfig with custom permissions for serialization testing.

    Creates a valid config with at least one custom permission entry, where
    entries have varying combinations of optional attributes (validation, fields,
    permissions) including null and non-null values.

    Returns a DirectusACConfig instance.
    """
    from directus_ac.models import CustomPermissionEntry, DirectusACConfig, GroupDefinition, PermissionKeyword

    # Generate 1-3 collections
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collection_names = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )

    # Generate 1-3 roles
    num_roles = draw(st.integers(min_value=1, max_value=3))
    role_names = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
                min_size=1,
                max_size=20,
            ),
            min_size=num_roles,
            max_size=num_roles,
            unique=True,
        )
    )

    # Generate at least one group
    keywords = [PermissionKeyword.READ, PermissionKeyword.WRITE, PermissionKeyword.UPDATE, PermissionKeyword.DELETE]
    permissions_dict = {}
    for role_name in role_names:
        num_kw = draw(st.integers(min_value=1, max_value=4))
        chosen_kw = draw(
            st.lists(
                st.sampled_from(keywords),
                min_size=num_kw,
                max_size=num_kw,
                unique=True,
            )
        )
        permissions_dict[role_name] = chosen_kw

    groups = [GroupDefinition(collections=collection_names, permissions=permissions_dict)]

    # Generate 1-5 custom permission entries with varying optional attributes
    num_custom = draw(st.integers(min_value=1, max_value=5))
    custom_entries = []
    for i in range(num_custom):
        col = draw(st.sampled_from(collection_names))
        action = draw(_action)
        policy_name = draw(_policy_name)

        # Randomly include or exclude optional attributes
        include_validation = draw(st.booleans())
        include_fields = draw(st.booleans())
        include_permissions = draw(st.booleans())

        validation = None
        fields = None
        item_permissions = None

        if include_validation:
            # Generate non-empty or empty validation dict
            use_empty_validation = draw(st.booleans())
            if use_empty_validation:
                validation = {}
            else:
                validation = {"_and": [{"status": {"_eq": "draft"}}]}

        if include_fields:
            # Generate non-empty or empty fields list
            use_empty_fields = draw(st.booleans())
            if use_empty_fields:
                fields = []
            else:
                fields = draw(
                    st.lists(
                        st.text(
                            alphabet=st.characters(whitelist_categories=("L",)),
                            min_size=1,
                            max_size=10,
                        ),
                        min_size=1,
                        max_size=5,
                    )
                )

        if include_permissions:
            # Generate non-empty or empty permissions dict
            use_empty_permissions = draw(st.booleans())
            if use_empty_permissions:
                item_permissions = {}
            else:
                item_permissions = {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}

        name = generate_permission_name(action, i + 1)
        custom_entries.append(
            CustomPermissionEntry(
                name=name,
                policy=policy_name,
                collection=col,
                action=action,
                validation=validation,
                fields=fields,
                permissions=item_permissions,
            )
        )

    # Use model_construct to bypass validators (we may have custom_permissions
    # referencing collections not in the groups, which is fine for serialization testing)
    config = DirectusACConfig.model_construct(
        collections=sorted(collection_names),
        roles=sorted(role_names),
        groups=groups,
        custom_permissions=custom_entries,
    )

    return config


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_serialization_key_order(config) -> None:
    """Property 9: Serialization key order and content (key order).

    For any DirectusACConfig with custom permissions, the serialized YAML SHALL
    maintain key order: collections, roles, groups, custom_permissions.

    **Validates: Requirements 4.2, 4.4**
    """
    from directus_ac.models import DirectusACConfig

    yaml_output = serialize_config(config)

    # Parse YAML preserving key order (Python 3.7+ dicts preserve insertion order)
    parsed = yaml.safe_load(yaml_output)

    # Verify all expected top-level keys are present
    assert "collections" in parsed, "Missing 'collections' key in serialized YAML"
    assert "roles" in parsed, "Missing 'roles' key in serialized YAML"
    assert "groups" in parsed, "Missing 'groups' key in serialized YAML"
    assert "custom_permissions" in parsed, (
        "Missing 'custom_permissions' key in serialized YAML when config has custom permissions"
    )

    # Verify key order by checking positions in the YAML string
    # Since yaml.dump with sort_keys=False preserves insertion order,
    # and Python dicts preserve insertion order, we verify the order of keys
    # in the raw YAML output
    top_level_keys = list(parsed.keys())
    expected_order = ["collections", "roles", "groups", "custom_permissions"]

    # Filter to only expected keys (in case there are others)
    actual_order = [k for k in top_level_keys if k in expected_order]
    assert actual_order == expected_order, (
        f"Top-level key order should be {expected_order}, got {actual_order}"
    )


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_serialization_custom_permission_content(config) -> None:
    """Property 9: Serialization key order and content (entry content).

    For any DirectusACConfig with custom permissions, each custom permission
    entry in the serialized YAML SHALL contain the policy name, collection,
    action, and only non-null/non-empty optional attributes.

    **Validates: Requirements 4.2, 4.4**
    """
    from directus_ac.models import DirectusACConfig

    yaml_output = serialize_config(config)
    parsed = yaml.safe_load(yaml_output)

    assert "custom_permissions" in parsed
    serialized_entries = parsed["custom_permissions"]

    assert len(serialized_entries) == len(config.custom_permissions), (
        f"Expected {len(config.custom_permissions)} entries, got {len(serialized_entries)}"
    )

    for i, (entry, serialized) in enumerate(zip(config.custom_permissions, serialized_entries)):
        # Required fields must always be present
        assert "name" in serialized, f"Entry {i} missing 'name'"
        assert "policy" in serialized, f"Entry {i} missing 'policy'"
        assert "collection" in serialized, f"Entry {i} missing 'collection'"
        assert "action" in serialized, f"Entry {i} missing 'action'"

        # Required field values must match the config entry
        assert serialized["name"] == entry.name, (
            f"Entry {i}: name mismatch: {serialized['name']} != {entry.name}"
        )
        assert serialized["policy"] == entry.policy, (
            f"Entry {i}: policy mismatch: {serialized['policy']} != {entry.policy}"
        )
        assert serialized["collection"] == entry.collection, (
            f"Entry {i}: collection mismatch: {serialized['collection']} != {entry.collection}"
        )
        assert serialized["action"] == entry.action, (
            f"Entry {i}: action mismatch: {serialized['action']} != {entry.action}"
        )

        # Optional attributes: only present when non-null AND non-empty
        # validation: present only if not None and not {}
        if entry.validation is not None and entry.validation != {}:
            assert "validation" in serialized, (
                f"Entry {i}: non-empty validation should be present in serialized output"
            )
            assert serialized["validation"] == entry.validation
        else:
            assert "validation" not in serialized, (
                f"Entry {i}: null or empty validation should NOT be present in serialized output, "
                f"but found: {serialized.get('validation')}"
            )

        # fields: present only if not None and not []
        if entry.fields is not None and entry.fields != []:
            assert "fields" in serialized, (
                f"Entry {i}: non-empty fields should be present in serialized output"
            )
            assert serialized["fields"] == entry.fields
        else:
            assert "fields" not in serialized, (
                f"Entry {i}: null or empty fields should NOT be present in serialized output, "
                f"but found: {serialized.get('fields')}"
            )

        # permissions: present only if not None and not {}
        if entry.permissions is not None and entry.permissions != {}:
            assert "permissions" in serialized, (
                f"Entry {i}: non-empty permissions should be present in serialized output"
            )
            assert serialized["permissions"] == entry.permissions
        else:
            assert "permissions" not in serialized, (
                f"Entry {i}: null or empty permissions should NOT be present in serialized output, "
                f"but found: {serialized.get('permissions')}"
            )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 6: Config parsing round-trip
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------


@given(config=_config_with_custom_permissions())
@settings(max_examples=100)
def test_config_parsing_round_trip(config) -> None:
    """Property 6: Config parsing round-trip.

    For any valid DirectusACConfig containing custom permissions, serializing it
    to YAML and parsing it back with load_config SHALL produce an equivalent
    custom_permissions list (same entries with same field values).

    **Validates: Requirements 3.1, 3.2**
    """
    import tempfile
    import os
    from directus_ac.config import load_config

    # Serialize the config to YAML
    yaml_output = serialize_config(config)

    # Write to a temporary file for load_config to read
    fd, config_path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml_output)

        # Parse it back
        loaded_config = load_config(config_path)
    finally:
        os.unlink(config_path)

    # Verify the custom_permissions list is equivalent
    assert len(loaded_config.custom_permissions) == len(config.custom_permissions), (
        f"Expected {len(config.custom_permissions)} custom permissions after round-trip, "
        f"got {len(loaded_config.custom_permissions)}"
    )

    for i, (original, loaded) in enumerate(
        zip(config.custom_permissions, loaded_config.custom_permissions)
    ):
        assert loaded.name == original.name, (
            f"Entry {i}: name mismatch after round-trip: "
            f"'{loaded.name}' != '{original.name}'"
        )
        assert loaded.policy == original.policy, (
            f"Entry {i}: policy mismatch after round-trip: "
            f"'{loaded.policy}' != '{original.policy}'"
        )
        assert loaded.collection == original.collection, (
            f"Entry {i}: collection mismatch after round-trip: "
            f"'{loaded.collection}' != '{original.collection}'"
        )
        assert loaded.action == original.action, (
            f"Entry {i}: action mismatch after round-trip: "
            f"'{loaded.action}' != '{original.action}'"
        )

        # For optional attributes, the round-trip should preserve non-null/non-empty
        # values and normalize null/empty values to None (since serialize omits them)
        if original.validation is not None and original.validation != {}:
            assert loaded.validation == original.validation, (
                f"Entry {i}: validation mismatch after round-trip: "
                f"{loaded.validation} != {original.validation}"
            )
        else:
            assert loaded.validation is None, (
                f"Entry {i}: expected validation to be None after round-trip "
                f"(original was {original.validation!r}), got {loaded.validation!r}"
            )

        if original.fields is not None and original.fields != []:
            assert loaded.fields == original.fields, (
                f"Entry {i}: fields mismatch after round-trip: "
                f"{loaded.fields} != {original.fields}"
            )
        else:
            assert loaded.fields is None, (
                f"Entry {i}: expected fields to be None after round-trip "
                f"(original was {original.fields!r}), got {loaded.fields!r}"
            )

        if original.permissions is not None and original.permissions != {}:
            assert loaded.permissions == original.permissions, (
                f"Entry {i}: permissions mismatch after round-trip: "
                f"{loaded.permissions} != {original.permissions}"
            )
        else:
            assert loaded.permissions is None, (
                f"Entry {i}: expected permissions to be None after round-trip "
                f"(original was {original.permissions!r}), got {loaded.permissions!r}"
            )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 7: Invalid custom permission entry detection
# Validates: Requirements 3.4, 3.6, 8.3
# ---------------------------------------------------------------------------

# Valid actions for custom permissions
_VALID_ACTIONS = ("create", "read", "update", "delete")

# Required fields for a custom permission entry
_REQUIRED_FIELDS = ("name", "policy", "collection", "action")

# Strategy for valid string field values (1-255 chars)
_valid_field_value = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
    min_size=1,
    max_size=50,
)

# Strategy for invalid action values: strings that are NOT valid actions
_invalid_action = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
).filter(lambda s: s.lower() not in _VALID_ACTIONS)


@st.composite
def _entry_missing_required_field(draw):
    """Generate a custom permission entry dict with one required field removed.

    Returns (entry_list, missing_field, index) where:
    - entry_list is a list containing valid entries before the invalid one
    - missing_field is the name of the field that was removed
    - index is the position of the invalid entry in the list
    """
    # Generate 0-3 valid entries before the invalid one
    num_valid_before = draw(st.integers(min_value=0, max_value=3))
    valid_entries = []
    for i in range(num_valid_before):
        action = draw(st.sampled_from(_VALID_ACTIONS))
        valid_entries.append({
            "name": f"{action.upper()}_C_{i + 1}",
            "policy": draw(_valid_field_value),
            "collection": draw(_valid_field_value),
            "action": action,
        })

    # Create an entry with one required field missing
    field_to_remove = draw(st.sampled_from(_REQUIRED_FIELDS))
    entry_action = draw(st.sampled_from(_VALID_ACTIONS))
    invalid_entry = {
        "name": f"{entry_action.upper()}_C_{num_valid_before + 1}",
        "policy": draw(_valid_field_value),
        "collection": draw(_valid_field_value),
        "action": entry_action,
    }
    del invalid_entry[field_to_remove]

    entry_list = valid_entries + [invalid_entry]
    return entry_list, field_to_remove, num_valid_before


@st.composite
def _entry_with_invalid_action(draw):
    """Generate a custom permission entry list where one entry has an invalid action.

    Returns (entry_list, invalid_action_value, index) where:
    - entry_list is a list containing valid entries before the invalid one
    - invalid_action_value is the invalid action string
    - index is the position of the invalid entry in the list
    """
    # Generate 0-3 valid entries before the invalid one
    num_valid_before = draw(st.integers(min_value=0, max_value=3))
    valid_entries = []
    for i in range(num_valid_before):
        action = draw(st.sampled_from(_VALID_ACTIONS))
        valid_entries.append({
            "name": f"{action.upper()}_C_{i + 1}",
            "policy": draw(_valid_field_value),
            "collection": draw(_valid_field_value),
            "action": action,
        })

    # Create an entry with an invalid action value
    bad_action = draw(_invalid_action)
    invalid_entry = {
        "name": f"READ_C_{num_valid_before + 1}",
        "policy": draw(_valid_field_value),
        "collection": draw(_valid_field_value),
        "action": bad_action,
    }

    entry_list = valid_entries + [invalid_entry]
    return entry_list, bad_action, num_valid_before


@given(data=_entry_missing_required_field())
@settings(max_examples=100)
def test_missing_required_field_raises_config_error(data) -> None:
    """Property 7: Invalid custom permission entry detection (missing field).

    For any custom permission entry that is missing a required field (`name`,
    `policy`, `collection`, or `action`), the config loader SHALL raise a
    `ConfigError` whose message identifies the specific problem and the entry
    index.

    **Validates: Requirements 3.4, 3.6, 8.3**
    """
    entry_list, missing_field, expected_index = data

    with pytest.raises(ConfigError) as exc_info:
        _parse_custom_permissions(entry_list)

    error_message = str(exc_info.value)

    # The error message must identify the entry index
    assert str(expected_index) in error_message, (
        f"Error message does not contain the entry index {expected_index}: "
        f"'{error_message}'"
    )

    # The error message must identify the missing field
    assert missing_field in error_message, (
        f"Error message does not identify the missing field '{missing_field}': "
        f"'{error_message}'"
    )

    # The error message must mention "missing required field"
    assert "missing required field" in error_message, (
        f"Error message does not contain 'missing required field': "
        f"'{error_message}'"
    )


@given(data=_entry_with_invalid_action())
@settings(max_examples=100)
def test_invalid_action_raises_config_error(data) -> None:
    """Property 7: Invalid custom permission entry detection (invalid action).

    For any custom permission entry that has an invalid action value (not one
    of create, read, update, delete), the config loader SHALL raise a
    `ConfigError` whose message identifies the specific problem and the entry
    index.

    **Validates: Requirements 3.4, 3.6, 8.3**
    """
    entry_list, invalid_action_value, expected_index = data

    with pytest.raises(ConfigError) as exc_info:
        _parse_custom_permissions(entry_list)

    error_message = str(exc_info.value)

    # The error message must identify the entry index
    assert str(expected_index) in error_message, (
        f"Error message does not contain the entry index {expected_index}: "
        f"'{error_message}'"
    )

    # The error message must identify the invalid action value
    assert invalid_action_value in error_message, (
        f"Error message does not contain the invalid action value "
        f"'{invalid_action_value}': '{error_message}'"
    )

    # The error message must mention "invalid action"
    assert "invalid action" in error_message, (
        f"Error message does not contain 'invalid action': "
        f"'{error_message}'"
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 10: Check command custom permission formatting
# Validates: Requirements 5.2, 5.3, 5.4
# ---------------------------------------------------------------------------


@st.composite
def _check_command_custom_permissions(draw):
    """Generate custom permissions with various attribute combinations for CheckCommand.

    Returns (permissions, policies) where all permissions are custom (have at
    least one non-default attribute) and policies map policy IDs to names.
    """
    # Generate 1-3 policies
    num_policies = draw(st.integers(min_value=1, max_value=3))
    policy_names = draw(
        st.lists(
            _policy_name,
            min_size=num_policies,
            max_size=num_policies,
            unique=True,
        )
    )
    policies = []
    for i, pname in enumerate(policy_names):
        policy_id = f"policy-{i}"
        policies.append(
            DirectusPolicy(id=policy_id, name=pname, roles=[f"role-{i}"])
        )

    # Generate 1-3 collections
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collection_names = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )

    # Generate 1-6 custom permissions with unique IDs
    num_perms = draw(st.integers(min_value=1, max_value=6))
    perm_ids = draw(
        st.lists(
            st.integers(min_value=1, max_value=100000),
            min_size=num_perms,
            max_size=num_perms,
            unique=True,
        )
    )

    # Field name strategy: lowercase letters only for simplicity
    _field_name = st.text(
        alphabet=st.characters(whitelist_categories=("Ll",)),
        min_size=1,
        max_size=10,
    )

    permissions = []
    for perm_id in perm_ids:
        policy = draw(st.sampled_from(policies))
        col_name = draw(st.sampled_from(collection_names))
        action = draw(_action)

        # Decide which attributes to set (at least one must be non-null to be custom)
        has_validation = draw(st.booleans())
        has_fields = draw(st.booleans())
        has_item_permissions = draw(st.booleans())

        # Ensure at least one is True
        if not (has_validation or has_fields or has_item_permissions):
            choice = draw(st.sampled_from(["validation", "fields", "permissions"]))
            if choice == "validation":
                has_validation = True
            elif choice == "fields":
                has_fields = True
            else:
                has_item_permissions = True

        validation = (
            {"_and": [{"status": {"_eq": "draft"}}]} if has_validation else None
        )
        fields = (
            draw(st.lists(_field_name, min_size=1, max_size=5))
            if has_fields
            else None
        )
        item_permissions = (
            {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}
            if has_item_permissions
            else None
        )

        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy.id,
                collection=col_name,
                action=action,
                validation=validation,
                fields=fields,
                permissions=item_permissions,
            )
        )

    return permissions, policies


@given(data=_check_command_custom_permissions())
@settings(max_examples=100)
def test_check_command_custom_permission_formatting(data) -> None:
    """Property 10: Check command custom permission formatting.

    For any custom permission displayed by CheckCommand, the output SHALL
    contain the Permission_Name (C_N) inline alongside standard actions,
    plus a "fields:(...)" indicator when fields is non-null, and
    "has validation"/"has item permissions" indicators when those attributes
    are non-null.

    **Validates: Requirements 5.2, 5.3, 5.4**
    """
    from directus_ac.check import CheckCommand

    permissions, policies = data

    # Build roles from the policies (each policy references a role)
    roles = []
    for policy in policies:
        for role_id in policy.roles:
            roles.append(DirectusRole(id=role_id, name=f"Role_{role_id}"))

    cmd = CheckCommand(client=None, enable_private_collections=True)  # type: ignore[arg-type]
    result = cmd._format_policies(permissions, policies, roles)

    # The output should start with "Policies"
    lines = result.split("\n")
    assert lines[0] == "Policies", (
        f"Expected header 'Policies', got: {lines[0]!r}"
    )

    # Since all generated permissions are custom, there should be no separate
    # "Custom Permissions" section - everything is inline
    assert "Custom Permissions" not in result

    # Sort permissions by id (same as the implementation does for counter assignment)
    sorted_perms = sorted(permissions, key=lambda p: p.id)

    # Verify each custom permission's C_N reference and indicators appear in the output
    for counter, perm in enumerate(sorted_perms, start=1):
        expected_name = generate_permission_name(perm.action, counter)

        # The C_N reference must appear in the output
        assert expected_name in result, (
            f"Expected permission name '{expected_name}' in output but not found"
        )

        # Find the collection line(s) containing this C_N reference
        ref_lines = [line for line in lines if expected_name in line]
        assert len(ref_lines) >= 1, (
            f"Expected at least one line containing '{expected_name}'"
        )

        # Check the line containing this reference for correct indicators
        for ref_line in ref_lines:
            # Check fields indicator
            if perm.fields is not None:
                expected_fields = f"fields:({','.join(perm.fields)})"
                assert expected_fields in ref_line, (
                    f"Expected '{expected_fields}' in line: {ref_line!r}"
                )

            # Check validation indicator
            if perm.validation is not None:
                assert "has validation" in ref_line, (
                    f"Expected 'has validation' in line: {ref_line!r}"
                )

            # Check item permissions indicator
            if perm.permissions is not None:
                assert "has item permissions" in ref_line, (
                    f"Expected 'has item permissions' in line: {ref_line!r}"
                )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 11: Update command create/update correctness
# Validates: Requirements 6.1, 6.2, 6.4
# ---------------------------------------------------------------------------


@st.composite
def _custom_perms_with_existing_state(draw):
    """Generate custom permission config entries and existing Directus permission state.

    Creates:
    - A set of custom permission config entries (CustomPermissionEntry)
    - A policy_name_to_id mapping
    - A set of existing Directus permissions (some with constraints, some without)

    The existing permissions are designed so that some will match config entries
    (triggering updates) and some won't (triggering creates).

    Returns (custom_entries, policy_name_to_id, existing_permissions).
    """
    # Generate 1-3 policy names with corresponding IDs
    num_policies = draw(st.integers(min_value=1, max_value=3))
    policy_names = draw(
        st.lists(
            _policy_name,
            min_size=num_policies,
            max_size=num_policies,
            unique=True,
        )
    )
    policy_name_to_id = {name: f"policy-id-{i}" for i, name in enumerate(policy_names)}

    # Generate 1-4 collection names
    num_collections = draw(st.integers(min_value=1, max_value=4))
    collection_names = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )

    actions = ["create", "read", "update", "delete"]

    # Generate 1-8 custom permission config entries
    num_entries = draw(st.integers(min_value=1, max_value=8))
    custom_entries: list[CustomPermissionEntry] = []
    for i in range(num_entries):
        policy_name = draw(st.sampled_from(policy_names))
        collection = draw(st.sampled_from(collection_names))
        action = draw(st.sampled_from(actions))

        # At least one optional attribute must be non-null for it to be a custom permission
        has_validation = draw(st.booleans())
        has_fields = draw(st.booleans())
        has_item_permissions = draw(st.booleans())

        if not (has_validation or has_fields or has_item_permissions):
            choice = draw(st.sampled_from(["validation", "fields", "permissions"]))
            if choice == "validation":
                has_validation = True
            elif choice == "fields":
                has_fields = True
            else:
                has_item_permissions = True

        validation = {"_and": [{"status": {"_eq": "draft"}}]} if has_validation else None
        fields = draw(
            st.lists(
                st.text(alphabet=st.characters(whitelist_categories=("Ll",)), min_size=1, max_size=10),
                min_size=1,
                max_size=5,
            )
        ) if has_fields else None
        item_permissions = {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]} if has_item_permissions else None

        custom_entries.append(
            CustomPermissionEntry(
                name=f"{action.upper()}_C_{i + 1}",
                policy=policy_name,
                collection=collection,
                action=action,
                validation=validation,
                fields=fields,
                permissions=item_permissions,
            )
        )

    # Generate existing Directus permissions:
    # Some will match config entries (same policy_id + collection + action with constraints)
    # Some will be unrelated
    existing_permissions: list[DirectusPermission] = []
    perm_id = 1

    # For each config entry, randomly decide if a matching existing permission exists
    for entry in custom_entries:
        should_exist = draw(st.booleans())
        if should_exist:
            policy_id = policy_name_to_id[entry.policy]
            # Create an existing permission with constraints (so it matches)
            existing_permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=policy_id,
                    collection=entry.collection,
                    action=entry.action,
                    validation={"_and": [{"old_rule": {"_eq": "value"}}]},
                    fields=None,
                    permissions=None,
                )
            )
            perm_id += 1

    # Add some unrelated existing permissions (standard ones without constraints)
    num_unrelated = draw(st.integers(min_value=0, max_value=3))
    for _ in range(num_unrelated):
        policy_id = draw(st.sampled_from(list(policy_name_to_id.values())))
        collection = draw(st.sampled_from(collection_names))
        action = draw(st.sampled_from(actions))
        existing_permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy_id,
                collection=collection,
                action=action,
                validation=None,
                fields=None,
                permissions=None,
            )
        )
        perm_id += 1

    return custom_entries, policy_name_to_id, existing_permissions


@given(data=_custom_perms_with_existing_state())
@settings(max_examples=100)
def test_update_command_create_update_correctness(data) -> None:
    """Property 11: Update command create/update correctness.

    For any set of custom permission config entries and existing Directus
    permission state, the PermissionManager SHALL create entries that don't
    exist and update entries that match (by policy_id + collection + action
    with non-null constraints), and the returned counts SHALL equal the number
    of POST and PATCH operations performed respectively.

    **Validates: Requirements 6.1, 6.2, 6.4**
    """
    from directus_ac.permissions import PermissionManager

    custom_entries, policy_name_to_id, existing_permissions = data

    # Build the custom_index the same way the implementation does:
    # Match by (policy_id, collection, action) where existing entry has constraints
    custom_index: dict[tuple[str, str, str], int] = {}
    for perm in existing_permissions:
        has_constraints = (
            perm.validation is not None
            or (perm.fields is not None and perm.fields != ["*"])
            or perm.permissions is not None
        )
        if has_constraints:
            key = (perm.policy, perm.collection, perm.action)
            custom_index[key] = perm.id

    # Compute expected creates and updates
    expected_creates = 0
    expected_updates = 0
    for entry in custom_entries:
        policy_id = policy_name_to_id[entry.policy]
        lookup_key = (policy_id, entry.collection, entry.action)
        if lookup_key in custom_index:
            expected_updates += 1
        else:
            expected_creates += 1

    # Mock the client
    mock_client = MagicMock()
    mock_client.get_permissions.return_value = existing_permissions
    mock_client.create_permission.return_value = DirectusPermission(
        id=999, policy="x", collection="x", action="x"
    )
    mock_client.update_permission.return_value = DirectusPermission(
        id=999, policy="x", collection="x", action="x"
    )

    manager = PermissionManager(mock_client)
    created_count, updated_count = manager.apply_custom_permissions(
        custom_entries, policy_name_to_id
    )

    # The returned counts SHALL equal the number of POST and PATCH operations
    assert created_count == expected_creates, (
        f"Expected {expected_creates} creates, got {created_count}. "
        f"Entries: {[(e.policy, e.collection, e.action) for e in custom_entries]}, "
        f"Existing custom index keys: {list(custom_index.keys())}"
    )
    assert updated_count == expected_updates, (
        f"Expected {expected_updates} updates, got {updated_count}. "
        f"Entries: {[(e.policy, e.collection, e.action) for e in custom_entries]}, "
        f"Existing custom index keys: {list(custom_index.keys())}"
    )

    # Verify the actual API calls match the counts
    assert mock_client.create_permission.call_count == expected_creates, (
        f"Expected {expected_creates} POST calls, got {mock_client.create_permission.call_count}"
    )
    assert mock_client.update_permission.call_count == expected_updates, (
        f"Expected {expected_updates} PATCH calls, got {mock_client.update_permission.call_count}"
    )

    # Verify that each create call used the correct policy_id, collection, action
    for call in mock_client.create_permission.call_args_list:
        args = call[0]
        kwargs = call[1]
        policy_id = args[0]
        collection = args[1]
        action = args[2]
        # The triple should NOT be in the custom_index (it's a create)
        lookup_key = (policy_id, collection, action)
        assert lookup_key not in custom_index, (
            f"Create call for {lookup_key} should not match existing custom permission"
        )

    # Verify that each update call used the correct permission_id from the index
    for call in mock_client.update_permission.call_args_list:
        args = call[0]
        permission_id = args[0]
        policy_id = args[1]
        collection = args[2]
        action = args[3]
        lookup_key = (policy_id, collection, action)
        assert lookup_key in custom_index, (
            f"Update call for {lookup_key} should match an existing custom permission"
        )
        assert custom_index[lookup_key] == permission_id, (
            f"Update call used permission_id {permission_id} but expected "
            f"{custom_index[lookup_key]} for key {lookup_key}"
        )
