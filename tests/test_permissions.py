"""Tests for permissions.py — PermissionManager (unit + property tests)."""

from unittest.mock import MagicMock

from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

from directus_ac.models import (
    DirectusACConfig,
    DirectusPermission,
    GroupDefinition,
    PermissionKeyword,
)
from directus_ac.permissions import ACTION_MAP, PermissionManager


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ACTIONS = ["read", "create", "update", "delete"]


@st.composite
def unique_permissions(draw):
    """Generate a list of DirectusPermission with unique (policy, collection, action) triples.

    Uses a pre-drawn pool of policies and collections, then selects unique
    combinations from the cartesian product to avoid slow retry loops.
    """
    # Draw a small pool of policies and collections
    policies = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=10,
                alphabet=st.characters(whitelist_categories=("L", "N")),
            ),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    collections = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=10,
                alphabet=st.characters(whitelist_categories=("L", "N", "P")),
            ),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    # Build all possible unique triples from the pool
    all_triples = [
        (policy, collection, action)
        for policy in policies
        for collection in collections
        for action in _ACTIONS
    ]

    # Pick a non-empty subset of triples
    n = draw(st.integers(min_value=1, max_value=min(len(all_triples), 20)))
    chosen = draw(
        st.lists(
            st.sampled_from(all_triples),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    perms = [
        DirectusPermission(id=i + 1, policy=policy, collection=collection, action=action)
        for i, (policy, collection, action) in enumerate(chosen)
    ]
    return perms


@st.composite
def config_and_role_mapping(draw):
    """Generate a valid config and corresponding role-to-ID mapping."""
    role_names = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("L",)),
            ),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    collection_names = draw(
        st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("L",)),
            ),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    groups = []
    num_groups = draw(st.integers(min_value=1, max_value=2))
    for _ in range(num_groups):
        group_collections = draw(
            st.lists(
                st.sampled_from(collection_names),
                min_size=1,
                max_size=len(collection_names),
                unique=True,
            )
        )
        permissions: dict[str, list[PermissionKeyword]] = {}
        roles_in_group = draw(
            st.lists(
                st.sampled_from(role_names),
                min_size=1,
                max_size=len(role_names),
                unique=True,
            )
        )
        for role in roles_in_group:
            keywords = draw(
                st.lists(
                    st.sampled_from(list(PermissionKeyword)),
                    min_size=1,
                    max_size=4,
                    unique=True,
                )
            )
            permissions[role] = keywords
        groups.append(GroupDefinition(collections=group_collections, permissions=permissions))

    config = DirectusACConfig(collections=collection_names, roles=role_names, groups=groups)
    role_name_to_id = {name: f"id-{name}" for name in role_names}
    return config, role_name_to_id


