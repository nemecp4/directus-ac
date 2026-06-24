"""Property-based tests for _format_custom_ref returning only the name.

Feature: custom-permissions-display, Property 5: Format custom ref returns only the name
**Validates: Requirements 4.1, 4.2, 4.3, 4.4**
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.check import CheckCommand
from directus_ac.models import DirectusPermission


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

_custom_permission_name = st.builds(
    lambda action, counter: f"{action.upper()}_C_{counter}",
    action=_action,
    counter=st.integers(min_value=1, max_value=9999),
)

_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
)

# Fields strategies: None, ["*"], or a custom list of field names
_fields_strategy = st.one_of(
    st.none(),
    st.just(["*"]),
    st.lists(_field_name, min_size=1, max_size=5).filter(lambda f: f != ["*"]),
)

# Validation strategies: None or a non-null dict
_validation_strategy = st.one_of(
    st.none(),
    st.fixed_dictionaries({"_and": st.just([{"status": {"_eq": "draft"}}])}),
)

# Permissions (item-level) strategies: None or a non-null dict
_permissions_strategy = st.one_of(
    st.none(),
    st.fixed_dictionaries({"_and": st.just([{"author": {"_eq": "$CURRENT_USER"}}])}),
)

_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
).filter(lambda s: not s.startswith("directus_") and s.strip() == s)


@st.composite
def _directus_permission(draw):
    """Generate a DirectusPermission with varying fields, validation, and permissions."""
    return DirectusPermission(
        id=draw(st.integers(min_value=1, max_value=99999)),
        policy=draw(st.uuids().map(str)),
        collection=draw(_collection_name),
        action=draw(_action),
        fields=draw(_fields_strategy),
        validation=draw(_validation_strategy),
        permissions=draw(_permissions_strategy),
    )


# ---------------------------------------------------------------------------
# Property 5: Format custom ref returns only the name
# **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
# ---------------------------------------------------------------------------


@given(name=_custom_permission_name, perm=_directus_permission())
@settings(max_examples=200)
def test_format_custom_ref_returns_only_name(name: str, perm: DirectusPermission) -> None:
    """Property 5: _format_custom_ref returns exactly the name string.

    For any custom permission name and any DirectusPermission object (regardless
    of its fields, validation, or permissions values), _format_custom_ref(name, perm)
    SHALL return exactly the name string with no additional content.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
    """
    cmd = _make_check_command()
    result = cmd._format_custom_ref(name, perm)

    assert result == name, (
        f"Expected _format_custom_ref to return exactly '{name}', got '{result}'"
    )


@given(name=_custom_permission_name, perm=_directus_permission())
@settings(max_examples=200)
def test_format_custom_ref_no_field_indicators(name: str, perm: DirectusPermission) -> None:
    """Property 5 (part B): No field restriction indicators in output.

    The output SHALL NOT contain any field restriction indicators such as
    'fields:(' regardless of the permission's fields value.

    **Validates: Requirements 4.1, 4.2**
    """
    cmd = _make_check_command()
    result = cmd._format_custom_ref(name, perm)

    assert "fields:(" not in result, (
        f"Expected no field indicators in output, got '{result}'"
    )
    assert "fields:" not in result, (
        f"Expected no field indicators in output, got '{result}'"
    )


@given(name=_custom_permission_name, perm=_directus_permission())
@settings(max_examples=200)
def test_format_custom_ref_no_validation_indicators(name: str, perm: DirectusPermission) -> None:
    """Property 5 (part C): No validation indicators in output.

    The output SHALL NOT contain any validation indicators such as
    'has validation' regardless of the permission's validation value.

    **Validates: Requirements 4.1, 4.3**
    """
    cmd = _make_check_command()
    result = cmd._format_custom_ref(name, perm)

    assert "validation" not in result, (
        f"Expected no validation indicators in output, got '{result}'"
    )


@given(name=_custom_permission_name, perm=_directus_permission())
@settings(max_examples=200)
def test_format_custom_ref_no_item_permission_indicators(name: str, perm: DirectusPermission) -> None:
    """Property 5 (part D): No item permission indicators in output.

    The output SHALL NOT contain any item permission indicators such as
    'has item permissions' regardless of the permission's permissions value.

    **Validates: Requirements 4.1, 4.4**
    """
    cmd = _make_check_command()
    result = cmd._format_custom_ref(name, perm)

    assert "item permissions" not in result, (
        f"Expected no item permission indicators in output, got '{result}'"
    )
    assert "has item" not in result, (
        f"Expected no item permission indicators in output, got '{result}'"
    )
