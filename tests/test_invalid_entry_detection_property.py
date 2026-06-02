"""Property-based tests for invalid custom permission entry detection.

Feature: custom-permissions, Property 5: Invalid custom permission entry detection
Validates: Requirements 3.4, 3.6, 8.3

Property 5: For any custom permission entry that is missing a required field
(name, policy, collection, or action) or has an action value not in
{create, read, update, delete}, the config loader SHALL raise a ConfigError
whose message identifies the specific problem and the entry index.
"""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.config import _parse_custom_permissions
from directus_ac.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid string values for required fields (1-255 chars)
_valid_string = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=50,
)

# Valid C_N name pattern
_valid_name = st.tuples(st.sampled_from(["CREATE", "READ", "UPDATE", "DELETE"]), st.integers(min_value=1, max_value=1000)).map(lambda t: f"{t[0]}_C_{t[1]}")

# Valid actions
_valid_action = st.sampled_from(["create", "read", "update", "delete"])

# Invalid actions: strings that are NOT one of the valid actions
_invalid_action = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.lower() not in {"create", "read", "update", "delete"})

# Required fields for a custom permission entry
_REQUIRED_FIELDS = ("name", "policy", "collection", "action")


@st.composite
def _valid_entry(draw) -> dict:
    """Generate a fully valid custom permission entry."""
    return {
        "name": draw(_valid_name),
        "policy": draw(_valid_string),
        "collection": draw(_valid_string),
        "action": draw(_valid_action),
    }


@st.composite
def _entry_missing_field(draw):
    """Generate an entry with one required field removed.

    Returns (entry_list, missing_field, entry_index) where entry_list is a
    list of entries with one entry at entry_index missing the specified field.
    """
    # Generate 0-3 valid entries before the invalid one
    num_before = draw(st.integers(min_value=0, max_value=3))
    entries_before = [draw(_valid_entry()) for _ in range(num_before)]

    # Generate the invalid entry (missing one required field)
    full_entry = draw(_valid_entry())
    field_to_remove = draw(st.sampled_from(list(_REQUIRED_FIELDS)))
    invalid_entry = {k: v for k, v in full_entry.items() if k != field_to_remove}

    # Generate 0-2 valid entries after the invalid one
    num_after = draw(st.integers(min_value=0, max_value=2))
    entries_after = [draw(_valid_entry()) for _ in range(num_after)]

    entry_list = entries_before + [invalid_entry] + entries_after
    entry_index = num_before

    return entry_list, field_to_remove, entry_index


@st.composite
def _entry_with_invalid_action(draw):
    """Generate an entry with an invalid action value.

    Returns (entry_list, invalid_action_value, entry_index) where entry_list
    contains one entry at entry_index with an invalid action.
    """
    # Generate 0-3 valid entries before the invalid one
    num_before = draw(st.integers(min_value=0, max_value=3))
    entries_before = [draw(_valid_entry()) for _ in range(num_before)]

    # Generate the invalid entry (invalid action)
    invalid_action_value = draw(_invalid_action)
    invalid_entry = {
        "name": draw(_valid_name),
        "policy": draw(_valid_string),
        "collection": draw(_valid_string),
        "action": invalid_action_value,
    }

    # Generate 0-2 valid entries after the invalid one
    num_after = draw(st.integers(min_value=0, max_value=2))
    entries_after = [draw(_valid_entry()) for _ in range(num_after)]

    entry_list = entries_before + [invalid_entry] + entries_after
    entry_index = num_before

    return entry_list, invalid_action_value, entry_index


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 5: Invalid custom permission entry detection
# Validates: Requirements 3.4, 3.6, 8.3
# ---------------------------------------------------------------------------


@given(data=_entry_missing_field())
@settings(max_examples=100)
def test_missing_required_field_raises_config_error(data) -> None:
    """Property 5: Missing required field raises ConfigError with correct message.

    For any custom permission entry that is missing a required field (name,
    policy, collection, or action), _parse_custom_permissions SHALL raise a
    ConfigError whose message identifies the missing field name and the
    zero-based entry index.

    **Validates: Requirements 3.4**
    """
    entry_list, missing_field, entry_index = data

    with pytest.raises(ConfigError) as exc_info:
        _parse_custom_permissions(entry_list)

    error_message = str(exc_info.value)

    # Verify the error message contains the entry index
    assert str(entry_index) in error_message, (
        f"Error message should contain entry index {entry_index}, "
        f"got: '{error_message}'"
    )

    # Verify the error message contains the missing field name
    assert missing_field in error_message, (
        f"Error message should contain missing field name '{missing_field}', "
        f"got: '{error_message}'"
    )

    # Verify the exact message format
    expected_msg = (
        f"Custom permission at index {entry_index} is missing required field: {missing_field}"
    )
    assert error_message == expected_msg, (
        f"Expected message: '{expected_msg}', got: '{error_message}'"
    )


@given(data=_entry_with_invalid_action())
@settings(max_examples=100)
def test_invalid_action_raises_config_error(data) -> None:
    """Property 5: Invalid action value raises ConfigError with correct message.

    For any custom permission entry with an action value not in
    {create, read, update, delete}, _parse_custom_permissions SHALL raise a
    ConfigError whose message identifies the invalid action value and the
    entry index.

    **Validates: Requirements 3.6, 8.3**
    """
    entry_list, invalid_action_value, entry_index = data

    with pytest.raises(ConfigError) as exc_info:
        _parse_custom_permissions(entry_list)

    error_message = str(exc_info.value)

    # Verify the error message contains the entry index
    assert str(entry_index) in error_message, (
        f"Error message should contain entry index {entry_index}, "
        f"got: '{error_message}'"
    )

    # Verify the error message contains the invalid action value
    assert invalid_action_value in error_message, (
        f"Error message should contain invalid action '{invalid_action_value}', "
        f"got: '{error_message}'"
    )

    # Verify the exact message format
    expected_msg = (
        f"Custom permission at index {entry_index} has invalid action "
        f"'{invalid_action_value}'. Must be one of: create, read, update, delete"
    )
    assert error_message == expected_msg, (
        f"Expected message: '{expected_msg}', got: '{error_message}'"
    )


@given(data=_entry_missing_field())
@settings(max_examples=100)
def test_missing_field_error_is_config_error_type(data) -> None:
    """Property 5: Missing field error is specifically a ConfigError.

    For any entry with a missing required field, the raised exception SHALL
    be an instance of ConfigError (not a generic exception).

    **Validates: Requirements 3.4**
    """
    entry_list, missing_field, entry_index = data

    with pytest.raises(ConfigError):
        _parse_custom_permissions(entry_list)


@given(data=_entry_with_invalid_action())
@settings(max_examples=100)
def test_invalid_action_error_is_config_error_type(data) -> None:
    """Property 5: Invalid action error is specifically a ConfigError.

    For any entry with an invalid action value, the raised exception SHALL
    be an instance of ConfigError (not a generic exception).

    **Validates: Requirements 3.6, 8.3**
    """
    entry_list, invalid_action_value, entry_index = data

    with pytest.raises(ConfigError):
        _parse_custom_permissions(entry_list)
