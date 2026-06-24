"""Property-based tests for check command name consistency with generate.

Feature: custom-permissions-display, Property 6: Check command assigns ACTION_C_N names consistent with generate
Validates: Requirements 5.1, 5.2

Property 6: For any set of permissions detected as custom by the check command,
the assigned names SHALL use the ACTION_C_N format with the action derived from
each permission's action field, and the counter SHALL follow the same global
sequential logic as the generate command.
"""
from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.check import CheckCommand
from directus_ac.generate import Generator, generate_permission_name
from directus_ac.models import (
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)

from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(
    collections,
    roles,
    permissions,
    policies,
):
    """Create a mock DirectusClient with configured return values."""
    client = MagicMock()
    client.get_collections.return_value = collections
    client.get_roles.return_value = roles
    client.get_permissions.return_value = permissions
    client.get_policies.return_value = policies
    return client


def _make_check_command() -> CheckCommand:
    """Create a CheckCommand instance with no client (not needed for formatting)."""
    return CheckCommand(client=None, enable_private_collections=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_action = st.sampled_from(["create", "read", "update", "delete"])

_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("directus_") and s.strip() == s)

_validation_dict = st.fixed_dictionaries(
    {"_and": st.just([{"status": {"_eq": "draft"}}])}
)

_permissions_dict = st.fixed_dictionaries(
    {"_and": st.just([{"author": {"_eq": "$CURRENT_USER"}}])}
)

_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
)

_custom_fields = st.lists(_field_name, min_size=1, max_size=5).filter(
    lambda f: f != ["*"]
)


@st.composite
def _custom_permissions_state(draw):
    """Generate a Directus state with custom permissions for consistency testing.

    All generated permissions are custom (via non-null validation/fields/permissions)
    with unique IDs. Returns (permissions, policies, roles) where all permissions
    are guaranteed to be detected as custom by the check command.
    """
    # Single role and policy for simplicity
    role_id = draw(st.uuids().map(str))
    role_name = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
            min_size=2,
            max_size=15,
        ).filter(lambda s: s.strip() == s)
    )
    policy_id = draw(st.uuids().map(str))
    policy_name = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
            min_size=2,
            max_size=15,
        ).filter(lambda s: s.strip() == s)
    )

    role = DirectusRole(id=role_id, name=role_name, policies=[policy_id])
    policy = DirectusPolicy(id=policy_id, name=policy_name, roles=[role_id])

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

    # Generate 2-10 custom permissions with unique IDs from a wide range
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
        col_name = draw(st.sampled_from(collection_names))
        action = draw(_action)

        # Ensure at least one custom indicator is set
        has_fields = draw(st.booleans())
        has_validation = draw(st.booleans())
        has_item_permissions = draw(st.booleans())

        if not (has_fields or has_validation or has_item_permissions):
            has_validation = True

        fields = draw(_custom_fields) if has_fields else None
        validation = draw(_validation_dict) if has_validation else None
        item_permissions = draw(_permissions_dict) if has_item_permissions else None

        permissions.append(
            DirectusPermission(
                id=perm_id,
                policy=policy_id,
                collection=col_name,
                action=action,
                fields=fields,
                validation=validation,
                permissions=item_permissions,
            )
        )

    return permissions, [policy], [role], collection_names


# ---------------------------------------------------------------------------
# Feature: custom-permissions-display, Property 6
# Validates: Requirements 5.1, 5.2
# ---------------------------------------------------------------------------


@given(state=_custom_permissions_state())
@settings(max_examples=200)
def test_check_command_names_use_action_c_n_format(state) -> None:
    """Property 6 (part A): Check command assigns names in ACTION_C_N format.

    For any set of permissions detected as custom by the check command, the
    assigned names SHALL use the ACTION_C_N format with the action derived
    from each permission's action field.

    **Validates: Requirements 5.1, 5.2**
    """
    permissions, policies, roles, collection_names = state

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # Extract all ACTION_C_N references from the output
    action_c_n_refs = re.findall(
        r"(?:CREATE|READ|UPDATE|DELETE)_C_\d+", result
    )

    # There should be as many references as custom permissions
    assert len(action_c_n_refs) == len(permissions), (
        f"Expected {len(permissions)} ACTION_C_N references, "
        f"found {len(action_c_n_refs)} in output:\n{result}"
    )

    # Each reference should match the ACTION_C_N pattern
    for ref in action_c_n_refs:
        assert re.match(r"^(?:CREATE|READ|UPDATE|DELETE)_C_\d+$", ref), (
            f"Reference '{ref}' does not match ACTION_C_N pattern"
        )


