"""Property-based tests for custom permission detection (Feature: custom-permissions).

Property 1: Custom permission detection correctness
Validates: Requirements 1.1, 1.2
"""
from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.generate import Generator
from directus_ac.models import (
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

# Simple field lists (non-null, not ["*"])
_custom_fields = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
        min_size=1,
        max_size=20,
    ),
    min_size=1,
    max_size=5,
).filter(lambda f: f != ["*"])

# Validation dicts (non-null)
_validation_dict = st.fixed_dictionaries(
    {"_and": st.just([{"status": {"_eq": "draft"}}])}
)

# Permissions dicts (non-null, item-level)
_permissions_dict = st.fixed_dictionaries(
    {"_and": st.just([{"author": {"_eq": "$CURRENT_USER"}}])}
)

# Actions
_action = st.sampled_from(["read", "create", "update", "delete"])

# Collection names
_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("directus_"))


@st.composite
def _permission_with_custom_attributes(draw) -> DirectusPermission:
    """Generate a DirectusPermission that has at least one custom attribute.

    This ensures the permission should be detected as custom based on its
    attributes alone (Requirement 1.1).
    """
    perm_id = draw(st.integers(min_value=1, max_value=100000))
    policy_id = draw(st.uuids().map(str))
    collection = draw(_collection_name)
    action = draw(_action)

    # At least one of these must be set to make it custom
    has_validation = draw(st.booleans())
    has_fields = draw(st.booleans())
    has_permissions = draw(st.booleans())

    # Ensure at least one is True
    if not (has_validation or has_fields or has_permissions):
        choice = draw(st.sampled_from(["validation", "fields", "permissions"]))
        if choice == "validation":
            has_validation = True
        elif choice == "fields":
            has_fields = True
        else:
            has_permissions = True

    validation = draw(_validation_dict) if has_validation else None
    fields = draw(_custom_fields) if has_fields else None
    permissions = draw(_permissions_dict) if has_permissions else None

    return DirectusPermission(
        id=perm_id,
        policy=policy_id,
        collection=collection,
        action=action,
        validation=validation,
        fields=fields,
        permissions=permissions,
    )


