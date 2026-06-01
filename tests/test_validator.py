"""Tests for validator.py — collection and role existence checks (unit tests)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.exceptions import ValidationError
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusCollection,
    DirectusPolicy,
    DirectusRole,
)
from directus_ac.validator import Validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(collections: list[str] | None = None, roles: list[DirectusRole] | None = None) -> MagicMock:
    """Return a mock DirectusClient pre-configured with the given data."""
    client = MagicMock()
    if collections is not None:
        client.get_collections.return_value = [
            DirectusCollection(collection=c) for c in collections
        ]
    if roles is not None:
        client.get_roles.return_value = roles
    return client


def _parse_missing_collections(error: ValidationError) -> set[str]:
    """Extract the set of missing collection names from a ValidationError.

    Uses the ``missing_names`` attribute stored on the exception so that names
    containing special characters (spaces, dashes, etc.) are returned verbatim.
    """
    return set(error.missing_names)


def _parse_missing_roles(error: ValidationError) -> set[str]:
    """Extract the set of missing role names from a ValidationError."""
    return set(error.missing_names)


# ---------------------------------------------------------------------------
# Unit tests — validate_collections
# ---------------------------------------------------------------------------


class TestValidateCollections:
    def test_all_present_no_error(self) -> None:
        client = _make_client(collections=["articles", "comments"])
        validator = Validator(client)
        # Should not raise
        validator.validate_collections(["articles", "comments"])

    def test_single_missing_raises(self) -> None:
        client = _make_client(collections=["articles"])
        validator = Validator(client)
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_collections(["articles", "missing_col"])
        assert "missing_col" in str(exc_info.value)

    def test_multiple_missing_all_reported(self) -> None:
        client = _make_client(collections=["articles"])
        validator = Validator(client)
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_collections(["articles", "alpha", "beta"])
        msg = str(exc_info.value)
        assert "alpha" in msg
        assert "beta" in msg

    def test_empty_existing_all_missing(self) -> None:
        client = _make_client(collections=[])
        validator = Validator(client)
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_collections(["col1", "col2"])
        msg = str(exc_info.value)
        assert "col1" in msg
        assert "col2" in msg

    def test_case_sensitive_mismatch_raises(self) -> None:
        client = _make_client(collections=["Articles"])
        validator = Validator(client)
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_collections(["articles"])
        assert "articles" in str(exc_info.value)

    def test_case_sensitive_exact_match_passes(self) -> None:
        client = _make_client(collections=["Articles"])
        validator = Validator(client)
        # Exact case match should not raise
        validator.validate_collections(["Articles"])


# ---------------------------------------------------------------------------
# Unit tests — validate_roles
# ---------------------------------------------------------------------------


class TestValidateRoles:
    def _make_roles(self, names: list[str]) -> list[DirectusRole]:
        return [DirectusRole(id=f"id-{n}", name=n) for n in names]

    def test_all_present_returns_mapping(self) -> None:
        roles = self._make_roles(["editor", "viewer"])
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        result = validator.validate_roles(["editor", "viewer"], create_missing=False, permission_manager=pm)
        assert result == {"editor": "id-editor", "viewer": "id-viewer"}
        pm.create_role.assert_not_called()

    def test_missing_role_no_create_raises(self) -> None:
        roles = self._make_roles(["editor"])
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_roles(["editor", "missing_role"], create_missing=False, permission_manager=pm)
        assert "missing_role" in str(exc_info.value)
        pm.create_role.assert_not_called()

    def test_missing_role_with_create_calls_permission_manager(self) -> None:
        roles = self._make_roles(["editor"])
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        pm.create_role.return_value = "new-id"
        result = validator.validate_roles(["editor", "new_role"], create_missing=True, permission_manager=pm)
        pm.create_role.assert_called_once_with("new_role")
        assert result["new_role"] == "new-id"
        assert result["editor"] == "id-editor"

    def test_multiple_missing_all_reported_no_create(self) -> None:
        roles = self._make_roles(["editor"])
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_roles(["editor", "alpha", "beta"], create_missing=False, permission_manager=pm)
        msg = str(exc_info.value)
        assert "alpha" in msg
        assert "beta" in msg

    def test_case_sensitive_role_mismatch_raises(self) -> None:
        roles = self._make_roles(["Editor"])
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_roles(["editor"], create_missing=False, permission_manager=pm)
        assert "editor" in str(exc_info.value)

    def test_case_sensitive_role_exact_match_passes(self) -> None:
        roles = self._make_roles(["Editor"])
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        result = validator.validate_roles(["Editor"], create_missing=False, permission_manager=pm)
        assert result == {"Editor": "id-Editor"}


# ---------------------------------------------------------------------------
# Property 4: All missing names are reported (collections)
# Feature: directus-access-control, Property 4: All missing names are reported (collections)
# Validates: Requirements 3.4, 3.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    config_names=st.lists(st.text(min_size=1, max_size=255), min_size=0, max_size=20),
    existing_names=st.lists(st.text(min_size=1, max_size=255), min_size=0, max_size=20),
)
def test_property4_all_missing_collections_reported(
    config_names: list[str], existing_names: list[str]
) -> None:
    # Feature: directus-access-control, Property 4: All missing names are reported (collections)
    client = _make_client(collections=existing_names)
    validator = Validator(client)

    expected_missing = set(config_names) - set(existing_names)

    if expected_missing:
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_collections(config_names)
        reported = _parse_missing_collections(exc_info.value)
        # Every missing name must appear in the error — no omissions, no extras
        assert reported == expected_missing, (
            f"Expected missing={expected_missing!r}, got reported={reported!r}"
        )
    else:
        # No missing names — should not raise
        validator.validate_collections(config_names)


# ---------------------------------------------------------------------------
# Property 5: Name matching is case-sensitive (collections and roles)
# Feature: directus-access-control, Property 5: Name matching is case-sensitive
# Validates: Requirements 3.3, 4.3
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(name=st.text(min_size=1, max_size=255))
def test_property5_case_sensitive_collections(name: str) -> None:
    # Feature: directus-access-control, Property 5: Name matching is case-sensitive
    variant = name.swapcase()

    # If swapcase produces the same string (e.g. digits/symbols), skip the
    # case-sensitivity check — there is no case variant to distinguish.
    if variant == name:
        # Exact name is present → no error
        client = _make_client(collections=[name])
        validator = Validator(client)
        validator.validate_collections([name])
        return

    # Exact name present → should NOT raise
    client_exact = _make_client(collections=[name])
    validator_exact = Validator(client_exact)
    validator_exact.validate_collections([name])

    # Case variant present but exact name absent → SHOULD raise
    client_variant = _make_client(collections=[variant])
    validator_variant = Validator(client_variant)
    with pytest.raises(ValidationError) as exc_info:
        validator_variant.validate_collections([name])
    assert name in str(exc_info.value)


@settings(max_examples=100)
@given(name=st.text(min_size=1, max_size=255))
def test_property5_case_sensitive_roles(name: str) -> None:
    # Feature: directus-access-control, Property 5: Name matching is case-sensitive
    variant = name.swapcase()

    if variant == name:
        # No case variant — just verify exact match passes
        roles = [DirectusRole(id="some-id", name=name)]
        client = _make_client(roles=roles)
        validator = Validator(client)
        pm = MagicMock()
        result = validator.validate_roles([name], create_missing=False, permission_manager=pm)
        assert result[name] == "some-id"
        return

    # Exact name present → should NOT raise
    roles_exact = [DirectusRole(id="exact-id", name=name)]
    client_exact = _make_client(roles=roles_exact)
    validator_exact = Validator(client_exact)
    pm = MagicMock()
    result = validator_exact.validate_roles([name], create_missing=False, permission_manager=pm)
    assert result[name] == "exact-id"

    # Case variant present but exact name absent → SHOULD raise
    roles_variant = [DirectusRole(id="variant-id", name=variant)]
    client_variant = _make_client(roles=roles_variant)
    validator_variant = Validator(client_variant)
    pm2 = MagicMock()
    with pytest.raises(ValidationError) as exc_info:
        validator_variant.validate_roles([name], create_missing=False, permission_manager=pm2)
    assert name in str(exc_info.value)


# ---------------------------------------------------------------------------
# Property 4: All missing names are reported (roles)
# Feature: directus-access-control, Property 4: All missing names are reported (roles)
# Validates: Requirements 4.4
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    config_names=st.lists(st.text(min_size=1, max_size=255), min_size=0, max_size=20),
    existing_names=st.lists(st.text(min_size=1, max_size=255), min_size=0, max_size=20),
)
def test_property4_all_missing_roles_reported(
    config_names: list[str], existing_names: list[str]
) -> None:
    # Feature: directus-access-control, Property 4: All missing names are reported (roles)
    roles = [DirectusRole(id=f"id-{i}", name=n) for i, n in enumerate(existing_names)]
    client = _make_client(roles=roles)
    validator = Validator(client)
    pm = MagicMock()

    expected_missing = set(config_names) - set(existing_names)

    if expected_missing:
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_roles(config_names, create_missing=False, permission_manager=pm)
        reported = _parse_missing_roles(exc_info.value)
        assert reported == expected_missing, (
            f"Expected missing={expected_missing!r}, got reported={reported!r}"
        )
    else:
        # No missing names — should not raise
        validator.validate_roles(config_names, create_missing=False, permission_manager=pm)


# ---------------------------------------------------------------------------
# Unit tests — validate_custom_permissions
# ---------------------------------------------------------------------------


def _make_client_with_policies(
    policy_names: list[str],
) -> MagicMock:
    """Return a mock DirectusClient with the given policy names."""
    client = MagicMock()
    client.get_policies.return_value = [
        DirectusPolicy(id=f"policy-id-{i}", name=name)
        for i, name in enumerate(policy_names)
    ]
    return client


def _make_custom_perm(
    name: str = "C_1",
    policy: str = "editor",
    collection: str = "articles",
    action: str = "read",
) -> CustomPermissionEntry:
    """Create a CustomPermissionEntry with defaults."""
    return CustomPermissionEntry(
        name=name, policy=policy, collection=collection, action=action
    )


class TestValidateCustomPermissions:
    def test_empty_list_no_error(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        # Should not raise, should not even call get_policies
        validator.validate_custom_permissions([], ["articles"])
        client.get_policies.assert_not_called()

    def test_all_valid_no_error(self) -> None:
        client = _make_client_with_policies(["editor", "viewer"])
        validator = Validator(client)
        perms = [
            _make_custom_perm(policy="editor", collection="articles"),
            _make_custom_perm(name="C_2", policy="viewer", collection="comments"),
        ]
        # Should not raise
        validator.validate_custom_permissions(perms, ["articles", "comments"])

    def test_unknown_policy_raises(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [_make_custom_perm(policy="nonexistent", collection="articles")]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        assert "Custom permissions reference unknown policies:" in msg
        assert "nonexistent" in msg

    def test_unknown_collection_raises(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [_make_custom_perm(policy="editor", collection="unknown_col")]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        assert "Custom permissions reference unknown collections:" in msg
        assert "unknown_col" in msg

    def test_both_unknown_policy_and_collection_raises_combined(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [_make_custom_perm(policy="bad_policy", collection="bad_col")]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        assert "Custom permissions reference unknown policies:" in msg
        assert "bad_policy" in msg
        assert "Custom permissions reference unknown collections:" in msg
        assert "bad_col" in msg

    def test_multiple_unknown_policies_all_reported(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [
            _make_custom_perm(name="C_1", policy="ghost1", collection="articles"),
            _make_custom_perm(name="C_2", policy="ghost2", collection="articles"),
        ]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        assert "ghost1" in msg
        assert "ghost2" in msg

    def test_multiple_unknown_collections_all_reported(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [
            _make_custom_perm(name="C_1", policy="editor", collection="col_a"),
            _make_custom_perm(name="C_2", policy="editor", collection="col_b"),
        ]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        assert "col_a" in msg
        assert "col_b" in msg

    def test_duplicate_unknown_policy_reported_once(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [
            _make_custom_perm(name="C_1", policy="ghost", collection="articles"),
            _make_custom_perm(name="C_2", policy="ghost", collection="articles"),
        ]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        # "ghost" should appear exactly once in the bullet list
        assert msg.count("  - ghost") == 1

    def test_duplicate_unknown_collection_reported_once(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [
            _make_custom_perm(name="C_1", policy="editor", collection="missing"),
            _make_custom_perm(name="C_2", policy="editor", collection="missing"),
        ]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        msg = str(exc_info.value)
        assert msg.count("  - missing") == 1

    def test_missing_names_attribute_contains_all_invalid(self) -> None:
        client = _make_client_with_policies(["editor"])
        validator = Validator(client)
        perms = [
            _make_custom_perm(name="C_1", policy="bad_pol", collection="bad_col"),
        ]
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_custom_permissions(perms, ["articles"])
        assert set(exc_info.value.missing_names) == {"bad_pol", "bad_col"}


# ---------------------------------------------------------------------------
# Property 12: Validation batch error collection
# Feature: custom-permissions, Property 12: Validation batch error collection
# Validates: Requirements 8.1, 8.2
# ---------------------------------------------------------------------------


# Strategy: generate a non-empty list of policy names that exist in Directus
_policy_name_st = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S"), exclude_characters="\x00"),
    min_size=1,
    max_size=30,
)


@st.composite
def _custom_perms_with_invalid_refs(draw):
    """Generate custom permission entries where some reference invalid policies/collections.

    Returns (entries, existing_policies, config_collections, expected_unknown_policies, expected_unknown_collections).
    """
    # Generate a set of existing policy names (at least 1)
    existing_policies = draw(
        st.lists(_policy_name_st, min_size=1, max_size=10, unique=True)
    )
    # Generate a set of config collections (at least 1)
    config_collections = draw(
        st.lists(
            st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"), exclude_characters="\x00")),
            min_size=1,
            max_size=10,
            unique=True,
        )
    )

    # Generate some invalid policy names (guaranteed not in existing_policies)
    invalid_policies = draw(
        st.lists(
            _policy_name_st.filter(lambda x: x not in existing_policies),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )
    # Generate some invalid collections (guaranteed not in config_collections)
    invalid_collections = draw(
        st.lists(
            st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"), exclude_characters="\x00")).filter(
                lambda x: x not in config_collections
            ),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )

    # Ensure at least one invalid reference exists
    if not invalid_policies and not invalid_collections:
        # Force at least one invalid policy
        forced = draw(
            _policy_name_st.filter(lambda x: x not in existing_policies)
        )
        invalid_policies = [forced]

    # Build entries: mix of valid and invalid references
    entries: list[CustomPermissionEntry] = []
    counter = 1

    # Add entries with invalid policies
    for pol in invalid_policies:
        col = draw(st.sampled_from(config_collections))
        action = draw(st.sampled_from(["create", "read", "update", "delete"]))
        entries.append(
            CustomPermissionEntry(
                name=f"C_{counter}",
                policy=pol,
                collection=col,
                action=action,
            )
        )
        counter += 1

    # Add entries with invalid collections
    for col in invalid_collections:
        pol = draw(st.sampled_from(existing_policies))
        action = draw(st.sampled_from(["create", "read", "update", "delete"]))
        entries.append(
            CustomPermissionEntry(
                name=f"C_{counter}",
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
                name=f"C_{counter}",
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


@settings(max_examples=100)
@given(data=_custom_perms_with_invalid_refs())
def test_property12_validation_batch_error_collection(data) -> None:
    """Property 12: Validation batch error collection.

    For any set of custom permission entries where some reference unresolvable
    policy names or unknown collections, the Validator SHALL collect ALL invalid
    references before raising a single ValidationError that lists every
    unresolvable policy name and every unknown collection.

    **Validates: Requirements 8.1, 8.2**
    """
    # Feature: custom-permissions, Property 12: Validation batch error collection
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
    # caught exactly one exception and it contains ALL references confirms this