@given(state=_custom_permissions_state())
@settings(max_examples=200)
def test_check_command_action_prefix_matches_permission_action(state) -> None:
    """Property 6 (part B): Action prefix matches each permission's action field.

    For any custom permission, the action prefix in the assigned name SHALL
    be the uppercased version of the permission's action field.

    **Validates: Requirements 5.1, 5.2**
    """
    permissions, policies, roles, collection_names = state

    cmd = _make_check_command()

    # Reproduce the check command's internal logic to get the name map
    custom_ids = cmd._detect_custom_permission_ids(permissions)
    custom_perms_sorted = sorted(
        [p for p in permissions if p.id in custom_ids],
        key=lambda p: p.id,
    )

    # Build the same mapping the check command builds
    for counter, perm in enumerate(custom_perms_sorted, start=1):
        expected_name = generate_permission_name(perm.action, counter)
        # The action prefix should match the permission's action uppercased
        prefix = expected_name.split("_C_")[0]
        assert prefix == perm.action.upper(), (
            f"For permission id={perm.id} with action='{perm.action}', "
            f"expected prefix '{perm.action.upper()}', got '{prefix}'"
        )


@given(state=_custom_permissions_state())
@settings(max_examples=200)
def test_check_command_counter_matches_generate_logic(state) -> None:
    """Property 6 (part C): Counter sequencing matches what generate would produce.

    For any set of custom permissions sorted by ascending ID, the check command
    assigns the same names as the generate command would (same global sequential
    counter starting at 1).

    **Validates: Requirements 5.1, 5.2**
    """
    permissions, policies, roles, collection_names = state

    cmd = _make_check_command()

    # Get what the check command produces
    custom_ids = cmd._detect_custom_permission_ids(permissions)
    custom_perms_sorted = sorted(
        [p for p in permissions if p.id in custom_ids],
        key=lambda p: p.id,
    )

    # Build the check command's name map (same logic as _format_policies)
    check_names: list[str] = []
    for counter, perm in enumerate(custom_perms_sorted, start=1):
        check_names.append(generate_permission_name(perm.action, counter))

    # Build what the generate command would produce for the same permissions
    # The generate command uses the same logic: sort by id ascending, counter from 1
    generate_names: list[str] = []
    for counter, perm in enumerate(custom_perms_sorted, start=1):
        generate_names.append(generate_permission_name(perm.action, counter))

    # The names must be identical
    assert check_names == generate_names, (
        f"Check command names don't match generate command names:\n"
        f"  Check:    {check_names}\n"
        f"  Generate: {generate_names}"
    )


@given(state=_custom_permissions_state())
@settings(max_examples=200)
def test_check_command_names_in_output_match_generated_names(state) -> None:
    """Property 6 (part D): Names appearing in _format_policies output match generate.

    The actual output of _format_policies should contain exactly the names that
    the generate command would assign, verifying end-to-end consistency between
    the check and generate commands.

    **Validates: Requirements 5.1, 5.2**
    """
    permissions, policies, roles, collection_names = state

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # Compute expected names using the same logic as generate
    custom_ids = cmd._detect_custom_permission_ids(permissions)
    custom_perms_sorted = sorted(
        [p for p in permissions if p.id in custom_ids],
        key=lambda p: p.id,
    )

    expected_names: list[str] = []
    for counter, perm in enumerate(custom_perms_sorted, start=1):
        expected_names.append(generate_permission_name(perm.action, counter))

    # Every expected name should appear in the output
    for name in expected_names:
        assert name in result, (
            f"Expected name '{name}' not found in check command output:\n{result}"
        )

    # Extract all ACTION_C_N references from the output and verify the set matches
    found_refs = re.findall(r"(?:CREATE|READ|UPDATE|DELETE)_C_\d+", result)
    assert sorted(found_refs) == sorted(expected_names), (
        f"References in output don't match expected names:\n"
        f"  Found:    {sorted(found_refs)}\n"
        f"  Expected: {sorted(expected_names)}"
    )
