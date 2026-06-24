"""Property-based test for config serialization round-trip (Feature: custom-permissions).

Property 4: Config serialization round-trip preserves custom permission data
For any valid DirectusACConfig containing custom permissions with ACTION_C_N names,
serializing with serialize_config and then loading with load_config SHALL produce an
equivalent config where all custom permission names, Permission_Set references, and
associated data are preserved.

**Validates: Requirements 3.1, 3.2, 3.3**
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

    # Build a deterministic name using ACTION_C_N pattern
    entry_name = f"{action.upper()}_C_{counter}"

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
def _valid_config_with_custom_permissions_and_refs(draw):
    """Generate a valid DirectusACConfig with custom_permissions AND group refs.

    Ensures:
    - At least 1 collection, 1 role, 1 group
    - 1-5 custom permission entries
    - Groups reference custom permissions via custom_permission_refs
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

    # Generate 1-5 custom permission entries
    num_custom = draw(st.integers(min_value=1, max_value=5))
    custom_permissions = []
    for i in range(num_custom):
        entry = draw(_custom_permission_entry(counter=i + 1))
        custom_permissions.append(entry)

    # Build group with standard keywords AND custom permission refs
    keywords = draw(
        st.lists(
            st.sampled_from(list(PermissionKeyword)),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )

    # Assign some custom permissions as refs to roles in the group
    # Each role gets a subset of custom permission names
    custom_permission_refs: dict[str, list[str]] = {}
    all_custom_names = [cp.name for cp in custom_permissions]

    for role in roles:
        # Each role gets at least one custom ref (draw a non-empty subset)
        num_refs = draw(st.integers(min_value=1, max_value=len(all_custom_names)))
        refs = draw(
            st.lists(
                st.sampled_from(all_custom_names),
                min_size=num_refs,
                max_size=num_refs,
                unique=True,
            )
        )
        custom_permission_refs[role] = refs

    group = GroupDefinition(
        collections=collections[:1],
        permissions={roles[0]: keywords},
        custom_permission_refs=custom_permission_refs,
    )

    return DirectusACConfig(
        collections=collections,
        roles=roles,
        groups=[group],
        custom_permissions=custom_permissions,
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 4: Config serialization round-trip
# Validates: Requirements 3.1, 3.2, 3.3
# ---------------------------------------------------------------------------


@given(config=_valid_config_with_custom_permissions_and_refs())
@settings(max_examples=100)
def test_config_roundtrip_preserves_custom_permission_data(config: DirectusACConfig) -> None:
    """Property 4: Config serialization round-trip preserves custom permission data.

    For any valid DirectusACConfig containing custom permissions with ACTION_C_N names,
    serializing with serialize_config and then loading with load_config SHALL produce
    an equivalent config where all custom permission names, Permission_Set references,
    and associated data are preserved.

    **Validates: Requirements 3.1, 3.2, 3.3**
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

        # --- Verify custom permission names are preserved (Req 3.1) ---
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
                f"Entry {i}: collection mismatch: "
                f"'{parsed.collection}' != '{original.collection}'"
            )
            assert parsed.action == original.action, (
                f"Entry {i}: action mismatch: '{parsed.action}' != '{original.action}'"
            )

            # For optional attributes, serialize_config skips empty dicts/lists,
            # so after round-trip they become None. Normalize for comparison.
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

        # --- Verify Permission_Set references in groups are preserved (Req 3.2) ---
        assert len(parsed_config.groups) == len(config.groups), (
            f"Expected {len(config.groups)} groups after round-trip, "
            f"got {len(parsed_config.groups)}"
        )

        for g_idx, (orig_group, parsed_group) in enumerate(
            zip(config.groups, parsed_config.groups)
        ):
            # Verify custom_permission_refs are preserved for each role
            orig_refs = orig_group.custom_permission_refs
            parsed_refs = parsed_group.custom_permission_refs

            # All roles with custom refs in original should exist in parsed
            for role_name, orig_role_refs in orig_refs.items():
                assert role_name in parsed_refs, (
                    f"Group {g_idx}: role '{role_name}' missing from "
                    f"parsed custom_permission_refs. "
                    f"Original refs: {orig_refs}, Parsed refs: {parsed_refs}"
                )
                # Compare as sets since order within a Permission_Set string
                # is: keywords first, then custom refs in list order.
                # serialize_config preserves the list order of custom_refs.
                assert parsed_refs[role_name] == orig_role_refs, (
                    f"Group {g_idx}, role '{role_name}': "
                    f"custom_permission_refs mismatch: "
                    f"{parsed_refs[role_name]} != {orig_role_refs}"
                )

        # --- Verify standard keywords are also preserved (Req 3.3 context) ---
        for g_idx, (orig_group, parsed_group) in enumerate(
            zip(config.groups, parsed_config.groups)
        ):
            for role_name, orig_keywords in orig_group.permissions.items():
                assert role_name in parsed_group.permissions, (
                    f"Group {g_idx}: role '{role_name}' missing from "
                    f"parsed permissions"
                )
                # Keywords should be preserved (possibly reordered to canonical)
                assert set(parsed_group.permissions[role_name]) == set(orig_keywords), (
                    f"Group {g_idx}, role '{role_name}': "
                    f"keywords mismatch: "
                    f"{parsed_group.permissions[role_name]} != {orig_keywords}"
                )
    finally:
        # Clean up temp file
        os.unlink(tmp_path)
