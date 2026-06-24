"""Property-based test for name generation format.

Feature: custom-permissions-display, Property 1: Name generation produces valid ACTION_C_N format
Validates: Requirements 1.1, 1.2

Property 1: For any valid action string (one of "create", "read", "update",
"delete", in any casing) and any positive integer counter,
`generate_permission_name(action, counter)` SHALL produce a string matching
the pattern `^(CREATE|READ|UPDATE|DELETE)_C_\\d+$` where the action prefix is
the uppercased action and the numeric suffix equals the counter.
"""
from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.generate import generate_permission_name


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid actions in any casing: generate mixed-case variants of the four actions
_BASE_ACTIONS = ["create", "read", "update", "delete"]


@st.composite
def _any_cased_action(draw):
    """Generate a valid action string in any casing (e.g., 'CrEaTe', 'READ', 'delete')."""
    base = draw(st.sampled_from(_BASE_ACTIONS))
    # Apply random casing to each character
    chars = []
    for ch in base:
        if draw(st.booleans()):
            chars.append(ch.upper())
        else:
            chars.append(ch.lower())
    return "".join(chars)


# Positive integer counters
_positive_counter = st.integers(min_value=1, max_value=1_000_000)

# Compiled regex for the expected pattern
_ACTION_C_N_PATTERN = re.compile(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$")


# ---------------------------------------------------------------------------
# Feature: custom-permissions-display, Property 1
# Validates: Requirements 1.1, 1.2
# ---------------------------------------------------------------------------


@given(action=_any_cased_action(), counter=_positive_counter)
@settings(max_examples=200)
def test_name_generation_matches_action_c_n_pattern(action: str, counter: int) -> None:
    """Property 1: Name generation produces valid ACTION_C_N format.

    For any valid action string in any casing and any positive integer counter,
    the generated name SHALL match the pattern ^(CREATE|READ|UPDATE|DELETE)_C_\\d+$.

    **Validates: Requirements 1.1, 1.2**
    """
    result = generate_permission_name(action, counter)

    assert _ACTION_C_N_PATTERN.match(result), (
        f"Generated name '{result}' does not match pattern "
        f"^(CREATE|READ|UPDATE|DELETE)_C_\\d+$ for action='{action}', counter={counter}"
    )


@given(action=_any_cased_action(), counter=_positive_counter)
@settings(max_examples=200)
def test_name_generation_action_prefix_is_uppercased(action: str, counter: int) -> None:
    """Property 1: The action prefix in the generated name is the uppercased action.

    For any valid action string in any casing, the prefix before '_C_' SHALL be
    the uppercased version of the input action.

    **Validates: Requirements 1.1, 1.2**
    """
    result = generate_permission_name(action, counter)

    # Extract the prefix (everything before _C_)
    prefix = result.split("_C_")[0]

    assert prefix == action.upper(), (
        f"Expected prefix '{action.upper()}', got '{prefix}' "
        f"for action='{action}', counter={counter}"
    )


@given(action=_any_cased_action(), counter=_positive_counter)
@settings(max_examples=200)
def test_name_generation_numeric_suffix_equals_counter(action: str, counter: int) -> None:
    """Property 1: The numeric suffix in the generated name equals the counter.

    For any valid action and positive integer counter, the numeric portion
    after '_C_' SHALL equal the counter value.

    **Validates: Requirements 1.1, 1.2**
    """
    result = generate_permission_name(action, counter)

    # Extract the numeric suffix (everything after the last _C_)
    suffix_str = result.split("_C_")[1]
    suffix_int = int(suffix_str)

    assert suffix_int == counter, (
        f"Expected counter {counter}, got {suffix_int} from name '{result}' "
        f"for action='{action}'"
    )
