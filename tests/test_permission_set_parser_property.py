"""Property-based test for Permission_Set parser classification.

Feature: custom-permissions-display, Property 7: Permission_Set parser classifies ACTION_C_N tokens as custom refs
Validates: Requirements 6.1, 6.2

Property 7: For any Permission_Set string containing tokens that match
`^(CREATE|READ|UPDATE|DELETE)_C_\\d+$`, the parser SHALL classify those tokens
as custom permission references (not as standard keywords or invalid tokens).
"""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.config import _parse_permission_set
from directus_ac.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ACTIONS = ["CREATE", "READ", "UPDATE", "DELETE"]

# Pattern used by the parser to classify custom refs
_ACTION_C_N_PATTERN = re.compile(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$")


@st.composite
def _action_c_n_token(draw):
    """Generate a valid ACTION_C_N token (e.g., 'UPDATE_C_3', 'READ_C_12')."""
    action = draw(st.sampled_from(_ACTIONS))
    counter = draw(st.integers(min_value=0, max_value=999_999))
    return f"{action}_C_{counter}"


@st.composite
def _permission_set_with_custom_refs(draw):
    """Generate a Permission_Set string containing one or more ACTION_C_N tokens.

    May optionally include standard keywords (READ, WRITE, UPDATE, DELETE)
    interspersed with custom refs.
    """
    standard_keywords = ["READ", "WRITE", "UPDATE", "DELETE"]

    # Generate at least 1 custom ref token
    num_refs = draw(st.integers(min_value=1, max_value=5))
    refs = [draw(_action_c_n_token()) for _ in range(num_refs)]

    # Optionally add standard keywords
    num_keywords = draw(st.integers(min_value=0, max_value=3))
    keywords = [draw(st.sampled_from(standard_keywords)) for _ in range(num_keywords)]

    # Combine and shuffle
    all_tokens = refs + keywords
    shuffled = draw(st.permutations(all_tokens))
    return " ".join(shuffled), refs, keywords


@st.composite
def _invalid_token(draw):
    """Generate tokens that don't match standard keywords or ACTION_C_N pattern.

    Examples: 'INVALID_C_1', 'C_1', 'FOO', 'EXECUTE_C_5', 'read_c_1' (lowercase).
    """
    invalid_options = st.one_of(
        # Old-format C_N pattern (no longer valid)
        st.integers(min_value=0, max_value=999).map(lambda n: f"C_{n}"),
        # Invalid action prefix
        st.sampled_from(["EXECUTE", "SELECT", "INSERT", "PATCH", "REMOVE"]).flatmap(
            lambda action: st.integers(min_value=0, max_value=99).map(
                lambda n: f"{action}_C_{n}"
            )
        ),
        # Lowercase action_c_n (parser uses upper for keywords but match is case-sensitive for refs)
        st.sampled_from(["create", "read", "update", "delete"]).flatmap(
            lambda action: st.integers(min_value=0, max_value=99).map(
                lambda n: f"{action}_C_{n}"
            )
        ),
        # Random non-keyword strings
        st.sampled_from(["FOO", "BAR", "UNKNOWN", "ADMIN", "NONE", "FULL"]),
    )
    return draw(invalid_options)


# ---------------------------------------------------------------------------
# Feature: custom-permissions-display, Property 7
# Validates: Requirements 6.1, 6.2
# ---------------------------------------------------------------------------


@given(data=_permission_set_with_custom_refs())
@settings(max_examples=200)
def test_parser_classifies_action_c_n_tokens_as_custom_refs(
    data: tuple[str, list[str], list[str]],
) -> None:
    """Property 7: Permission_Set parser classifies ACTION_C_N tokens as custom refs.

    For any Permission_Set string containing tokens that match the ACTION_C_N
    pattern, the parser SHALL classify those tokens as custom permission references.

    **Validates: Requirements 6.1, 6.2**
    """
    perm_set_str, expected_refs, _ = data

    keywords, custom_refs = _parse_permission_set(
        perm_set_str, role="test_role", collection="test_collection"
    )

    # All expected refs should appear in the custom_refs output (deduplicated)
    expected_unique_refs = list(dict.fromkeys(expected_refs))
    assert set(custom_refs) == set(expected_unique_refs), (
        f"Expected custom refs {expected_unique_refs}, got {custom_refs} "
        f"for input '{perm_set_str}'"
    )

    # No ACTION_C_N token should appear as a keyword
    keyword_values = [kw.value for kw in keywords]
    for ref in expected_unique_refs:
        assert ref not in keyword_values, (
            f"Custom ref '{ref}' was incorrectly classified as a keyword"
        )


@given(token=_action_c_n_token())
@settings(max_examples=200)
def test_parser_single_action_c_n_token_is_custom_ref(token: str) -> None:
    """Property 7: A single ACTION_C_N token is classified as a custom ref.

    For any token matching the ACTION_C_N pattern, parsing it alone SHALL
    result in it appearing in the custom_refs list and not in keywords.

    **Validates: Requirements 6.1, 6.2**
    """
    keywords, custom_refs = _parse_permission_set(
        token, role="test_role", collection="test_collection"
    )

    assert custom_refs == [token], (
        f"Expected custom_refs=['{token}'], got {custom_refs}"
    )
    assert keywords == [], (
        f"Expected no keywords, got {keywords} for token '{token}'"
    )


@given(token=_invalid_token())
@settings(max_examples=200)
def test_parser_raises_config_error_for_invalid_tokens(token: str) -> None:
    """Property 7: Invalid tokens raise ConfigError.

    For any token that does not match a standard keyword or the ACTION_C_N
    pattern, the parser SHALL raise a ConfigError.

    **Validates: Requirements 6.2**
    """
    with pytest.raises(ConfigError):
        _parse_permission_set(token, role="test_role", collection="test_collection")
