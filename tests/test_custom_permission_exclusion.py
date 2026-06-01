"""Property-based tests for custom permission exclusion from groups.

Feature: custom-permissions, Property 2: Custom permission exclusion from groups
Validates: Requirements 1.3, 1.4

For any Directus state containing a mix of standard and custom permissions,
expanding the generated config's `groups` section back into (policy_id,
collection, action) triples SHALL never include any triple that was classified
as a custom permission.
"""
from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.generate import Generator, REVERSE_ACTION_MAP
from directus_ac.models import (
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)
from directus_ac.permissions import ACTION_MAP


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

_collection_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("directus_"))

_action = st.sampled_from(["create", "read", "update", "delete"])

# Validation dicts (non-null)
_validation_dict = st.fixed_dictionaries(
    {"_and": st.just([{"status": {"_eq": "draft"}}])}
)

# Custom fields (non-null, not ["*"])
_custom_fields = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
        min_size=1,
        max_size=10,
    ),
    min_size=1,
    max_size=5,
).filter(lambda f: f != ["*"])

# Permissions dicts (non-null, item-level)
_permissions_dict = st.fixed_dictionaries(
    {"_and": st.just([{"author": {"_eq": "$CURRENT_USER"}}])}
)


@st.composite
def _mixed_standard_and_custom_state(draw):
    """Generate a Directus state with both standard and custom permissions.

    Returns (collections, roles, policies, permissions, custom_triples) where:
    - custom_triples is the set of (policy_id, collection, action) triples
      that should be classified as custom permissions.
    - The state includes both standard permissions (no custom attributes,
      unique triples) and custom permissions (with attributes or duplicate triples).
    """
    # Generate 1-3 roles with unique names
    num_roles = draw(st.integers(min_value=1, max_value=3))
    role_names = [f"role_{i}" for i in range(num_roles)]
    roles = [
        DirectusRole(id=f"role-{i}", name=role_names[i])
        for i in range(num_roles)
    ]

    # Generate 1:1 policies for roles
    policies = [
        DirectusPolicy(
            id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id]
        )
        for role in roles
    ]
    policy_ids = [p.id for p in policies]

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

    permissions: list[DirectusPermission] = []
    perm_id = 1
    used_triples: set[tuple[str, str, str]] = set()
    custom_triples: set[tuple[str, str, str]] = set()

    # Generate standard permissions (unique triples, no custom attributes)
    num_standard = draw(st.integers(min_value=1, max_value=8))
    for _ in range(num_standard):
        policy_id = draw(st.sampled_from(policy_ids))
        col = draw(st.sampled_from(collection_names))
        action = draw(_action)
        triple = (policy_id, col, action)

        if triple in used_triples:
            continue
        used_triples.add(triple)

        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy_id,
                collection=col,
                action=action,
                validation=None,
                fields=draw(st.sampled_from([None, ["*"]])),
                permissions=None,
            )
        )
        perm_id += 1

    # Generate attribute-based custom permissions (unique triples, with custom attrs)
    num_custom_attr = draw(st.integers(min_value=1, max_value=5))
    for _ in range(num_custom_attr):
        policy_id = draw(st.sampled_from(policy_ids))
        col = draw(st.sampled_from(collection_names))
        action = draw(_action)
        triple = (policy_id, col, action)

        if triple in used_triples:
            continue
        used_triples.add(triple)

        # Make it custom via at least one attribute
        make_via = draw(st.sampled_from(["validation", "fields", "permissions"]))
        validation = draw(_validation_dict) if make_via == "validation" else None
        fields = draw(_custom_fields) if make_via == "fields" else None
        item_perms = draw(_permissions_dict) if make_via == "permissions" else None

        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy_id,
                collection=col,
                action=action,
                validation=validation,
                fields=fields,
                permissions=item_perms,
            )
        )
        custom_triples.add(triple)
        perm_id += 1

    # Generate duplicate-triple custom permissions (same triple appears 2+ times)
    should_add_duplicates = draw(st.booleans())
    if should_add_duplicates and policy_ids and collection_names:
        dup_policy_id = draw(st.sampled_from(policy_ids))
        dup_col = draw(st.sampled_from(collection_names))
        dup_action = draw(_action)
        dup_triple = (dup_policy_id, dup_col, dup_action)

        # If this triple was already used as standard, it becomes custom now
        # due to duplication
        dup_count = draw(st.integers(min_value=2, max_value=3))
        if dup_triple in used_triples:
            # Already one entry exists; add one more to make it a duplicate
            dup_count = 1

        for _ in range(dup_count):
            permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=dup_policy_id,
                    collection=dup_col,
                    action=dup_action,
                    validation=None,
                    fields=None,
                    permissions=None,
                )
            )
            perm_id += 1

        custom_triples.add(dup_triple)
        used_triples.add(dup_triple)

    return collections, roles, policies, permissions, custom_triples


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 2: Custom permission exclusion from groups
# Validates: Requirements 1.3, 1.4
# ---------------------------------------------------------------------------


