"""Property-based tests for check command inline display with indicators.

Feature: custom-permissions, Property 7: Check command inline display with indicators
Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.check import CheckCommand
from directus_ac.models import (
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check_command() -> CheckCommand:
    """Create a CheckCommand instance with no client (not needed for formatting)."""
    return CheckCommand(client=None, enable_private_collections=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_action = st.sampled_from(["read", "create", "update", "delete"])

_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("directus_") and s.strip() == s)

_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
)

# Non-null fields list (not ["*"])
_custom_fields = st.lists(_field_name, min_size=1, max_size=5).filter(
    lambda f: f != ["*"]
)

# Validation dicts (non-null)
_validation_dict = st.fixed_dictionaries(
    {"_and": st.just([{"status": {"_eq": "draft"}}])}
)

# Permissions dicts (non-null, item-level)
_permissions_dict = st.fixed_dictionaries(
    {"_and": st.just([{"author": {"_eq": "$CURRENT_USER"}}])}
)


@st.composite
def _custom_permission_entry(draw, perm_id, policy_id, collection, action=None):
    """Generate a DirectusPermission that qualifies as custom (has at least one indicator)."""
    if action is None:
        action = draw(_action)

    # Decide which indicators to include (at least one)
    has_fields = draw(st.booleans())
    has_validation = draw(st.booleans())
    has_item_permissions = draw(st.booleans())

    # Ensure at least one is True
    if not (has_fields or has_validation or has_item_permissions):
        choice = draw(st.sampled_from(["fields", "validation", "permissions"]))
        if choice == "fields":
            has_fields = True
        elif choice == "validation":
            has_validation = True
        else:
            has_item_permissions = True

    fields = draw(_custom_fields) if has_fields else None
    validation = draw(_validation_dict) if has_validation else None
    permissions = draw(_permissions_dict) if has_item_permissions else None

    return DirectusPermission(
        id=perm_id,
        policy=policy_id,
        collection=collection,
        action=action,
        fields=fields,
        validation=validation,
        permissions=permissions,
    )


@st.composite
def _check_command_state_with_custom_perms(draw):
    """Generate a Directus state with both standard and custom permissions.

    Returns (permissions, policies, roles, custom_collection,
    standard_actions_for_custom_col, custom_perm_details) where
    custom_perm_details is a list of dicts with id, fields, validation, permissions, action.

    IMPORTANT: Standard permissions on the custom collection must use actions
    that are NOT shared by any custom permission on the same collection+policy,
    otherwise the duplicate-triple detection would mark them as custom too.
    """
    # Generate a single role and policy for simplicity
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
    collections = draw(
        st.lists(_collection_name, min_size=1, max_size=3, unique=True)
    )

    # Pick one collection for custom permissions
    custom_collection = draw(st.sampled_from(collections))

    perm_id_counter = 1
    all_permissions: list[DirectusPermission] = []

    # Standard permissions for other collections
    for col in collections:
        if col != custom_collection:
            num_actions = draw(st.integers(min_value=1, max_value=4))
            actions = draw(
                st.lists(
                    _action, min_size=num_actions, max_size=num_actions, unique=True
                )
            )
            for action in actions:
                all_permissions.append(
                    DirectusPermission(
                        id=perm_id_counter,
                        policy=policy_id,
                        collection=col,
                        action=action,
                    )
                )
                perm_id_counter += 1

    # Generate 1-3 custom permissions for the custom collection, each with a UNIQUE action
    all_actions = ["read", "create", "update", "delete"]
    # Shuffle and pick unique actions for custom perms
    num_custom = draw(st.integers(min_value=1, max_value=3))
    custom_actions = draw(
        st.lists(
            st.sampled_from(all_actions),
            min_size=num_custom,
            max_size=num_custom,
            unique=True,
        )
    )

    custom_perm_details: list[dict] = []
    for custom_action in custom_actions:
        perm = draw(
            _custom_permission_entry(perm_id_counter, policy_id, custom_collection, custom_action)
        )
        all_permissions.append(perm)
        custom_perm_details.append({
            "id": perm.id,
            "fields": perm.fields,
            "validation": perm.validation,
            "permissions": perm.permissions,
            "action": perm.action,
        })
        perm_id_counter += 1

    # Standard permissions for the custom collection use actions NOT used by custom perms
    remaining_actions = [a for a in all_actions if a not in custom_actions]
    standard_actions_for_custom_col: list[str] = []
    if remaining_actions:
        num_standard = draw(st.integers(min_value=0, max_value=len(remaining_actions)))
        if num_standard > 0:
            standard_actions = draw(
                st.lists(
                    st.sampled_from(remaining_actions),
                    min_size=num_standard,
                    max_size=num_standard,
                    unique=True,
                )
            )
            for action in standard_actions:
                all_permissions.append(
                    DirectusPermission(
                        id=perm_id_counter,
                        policy=policy_id,
                        collection=custom_collection,
                        action=action,
                    )
                )
                standard_actions_for_custom_col.append(action)
                perm_id_counter += 1

    return (
        all_permissions,
        [policy],
        [role],
        custom_collection,
        standard_actions_for_custom_col,
        custom_perm_details,
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 7: Check command inline display with indicators
# Validates: Requirements 5.1, 5.2, 5.3, 5.4
# ---------------------------------------------------------------------------


@given(data=_check_command_state_with_custom_perms())
@settings(max_examples=100)
def test_custom_refs_appear_inline_with_standard_actions(data) -> None:
    """Property 7 (part A): Custom permission references appear inline.

    For any Directus state with custom permissions, the CheckCommand policies
    section output SHALL show custom permission references (C_N) inline alongside
    standard action names in the policies section output for that role+collection.

    **Validates: Requirements 5.1, 5.2**
    """
    (
        permissions,
        policies,
        roles,
        custom_collection,
        standard_actions,
        custom_perm_details,
    ) = data

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # Find the line for the custom collection
    lines = result.split("\n")
    collection_lines = [
        line for line in lines if line.strip().startswith(f"{custom_collection}:")
    ]

    assert len(collection_lines) >= 1, (
        f"Expected at least one line for collection '{custom_collection}' in output:\n{result}"
    )

    # The line should contain C_N references
    coll_line = collection_lines[0].strip()
    # Extract the part after "collection: "
    parts_str = coll_line.split(": ", 1)[1]

    # Verify C_N references are present
    import re
    c_refs = re.findall(r"C_\d+", parts_str)
    assert len(c_refs) == len(custom_perm_details), (
        f"Expected {len(custom_perm_details)} C_N references, found {len(c_refs)} "
        f"in line: {coll_line}"
    )

    # Verify standard actions are also present (if any)
    for action in standard_actions:
        assert action in parts_str, (
            f"Standard action '{action}' should appear in the line: {coll_line}"
        )


@given(data=_check_command_state_with_custom_perms())
@settings(max_examples=100)
def test_comma_separated_list_format(data) -> None:
    """Property 7 (part B): Standard actions and custom refs in comma-separated list.

    When displaying permissions for a collection under a policy, the CheckCommand
    SHALL show both standard actions and Custom_Permission references in a single
    comma-separated list (using ", " as separator).

    **Validates: Requirements 5.1, 5.2**
    """
    (
        permissions,
        policies,
        roles,
        custom_collection,
        standard_actions,
        custom_perm_details,
    ) = data

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # Find the line for the custom collection
    lines = result.split("\n")
    collection_lines = [
        line for line in lines if line.strip().startswith(f"{custom_collection}:")
    ]
    assert len(collection_lines) >= 1

    coll_line = collection_lines[0].strip()
    parts_str = coll_line.split(": ", 1)[1]

    # The format uses ", " (comma-space) as the top-level separator
    parts = [p.strip() for p in parts_str.split(", ")]

    # Total parts should be standard_actions + custom_perm_details
    expected_count = len(standard_actions) + len(custom_perm_details)
    assert len(parts) == expected_count, (
        f"Expected {expected_count} comma-separated parts "
        f"({len(standard_actions)} standard + {len(custom_perm_details)} custom), "
        f"got {len(parts)} in: {parts_str}"
    )

    # Standard actions should come first in the list
    for i, action in enumerate(standard_actions):
        assert parts[i] == action, (
            f"Expected standard action '{action}' at position {i}, "
            f"got '{parts[i]}' in: {parts_str}"
        )


@given(data=_check_command_state_with_custom_perms())
@settings(max_examples=100)
def test_fields_indicator_not_appended(data) -> None:
    """Property 7 (part C): No fields indicator appended to custom refs.

    When a Custom_Permission has non-null fields, the CheckCommand SHALL NOT
    append any field indicators - only the permission name is displayed.

    **Validates: Requirements 4.1, 4.2**
    """
    (
        permissions,
        policies,
        roles,
        custom_collection,
        standard_actions,
        custom_perm_details,
    ) = data

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # No fields indicator should appear anywhere in the output
    assert "fields:(" not in result, (
        f"Expected no 'fields:(...)' indicators in output, but found one in:\n{result}"
    )


@given(data=_check_command_state_with_custom_perms())
@settings(max_examples=100)
def test_validation_indicator_not_appended(data) -> None:
    """Property 7 (part D): No validation indicator appended to custom refs.

    When a Custom_Permission has non-null validation, the CheckCommand SHALL NOT
    append any validation indicators - only the permission name is displayed.

    **Validates: Requirements 4.1, 4.3**
    """
    (
        permissions,
        policies,
        roles,
        custom_collection,
        standard_actions,
        custom_perm_details,
    ) = data

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # No validation indicator should appear anywhere in the output
    assert "has validation" not in result, (
        f"Expected no 'has validation' indicators in output, but found one in:\n{result}"
    )


@given(data=_check_command_state_with_custom_perms())
@settings(max_examples=100)
def test_item_permissions_indicator_not_appended(data) -> None:
    """Property 7 (part E): No item permissions indicator appended to custom refs.

    When a Custom_Permission has non-null permissions (item-level), the CheckCommand
    SHALL NOT append any item permission indicators - only the permission name is displayed.

    **Validates: Requirements 4.1, 4.4**
    """
    (
        permissions,
        policies,
        roles,
        custom_collection,
        standard_actions,
        custom_perm_details,
    ) = data

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # No item permissions indicator should appear anywhere in the output
    assert "has item permissions" not in result, (
        f"Expected no 'has item permissions' indicators in output, but found one in:\n{result}"
    )


@st.composite
def _state_without_custom_permissions(draw):
    """Generate a Directus state with only standard permissions (no custom)."""
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

    # Generate collections
    collections = draw(
        st.lists(_collection_name, min_size=1, max_size=3, unique=True)
    )

    # Generate standard permissions only (no custom attributes, unique triples)
    perm_id_counter = 1
    all_permissions: list[DirectusPermission] = []
    used_triples: set[tuple[str, str, str]] = set()

    for col in collections:
        num_actions = draw(st.integers(min_value=1, max_value=4))
        actions = draw(
            st.lists(_action, min_size=num_actions, max_size=num_actions, unique=True)
        )
        for action in actions:
            triple = (policy_id, col, action)
            if triple in used_triples:
                continue
            used_triples.add(triple)
            all_permissions.append(
                DirectusPermission(
                    id=perm_id_counter,
                    policy=policy_id,
                    collection=col,
                    action=action,
                    fields=None,
                    validation=None,
                    permissions=None,
                )
            )
            perm_id_counter += 1

    return all_permissions, [policy], [role]


@given(data=_state_without_custom_permissions())
@settings(max_examples=100)
def test_no_custom_refs_when_no_custom_permissions(data) -> None:
    """Property 7 (part F): No custom references when no custom permissions exist.

    When no Custom_Permissions exist, the CheckCommand SHALL display only standard
    actions in the policies section without any custom permission references.

    **Validates: Requirements 5.1, 5.2**
    """
    permissions, policies, roles = data

    cmd = _make_check_command()
    result = cmd._format_policies(permissions, policies, roles)

    # No C_N references should appear anywhere in the output
    import re
    c_refs = re.findall(r"C_\d+", result)
    assert len(c_refs) == 0, (
        f"Expected no C_N references when no custom permissions exist, "
        f"but found: {c_refs} in output:\n{result}"
    )

    # No indicators should appear
    assert "fields:(" not in result
    assert "has validation" not in result
    assert "has item permissions" not in result
