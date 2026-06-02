"""Property test for validation batch error collection (Property 9).

Feature: custom-permissions, Property 9: Validation batch error collection

For any set of custom permission entries where some reference unresolvable
policy names or unknown collections, the Validator SHALL collect ALL invalid
references before raising a single ValidationError that lists every
unresolvable policy name and every unknown collection.

**Validates: Requirements 8.1, 8.2**
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.exceptions import ValidationError
from directus_ac.models import CustomPermissionEntry, DirectusPolicy
from directus_ac.validator import Validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client_with_policies(policy_names: list[str]) -> MagicMock:
    """Return a mock DirectusClient with the given policy names."""
    client = MagicMock()
    client.get_policies.return_value = [
        DirectusPolicy(id=f"policy-id-{i}", name=name)
        for i, name in enumerate(policy_names)
    ]
    return client


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating policy/collection names
_name_st = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S"), exclude_characters="\x00"),
    min_size=1,
    max_size=30,
)

_collection_name_st = st.text(
    alphabet=st.characters(categories=("L", "N"), exclude_characters="\x00"),
    min_size=1,
    max_size=30,
)


@st.composite
def _entries_with_invalid_refs(draw):
    """Generate custom permission entries where some reference invalid policies/collections.

    Returns a tuple:
        (entries, existing_policies, config_collections,
         expected_unknown_policies, expected_unknown_collections)

    Guarantees at least one invalid reference (policy or collection) exists.
    """
    # Generate a set of existing policy names (at least 1)
    existing_policies = draw(
        st.lists(_name_st, min_size=1, max_size=10, unique=True)
    )
    # Generate a set of config collections (at least 1)
    config_collections = draw(
        st.lists(_collection_name_st, min_size=1, max_size=10, unique=True)
    )

    # Generate some invalid policy names (guaranteed not in existing_policies)
    invalid_policies = draw(
        st.lists(
            _name_st.filter(lambda x: x not in existing_policies),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )
    # Generate some invalid collections (guaranteed not in config_collections)
    invalid_collections = draw(
        st.lists(
            _collection_name_st.filter(lambda x: x not in config_collections),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )

    # Ensure at least one invalid reference exists
    if not invalid_policies and not invalid_collections:
        forced = draw(_name_st.filter(lambda x: x not in existing_policies))
        invalid_policies = [forced]

    # Build entries: mix of valid and invalid references
    entries: list[CustomPermissionEntry] = []
    counter = 1

    # Add entries with invalid policies (using valid collections)
    for pol in invalid_policies:
        col = draw(st.sampled_from(config_collections))
        action = draw(st.sampled_from(["create", "read", "update", "delete"]))
        entries.append(
            CustomPermissionEntry(
                name=f"{action.upper()}_C_{counter}",
                policy=pol,
                collection=col,
                action=action,
            )
        )
        counter += 1

    # Add entries with invalid collections (using valid policies)
    for col in invalid_collections:
        pol = draw(st.sampled_from(existing_policies))
        action = draw(st.sampled_from(["create", "read", "update", "delete"]))
        entries.append(
            CustomPermissionEntry(
                name=f"{action.upper()}_C_{counter}",
                policy=pol,
                collection=col,
                action=action,
            )
        )
        counter += 1

    # Optionally add some fully valid entries (to ensure they don't interfere)
    num_valid = draw(st.integers(min_value=0, max_value=5))
    for _ in range(num_valid):
        pol = draw(st.sampled_from(existing_policies))
        col = draw(st.sampled_from(config_collections))
        action = draw(st.sampled_from(["create", "read", "update", "delete"]))
        entries.append(
            CustomPermissionEntry(
                name=f"{action.upper()}_C_{counter}",
                policy=pol,
                collection=col,
                action=action,
            )
        )
        counter += 1

    # Shuffle entries so invalid ones aren't always first
    shuffled = draw(st.permutations(entries))

    return (
        list(shuffled),
        existing_policies,
        config_collections,
        set(invalid_policies),
        set(invalid_collections),
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 9: Validation batch error collection
# Validates: Requirements 8.1, 8.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=_entries_with_invalid_refs())
def test_property9_validation_batch_error_collection(data) -> None:
    """Property 9: Validation batch error collection.

    For any set of custom permission entries where some reference unresolvable
    policy names or unknown collections, the Validator SHALL collect ALL invalid
    references before raising a single ValidationError that lists every
    unresolvable policy name and every unknown collection.

    **Validates: Requirements 8.1, 8.2**
    """
    # Feature: custom-permissions, Property 9: Validation batch error collection
    entries, existing_policies, config_collections, expected_unknown_policies, expected_unknown_collections = data

    client = _make_client_with_policies(existing_policies)
    validator = Validator(client)

    # The validator must raise a single ValidationError
    with pytest.raises(ValidationError) as exc_info:
        validator.validate_custom_permissions(entries, config_collections)

    error = exc_info.value
    msg = str(error)

    # All unknown policies must be reported in the error message
    if expected_unknown_policies:
        assert "Custom permissions reference unknown policies:" in msg
        for pol_name in expected_unknown_policies:
            assert f"  - {pol_name}" in msg, (
                f"Expected unknown policy '{pol_name}' to be listed in error message"
            )

    # All unknown collections must be reported in the error message
    if expected_unknown_collections:
        assert "Custom permissions reference unknown collections:" in msg
        for col_name in expected_unknown_collections:
            assert f"  - {col_name}" in msg, (
                f"Expected unknown collection '{col_name}' to be listed in error message"
            )

    # The missing_names attribute should contain all invalid references
    reported_missing = set(error.missing_names)
    expected_all_missing = expected_unknown_policies | expected_unknown_collections
    assert reported_missing == expected_all_missing, (
        f"Expected missing_names={expected_all_missing!r}, got {reported_missing!r}"
    )

    # Verify it's a SINGLE error (not multiple raises) — the fact that we
    # caught exactly one exception and it contains ALL references confirms
    # batch collection behavior.
