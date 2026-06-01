"""Property-based tests for directus_ac/generate.py."""
from __future__ import annotations

import tempfile
import os

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.config import load_config
from directus_ac.generate import serialize_config
from directus_ac.models import (
    DirectusACConfig,
    GroupDefinition,
    PermissionKeyword,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating valid DirectusACConfig objects
# ---------------------------------------------------------------------------

# Strategy for valid collection/role names: alphanumeric + underscores, 1-50 chars
_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,49}", fullmatch=True)

# Strategy for non-empty subsets of PermissionKeyword
_permission_set_strategy = st.lists(
    st.sampled_from(list(PermissionKeyword)),
    min_size=1,
    max_size=4,
    unique=True,
)


@st.composite
def directus_ac_config_strategy(draw):
    """Generate a random valid DirectusACConfig with non-empty collections,
    roles, and groups where each group has valid Permission_Set subsets."""
    # Generate 1-5 unique collection names
    collections = draw(
        st.lists(_name_strategy, min_size=1, max_size=5, unique=True)
    )

    # Generate 1-5 unique role names
    roles = draw(
        st.lists(_name_strategy, min_size=1, max_size=5, unique=True)
    )

    # Build one group per collection (matching the Generator's output structure)
    groups = []
    for collection in collections:
        # Each group has at least one role with permissions
        # Pick a non-empty subset of roles for this group
        num_roles = draw(st.integers(min_value=1, max_value=len(roles)))
        group_roles = draw(
            st.lists(
                st.sampled_from(roles),
                min_size=num_roles,
                max_size=num_roles,
                unique=True,
            )
        )

        permissions: dict[str, list[PermissionKeyword]] = {}
        for role in group_roles:
            permissions[role] = draw(_permission_set_strategy)

        groups.append(
            GroupDefinition(
                collections=[collection],
                permissions=permissions,
            )
        )

    return DirectusACConfig(
        collections=collections,
        roles=roles,
        groups=groups,
    )


# ---------------------------------------------------------------------------
# Property-based test: Serialization round-trip
# ---------------------------------------------------------------------------


# Feature: directus-ac-generate, Property 1: Serialization round-trip
# **Validates: Requirements 5.1, 5.2, 5.3, 6.2**
@given(config=directus_ac_config_strategy())
@settings(max_examples=100)
def test_serialization_round_trip(config: DirectusACConfig, tmp_path_factory):
    """For any valid DirectusACConfig, serializing with serialize_config() and
    parsing back with load_config() produces an equivalent config.

    This verifies:
    - The serialized YAML has correct top-level key ordering (collections, roles, groups)
    - Permission_Set values are space-separated strings parseable by load_config
    - The round-trip preserves all collections, roles, and group permissions
    """
    # Serialize the config to YAML
    yaml_str = serialize_config(config)

    # Write to a temp file (load_config requires a file path)
    tmp_dir = tmp_path_factory.mktemp("roundtrip")
    tmp_file = tmp_dir / "directus_ac.yaml"
    tmp_file.write_text(yaml_str, encoding="utf-8")

    # Parse back with load_config
    parsed = load_config(str(tmp_file))

    # Assert equivalence: same collections
    assert sorted(parsed.collections) == sorted(config.collections)

    # Assert equivalence: same roles
    assert sorted(parsed.roles) == sorted(config.roles)

    # Assert equivalence: same number of groups
    assert len(parsed.groups) == len(config.groups)

    # Assert equivalence: same group permissions (order-independent comparison)
    # Build a map of collection -> {role -> set(keywords)} for both configs
    def build_permission_map(cfg: DirectusACConfig) -> dict[str, dict[str, set[PermissionKeyword]]]:
        result: dict[str, dict[str, set[PermissionKeyword]]] = {}
        for group in cfg.groups:
            for col in group.collections:
                if col not in result:
                    result[col] = {}
                for role, keywords in group.permissions.items():
                    result[col][role] = set(keywords)
        return result

    original_map = build_permission_map(config)
    parsed_map = build_permission_map(parsed)

    assert original_map == parsed_map
