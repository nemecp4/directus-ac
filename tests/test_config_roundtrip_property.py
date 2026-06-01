"""Property-based test for config parsing round-trip (Feature: custom-permissions).

Property 6: Config parsing round-trip
For any valid DirectusACConfig containing custom permissions, serializing it to
YAML and parsing it back with load_config SHALL produce an equivalent
custom_permissions list (same entries with same field values).

**Validates: Requirements 3.1, 3.2**
"""
from __future__ import annotations

import tempfile
import os

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.config import load_config
from directus_ac.generate import serialize_config
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusACConfig,
    GroupDefinition,
    PermissionKeyword,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_action = st.sampled_from(["create", "read", "update", "delete"])

# Simple field names: lowercase letters, 1-20 chars
_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

# Simple string values for names (1-50 chars, printable ASCII to avoid YAML issues)
_simple_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=50,
)

# Collection names: simple identifiers
_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)

# Role names
_role_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
)


# Strategy for validation dicts (simple nested structures that survive YAML round-trip)
@st.composite
def _validation_dict(draw):
    """Generate a simple validation dict that round-trips cleanly through YAML."""
    field = draw(_field_name)
    operator = draw(st.sampled_from(["_eq", "_neq", "_contains", "_in"]))
    value = draw(st.one_of(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
        st.integers(min_value=0, max_value=100),
        st.booleans(),
    ))
    return {"_and": [{field: {operator: value}}]}


# Strategy for non-null, non-empty optional attributes
_opt_validation = st.one_of(st.none(), _validation_dict())
_opt_fields = st.one_of(
    st.none(),
    st.lists(_field_name, min_size=1, max_size=5),
)
_opt_permissions = st.one_of(st.none(), _validation_dict())


@st.composite
def _custom_permission_entry(draw, counter: int):
    """Generate a valid CustomPermissionEntry."""
    policy = draw(_simple_name)
    collection = draw(_collection_name)
    action = draw(_action)
    validation = draw(_opt_validation)
    fields = draw(_opt_fields)
    permissions = draw(_opt_permissions)

    # Build a deterministic name using C_N pattern
    entry_name = f"C_{counter}"

    return CustomPermissionEntry(
        name=entry_name,
        policy=policy,
        collection=collection,
        action=action,
        validation=validation,
        fields=fields,
        permissions=permissions,
    )


@st.composite
def _valid_config_with_custom_permissions(draw):
    """Generate a valid DirectusACConfig with custom_permissions.

    Ensures:
    - At least 1 collection, 1 role, 1 group
    - 1-5 custom permission entries
    - All values are YAML-safe (round-trip cleanly)
    """
    # Generate collections (1-3)
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collections = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )

    # Generate roles (1-3)
    num_roles = draw(st.integers(min_value=1, max_value=3))
    roles = draw(
        st.lists(
            _role_name,
            min_size=num_roles,
            max_size=num_roles,
            unique=True,
        )
    )

    # Generate at least one group
    keywords = draw(
        st.lists(
            st.sampled_from(list(PermissionKeyword)),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    group = GroupDefinition(
        collections=collections[:1],
        permissions={roles[0]: keywords},
    )

    # Generate 1-5 custom permission entries
    num_custom = draw(st.integers(min_value=1, max_value=5))
    custom_permissions = []
    for i in range(num_custom):
        entry = draw(_custom_permission_entry(counter=i + 1))
        custom_permissions.append(entry)

    return DirectusACConfig(
        collections=collections,
        roles=roles,
        groups=[group],
        custom_permissions=custom_permissions,
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 6: Config parsing round-trip
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------


@given(config=_valid_config_with_custom_permissions())
@settings(max_examples=100)
def test_config_parsing_round_trip(config: DirectusACConfig) -> None:
    """Property 6: Config parsing round-trip.

    For any valid DirectusACConfig containing custom permissions, serializing
    it to YAML and parsing it back with load_config SHALL produce an equivalent
    custom_permissions list (same entries with same field values).

    **Validates: Requirements 3.1, 3.2**
    """
    # Step 1: Serialize the config to YAML
    yaml_output = serialize_config(config)

    # Step 2: Write to a temporary file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(yaml_output)
        tmp_path = f.name

    try:
        # Step 3: Parse back with load_config
        parsed_config = load_config(tmp_path)

        # Step 4: Verify equivalence of custom_permissions
        assert len(parsed_config.custom_permissions) == len(config.custom_permissions), (
            f"Expected {len(config.custom_permissions)} custom permissions after "
            f"round-trip, got {len(parsed_config.custom_permissions)}"
        )

        for i, (original, parsed) in enumerate(
            zip(config.custom_permissions, parsed_config.custom_permissions)
        ):
            assert parsed.name == original.name, (
                f"Entry {i}: name mismatch: '{parsed.name}' != '{original.name}'"
            )
            assert parsed.policy == original.policy, (
                f"Entry {i}: policy mismatch: '{parsed.policy}' != '{original.policy}'"
            )
            assert parsed.collection == original.collection, (
                f"Entry {i}: collection mismatch: '{parsed.collection}' != '{original.collection}'"
            )
            assert parsed.action == original.action, (
                f"Entry {i}: action mismatch: '{parsed.action}' != '{original.action}'"
            )

            # For optional attributes, serialize_config skips empty dicts/lists,
            # so after round-trip they become None. We normalize for comparison:
            # - None stays None
            # - {} becomes None (skipped during serialization)
            # - [] becomes None (skipped during serialization)
            # - Non-empty values stay as-is
            def normalize(val):
                if val is None:
                    return None
                if val == {} or val == []:
                    return None
                return val

            assert normalize(parsed.validation) == normalize(original.validation), (
                f"Entry {i}: validation mismatch: "
                f"{parsed.validation} != {original.validation}"
            )
            assert normalize(parsed.fields) == normalize(original.fields), (
                f"Entry {i}: fields mismatch: "
                f"{parsed.fields} != {original.fields}"
            )
            assert normalize(parsed.permissions) == normalize(original.permissions), (
                f"Entry {i}: permissions mismatch: "
                f"{parsed.permissions} != {original.permissions}"
            )
    finally:
        # Clean up temp file
        os.unlink(tmp_path)
