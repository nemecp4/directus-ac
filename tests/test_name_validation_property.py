"""Property-based tests for CustomPermissionEntry.validate_name_pattern (Property 3).

**Validates: Requirements 2.1, 2.2**

Property 3: Name validation accepts only valid ACTION_C_N patterns.

For any string, CustomPermissionEntry.validate_name_pattern SHALL accept it
if and only if it matches ^(CREATE|READ|UPDATE|DELETE)_C_\\d+$.
"""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from directus_ac.models import CustomPermissionEntry


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_VALID_ACTIONS = ["CREATE", "READ", "UPDATE", "DELETE"]

# Strategy for valid ACTION_C_N names
_valid_name = st.builds(
    lambda action, counter: f"{action}_C_{counter}",
    action=st.sampled_from(_VALID_ACTIONS),
    counter=st.integers(min_value=0, max_value=99999),
)

# Strategy for arbitrary strings that do NOT match the valid pattern
_ACTION_C_N_PATTERN = re.compile(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$")

_invalid_name = st.text(min_size=0, max_size=50).filter(
    lambda s: not _ACTION_C_N_PATTERN.match(s)
)


# ---------------------------------------------------------------------------
# Property 3: Name validation accepts only valid ACTION_C_N patterns
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(name=_valid_name)
def test_valid_action_c_n_names_are_accepted(name: str) -> None:
    """All strings matching ^(CREATE|READ|UPDATE|DELETE)_C_\\d+$ are accepted.

    **Validates: Requirements 2.1, 2.2**
    """
    # Should not raise — create a valid CustomPermissionEntry
    entry = CustomPermissionEntry(
        name=name,
        policy="test-policy",
        collection="test-collection",
        action="read",
    )
    assert entry.name == name


@settings(max_examples=200, deadline=None)
@given(name=_invalid_name)
def test_invalid_names_are_rejected(name: str) -> None:
    """All strings NOT matching ^(CREATE|READ|UPDATE|DELETE)_C_\\d+$ are rejected.

    **Validates: Requirements 2.1, 2.2**
    """
    with pytest.raises(ValidationError):
        CustomPermissionEntry(
            name=name,
            policy="test-policy",
            collection="test-collection",
            action="read",
        )