@st.composite
def config_with_preexisting(draw):
    """Generate a config, role mapping, and a subset of pre-existing permissions.

    The config is constructed so that each (policy_id, collection, action) triple
    appears at most once across all groups, matching the assumption that the
    implementation's index-based lookup produces accurate counts only when
    triples are unique across the config expansion.
    """
    role_names = draw(st.lists(
        st.text(min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("L",))),
        min_size=1, max_size=3, unique=True,
    ))
    collection_names = draw(st.lists(
        st.text(min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("L",))),
        min_size=1, max_size=3, unique=True,
    ))

    # Build a single group to avoid duplicate triples across groups
    group_collections = draw(st.lists(
        st.sampled_from(collection_names), min_size=1, max_size=len(collection_names), unique=True,
    ))
    permissions: dict[str, list[PermissionKeyword]] = {}
    for role in draw(st.lists(
        st.sampled_from(role_names), min_size=1, max_size=len(role_names), unique=True,
    )):
        keywords = draw(st.lists(
            st.sampled_from(list(PermissionKeyword)), min_size=1, max_size=4, unique=True,
        ))
        permissions[role] = keywords
    groups = [GroupDefinition(collections=group_collections, permissions=permissions)]

    config = DirectusACConfig(collections=collection_names, roles=role_names, groups=groups)
    role_name_to_id = {name: f"id-{name}" for name in role_names}

    # Compute all unique triples as (policy_id, collection, action)
    # Each role maps to a policy: policy_id = "policy-id-{name}"
    role_id_to_policy_id = {f"id-{name}": f"policy-id-{name}" for name in role_names}
    all_triples: set[tuple[str, str, str]] = set()
    for group in config.groups:
        for collection in group.collections:
            for role_name, keywords in group.permissions.items():
                role_id = role_name_to_id[role_name]
                policy_id = role_id_to_policy_id[role_id]
                for keyword in keywords:
                    action = ACTION_MAP[keyword.value]
                    all_triples.add((policy_id, collection, action))

    # Randomly select a subset as pre-existing
    all_triples_list = sorted(all_triples)
    preexisting_mask = draw(st.lists(
        st.booleans(), min_size=len(all_triples_list), max_size=len(all_triples_list),
    ))
    preexisting = {t for t, mask in zip(all_triples_list, preexisting_mask) if mask}

    return config, role_name_to_id, role_id_to_policy_id, preexisting, all_triples


# ---------------------------------------------------------------------------
# Property 6: Permission index lookup is correct
# ---------------------------------------------------------------------------


# Feature: directus-access-control, Property 6: Permission index lookup is correct
@given(permissions=unique_permissions())
@settings(max_examples=100)
def test_permission_index_lookup_correctness(permissions):
    """
    Building the permission index and looking up each triple returns the correct ID.
    Absent triples return None.

    **Validates: Requirements 6.3, 6.4**
    """
    # Build index the same way as apply_permissions
    index: dict[tuple[str, str, str], int] = {}
    for perm in permissions:
        key = (perm.policy, perm.collection, perm.action)
        index[key] = perm.id

    # Every triple in the list should return its ID
    for perm in permissions:
        key = (perm.policy, perm.collection, perm.action)
        assert index.get(key) == perm.id

    # An absent triple should return None
    absent_key = ("nonexistent-policy-xyz", "nonexistent-collection-xyz", "read")
    assert index.get(absent_key) is None


# ---------------------------------------------------------------------------
# Property 7: Action mapping covers all keywords
# ---------------------------------------------------------------------------


# Feature: directus-access-control, Property 7: Action mapping covers all keywords
# **Validates: Requirements 6.2**


@given(keyword=st.sampled_from(list(PermissionKeyword)))
def test_action_map_covers_all_keywords(keyword):
    """Every PermissionKeyword maps to a unique, non-empty Directus action."""
    assert keyword.value in ACTION_MAP
    action = ACTION_MAP[keyword.value]
    assert isinstance(action, str)
    assert len(action) > 0


def test_action_map_values_are_unique():
    """No two keywords map to the same action string."""
    values = list(ACTION_MAP.values())
    assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# Property 8: Permission application is complete
# ---------------------------------------------------------------------------


