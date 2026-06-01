"""Property-based tests for the Generator and Serializer (directus-ac-generate)."""
from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.generate import Generator, REVERSE_ACTION_MAP, KEYWORD_ORDER
from directus_ac.models import (
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
    PermissionKeyword,
)
from directus_ac.permissions import ACTION_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    collections: list[DirectusCollection],
    roles: list[DirectusRole],
    permissions: list[DirectusPermission],
    policies: list[DirectusPolicy] | None = None,
) -> MagicMock:
    """Create a mock DirectusClient with configured return values.

    If policies is None, auto-generates a 1:1 policy per role.
    """
    if policies is None:
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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Collection names: non-empty, no newlines, no directus_ prefix (user collections)
_user_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
).filter(lambda s: not s.startswith("directus_"))

# Role names: non-empty, no newlines
_role_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)


# ---------------------------------------------------------------------------
# Feature: directus-ac-generate, Property 4: Grouping correctness
# Validates: Requirements 4.3, 4.4, 4.5, 4.7
# ---------------------------------------------------------------------------


@st.composite
def generate_directus_state(draw):
    """Generate a consistent Directus state: collections, roles, policies, and permissions.

    Returns (collections, roles, policies, permissions) where:
    - collections are non-system collection names
    - roles have unique IDs and names
    - policies link 1:1 to roles
    - permissions reference only known policy IDs and collection names with valid actions
    """
    # Generate non-system collection names
    collection_names = draw(
        st.lists(
            _user_collection_name,
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    # Generate roles with unique IDs and names
    role_count = draw(st.integers(min_value=1, max_value=5))
    role_ids = draw(
        st.lists(
            st.uuids().map(str),
            min_size=role_count,
            max_size=role_count,
            unique=True,
        )
    )
    role_names = draw(
        st.lists(
            _role_name,
            min_size=role_count,
            max_size=role_count,
            unique=True,
        )
    )
    roles = [
        DirectusRole(id=rid, name=rname)
        for rid, rname in zip(role_ids, role_names)
    ]

    # Generate 1:1 policies for roles
    policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in roles
    ]
    policy_ids = [p.id for p in policies]

    collections = [DirectusCollection(collection=name) for name in collection_names]

    # Build all possible (policy_id, collection, action) triples
    all_triples = [
        (policy_id, col_name, action)
        for policy_id in policy_ids
        for col_name in collection_names
        for action in ["read", "create", "update", "delete"]
    ]

    # Pick a non-empty subset
    n = draw(st.integers(min_value=1, max_value=min(len(all_triples), 30)))
    chosen = draw(
        st.lists(
            st.sampled_from(all_triples),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    permissions = [
        DirectusPermission(id=i + 1, policy=policy_id, collection=collection, action=action)
        for i, (policy_id, collection, action) in enumerate(chosen)
    ]

    return collections, roles, policies, permissions


@given(state=generate_directus_state())
@settings(max_examples=100)
def test_grouping_correctness(state) -> None:
    """Property 4: Grouping correctness.

    For any set of permissions (after filtering), the Generator SHALL produce
    exactly one group per distinct collection, where each group's `collections`
    field is a single-element list containing that collection name, and each
    group's `permissions` map correctly reflects all role-action pairs for that
    collection.

    **Validates: Requirements 4.3, 4.4, 4.5, 4.7**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies=policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Build policy_id -> role_ids and role_id -> name maps
    policy_to_role_ids: dict[str, list[str]] = {p.id: p.roles for p in policies}
    role_id_to_name = {role.id: role.name for role in roles}

    # Compute expected grouping from the input permissions
    expected_groups: dict[str, dict[str, set[PermissionKeyword]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for perm in permissions:
        keyword = REVERSE_ACTION_MAP.get(perm.action)
        if keyword is None:
            continue
        role_ids = policy_to_role_ids.get(perm.policy, [])
        for role_id in role_ids:
            role_name = role_id_to_name.get(role_id)
            if role_name is None:
                continue
            expected_groups[perm.collection][role_name].add(keyword)

    # Assert exactly one group per distinct collection
    group_collections = [g.collections[0] for g in config.groups]
    assert len(group_collections) == len(set(group_collections)), (
        "Duplicate collection found in groups"
    )
    assert set(group_collections) == set(expected_groups.keys()), (
        f"Groups don't match expected collections.\n"
        f"Got: {set(group_collections)}\n"
        f"Expected: {set(expected_groups.keys())}"
    )

    # Assert each group's `collections` field is a single-element list
    for group in config.groups:
        assert len(group.collections) == 1, (
            f"Group should have exactly one collection, got {group.collections}"
        )

    # Assert each group's `permissions` map correctly reflects all role-action pairs
    for group in config.groups:
        collection_name = group.collections[0]
        expected_perms = expected_groups[collection_name]

        # Same set of roles
        assert set(group.permissions.keys()) == set(expected_perms.keys()), (
            f"For collection '{collection_name}', roles don't match.\n"
            f"Got: {set(group.permissions.keys())}\n"
            f"Expected: {set(expected_perms.keys())}"
        )

        # For each role, same set of keywords
        for role_name, expected_keywords in expected_perms.items():
            actual_keywords = set(group.permissions[role_name])
            assert actual_keywords == expected_keywords, (
                f"For collection '{collection_name}', role '{role_name}', "
                f"keywords don't match.\n"
                f"Got: {actual_keywords}\n"
                f"Expected: {expected_keywords}"
            )


# ---------------------------------------------------------------------------
# Feature: directus-ac-generate, Property 5: Orphan permission exclusion
# Validates: Requirements 4.8
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=st.data())
def test_orphan_permission_exclusion(data: st.DataObject) -> None:
    """Property 5: Orphan permission exclusion.

    For any set of permissions where some reference policy IDs not linked to
    any known role, the Generator SHALL exclude those orphan permissions from
    the output, and the resulting config SHALL contain no references to the
    orphan policy IDs.

    **Validates: Requirements 4.8**
    """
    # Generate known roles (these will be in the roles list)
    known_roles = data.draw(
        st.lists(
            st.builds(
                DirectusRole,
                id=st.uuids().map(str),
                name=_role_name,
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda r: r.id,
        )
    )
    known_role_ids = {role.id for role in known_roles}

    # Generate 1:1 policies for known roles
    known_policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in known_roles
    ]
    known_policy_ids = {p.id for p in known_policies}

    # Generate orphan policy IDs (NOT linked to any known role)
    orphan_policy_ids = data.draw(
        st.lists(
            st.uuids().map(lambda u: f"orphan-policy-{u}"),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    # Generate collections
    collections = data.draw(
        st.lists(
            _user_collection_name,
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    # Generate permissions referencing known policies (valid permissions)
    valid_permissions = data.draw(
        st.lists(
            st.builds(
                DirectusPermission,
                id=st.integers(min_value=1, max_value=10000),
                policy=st.sampled_from([p.id for p in known_policies]),
                collection=st.sampled_from(collections),
                action=st.sampled_from(["read", "create", "update", "delete"]),
            ),
            min_size=0,
            max_size=10,
        )
    )

    # Generate permissions referencing orphan policy IDs (should be excluded)
    orphan_permissions = data.draw(
        st.lists(
            st.builds(
                DirectusPermission,
                id=st.integers(min_value=10001, max_value=20000),
                policy=st.sampled_from(orphan_policy_ids),
                collection=st.sampled_from(collections),
                action=st.sampled_from(["read", "create", "update", "delete"]),
            ),
            min_size=1,
            max_size=10,
        )
    )

    all_permissions = valid_permissions + orphan_permissions

    # Build mock client
    directus_collections = [DirectusCollection(collection=c) for c in collections]
    client = _make_mock_client(
        directus_collections, known_roles, all_permissions, policies=known_policies
    )

    # Run Generator
    generator = Generator(client, include_system=True)
    config = generator.generate()

    # Assert: no orphan policy IDs appear as role names in the config
    for orphan_id in orphan_policy_ids:
        assert orphan_id not in config.roles, (
            f"Orphan policy ID {orphan_id} should not appear in config.roles"
        )

    # Assert: no group permissions reference orphan policy IDs
    for group in config.groups:
        for role_name in group.permissions:
            assert role_name not in orphan_policy_ids, (
                f"Orphan policy ID {role_name} should not appear in group permissions"
            )

    # Assert: the output only contains roles that are in the known roles list
    known_role_names = {role.name for role in known_roles}
    for role_name in config.roles:
        assert role_name in known_role_names, (
            f"Role name {role_name!r} in config.roles is not from a known role"
        )

    # Assert: all role names in group permissions are from known roles
    for group in config.groups:
        for role_name in group.permissions:
            assert role_name in known_role_names, (
                f"Role name {role_name!r} in group permissions is not from a known role"
            )

    # Assert: if there are valid permissions, the config should reflect them
    if not valid_permissions:
        assert config.collections == []
        assert config.roles == []
        assert config.groups == []


# ---------------------------------------------------------------------------
# Feature: directus-ac-generate, Property 2: System collection filter correctness
# Validates: Requirements 3.1, 3.2, 4.9
# ---------------------------------------------------------------------------


@st.composite
def _collections_with_system_mix(draw):
    """Generate collections, roles, policies, and permissions with a mix of system and non-system names.

    Returns (collections, roles, policies, permissions, system_names, non_system_names)
    """
    # Generate non-system collection names
    non_system_names = draw(
        st.lists(
            _user_collection_name,
            min_size=0,
            max_size=5,
            unique=True,
        )
    )

    # Generate system collection names (always prefixed with directus_)
    system_suffixes = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=15,
            ),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )
    system_names = [f"directus_{suffix}" for suffix in system_suffixes]

    all_collection_names = non_system_names + system_names

    # Ensure at least one collection exists for permissions to reference
    if not all_collection_names:
        all_collection_names = ["my_collection"]
        non_system_names = ["my_collection"]

    collections = [DirectusCollection(collection=name) for name in all_collection_names]

    # Generate roles
    role_count = draw(st.integers(min_value=1, max_value=5))
    role_ids = [f"role-id-{i}" for i in range(role_count)]
    role_names_list = [f"role_{i}" for i in range(role_count)]
    roles = [
        DirectusRole(id=role_ids[i], name=role_names_list[i])
        for i in range(role_count)
    ]

    # Generate 1:1 policies
    policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in roles
    ]
    policy_ids = [p.id for p in policies]

    # Generate permissions referencing valid policies and collections
    num_permissions = draw(st.integers(min_value=1, max_value=20))
    permissions = []
    for i in range(num_permissions):
        policy_id = draw(st.sampled_from(policy_ids))
        collection = draw(st.sampled_from(all_collection_names))
        action = draw(st.sampled_from(["read", "create", "update", "delete"]))
        permissions.append(
            DirectusPermission(
                id=i + 1, policy=policy_id, collection=collection, action=action
            )
        )

    return collections, roles, policies, permissions, set(system_names), set(non_system_names)


@given(data=_collections_with_system_mix())
@settings(max_examples=100)
def test_system_collection_filter_exclude(data):
    """Property 2: System collection filter correctness (exclude mode).

    With include_system=False, no directus_-prefixed collections appear in the
    Generator output.

    **Validates: Requirements 3.1, 3.2, 4.9**
    """
    collections, roles, policies, permissions, system_names, non_system_names = data

    mock_client = _make_mock_client(collections, roles, permissions, policies=policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Assert: no directus_-prefixed collections in config.collections
    for collection_name in config.collections:
        assert not collection_name.startswith("directus_"), (
            f"System collection '{collection_name}' should be excluded "
            f"when include_system=False"
        )

    # Assert: no groups reference directus_-prefixed collections
    for group in config.groups:
        for col in group.collections:
            assert not col.startswith("directus_"), (
                f"Group references system collection '{col}' "
                f"when include_system=False"
            )


@given(data=_collections_with_system_mix())
@settings(max_examples=100)
def test_system_collection_filter_include(data):
    """Property 2: System collection filter correctness (include mode).

    With include_system=True, all collections that have at least one valid
    permission are included in the Generator output.

    **Validates: Requirements 3.1, 3.2, 4.9**
    """
    collections, roles, policies, permissions, system_names, non_system_names = data

    mock_client = _make_mock_client(collections, roles, permissions, policies=policies)
    generator = Generator(mock_client, include_system=True)
    config = generator.generate()

    # Build the set of known policy IDs and collection names
    known_policy_ids = {p.id for p in policies}
    # Build policy -> role_ids mapping
    policy_to_role_ids: dict[str, list[str]] = {p.id: p.roles for p in policies}
    role_id_to_name = {role.id: role.name for role in roles}
    all_collection_names = {col.collection for col in collections}

    # Compute expected collections: all collections that have at least one
    # valid permission (valid policy ID linked to known role, valid action, collection in the list)
    expected_collections: set[str] = set()
    for perm in permissions:
        if perm.policy not in known_policy_ids:
            continue
        if perm.collection not in all_collection_names:
            continue
        if perm.action not in REVERSE_ACTION_MAP:
            continue
        # Check that the policy links to at least one known role
        role_ids = policy_to_role_ids.get(perm.policy, [])
        if any(rid in role_id_to_name for rid in role_ids):
            expected_collections.add(perm.collection)

    # Assert: all collections with permissions are included in output
    output_collections = set(config.collections)
    assert output_collections == expected_collections, (
        f"Expected collections {expected_collections}, got {output_collections}"
    )


# ---------------------------------------------------------------------------
# Feature: directus-ac-generate, Property 3: Completeness invariant
# Validates: Requirements 4.1, 4.2, 6.3
# ---------------------------------------------------------------------------


@st.composite
def _directus_state_for_completeness(draw):
    """Generate a consistent Directus state where all permissions are valid.

    All permissions reference valid policy IDs linked to known roles and
    non-system collections, so after filtering nothing is excluded.
    """
    # Draw unique role names and assign UUIDs
    role_names = draw(
        st.lists(_role_name, min_size=1, max_size=5, unique=True)
    )
    roles = [
        DirectusRole(id=f"role-{i}", name=name)
        for i, name in enumerate(role_names)
    ]
    role_id_to_name = {role.id: role.name for role in roles}

    # Generate 1:1 policies
    policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in roles
    ]
    policy_ids = [p.id for p in policies]
    # Map policy_id -> role_id for verification
    policy_to_role_id = {p.id: p.roles[0] for p in policies}

    # Draw unique non-system collection names
    collection_names = draw(
        st.lists(_user_collection_name, min_size=1, max_size=5, unique=True)
    )
    collections = [
        DirectusCollection(collection=name) for name in collection_names
    ]

    # Build all possible (policy_id, collection, action) triples
    valid_actions = ["read", "create", "update", "delete"]
    all_triples = [
        (policy_id, col_name, action)
        for policy_id in policy_ids
        for col_name in collection_names
        for action in valid_actions
    ]

    # Pick a non-empty subset of triples as permissions
    n = draw(st.integers(min_value=1, max_value=min(len(all_triples), 30)))
    chosen = draw(
        st.lists(
            st.sampled_from(all_triples),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    permissions = [
        DirectusPermission(id=i + 1, policy=policy_id, collection=col, action=action)
        for i, (policy_id, col, action) in enumerate(chosen)
    ]

    return collections, roles, policies, permissions, role_id_to_name, policy_to_role_id


@settings(max_examples=100)
@given(data=_directus_state_for_completeness())
def test_completeness_invariant(data):
    """Property 3: Completeness invariant.

    The generated config's `collections` list equals exactly the set of
    collection names appearing in at least one permission, and `roles`
    equals exactly the set of role names appearing in at least one permission.

    **Validates: Requirements 4.1, 4.2, 6.3**
    """
    collections, roles, policies, permissions, role_id_to_name, policy_to_role_id = data

    # Mock the DirectusClient
    client = _make_mock_client(collections, roles, permissions, policies=policies)

    # Run Generator (include_system=True since we have no system collections)
    generator = Generator(client, include_system=True)
    config = generator.generate()

    # Compute expected collections: those that appear in at least one permission
    expected_collections = {perm.collection for perm in permissions}

    # Compute expected roles: role names for roles linked through policies in permissions
    expected_roles: set[str] = set()
    for perm in permissions:
        role_id = policy_to_role_id.get(perm.policy)
        if role_id and role_id in role_id_to_name:
            expected_roles.add(role_id_to_name[role_id])

    # Verify completeness invariant for collections
    assert set(config.collections) == expected_collections, (
        f"config.collections mismatch: got {set(config.collections)}, "
        f"expected {expected_collections}"
    )

    # Verify completeness invariant for roles
    assert set(config.roles) == expected_roles, (
        f"config.roles mismatch: got {set(config.roles)}, "
        f"expected {expected_roles}"
    )


# ---------------------------------------------------------------------------
# Feature: directus-ac-generate, Property 6: Idempotency
# Validates: Requirements 6.1
# ---------------------------------------------------------------------------


@st.composite
def _consistent_directus_state(draw):
    """Generate a consistent Directus state: roles, policies, collections, and permissions.

    All permissions reference valid policy IDs linked to known roles,
    valid (non-system) collections, and valid action strings.
    """
    # Generate unique role names and assign IDs
    role_names = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("L",)),
            ),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    roles = [DirectusRole(id=f"role-id-{i}", name=name) for i, name in enumerate(role_names)]
    role_id_map = {role.id: role.name for role in roles}

    # Generate 1:1 policies
    policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in roles
    ]
    policy_ids = [p.id for p in policies]
    # Map role_id -> policy_id for expansion
    role_id_to_policy_id = {role.id: f"policy-{role.id}" for role in roles}
    # Map policy_id -> role_id for verification
    policy_to_role_id = {p.id: p.roles[0] for p in policies}

    # Generate non-system collection names (no directus_ prefix)
    collection_names = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("L", "N")),
            ).filter(lambda s: not s.startswith("directus_")),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    collections = [DirectusCollection(collection=name) for name in collection_names]

    # Build all possible (policy_id, collection, action) triples
    valid_actions = list(REVERSE_ACTION_MAP.keys())
    all_triples = [
        (policy_id, col, action)
        for policy_id in policy_ids
        for col in collection_names
        for action in valid_actions
    ]

    # Pick a non-empty subset of triples as the permission set
    n = draw(st.integers(min_value=1, max_value=min(len(all_triples), 30)))
    chosen_triples = draw(
        st.lists(
            st.sampled_from(all_triples),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    # Build DirectusPermission objects
    permissions = [
        DirectusPermission(id=i + 1, policy=policy_id, collection=col, action=action)
        for i, (policy_id, col, action) in enumerate(chosen_triples)
    ]

    return roles, policies, collections, permissions, role_id_map, role_id_to_policy_id, policy_to_role_id


@settings(max_examples=100)
@given(state=_consistent_directus_state())
def test_idempotency(state):
    """Property 6: Idempotency.

    Generating a config from a consistent Directus state and expanding it back
    into (policy_id, collection, action) triples produces exactly the original
    permission set — zero creates, zero updates needed.

    **Validates: Requirements 6.1**
    """
    roles, policies, collections, permissions, role_id_map, role_id_to_policy_id, policy_to_role_id = state

    # Mock the DirectusClient to return the generated state
    mock_client = _make_mock_client(collections, roles, permissions, policies=policies)

    # Run Generator to produce config
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Build role_name_to_id map (inverse of role_id_map)
    role_name_to_id = {name: rid for rid, name in role_id_map.items()}

    # Expand the generated config into (policy_id, collection, action) triples
    generated_triples: set[tuple[str, str, str]] = set()
    for group in config.groups:
        for collection in group.collections:
            for role_name, keywords in group.permissions.items():
                role_id = role_name_to_id[role_name]
                policy_id = role_id_to_policy_id[role_id]
                for keyword in keywords:
                    action = ACTION_MAP[keyword.value]
                    generated_triples.add((policy_id, collection, action))

    # Build the original permission set as triples
    original_triples: set[tuple[str, str, str]] = set()
    for perm in permissions:
        original_triples.add((perm.policy, perm.collection, perm.action))

    # Assert zero diff: no creates (in generated but not original),
    # no updates needed (in original but not generated)
    creates = generated_triples - original_triples
    missing = original_triples - generated_triples

    assert creates == set(), f"Unexpected new triples (would be created): {creates}"
    assert missing == set(), f"Missing triples (would need update): {missing}"
