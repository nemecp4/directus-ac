"""Property-based test for update command create/update correctness.

Feature: custom-permissions, Property 8: Update command create/update correctness

Validates: Requirements 6.1, 6.2, 6.4
"""
from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.models import (
    CustomPermissionEntry,
    DirectusPermission,
)
from directus_ac.permissions import PermissionManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ACTIONS = ["create", "read", "update", "delete"]

# Policy names: non-empty strings
_policy_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=30,
)

# Collection names: non-empty strings
_collection_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=20,
)


@st.composite
def _custom_perms_with_existing_state(draw):
    """Generate custom permission entries and existing Directus permission state.

    Produces:
    - A list of CustomPermissionEntry objects to apply
    - A policy_name_to_id mapping
    - A list of existing DirectusPermission objects (some with constraints that
      will match entries, some without)

    The strategy ensures that:
    - Each custom permission entry has a resolvable policy
    - Some existing permissions match (same policy_id + collection + action with
      non-null constraints) → these should be updated (PATCH)
    - Some entries have no match → these should be created (POST)

    Returns (custom_entries, policy_name_to_id, existing_permissions,
             expected_creates, expected_updates).
    """
    # Generate 1-3 policy names
    num_policies = draw(st.integers(min_value=1, max_value=3))
    policy_names = draw(
        st.lists(
            _policy_name,
            min_size=num_policies,
            max_size=num_policies,
            unique=True,
        )
    )
    # Map policy names to IDs
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

    # Generate 1-8 custom permission entries with unique (policy, collection, action) triples
    # to avoid ambiguity in matching
    all_possible_triples = [
        (pname, col, action)
        for pname in policy_names
        for col in collection_names
        for action in _ACTIONS
    ]

    num_entries = draw(st.integers(min_value=1, max_value=min(8, len(all_possible_triples))))
    chosen_triples = draw(
        st.lists(
            st.sampled_from(all_possible_triples),
            min_size=num_entries,
            max_size=num_entries,
            unique=True,
        )
    )

    custom_entries = []
    for i, (pname, col, action) in enumerate(chosen_triples):
        # Generate optional attributes for the custom permission entry
        validation = draw(st.one_of(
            st.none(),
            st.just({"_and": [{"status": {"_eq": "draft"}}]}),
        ))
        fields = draw(st.one_of(
            st.none(),
            st.lists(
                st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=10),
                min_size=1,
                max_size=3,
            ),
        ))
        item_permissions = draw(st.one_of(
            st.none(),
            st.just({"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}),
        ))

        custom_entries.append(
            CustomPermissionEntry(
                name=f"{action.upper()}_C_{i + 1}",
                policy=pname,
                collection=col,
                action=action,
                validation=validation,
                fields=fields,
                permissions=item_permissions,
            )
        )

    # For each custom entry, decide whether an existing permission with constraints
    # should exist (making it an update) or not (making it a create)
    existing_permissions: list[DirectusPermission] = []
    expected_creates = 0
    expected_updates = 0
    perm_id = 1

    for entry in custom_entries:
        policy_id = policy_name_to_id[entry.policy]
        should_exist = draw(st.booleans())

        if should_exist:
            # Create an existing permission with constraints that matches
            # (policy_id, collection, action) — this will trigger an update
            existing_permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=policy_id,
                    collection=entry.collection,
                    action=entry.action,
                    validation={"_and": [{"old": {"_eq": "value"}}]},
                    fields=None,
                    permissions=None,
                )
            )
            expected_updates += 1
            perm_id += 1
        else:
            expected_creates += 1

    # Also add some "noise" existing permissions that should NOT match:
    # - Standard permissions (no constraints) with same triple
    # - Permissions with constraints but different triple
    num_noise = draw(st.integers(min_value=0, max_value=5))
    for _ in range(num_noise):
        noise_policy = draw(st.sampled_from(list(policy_name_to_id.values())))
        noise_col = draw(st.sampled_from(collection_names))
        noise_action = draw(st.sampled_from(_ACTIONS))
        noise_type = draw(st.sampled_from(["standard", "different_triple_with_constraints"]))

        if noise_type == "standard":
            # Standard permission (no constraints) — should NOT match for update
            existing_permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=noise_policy,
                    collection=noise_col,
                    action=noise_action,
                    validation=None,
                    fields=None,
                    permissions=None,
                )
            )
        else:
            # Permission with constraints but using a policy_id not in our entries
            # Use a completely different policy_id to avoid accidental matches
            existing_permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=f"unrelated-policy-{perm_id}",
                    collection=noise_col,
                    action=noise_action,
                    validation={"_and": [{"x": {"_eq": "y"}}]},
                    fields=None,
                    permissions=None,
                )
            )
        perm_id += 1

    return custom_entries, policy_name_to_id, existing_permissions, expected_creates, expected_updates


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 8: Update command create/update correctness
# ---------------------------------------------------------------------------


@given(data=_custom_perms_with_existing_state())
@settings(max_examples=100)
def test_update_command_create_update_correctness(data):
    """Property 8: Update command create/update correctness.

    For any set of custom permission config entries and existing Directus
    permission state, the PermissionManager SHALL create entries that don't
    exist (POST) and update entries that match by policy_id + collection +
    action with non-null constraints (PATCH), and the returned counts SHALL
    equal the number of POST and PATCH operations performed respectively.

    **Validates: Requirements 6.1, 6.2, 6.4**
    """
    custom_entries, policy_name_to_id, existing_permissions, expected_creates, expected_updates = data

    # Mock the DirectusClient
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

    # Verify counts match expected
    assert created_count == expected_creates, (
        f"Expected {expected_creates} creates, got {created_count}. "
        f"Entries: {[(e.policy, e.collection, e.action) for e in custom_entries]}"
    )
    assert updated_count == expected_updates, (
        f"Expected {expected_updates} updates, got {updated_count}. "
        f"Entries: {[(e.policy, e.collection, e.action) for e in custom_entries]}"
    )

    # Verify counts match actual API calls
    assert mock_client.create_permission.call_count == created_count, (
        f"create_permission called {mock_client.create_permission.call_count} times "
        f"but created_count is {created_count}"
    )
    assert mock_client.update_permission.call_count == updated_count, (
        f"update_permission called {mock_client.update_permission.call_count} times "
        f"but updated_count is {updated_count}"
    )

    # Verify total operations = total entries
    assert created_count + updated_count == len(custom_entries), (
        f"Total operations ({created_count} + {updated_count}) != "
        f"total entries ({len(custom_entries)})"
    )
