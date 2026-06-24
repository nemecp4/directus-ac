"""Property-based test for counter assignment sequentiality.

Feature: custom-permissions-display, Property 2: Counter assignment is sequential by ascending permission ID
Validates: Requirements 1.3, 5.2

Property 2: For any list of custom permissions with distinct IDs, the counter
values assigned by the generator SHALL be a contiguous sequence starting at 1,
ordered by ascending permission ID.
"""
from __future__ import annotations

import re
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

# Collection names: non-empty, no directus_ prefix
_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
).filter(lambda s: not s.startswith("directus_"))

# Policy names: non-empty
_policy_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=30,
)

_action = st.sampled_from(["create", "read", "update", "delete"])

# Regex to extract the counter from an ACTION_C_N name
_COUNTER_RE = re.compile(r"^(?:CREATE|READ|UPDATE|DELETE)_C_(\d+)$")


@st.composite
def _custom_permissions_with_distinct_ids(draw):
    """Generate a Directus state with custom permissions having distinct IDs.

    All permissions are marked as custom (via non-null validation attribute)
    and have unique IDs. The generator will assign sequential counters to them
    in order of ascending permission ID.

    Returns (collections, roles, policies, permissions).
    """
    # Generate 1-3 policies with distinct names and associated roles
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
                # Mark as custom via non-null validation
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            )
        )

    return collections, roles, policies, permissions


# ---------------------------------------------------------------------------
# Feature: custom-permissions-display, Property 2
# Validates: Requirements 1.3, 5.2
# ---------------------------------------------------------------------------


@given(state=_custom_permissions_with_distinct_ids())
@settings(max_examples=200)
def test_counter_assignment_sequential_by_ascending_id(state) -> None:
    """Property 2: Counter assignment is sequential by ascending permission ID.

    For any list of custom permissions with distinct IDs, the counter values
    assigned by the generator SHALL be a contiguous sequence starting at 1,
    ordered by ascending permission ID.

    **Validates: Requirements 1.3, 5.2**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    # All permissions should be classified as custom (they all have non-null validation)
    # and all have resolvable policies, so all should appear in config.custom_permissions
    assert len(config.custom_permissions) == len(permissions), (
        f"Expected {len(permissions)} custom permissions, "
        f"got {len(config.custom_permissions)}"
    )

    # Sort input permissions by ID ascending - this is the expected assignment order
    sorted_perms = sorted(permissions, key=lambda p: p.id)

    # Extract counters from the generated names
    counters = []
    for entry in config.custom_permissions:
        match = _COUNTER_RE.match(entry.name)
        assert match is not None, (
            f"Custom permission name '{entry.name}' does not match ACTION_C_N pattern"
        )
        counters.append(int(match.group(1)))

    # Verify counters form a contiguous sequence starting at 1
    expected_counters = list(range(1, len(permissions) + 1))
    assert counters == expected_counters, (
        f"Counters should be a contiguous sequence {expected_counters}, "
        f"got {counters}"
    )

    # Verify that the counter assignment follows ascending permission ID order:
    # the entry at position i should correspond to the permission with the
    # (i+1)-th smallest ID
    for i, (entry, perm) in enumerate(zip(config.custom_permissions, sorted_perms)):
        expected_name = generate_permission_name(perm.action, i + 1)
        assert entry.name == expected_name, (
            f"Position {i}: expected name '{expected_name}' for perm id={perm.id}, "
            f"got '{entry.name}'. Perm IDs sorted: {[p.id for p in sorted_perms]}"
        )
        assert entry.collection == perm.collection, (
            f"Position {i}: expected collection '{perm.collection}', "
            f"got '{entry.collection}'"
        )
        assert entry.action == perm.action, (
            f"Position {i}: expected action '{perm.action}', "
            f"got '{entry.action}'"
        )
