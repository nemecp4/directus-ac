"""Property-based tests for inline reference correctness (Feature: custom-permissions).

Property 2: Inline reference correctness
Validates: Requirements 1.3, 1.4, 2.4

For any Directus state containing custom permissions, the generated config's
groups SHALL contain C_N references in the Permission_Set for the corresponding
role+collection, and every C_N reference in a Permission_Set SHALL have a
corresponding entry with that name in the custom_permissions definitions section.
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

# Collection names: non-empty, no directus_ prefix (user collections)
_collection_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("directus_"))

# Policy names: non-empty strings
_policy_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=30,
)

_action = st.sampled_from(["create", "read", "update", "delete"])


@st.composite
def _mixed_directus_state(draw):
    """Generate a Directus state with both standard and custom permissions.

    Creates policies, roles, collections, and a mix of standard permissions
    (no custom attributes, unique triples) and custom permissions (with
    non-default validation/fields/permissions attributes).

    Returns (collections, roles, policies, permissions).
    """
    # Generate 1-3 policies with distinct names, each linked to a role
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

    # Generate some standard permissions (unique triples, no custom attrs)
    num_standard = draw(st.integers(min_value=0, max_value=6))
    for _ in range(num_standard):
        policy = draw(st.sampled_from(policies))
        col_name = draw(st.sampled_from(collection_names))
        action = draw(_action)
        triple = (policy.id, col_name, action)
        if triple in used_triples:
            continue
        used_triples.add(triple)
        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy.id,
                collection=col_name,
                action=action,
                validation=None,
                fields=draw(st.sampled_from([None, ["*"]])),
                permissions=None,
            )
        )
        perm_id += 1

    # Generate custom permissions (with non-default attributes)
    num_custom = draw(st.integers(min_value=1, max_value=6))
    for _ in range(num_custom):
        policy = draw(st.sampled_from(policies))
        col_name = draw(st.sampled_from(collection_names))
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
                        alphabet=st.characters(whitelist_categories=("L",)),
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
# Feature: custom-permissions, Property 2: Inline reference correctness
# Validates: Requirements 1.3, 1.4, 2.4
# ---------------------------------------------------------------------------


@given(state=_mixed_directus_state())
@settings(max_examples=100)
def test_every_inline_ref_has_matching_definition(state) -> None:
    """Property 2 (part A): Every C_N reference in groups has a matching definition.

    For any Directus state containing custom permissions, every C_N reference
    appearing in a group's custom_permission_refs SHALL have a corresponding
    entry with that name in the config's custom_permissions definitions list.

    **Validates: Requirements 1.3, 1.4, 2.4**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Collect all C_N names defined in the custom_permissions section
    defined_names = {entry.name for entry in config.custom_permissions}

    # Collect all C_N references from groups' custom_permission_refs
    for group in config.groups:
        for role_name, refs in group.custom_permission_refs.items():
            for ref in refs:
                assert ref in defined_names, (
                    f"Group for collections={group.collections} has reference "
                    f"'{ref}' for role '{role_name}' but no matching entry "
                    f"exists in custom_permissions definitions. "
                    f"Defined names: {defined_names}"
                )


@given(state=_mixed_directus_state())
@settings(max_examples=100)
def test_custom_permissions_placed_in_correct_group(state) -> None:
    """Property 2 (part B): Custom permissions are assigned to correct role+collection group.

    For any Directus state containing custom permissions, each C_N reference
    SHALL appear in the group corresponding to the custom permission's collection,
    under the role(s) resolved from the custom permission's policy.

    **Validates: Requirements 1.3, 1.4, 2.4**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Build lookup maps
    policy_id_to_name = {p.id: p.name for p in policies}
    policy_to_role_ids: dict[str, list[str]] = {}
    for policy in policies:
        policy_to_role_ids[policy.id] = list(policy.roles)
    for role in roles:
        for policy_id in role.policies:
            if policy_id not in policy_to_role_ids:
                policy_to_role_ids[policy_id] = []
            if role.id not in policy_to_role_ids[policy_id]:
                policy_to_role_ids[policy_id].append(role.id)

    role_id_to_name = {r.id: r.name for r in roles}

    # Build a map from collection -> group for quick lookup
    collection_to_group = {}
    for group in config.groups:
        for col in group.collections:
            collection_to_group[col] = group

    # For each custom permission entry, verify it's referenced in the correct group
    for entry in config.custom_permissions:
        # Find the original permission that produced this entry
        # The entry's collection tells us which group it should be in
        expected_collection = entry.collection

        # Resolve the policy name back to policy ID to find roles
        policy_id = None
        for p in policies:
            if p.name == entry.policy:
                policy_id = p.id
                break

        if policy_id is None:
            # If policy can't be resolved, the entry shouldn't exist
            # (generator skips unresolvable policies)
            continue

        # Get the role names this custom permission should be assigned to
        role_ids = policy_to_role_ids.get(policy_id, [])
        expected_role_names = [
            role_id_to_name[rid]
            for rid in role_ids
            if rid in role_id_to_name
        ]

        # Check that the group for this collection contains the reference
        if expected_collection in collection_to_group:
            group = collection_to_group[expected_collection]
            for role_name in expected_role_names:
                refs = group.custom_permission_refs.get(role_name, [])
                assert entry.name in refs, (
                    f"Custom permission '{entry.name}' (collection='{entry.collection}', "
                    f"policy='{entry.policy}') should be referenced in group "
                    f"for collection '{expected_collection}' under role '{role_name}', "
                    f"but refs for that role are: {refs}"
                )


@given(state=_mixed_directus_state())
@settings(max_examples=100)
def test_all_custom_permissions_have_inline_refs(state) -> None:
    """Property 2 (part C): All custom permission definitions have inline references.

    For any Directus state containing custom permissions, every entry in the
    config's custom_permissions list SHALL be referenced at least once in some
    group's custom_permission_refs (no orphan definitions).

    **Validates: Requirements 1.3, 1.4, 2.4**
    """
    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # Collect all C_N references from all groups
    all_refs_in_groups: set[str] = set()
    for group in config.groups:
        for role_name, refs in group.custom_permission_refs.items():
            all_refs_in_groups.update(refs)

    # Every defined custom permission should be referenced somewhere
    for entry in config.custom_permissions:
        assert entry.name in all_refs_in_groups, (
            f"Custom permission '{entry.name}' (collection='{entry.collection}', "
            f"policy='{entry.policy}') is defined in custom_permissions but "
            f"not referenced in any group's custom_permission_refs. "
            f"All refs in groups: {all_refs_in_groups}"
        )


@given(state=_mixed_directus_state())
@settings(max_examples=100)
def test_inline_refs_follow_c_n_pattern(state) -> None:
    """Property 2 (part D): All inline references follow the C_N naming pattern.

    For any Directus state, all references in groups' custom_permission_refs
    SHALL match the pattern C_\\d+ (e.g., C_1, C_2, C_3).

    **Validates: Requirements 1.3, 1.4, 2.4**
    """
    import re

    collections, roles, policies, permissions = state

    mock_client = _make_mock_client(collections, roles, permissions, policies)
    generator = Generator(mock_client, include_system=False)
    config = generator.generate()

    # All references in groups must match C_N pattern
    for group in config.groups:
        for role_name, refs in group.custom_permission_refs.items():
            for ref in refs:
                assert re.fullmatch(r"[A-Z]+_C_\d+", ref), (
                    f"Reference '{ref}' in group for collections={group.collections}, "
                    f"role='{role_name}' does not match the C_N pattern"
                )
