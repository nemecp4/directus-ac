"""Property-based tests for counter assignment determinism and uniqueness.

Feature: custom-permissions, Property 3: Counter assignment determinism and uniqueness
Validates: Requirements 2.2, 2.3

Property 3: For any set of custom permissions, the counter values SHALL be
assigned as a single global sequence starting at 1, where all custom permissions
are sorted by their Directus permission `id` (ascending) and assigned consecutive
counter values, resulting in all generated Permission_Name values being distinct.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.generate import Generator, generate_permission_name
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

# Policy names: non-empty strings
_policy_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
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
def _custom_permissions_with_various_ids(draw):
    """Generate a Directus state with custom permissions having various IDs.

    All permissions are custom (via non-null validation attribute) and have
    unique IDs drawn from a wide range to test ordering behavior.

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

    # Generate 2-15 custom permissions with unique IDs from a wide range
    num_perms = draw(st.integers(min_value=2, max_value=15))
    perm_ids = draw(
        st.lists(
            st.integers(min_value=1, max_value=100000),
            min_size=num_perms,
            max_size=num_perms,
            unique=True,
        )
    )

    permissions = []
    for perm_id in perm_ids:
        policy = draw(st.sampled_from(policies))
        col_name = draw(st.sampled_from(collection_names))
        action = draw(_action)
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


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 3: Counter assignment determinism and uniqueness
# Validates: Requirements 2.2, 2.3
# ---------------------------------------------------------------------------


@given(state=_custom_permissions_with_various_ids())
@settings(max_examples=200)
def test_counter_global_sequence_starts_at_1_and_increments(state) -> None:
    """Property 3: Counter assignment is a global sequence starting at 1.

    For any set of custom permissions, the counter SHALL start at 1 and
    increment by 1 for each custom permission, assigned by ascending
    Directus permission `id`.

    **Validates: Requirements 2.2, 2.3**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    # All permissions have resolvable policies, so all should appear
    assert len(config.custom_permissions) == len(permissions), (
        f"Expected {len(permissions)} custom permissions, "
        f"got {len(config.custom_permissions)}"
    )

    # Verify counter starts at 1 and increments by 1
    for i, entry in enumerate(config.custom_permissions, start=1):
        expected_name = f"C_{i}"
        assert entry.name == expected_name, (
            f"Entry at position {i} should have name '{expected_name}', "
            f"got '{entry.name}'. "
            f"All names: {[e.name for e in config.custom_permissions]}"
        )


@given(state=_custom_permissions_with_various_ids())
@settings(max_examples=200)
def test_counter_assigned_by_ascending_permission_id(state) -> None:
    """Property 3: Counter values assigned by ascending Directus permission id.

    For any set of custom permissions, the permission with the lowest `id`
    SHALL receive counter 1, the next lowest `id` SHALL receive counter 2,
    and so on.

    **Validates: Requirements 2.2, 2.3**
    """
    collections, roles, policies, permissions = state

    # Build policy_id -> name mapping for verification
    policy_id_to_name = {p.id: p.name for p in policies}

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    # Sort permissions by id ascending — this is the expected assignment order
    sorted_perms = sorted(permissions, key=lambda p: p.id)

    # Verify each entry matches the expected permission in sorted order
    for i, (entry, perm) in enumerate(
        zip(config.custom_permissions, sorted_perms), start=1
    ):
        expected_name = f"C_{i}"
        assert entry.name == expected_name, (
            f"Counter {i} (perm id={perm.id}) should have name "
            f"'{expected_name}', got '{entry.name}'"
        )
        assert entry.collection == perm.collection, (
            f"Counter {i} (perm id={perm.id}) should have collection "
            f"'{perm.collection}', got '{entry.collection}'"
        )
        assert entry.action == perm.action, (
            f"Counter {i} (perm id={perm.id}) should have action "
            f"'{perm.action}', got '{entry.action}'"
        )
        assert entry.policy == policy_id_to_name[perm.policy], (
            f"Counter {i} (perm id={perm.id}) should have policy "
            f"'{policy_id_to_name[perm.policy]}', got '{entry.policy}'"
        )


@given(state=_custom_permissions_with_various_ids())
@settings(max_examples=200)
def test_all_permission_names_are_distinct(state) -> None:
    """Property 3: All generated Permission_Name values are distinct.

    For any set of custom permissions, the global counter sequence guarantees
    that no two custom permissions share the same Permission_Name.

    **Validates: Requirements 2.2, 2.3**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    names = [entry.name for entry in config.custom_permissions]

    # All names must be unique
    assert len(names) == len(set(names)), (
        f"Duplicate permission names found: "
        f"{[n for n in names if names.count(n) > 1]}"
    )


@given(state=_custom_permissions_with_various_ids())
@settings(max_examples=200)
def test_counter_assignment_is_deterministic(state) -> None:
    """Property 3: Running generate() twice with the same input produces the same names.

    For any set of custom permissions, the counter assignment SHALL be
    deterministic — calling generate() multiple times with the same input
    SHALL produce identical Permission_Name values.

    **Validates: Requirements 2.2, 2.3**
    """
    collections, roles, policies, permissions = state

    # First run
    mock_client_1 = _make_mock_client(collections, roles, permissions, policies)
    generator_1 = Generator(mock_client_1, include_system=True)
    config_1 = generator_1.generate()

    # Second run with same input
    mock_client_2 = _make_mock_client(collections, roles, permissions, policies)
    generator_2 = Generator(mock_client_2, include_system=True)
    config_2 = generator_2.generate()

    # Both runs must produce the same names in the same order
    names_1 = [entry.name for entry in config_1.custom_permissions]
    names_2 = [entry.name for entry in config_2.custom_permissions]

    assert names_1 == names_2, (
        f"Determinism violated: first run produced {names_1}, "
        f"second run produced {names_2}"
    )

    # Also verify the full entries match (not just names)
    for i, (e1, e2) in enumerate(
        zip(config_1.custom_permissions, config_2.custom_permissions)
    ):
        assert e1.name == e2.name, f"Entry {i}: name mismatch"
        assert e1.policy == e2.policy, f"Entry {i}: policy mismatch"
        assert e1.collection == e2.collection, f"Entry {i}: collection mismatch"
        assert e1.action == e2.action, f"Entry {i}: action mismatch"