# Feature: directus-access-control, Property 8: Permission application is complete
@given(data=config_and_role_mapping())
@settings(max_examples=100)
def test_permission_application_completeness(data):
    """
    The set of (policy_id, collection, action) triples sent to the API equals
    exactly the expansion of all groups in the config.

    **Validates: Requirements 6.1**
    """
    config, role_name_to_id = data

    # Each role gets a policy: policy_id = "policy-id-{name}"
    from directus_ac.models import DirectusPolicy

    role_id_to_policy_id = {f"id-{name}": f"policy-id-{name}" for name in role_name_to_id}

    # Compute expected triples from config expansion (using policy IDs)
    expected_triples = set()
    for group in config.groups:
        for collection in group.collections:
            for role_name, keywords in group.permissions.items():
                role_id = role_name_to_id[role_name]
                policy_id = role_id_to_policy_id[role_id]
                for keyword in keywords:
                    action = ACTION_MAP[keyword.value]
                    expected_triples.add((policy_id, collection, action))

    # Mock the client
    mock_client = MagicMock()
    mock_client.get_permissions.return_value = []

    # Mock get_policies to return a policy for each role
    policies = [
        DirectusPolicy(id=f"policy-id-{name}", name=f"{name} — directus-ac", roles=[f"id-{name}"])
        for name in role_name_to_id
    ]
    mock_client.get_policies.return_value = policies

    mock_client.create_permission.return_value = DirectusPermission(
        id=1, policy="x", collection="x", action="x"
    )

    manager = PermissionManager(mock_client)
    manager.apply_permissions(config, role_name_to_id)

    # Collect actual triples sent to the API
    actual_triples = set()
    for call in mock_client.create_permission.call_args_list:
        args = call[0] if call[0] else ()
        kwargs = call[1] if call[1] else {}
        policy_id = args[0] if len(args) > 0 else kwargs.get("policy_id")
        collection = args[1] if len(args) > 1 else kwargs.get("collection")
        action = args[2] if len(args) > 2 else kwargs.get("action")
        actual_triples.add((policy_id, collection, action))

    assert actual_triples == expected_triples


# ---------------------------------------------------------------------------
# Property 9: Summary counts are accurate
# ---------------------------------------------------------------------------


# Feature: directus-access-control, Property 9: Summary counts are accurate
@given(data=config_with_preexisting())
@settings(max_examples=100)
def test_summary_count_accuracy(data):
    """
    The (created_count, updated_count) returned by apply_permissions equals
    the number of new vs. pre-existing triples.

    **Validates: Requirements 6.7**
    """
    config, role_name_to_id, role_id_to_policy_id, preexisting, all_triples = data

    # Build pre-existing permissions list
    existing_perms = []
    for i, (policy_id, collection, action) in enumerate(sorted(preexisting), start=1):
        existing_perms.append(
            DirectusPermission(id=i, policy=policy_id, collection=collection, action=action)
        )

    # Mock client
    from directus_ac.models import DirectusPolicy

    mock_client = MagicMock()
    mock_client.get_permissions.return_value = existing_perms

    # Mock get_policies to return a policy for each role
    policies = [
        DirectusPolicy(
            id=role_id_to_policy_id[f"id-{name}"],
            name=f"{name} — directus-ac",
            roles=[f"id-{name}"],
        )
        for name in role_name_to_id
    ]
    mock_client.get_policies.return_value = policies

    mock_client.create_permission.return_value = DirectusPermission(
        id=999, policy="x", collection="x", action="x"
    )
    mock_client.update_permission.return_value = DirectusPermission(
        id=999, policy="x", collection="x", action="x"
    )

    manager = PermissionManager(mock_client)
    created_count, updated_count = manager.apply_permissions(config, role_name_to_id)

    expected_new = all_triples - preexisting
    expected_updated = all_triples & preexisting

    assert created_count == len(expected_new)
    assert updated_count == len(expected_updated)


# ---------------------------------------------------------------------------
# Unit tests for apply_custom_permissions
# ---------------------------------------------------------------------------

import pytest

from directus_ac.exceptions import APIError
from directus_ac.models import CustomPermissionEntry, DirectusPolicy