@st.composite
def _standard_permission(draw) -> DirectusPermission:
    """Generate a DirectusPermission that has NO custom attributes.

    This permission should NOT be detected as custom based on attributes alone.
    It has: validation=None, fields=None or ["*"], permissions=None.
    """
    perm_id = draw(st.integers(min_value=1, max_value=100000))
    policy_id = draw(st.uuids().map(str))
    collection = draw(_collection_name)
    action = draw(_action)

    # fields is either None or ["*"] (both are standard)
    fields = draw(st.sampled_from([None, ["*"]]))

    return DirectusPermission(
        id=perm_id,
        policy=policy_id,
        collection=collection,
        action=action,
        validation=None,
        fields=fields,
        permissions=None,
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 1: Custom permission detection correctness
# Validates: Requirements 1.1, 1.2
# ---------------------------------------------------------------------------


@given(perm=_permission_with_custom_attributes())
@settings(max_examples=100)
def test_custom_detection_attribute_based(perm: DirectusPermission) -> None:
    """Property 1 (part A): Attribute-based custom detection.

    For any DirectusPermission entry with a non-null validation, a fields value
    that is non-null and not equal to ["*"], or a non-null permissions attribute,
    the detection function SHALL classify it as custom.

    **Validates: Requirements 1.1, 1.2**
    """
    # Create a minimal Generator with a mock client
    client = MagicMock()
    generator = Generator(client, include_system=False)

    # The permission should be detected as custom by attribute check
    assert generator._is_custom_permission(perm), (
        f"Permission with validation={perm.validation}, fields={perm.fields}, "
        f"permissions={perm.permissions} should be classified as custom"
    )


@given(perm=_standard_permission())
@settings(max_examples=100)
def test_standard_detection_attribute_based(perm: DirectusPermission) -> None:
    """Property 1 (part B): Standard permission non-detection.

    For any DirectusPermission entry with validation=None, fields=None or ["*"],
    and permissions=None, the detection function SHALL NOT classify it as custom
    based on attributes alone.

    **Validates: Requirements 1.1, 1.2**
    """
    client = MagicMock()
    generator = Generator(client, include_system=False)

    # The permission should NOT be detected as custom by attribute check
    assert not generator._is_custom_permission(perm), (
        f"Permission with validation={perm.validation}, fields={perm.fields}, "
        f"permissions={perm.permissions} should NOT be classified as custom"
    )


@st.composite
def _permissions_with_duplicates(draw):
    """Generate a set of permissions where some share the same (policy, collection, action) triple.

    Returns (all_permissions, duplicate_ids) where duplicate_ids is the set of
    permission IDs that share a triple with at least one other entry.
    """
    # Generate a shared triple
    shared_policy = draw(st.uuids().map(str))
    shared_collection = draw(_collection_name)
    shared_action = draw(_action)

    # Generate 2-4 permissions sharing this triple (all should be marked custom)
    dup_count = draw(st.integers(min_value=2, max_value=4))
    duplicate_perms = []
    for i in range(dup_count):
        # These may or may not have custom attributes - doesn't matter,
        # they should all be marked custom due to sharing a triple
        fields = draw(st.sampled_from([None, ["*"]]))
        duplicate_perms.append(
            DirectusPermission(
                id=i + 1,
                policy=shared_policy,
                collection=shared_collection,
                action=shared_action,
                validation=None,
                fields=fields,
                permissions=None,
            )
        )

    duplicate_ids = {p.id for p in duplicate_perms}

    # Generate some unique standard permissions (different triples, no custom attrs)
    unique_count = draw(st.integers(min_value=0, max_value=5))
    unique_perms = []
    used_triples = {(shared_policy, shared_collection, shared_action)}

    for i in range(unique_count):
        policy = draw(st.uuids().map(str))
        collection = draw(_collection_name)
        action = draw(_action)
        triple = (policy, collection, action)

        # Ensure this triple is unique
        if triple in used_triples:
            continue
        used_triples.add(triple)

        unique_perms.append(
            DirectusPermission(
                id=100 + i,
                policy=policy,
                collection=collection,
                action=action,
                validation=None,
                fields=draw(st.sampled_from([None, ["*"]])),
                permissions=None,
            )
        )

    all_permissions = duplicate_perms + unique_perms
    unique_standard_ids = {p.id for p in unique_perms}

    return all_permissions, duplicate_ids, unique_standard_ids


@given(data=_permissions_with_duplicates())
@settings(max_examples=100)
def test_custom_detection_duplicate_triples(data) -> None:
    """Property 1 (part C): Duplicate triple detection.

    When multiple permission entries share the same (policy, collection, action)
    triple, ALL entries in that combination SHALL be classified as custom,
    regardless of their individual attributes.

    **Validates: Requirements 1.1, 1.2**
    """
    all_permissions, duplicate_ids, unique_standard_ids = data

    client = MagicMock()
    generator = Generator(client, include_system=False)

    # Run the full detection logic
    detected_custom_ids = generator._detect_custom_permission_ids(all_permissions)

    # All duplicate IDs should be detected as custom
    assert duplicate_ids.issubset(detected_custom_ids), (
        f"Duplicate triple permissions {duplicate_ids} should all be classified as custom, "
        f"but detected custom IDs are {detected_custom_ids}"
    )

    # Unique standard permissions (no custom attrs, unique triple) should NOT be custom
    for uid in unique_standard_ids:
        assert uid not in detected_custom_ids, (
            f"Standard permission with unique triple (id={uid}) should NOT be "
            f"classified as custom"
        )


@st.composite
def _mixed_permissions_state(draw):
    """Generate a mixed set of permissions with both custom and standard entries.

    Returns (permissions, expected_custom_ids) where expected_custom_ids is the
    set of IDs that should be classified as custom.
    """
    # Use a fixed policy and collection pool for simplicity
    policy_ids = draw(
        st.lists(st.uuids().map(str), min_size=1, max_size=3, unique=True)
    )
    collections = draw(
        st.lists(_collection_name, min_size=1, max_size=3, unique=True)
    )
    actions = ["read", "create", "update", "delete"]

    permissions: list[DirectusPermission] = []
    perm_id = 1

    # Generate some standard permissions with unique triples
    standard_count = draw(st.integers(min_value=1, max_value=5))
    used_triples: set[tuple[str, str, str]] = set()

    for _ in range(standard_count):
        policy = draw(st.sampled_from(policy_ids))
        collection = draw(st.sampled_from(collections))
        action = draw(st.sampled_from(actions))
        triple = (policy, collection, action)

        if triple in used_triples:
            continue
        used_triples.add(triple)

        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy,
                collection=collection,
                action=action,
                validation=None,
                fields=draw(st.sampled_from([None, ["*"]])),
                permissions=None,
            )
        )
        perm_id += 1

    standard_ids = {p.id for p in permissions}

    # Generate some attribute-based custom permissions (unique triples)
    custom_attr_count = draw(st.integers(min_value=0, max_value=3))
    custom_attr_ids: set[int] = set()

    for _ in range(custom_attr_count):
        policy = draw(st.sampled_from(policy_ids))
        collection = draw(st.sampled_from(collections))
        action = draw(st.sampled_from(actions))
        triple = (policy, collection, action)

        if triple in used_triples:
            continue
        used_triples.add(triple)

        # At least one custom attribute
        choice = draw(st.sampled_from(["validation", "fields", "permissions"]))
        validation = draw(_validation_dict) if choice == "validation" else None
        fields = draw(_custom_fields) if choice == "fields" else None
        item_perms = draw(_permissions_dict) if choice == "permissions" else None

        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy,
                collection=collection,
                action=action,
                validation=validation,
                fields=fields,
                permissions=item_perms,
            )
        )
        custom_attr_ids.add(perm_id)
        perm_id += 1

    # Generate duplicate-triple permissions (pick a new triple, add 2+ entries)
    should_add_duplicates = draw(st.booleans())
    duplicate_ids: set[int] = set()

    if should_add_duplicates:
        dup_policy = draw(st.sampled_from(policy_ids))
        dup_collection = draw(st.sampled_from(collections))
        dup_action = draw(st.sampled_from(actions))
        dup_triple = (dup_policy, dup_collection, dup_action)

        # Check if this triple already exists - if so, those existing entries
        # also become custom due to duplication
        existing_with_triple = [
            p for p in permissions
            if (p.policy, p.collection, p.action) == dup_triple
        ]

        dup_count = draw(st.integers(min_value=2, max_value=3))
        # If there's already one entry with this triple, we only need 1 more
        if existing_with_triple:
            dup_count = max(1, dup_count - len(existing_with_triple))

        for _ in range(dup_count):
            permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=dup_policy,
                    collection=dup_collection,
                    action=dup_action,
                    validation=None,
                    fields=None,
                    permissions=None,
                )
            )
            duplicate_ids.add(perm_id)
            perm_id += 1

        # All entries sharing this triple are custom (including pre-existing ones)
        for p in existing_with_triple:
            duplicate_ids.add(p.id)

    # Compute expected custom IDs
    expected_custom_ids = custom_attr_ids | duplicate_ids

    return permissions, expected_custom_ids, standard_ids - duplicate_ids


@given(data=_mixed_permissions_state())
@settings(max_examples=100)
def test_custom_detection_mixed_state(data) -> None:
    """Property 1 (part D): Mixed state detection correctness.

    For any set of DirectusPermission entries, the detection function SHALL
    classify a permission as custom if and only if it has a non-null validation,
    a fields value that is non-null and not equal to ["*"], a non-null permissions
    attribute, OR it shares a (policy, collection, action) triple with at least
    one other permission entry in the set.

    **Validates: Requirements 1.1, 1.2**
    """
    permissions, expected_custom_ids, expected_standard_ids = data

    client = MagicMock()
    generator = Generator(client, include_system=False)

    detected_custom_ids = generator._detect_custom_permission_ids(permissions)

    # All expected custom IDs should be detected
    assert expected_custom_ids.issubset(detected_custom_ids), (
        f"Expected custom IDs {expected_custom_ids} should be subset of "
        f"detected {detected_custom_ids}"
    )

    # All expected standard IDs should NOT be detected as custom
    for sid in expected_standard_ids:
        assert sid not in detected_custom_ids, (
            f"Standard permission id={sid} should NOT be classified as custom"
        )