@given(state=_mixed_standard_and_custom_state())
@settings(max_examples=100)
def test_custom_permission_exclusion_from_groups(state) -> None:
    """Property 2: Custom permission exclusion from groups.

    For any Directus state containing a mix of standard and custom permissions,
    expanding the generated config's `groups` section back into (policy_id,
    collection, action) triples SHALL never include any triple that was
    classified as a custom permission.

    **Validates: Requirements 1.3, 1.4**
    """
    collections, roles, policies, permissions, custom_triples = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    # Build role_name -> role_id mapping
    role_name_to_id = {role.name: role.id for role in roles}

    # Build role_id -> policy_id mapping
    role_id_to_policy_id = {
        role.id: f"policy-{role.id}" for role in roles
    }

    # Expand the groups section back into (policy_id, collection, action) triples
    groups_triples: set[tuple[str, str, str]] = set()
    for group in config.groups:
        for collection in group.collections:
            for role_name, keywords in group.permissions.items():
                role_id = role_name_to_id.get(role_name)
                if role_id is None:
                    continue
                policy_id = role_id_to_policy_id.get(role_id)
                if policy_id is None:
                    continue
                for keyword in keywords:
                    action = ACTION_MAP[keyword.value]
                    groups_triples.add((policy_id, collection, action))

    # Verify: no custom permission triple appears in the groups expansion
    overlap = groups_triples & custom_triples
    assert overlap == set(), (
        f"Custom permission triples found in groups section:\n"
        f"  Overlap: {overlap}\n"
        f"  Custom triples: {custom_triples}\n"
        f"  Groups triples: {groups_triples}"
    )


@given(state=_mixed_standard_and_custom_state())
@settings(max_examples=100)
def test_standard_permissions_preserved_in_groups(state) -> None:
    """Property 2 (supplementary): Standard permissions remain in groups.

    For any Directus state, standard permissions (those NOT classified as custom)
    SHALL still appear in the groups section. This verifies that the exclusion
    logic does not accidentally remove standard permissions.

    **Validates: Requirements 1.3, 1.4**
    """
    collections, roles, policies, permissions, custom_triples = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)

    # Determine which permission IDs are custom using the Generator's detection
    custom_ids = generator._detect_custom_permission_ids(permissions)

    # Run generation
    config = generator.generate()

    # Build role_name -> role_id and role_id -> policy_id mappings
    role_name_to_id = {role.name: role.id for role in roles}
    role_id_to_policy_id = {role.id: f"policy-{role.id}" for role in roles}
    policy_to_role_ids = {p.id: p.roles for p in policies}
    role_id_to_name = {role.id: role.name for role in roles}
    collection_names = {c.collection for c in collections}

    # Compute expected standard triples (those that should appear in groups)
    expected_standard_triples: set[tuple[str, str, str]] = set()
    for perm in permissions:
        if perm.id in custom_ids:
            continue
        if perm.collection not in collection_names:
            continue
        if perm.action not in REVERSE_ACTION_MAP:
            continue
        role_ids = policy_to_role_ids.get(perm.policy, [])
        for role_id in role_ids:
            if role_id in role_id_to_name:
                expected_standard_triples.add(
                    (perm.policy, perm.collection, perm.action)
                )

    # Expand the groups section back into triples
    groups_triples: set[tuple[str, str, str]] = set()
    for group in config.groups:
        for collection in group.collections:
            for role_name, keywords in group.permissions.items():
                role_id = role_name_to_id.get(role_name)
                if role_id is None:
                    continue
                policy_id = role_id_to_policy_id.get(role_id)
                if policy_id is None:
                    continue
                for keyword in keywords:
                    action = ACTION_MAP[keyword.value]
                    groups_triples.add((policy_id, collection, action))

    # All expected standard triples should be present in groups
    missing = expected_standard_triples - groups_triples
    assert missing == set(), (
        f"Standard permission triples missing from groups section:\n"
        f"  Missing: {missing}\n"
        f"  Expected standard: {expected_standard_triples}\n"
        f"  Groups triples: {groups_triples}"
    )