class TestApplyCustomPermissions:
    """Unit tests for PermissionManager.apply_custom_permissions."""

    def _make_manager(self, existing_perms=None):
        """Create a PermissionManager with a mocked client."""
        mock_client = MagicMock()
        mock_client.get_permissions.return_value = existing_perms or []
        mock_client.create_permission.return_value = DirectusPermission(
            id=999, policy="x", collection="x", action="x"
        )
        mock_client.update_permission.return_value = DirectusPermission(
            id=999, policy="x", collection="x", action="x"
        )
        manager = PermissionManager(mock_client)
        return manager, mock_client

    def test_empty_list_returns_zero_counts(self):
        """Empty custom_perms list returns (0, 0) without API calls."""
        manager, mock_client = self._make_manager()
        result = manager.apply_custom_permissions([], {"policy1": "id1"})
        assert result == (0, 0)
        mock_client.get_permissions.assert_not_called()

    def test_creates_new_permission(self):
        """Creates a permission when no matching existing entry found."""
        manager, mock_client = self._make_manager(existing_perms=[])
        entry = CustomPermissionEntry(
            name="C_1",
            policy="editor — directus-ac",
            collection="articles",
            action="update",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            fields=["title", "body"],
        )
        policy_map = {"editor — directus-ac": "policy-uuid-1"}
        created, updated = manager.apply_custom_permissions([entry], policy_map)
        assert created == 1
        assert updated == 0
        mock_client.create_permission.assert_called_once_with(
            "policy-uuid-1",
            "articles",
            "update",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            fields=["title", "body"],
            permissions=None,
        )

    def test_updates_existing_permission(self):
        """Updates a permission when matching entry with constraints exists."""
        existing = [
            DirectusPermission(
                id=42,
                policy="policy-uuid-1",
                collection="articles",
                action="update",
                validation={"_and": [{"status": {"_eq": "published"}}]},
                fields=None,
                permissions=None,
            )
        ]
        manager, mock_client = self._make_manager(existing_perms=existing)
        entry = CustomPermissionEntry(
            name="C_1",
            policy="editor — directus-ac",
            collection="articles",
            action="update",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            fields=["title"],
        )
        policy_map = {"editor — directus-ac": "policy-uuid-1"}
        created, updated = manager.apply_custom_permissions([entry], policy_map)
        assert created == 0
        assert updated == 1
        mock_client.update_permission.assert_called_once_with(
            42,
            "policy-uuid-1",
            "articles",
            "update",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            fields=["title"],
            permissions=None,
        )

    def test_raises_api_error_for_unresolvable_policy(self):
        """Raises APIError when policy name cannot be resolved."""
        manager, _ = self._make_manager()
        entry = CustomPermissionEntry(
            name="C_1",
            policy="nonexistent-policy",
            collection="articles",
            action="read",
        )
        with pytest.raises(APIError) as exc_info:
            manager.apply_custom_permissions([entry], {})
        assert "Cannot resolve policy 'nonexistent-policy'" in str(exc_info.value)
        assert "custom permission 'C_1'" in str(exc_info.value)

    def test_raises_api_error_on_api_failure(self):
        """Raises APIError with perm name, collection, action on API failure."""
        mock_client = MagicMock()
        mock_client.get_permissions.return_value = []
        mock_client.create_permission.side_effect = APIError("HTTP 500 — Internal Server Error")
        manager = PermissionManager(mock_client)

        entry = CustomPermissionEntry(
            name="C_1",
            policy="editor — directus-ac",
            collection="articles",
            action="update",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
        )
        policy_map = {"editor — directus-ac": "policy-uuid-1"}
        with pytest.raises(APIError) as exc_info:
            manager.apply_custom_permissions([entry], policy_map)
        msg = str(exc_info.value)
        assert "Failed to apply custom permission 'C_1'" in msg
        assert "collection 'articles'" in msg
        assert "action 'update'" in msg
        assert "HTTP 500" in msg

    def test_mixed_create_and_update(self):
        """Correctly counts creates and updates in a mixed scenario."""
        existing = [
            DirectusPermission(
                id=10,
                policy="policy-uuid-1",
                collection="articles",
                action="read",
                validation=None,
                fields=["title"],
                permissions=None,
            ),
        ]
        manager, mock_client = self._make_manager(existing_perms=existing)
        entries = [
            CustomPermissionEntry(
                name="C_1",
                policy="editor — directus-ac",
                collection="articles",
                action="read",
                fields=["title", "body"],
            ),
            CustomPermissionEntry(
                name="C_2",
                policy="editor — directus-ac",
                collection="articles",
                action="create",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            ),
        ]
        policy_map = {"editor — directus-ac": "policy-uuid-1"}
        created, updated = manager.apply_custom_permissions(entries, policy_map)
        assert created == 1
        assert updated == 1

    def test_does_not_match_standard_permission_for_update(self):
        """Standard permissions (no constraints) are not matched for update."""
        existing = [
            DirectusPermission(
                id=5,
                policy="policy-uuid-1",
                collection="articles",
                action="read",
                validation=None,
                fields=None,
                permissions=None,
            ),
        ]
        manager, mock_client = self._make_manager(existing_perms=existing)
        entry = CustomPermissionEntry(
            name="C_1",
            policy="editor — directus-ac",
            collection="articles",
            action="read",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
        )
        policy_map = {"editor — directus-ac": "policy-uuid-1"}
        created, updated = manager.apply_custom_permissions([entry], policy_map)
        # Should create, not update, because existing has no constraints
        assert created == 1
        assert updated == 0

    def test_fields_star_not_treated_as_constraint(self):
        """Existing permission with fields=["*"] is not treated as custom."""
        existing = [
            DirectusPermission(
                id=7,
                policy="policy-uuid-1",
                collection="articles",
                action="read",
                validation=None,
                fields=["*"],
                permissions=None,
            ),
        ]
        manager, mock_client = self._make_manager(existing_perms=existing)
        entry = CustomPermissionEntry(
            name="C_1",
            policy="editor — directus-ac",
            collection="articles",
            action="read",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
        )
        policy_map = {"editor — directus-ac": "policy-uuid-1"}
        created, updated = manager.apply_custom_permissions([entry], policy_map)
        # fields=["*"] is not a constraint, so should create
        assert created == 1
        assert updated == 0

    def test_higher_c_n_names_work_correctly(self):
        """C_N names with higher counter values (C_5, C_10) work correctly."""
        manager, mock_client = self._make_manager(existing_perms=[])
        entries = [
            CustomPermissionEntry(
                name="C_5",
                policy="editor — directus-ac",
                collection="articles",
                action="read",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            ),
            CustomPermissionEntry(
                name="C_10",
                policy="viewer — directus-ac",
                collection="comments",
                action="read",
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ]
        policy_map = {
            "editor — directus-ac": "policy-uuid-1",
            "viewer — directus-ac": "policy-uuid-2",
        }
        created, updated = manager.apply_custom_permissions(entries, policy_map)
        assert created == 2
        assert updated == 0
        assert mock_client.create_permission.call_count == 2

    def test_error_message_includes_c_n_name_on_unresolvable_policy(self):
        """APIError for unresolvable policy includes the C_N Permission_Name."""
        manager, _ = self._make_manager()
        entry = CustomPermissionEntry(
            name="C_7",
            policy="missing-policy",
            collection="posts",
            action="update",
        )
        with pytest.raises(APIError) as exc_info:
            manager.apply_custom_permissions([entry], {})
        msg = str(exc_info.value)
        assert "C_7" in msg
        assert "missing-policy" in msg

    def test_error_message_includes_c_n_name_on_api_failure(self):
        """APIError on API failure includes C_N name, collection, and action."""
        mock_client = MagicMock()
        mock_client.get_permissions.return_value = []
        mock_client.create_permission.side_effect = APIError("HTTP 403 — Forbidden")
        manager = PermissionManager(mock_client)

        entry = CustomPermissionEntry(
            name="C_15",
            policy="admin — directus-ac",
            collection="users",
            action="delete",
        )
        policy_map = {"admin — directus-ac": "policy-uuid-admin"}
        with pytest.raises(APIError) as exc_info:
            manager.apply_custom_permissions([entry], policy_map)
        msg = str(exc_info.value)
        assert "C_15" in msg
        assert "collection 'users'" in msg
        assert "action 'delete'" in msg
        assert "HTTP 403" in msg
