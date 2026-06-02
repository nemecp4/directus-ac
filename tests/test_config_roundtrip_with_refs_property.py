"""Property-based test for config parsing round-trip with inline references.

Feature: custom-permissions, Property 4: Config parsing round-trip

For any valid DirectusACConfig containing custom permissions with inline
references in groups, serializing it to YAML and parsing it back with
load_config SHALL produce an equivalent config (same custom_permissions
entries with same field values, same Permission_Set contents including
custom references).

**Validates: Requirements 3.1, 3.2**
"""
from __future__ import annotations

import os
import tempfile

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

# Simple field names: lowercase letters and underscores, 1-20 chars
_field_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

# Simple string values for policy names (YAML-safe, no special chars)
_policy_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_- ",
    ),
    min_size=1,
    max_size=40,
)

# Collection names: simple identifiers (no YAML-breaking chars)
_collection_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=30,
)

# Role names: simple identifiers
_role_name = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- "),
    min_size=1,
    max_size=30,
)


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


_opt_validation = st.one_of(st.none(), _validation_dict())
_opt_fields = st.one_of(
    st.none(),
    st.lists(_field_name, min_size=1, max_size=5),
)
_opt_permissions = st.one_of(st.none(), _validation_dict())


@st.composite
def _valid_config_with_inline_refs(draw):
    """Generate a valid DirectusACConfig with custom permissions AND inline refs in groups.

    Ensures:
    - At least 1 collection, 1 role, 1 group
    - 1-5 custom permission entries with C_N names
    - Groups have custom_permission_refs populated for at least one role
    - Custom permission entries reference collections that exist in the config
    - All values are YAML-safe (round-trip cleanly)
    """
    # Generate collections (1-3, unique)
    num_collections = draw(st.integers(min_value=1, max_value=3))
    collections = draw(
        st.lists(
            _collection_name,
            min_size=num_collections,
            max_size=num_collections,
            unique=True,
        )
    )

    # Generate roles (1-3, unique)
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
    custom_permissions: list[CustomPermissionEntry] = []
    for i in range(num_custom):
        policy = draw(_policy_name)
        collection = draw(st.sampled_from(collections))
        action = draw(_action)
        validation = draw(_opt_validation)
        fields = draw(_opt_fields)
        permissions = draw(_opt_permissions)

        custom_permissions.append(
            CustomPermissionEntry(
                name=f"{action.upper()}_C_{i + 1}",
                policy=policy,
                collection=collection,
                action=action,
                validation=validation,
                fields=fields,
                permissions=permissions,
            )
        )

    # Build groups: one group per collection, with standard keywords and custom refs
    groups: list[GroupDefinition] = []
    for col in collections:
        # Assign standard keywords to each role
        permissions_dict: dict[str, list[PermissionKeyword]] = {}
        custom_refs_dict: dict[str, list[str]] = {}

        for role in roles:
            # Each role gets 1-4 random keywords
            keywords = draw(
                st.lists(
                    st.sampled_from(list(PermissionKeyword)),
                    min_size=1,
                    max_size=4,
                    unique=True,
                )
            )
            permissions_dict[role] = keywords

        # Assign custom permission refs to roles for this collection
        # Find which custom permissions reference this collection
        refs_for_col = [
            cp.name for cp in custom_permissions if cp.collection == col
        ]
        if refs_for_col:
            # Distribute refs among roles
            for ref in refs_for_col:
                role = draw(st.sampled_from(roles))
                if role not in custom_refs_dict:
                    custom_refs_dict[role] = []
                custom_refs_dict[role].append(ref)

        groups.append(
            GroupDefinition(
                collections=[col],
                permissions=permissions_dict,
                custom_permission_refs=custom_refs_dict,
            )
        )

    return DirectusACConfig(
        collections=sorted(collections),
        roles=sorted(roles),
        groups=groups,
        custom_permissions=custom_permissions,
    )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Property 4: Config parsing round-trip
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------


def _normalize_optional(val):
    """Normalize optional values for comparison after round-trip.

    serialize_config skips empty dicts/lists, so after round-trip they become None.
    """
    if val is None:
        return None
    if val == {} or val == []:
        return None
    return val


@given(config=_valid_config_with_inline_refs())
@settings(max_examples=100)
def test_config_parsing_round_trip_with_inline_refs(config: DirectusACConfig) -> None:
    """Property 4: Config parsing round-trip.

    For any valid DirectusACConfig containing custom permissions with inline
    references in groups, serializing it to YAML and parsing it back with
    load_config SHALL produce an equivalent config:
    - Same custom_permissions entries (name, policy, collection, action,
      validation, fields, permissions)
    - Same Permission_Set contents including custom references
      (same GroupDefinition.custom_permission_refs per role)

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

        # --- Verify custom_permissions entries ---
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
            assert _normalize_optional(parsed.validation) == _normalize_optional(
                original.validation
            ), (
                f"Entry {i}: validation mismatch: "
                f"{parsed.validation} != {original.validation}"
            )
            assert _normalize_optional(parsed.fields) == _normalize_optional(
                original.fields
            ), (
                f"Entry {i}: fields mismatch: "
                f"{parsed.fields} != {original.fields}"
            )
            assert _normalize_optional(parsed.permissions) == _normalize_optional(
                original.permissions
            ), (
                f"Entry {i}: permissions mismatch: "
                f"{parsed.permissions} != {original.permissions}"
            )

        # --- Verify groups' Permission_Set contents including custom refs ---
        assert len(parsed_config.groups) == len(config.groups), (
            f"Expected {len(config.groups)} groups after round-trip, "
            f"got {len(parsed_config.groups)}"
        )

        for g_idx, (orig_group, parsed_group) in enumerate(
            zip(config.groups, parsed_config.groups)
        ):
            # Verify collections match
            assert parsed_group.collections == orig_group.collections, (
                f"Group {g_idx}: collections mismatch: "
                f"{parsed_group.collections} != {orig_group.collections}"
            )

            # Verify standard keywords per role
            assert set(parsed_group.permissions.keys()) == set(
                orig_group.permissions.keys()
            ), (
                f"Group {g_idx}: permission roles mismatch: "
                f"{set(parsed_group.permissions.keys())} != "
                f"{set(orig_group.permissions.keys())}"
            )

            for role in orig_group.permissions:
                orig_keywords = set(orig_group.permissions[role])
                parsed_keywords = set(parsed_group.permissions[role])
                assert parsed_keywords == orig_keywords, (
                    f"Group {g_idx}, role '{role}': keywords mismatch: "
                    f"{parsed_keywords} != {orig_keywords}"
                )

            # Verify custom_permission_refs per role
            orig_refs = orig_group.custom_permission_refs
            parsed_refs = parsed_group.custom_permission_refs

            # All roles with refs in original should have same refs after round-trip
            all_ref_roles = set(orig_refs.keys()) | set(parsed_refs.keys())
            for role in all_ref_roles:
                orig_role_refs = sorted(orig_refs.get(role, []))
                parsed_role_refs = sorted(parsed_refs.get(role, []))
                assert parsed_role_refs == orig_role_refs, (
                    f"Group {g_idx}, role '{role}': custom_permission_refs mismatch: "
                    f"{parsed_role_refs} != {orig_role_refs}"
                )
    finally:
        # Clean up temp file
        os.unlink(tmp_path)
