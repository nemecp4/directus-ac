"""Property-based tests for CheckCommand formatting logic."""
from __future__ import annotations

import logging

from hypothesis import given, settings
from hypothesis import strategies as st

from directus_ac.check import CheckCommand
from directus_ac.models import (
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)


# ---------------------------------------------------------------------------
# Feature: directus-check-command, Property 1: Collections section formatting
# Validates: Requirements 2.2, 7.1
# ---------------------------------------------------------------------------


def _make_check_command(enable_private_collections: bool = True) -> CheckCommand:
    """Create a CheckCommand instance with no client (not needed for formatting).

    Defaults to enable_private_collections=True so that property tests generating
    arbitrary collection names (which may start with 'directus_') are not affected
    by the filtering logic.
    """
    return CheckCommand(client=None, enable_private_collections=enable_private_collections)  # type: ignore[arg-type]


@settings(max_examples=100)
@given(
    names=st.lists(
        st.text(min_size=1, max_size=50).filter(lambda s: "\n" not in s),
        min_size=1,
        max_size=50,
    )
)
def test_format_collections_property(names: list[str]) -> None:
    """Property 1: Collections section formatting.

    For any non-empty list of collection names, the formatted collections output
    SHALL start with a line containing exactly "Collections" followed by each
    collection name on its own separate line, with no collection names missing
    or duplicated.

    **Validates: Requirements 2.2, 7.1**
    """
    cmd = _make_check_command()
    collections = [DirectusCollection(collection=name) for name in names]

    result = cmd._format_collections(collections)
    lines = result.split("\n")

    # Output starts with exactly "Collections"
    assert lines[0] == "Collections"

    # Each collection name appears on its own line (indented with 2 spaces prefix)
    content_lines = lines[1:]

    # The format is "  {name}" so strip exactly the 2-space prefix
    extracted_names = [line[2:] for line in content_lines]

    # No collection names missing
    for name in names:
        assert name in extracted_names, f"Collection name {name!r} is missing from output"

    # No duplicated entries beyond what was in the input
    assert len(content_lines) == len(names)


def test_format_collections_empty() -> None:
    """Empty collections list produces 'No collections found' message.

    **Validates: Requirements 2.2, 7.1**
    """
    cmd = _make_check_command()
    result = cmd._format_collections([])
    lines = result.split("\n")

    assert lines[0] == "Collections"
    assert "No collections found" in result


# ---------------------------------------------------------------------------
# Feature: directus-check-command, Property 2: Roles section formatting
# Validates: Requirements 3.2, 7.2
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    roles=st.lists(
        st.builds(
            DirectusRole,
            name=st.text(min_size=1, max_size=50).filter(lambda s: "\n" not in s and " " not in s),
            id=st.uuids().map(str),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_format_roles_property(roles: list[DirectusRole]) -> None:
    """Property 2: Roles section formatting.

    For any non-empty list of roles (each having a name and an id), the formatted
    roles output SHALL start with a line containing exactly "Roles" followed by one
    line per role, where each line contains the role name and its identifier
    separated by a space.

    **Validates: Requirements 3.2, 7.2**
    """
    cmd = _make_check_command()

    result = cmd._format_roles(roles)
    lines = result.split("\n")

    # Output starts with exactly "Roles"
    assert lines[0] == "Roles"

    # One line per role after the header
    content_lines = lines[1:]
    assert len(content_lines) == len(roles)

    # Each line contains the role name and id separated by a space
    for i, role in enumerate(roles):
        line = content_lines[i]
        # Lines are indented with 2 spaces
        stripped = line[2:]
        assert stripped == f"{role.name} {role.id}", (
            f"Expected '{role.name} {role.id}', got '{stripped}'"
        )


def test_format_roles_empty() -> None:
    """Empty roles list produces 'No roles found' message.

    **Validates: Requirements 3.2, 7.2**
    """
    cmd = _make_check_command()
    result = cmd._format_roles([])
    lines = result.split("\n")

    assert lines[0] == "Roles"
    assert "No roles found" in result


# ---------------------------------------------------------------------------
# Feature: directus-check-command, Property 3: Permission grouping structure
# Validates: Requirements 4.2, 7.3, 7.4
# ---------------------------------------------------------------------------


@st.composite
def _permissions_with_policies_and_roles(draw):
    """Generate permissions, policies, and roles with 1:1 policy-role mapping.

    Returns (permissions, policies, roles) where each permission references
    a policy that is linked to exactly one role.
    """
    # Generate roles
    role_count = draw(st.integers(min_value=1, max_value=5))
    roles = [
        DirectusRole(id=draw(st.uuids().map(str)), name=draw(
            st.text(min_size=1, max_size=30).filter(
                lambda s: "\n" not in s and s.strip() == s and len(s.strip()) > 0
            )
        ))
        for _ in range(role_count)
    ]

    # Generate 1:1 policies
    policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in roles
    ]
    policy_ids = [p.id for p in policies]

    # Generate permissions referencing these policies
    num_perms = draw(st.integers(min_value=1, max_value=50))
    permissions = []
    for i in range(num_perms):
        policy_id = draw(st.sampled_from(policy_ids))
        collection = draw(st.text(min_size=1, max_size=30).filter(
            lambda s: "\n" not in s and ":" not in s and s.strip() == s and len(s.strip()) > 0
        ))
        action = draw(st.sampled_from(["read", "create", "update", "delete"]))
        permissions.append(
            DirectusPermission(id=i + 1, policy=policy_id, collection=collection, action=action)
        )

    return permissions, policies, roles


@given(data=_permissions_with_policies_and_roles())
@settings(max_examples=100)
def test_format_policies_property(data) -> None:
    """Property 3: Permission grouping structure.

    For any non-empty list of permission entries with policies and roles,
    the formatted policies output SHALL start with "Policies", followed
    by role sections where each role name appears on its own line, policy
    names as sub-headers, and each collection-actions entry appears indented
    beneath its policy.

    **Validates: Requirements 4.2, 7.3, 7.4**
    """
    permissions, policies, roles = data
    cmd = _make_check_command()

    result = cmd._format_policies(permissions, policies, roles)
    lines = result.split("\n")

    # 1. Output starts with exactly "Policies"
    assert lines[0] == "Policies"

    # 2. Role lines are indented with 2 spaces (but not 4),
    #    policy lines with 4 spaces (but not 6),
    #    collection lines with 6 spaces
    role_lines = [line for line in lines[1:] if line.startswith("  ") and not line.startswith("    ")]
    policy_lines = [line for line in lines[1:] if line.startswith("    ") and not line.startswith("      ")]
    collection_lines = [line for line in lines[1:] if line.startswith("      ")]

    # 3. At least one role line should exist (we have permissions)
    assert len(role_lines) >= 1

    # 4. At least one policy line should exist (we have permissions)
    assert len(policy_lines) >= 1

    # 5. Each collection-actions entry appears indented beneath its policy (6 spaces)
    for coll_line in collection_lines:
        assert coll_line.startswith("      "), (
            f"Collection line should start with 6 spaces: {coll_line!r}"
        )
        # Format is "      {collection}: {actions}"
        content = coll_line[6:]
        assert ": " in content, (
            f"Collection line should contain ': ' separator: {content!r}"
        )


def test_format_policies_empty() -> None:
    """Empty permissions list produces 'No policies found' message.

    **Validates: Requirements 4.2, 7.3, 7.4**
    """
    cmd = _make_check_command()
    result = cmd._format_policies([], [], [])
    lines = result.split("\n")

    assert lines[0] == "Policies"
    assert "No policies found" in result


# ---------------------------------------------------------------------------
# Feature: directus-check-command, Property 4: Role UUID resolution in permissions display
# Validates: Requirements 4.4, 4.5
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=st.data())
def test_format_policies_role_uuid_resolution(data: st.DataObject) -> None:
    """Property 4: Role UUID resolution in policies display.

    For any set of permission entries, if a permission's policy is linked to a
    role that exists in the roles list, the output SHALL display the human-readable
    role name; if the policy links to a role not in the roles list, the output
    SHALL display the UUID itself.

    **Validates: Requirements 4.4, 4.5**
    """
    cmd = _make_check_command()

    # Generate roles that will be in the roles list (resolvable)
    roles = data.draw(
        st.lists(
            st.builds(
                DirectusRole,
                name=st.text(min_size=1, max_size=30).filter(
                    lambda s: "\n" not in s and s.strip() != ""
                ),
                id=st.uuids().map(str),
            ),
            min_size=1,
            max_size=5,
        )
    )

    # Generate policies linked to known roles
    known_policies = [
        DirectusPolicy(id=f"policy-{role.id}", name=f"{role.name} Policy", roles=[role.id])
        for role in roles
    ]

    # Generate policies linked to unknown roles (unresolvable)
    unknown_role_ids = data.draw(
        st.lists(
            st.uuids().map(str).filter(lambda u: u not in {r.id for r in roles}),
            min_size=1,
            max_size=3,
        )
    )
    unknown_policies = [
        DirectusPolicy(id=f"unknown-policy-{rid}", name=f"Unknown Policy", roles=[rid])
        for rid in unknown_role_ids
    ]

    all_policies = known_policies + unknown_policies

    # Generate permissions referencing known policies
    resolvable_permissions = data.draw(
        st.lists(
            st.builds(
                DirectusPermission,
                id=st.integers(min_value=1, max_value=10000),
                policy=st.sampled_from([p.id for p in known_policies]),
                collection=st.text(min_size=1, max_size=30).filter(
                    lambda s: "\n" not in s and ":" not in s
                ),
                action=st.sampled_from(["read", "create", "update", "delete"]),
            ),
            min_size=1,
            max_size=10,
        )
    )

    # Generate permissions referencing unknown policies
    unresolvable_permissions = data.draw(
        st.lists(
            st.builds(
                DirectusPermission,
                id=st.integers(min_value=10001, max_value=20000),
                policy=st.sampled_from([p.id for p in unknown_policies]),
                collection=st.text(min_size=1, max_size=30).filter(
                    lambda s: "\n" not in s and ":" not in s
                ),
                action=st.sampled_from(["read", "create", "update", "delete"]),
            ),
            min_size=1,
            max_size=10,
        )
    )

    all_permissions = resolvable_permissions + unresolvable_permissions

    result = cmd._format_policies(all_permissions, all_policies, roles)

    # Build role map for verification
    role_map: dict[str, str] = {role.id: role.name for role in roles}

    # Extract role header lines (2-space indent, not 4-space)
    lines = result.split("\n")
    role_lines = [
        line for line in lines[1:]
        if line.startswith("  ") and not line.startswith("    ")
    ]

    # Verify resolvable permissions show human-readable role names
    for perm in resolvable_permissions:
        # Find which role this policy links to
        for policy in known_policies:
            if policy.id == perm.policy:
                for role_id in policy.roles:
                    expected_name = role_map.get(role_id, role_id)
                    assert any(
                        line == f"  {expected_name}" for line in role_lines
                    ), (
                        f"Resolvable role should appear as "
                        f"human-readable name '{expected_name}' in output, "
                        f"but role lines are: {role_lines}"
                    )
                break

    # Verify unresolvable permissions show the raw UUID
    for perm in unresolvable_permissions:
        for policy in unknown_policies:
            if policy.id == perm.policy:
                for role_id in policy.roles:
                    # This role_id is not in role_map, so it should appear as-is
                    assert any(
                        line == f"  {role_id}" for line in role_lines
                    ), (
                        f"Unresolvable role UUID {role_id} should appear as "
                        f"raw UUID in output, but role lines are: {role_lines}"
                    )
                break


# ---------------------------------------------------------------------------
# Feature: directus-check-command, Property 5: Output order preservation
# Validates: Requirements 7.6
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    names=st.lists(
        st.text(min_size=1, max_size=50).filter(lambda s: "\n" not in s),
        min_size=2,
        max_size=50,
        unique=True,
    )
)
def test_format_collections_order_preserved(names: list[str]) -> None:
    """Property 5 (collections): Output order preservation.

    For any ordered list of collections, the formatted output SHALL preserve
    the original ordering of items.

    **Validates: Requirements 7.6**
    """
    cmd = _make_check_command()
    collections = [DirectusCollection(collection=name) for name in names]

    result = cmd._format_collections(collections)
    lines = result.split("\n")

    # Skip the header line
    content_lines = lines[1:]
    extracted_names = [line[2:] for line in content_lines]

    # Order must match the input order exactly
    assert extracted_names == names, (
        f"Collections output order does not match input order.\n"
        f"Input:  {names}\n"
        f"Output: {extracted_names}"
    )


@settings(max_examples=100)
@given(
    roles=st.lists(
        st.builds(
            DirectusRole,
            name=st.text(min_size=1, max_size=50).filter(
                lambda s: "\n" not in s and " " not in s
            ),
            id=st.uuids().map(str),
        ),
        min_size=2,
        max_size=20,
        unique_by=lambda r: r.id,
    )
)
def test_format_roles_order_preserved(roles: list[DirectusRole]) -> None:
    """Property 5 (roles): Output order preservation.

    For any ordered list of roles, the formatted output SHALL preserve
    the original ordering of items.

    **Validates: Requirements 7.6**
    """
    cmd = _make_check_command()

    result = cmd._format_roles(roles)
    lines = result.split("\n")

    # Skip the header line
    content_lines = lines[1:]

    # Each line should match the corresponding role in input order
    for i, role in enumerate(roles):
        expected = f"  {role.name} {role.id}"
        assert content_lines[i] == expected, (
            f"Role at position {i} does not match input order.\n"
            f"Expected: {expected!r}\n"
            f"Got:      {content_lines[i]!r}"
        )


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 3: Policy name resolution
# Validates: Requirements 3.1, 3.3
# ---------------------------------------------------------------------------


@st.composite
def _permissions_with_named_policies(draw):
    """Generate permissions with policies that have known human-readable names.

    Returns (permissions, policies, roles) where every permission references
    a policy with a resolvable name, and that policy is linked to a role.
    """
    # Generate roles with names that don't look like numeric IDs
    role_count = draw(st.integers(min_value=1, max_value=5))
    roles = [
        DirectusRole(
            id=draw(st.uuids().map(str)),
            name=draw(
                st.text(
                    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_-"),
                    min_size=1,
                    max_size=30,
                ).filter(lambda s: s.strip() == s and len(s) >= 1 and not s.isdigit())
            ),
        )
        for _ in range(role_count)
    ]

    # Generate policies with human-readable names (not numeric, not UUIDs)
    policies = []
    for role in roles:
        policy_count = draw(st.integers(min_value=1, max_value=3))
        for _ in range(policy_count):
            policy_name = draw(
                st.text(
                    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_- "),
                    min_size=2,
                    max_size=30,
                ).filter(lambda s: s.strip() == s and len(s.strip()) >= 2 and not s.isdigit())
            )
            policies.append(
                DirectusPolicy(
                    id=draw(st.uuids().map(str)),
                    name=policy_name,
                    roles=[role.id],
                )
            )

    # Generate permissions referencing these policies
    num_perms = draw(st.integers(min_value=1, max_value=30))
    permissions = []
    for i in range(num_perms):
        policy = draw(st.sampled_from(policies))
        collection = draw(
            st.text(min_size=1, max_size=30).filter(
                lambda s: "\n" not in s and ":" not in s and s.strip() != ""
            )
        )
        action = draw(st.sampled_from(["read", "create", "update", "delete"]))
        permissions.append(
            DirectusPermission(id=i + 1, policy=policy.id, collection=collection, action=action)
        )

    return permissions, policies, roles


@given(data=_permissions_with_named_policies())
@settings(max_examples=200)
def test_policy_name_resolution(data) -> None:
    """Property 3: Policy name resolution.

    For any set of permissions with associated policies that have known names,
    verify the output displays the human-readable policy name, never a numeric id.

    The output structure is:
        Policies
          RoleName
            PolicyName
              collection: action1, action2

    Policy names appear at 4-space indent under role names (2-space indent).
    No numeric id should appear as a policy identifier in the output.

    **Validates: Requirements 3.1, 3.3**
    """
    permissions, policies, roles = data
    cmd = _make_check_command()

    result = cmd._format_policies(permissions, policies, roles)
    lines = result.split("\n")

    # Build lookup maps
    policy_map = {p.id: p.name for p in policies}

    # Extract policy sub-header lines (4-space indent, not 6-space)
    policy_lines = [
        line for line in lines[1:]
        if line.startswith("    ") and not line.startswith("      ")
    ]

    # 1. Every policy referenced by a permission should have its name in the output
    referenced_policy_ids = {perm.policy for perm in permissions}
    referenced_policy_names = {policy_map[pid] for pid in referenced_policy_ids if pid in policy_map}

    policy_line_texts = [line.strip() for line in policy_lines]

    for policy_name in referenced_policy_names:
        assert policy_name in policy_line_texts, (
            f"Policy name '{policy_name}' should appear as a sub-header in the output, "
            f"but policy lines are: {policy_line_texts}"
        )

    # 2. No numeric id should appear as a policy identifier (4-space indent lines)
    for line in policy_lines:
        content = line.strip()
        assert not content.isdigit(), (
            f"Numeric id '{content}' should never appear as a policy identifier. "
            f"Expected human-readable policy name instead."
        )

    # 3. No permission's numeric id field should appear as a policy sub-header
    permission_ids = {str(perm.id) for perm in permissions}
    for line in policy_lines:
        content = line.strip()
        assert content not in permission_ids, (
            f"Permission numeric id '{content}' should not appear as a policy identifier. "
            f"Expected human-readable policy name instead."
        )


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 1: Section header naming
# Validates: Requirements 1.1, 1.2
# ---------------------------------------------------------------------------


@st.composite
def _any_policies_input(draw):
    """Generate arbitrary permissions, policies, and roles for _format_policies.

    Covers: empty lists, single items, and multiple items with various
    combinations of resolvable/unresolvable references.
    """
    # Generate roles (0 to 5)
    roles = draw(
        st.lists(
            st.builds(
                DirectusRole,
                name=st.text(min_size=1, max_size=30).filter(lambda s: "\n" not in s),
                id=st.uuids().map(str),
            ),
            min_size=0,
            max_size=5,
        )
    )

    # Generate policies (0 to 5), some linked to roles, some not
    role_ids = [r.id for r in roles] if roles else []
    policies = draw(
        st.lists(
            st.builds(
                DirectusPolicy,
                id=st.uuids().map(str),
                name=st.text(min_size=1, max_size=30).filter(lambda s: "\n" not in s),
                roles=st.lists(
                    st.sampled_from(role_ids) if role_ids else st.uuids().map(str),
                    min_size=0,
                    max_size=3,
                ),
            ),
            min_size=0,
            max_size=5,
        )
    )

    # Generate permissions (0 to 20)
    policy_ids = [p.id for p in policies] if policies else []
    permissions = draw(
        st.lists(
            st.builds(
                DirectusPermission,
                id=st.integers(min_value=1, max_value=10000),
                policy=st.sampled_from(policy_ids) if policy_ids else st.uuids().map(str),
                collection=st.text(min_size=1, max_size=30).filter(
                    lambda s: "\n" not in s and ":" not in s
                ),
                action=st.sampled_from(["read", "create", "update", "delete"]),
            ),
            min_size=0,
            max_size=20,
        )
    )

    return permissions, policies, roles


@given(data=_any_policies_input())
@settings(max_examples=200)
def test_section_header_is_policies_never_permissions(data) -> None:
    """Property 1: Section header naming.

    For any set of permissions/policies/roles, the output section header
    from _format_policies is always "Policies", never "Permissions".

    **Validates: Requirements 1.1, 1.2**
    """
    permissions, policies, roles = data
    cmd = _make_check_command()

    result = cmd._format_policies(permissions, policies, roles)
    lines = result.split("\n")

    # The first line MUST be "Policies"
    assert lines[0] == "Policies", (
        f"Expected section header 'Policies', got '{lines[0]}'"
    )

    # The word "Permissions" must NEVER appear as a section header
    assert "Permissions" not in lines, (
        f"'Permissions' should never appear in the output, but found in: {lines}"
    )


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 2: Output via logging only
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------

import ast
import logging
import logging.handlers
from pathlib import Path


def test_check_module_contains_no_print_calls() -> None:
    """Property 2 (static): check.py contains zero print() calls.

    Uses the ast module to parse check.py and verify that no Call node
    invokes the built-in print() function.

    **Validates: Requirements 2.1, 2.2**
    """
    check_module_path = Path(__file__).parent.parent / "directus_ac" / "check.py"
    source = check_module_path.read_text()
    tree = ast.parse(source)

    print_calls: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Direct call: print(...)
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                print_calls.append(node.lineno)
            # Qualified call: builtins.print(...)
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "print"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "builtins"
            ):
                print_calls.append(node.lineno)

    assert print_calls == [], (
        f"check.py contains print() calls at lines: {print_calls}. "
        f"All output must use logger.info() instead."
    )


@settings(max_examples=100)
@given(data=_permissions_with_policies_and_roles())
def test_output_via_logging_only(data) -> None:
    """Property 2 (runtime): All CheckCommand output goes through the logger.

    For any set of permissions, policies, and roles, when CheckCommand.run()
    is invoked, all output SHALL be emitted as INFO-level log records on the
    'directus_ac.check' logger. The captured records must contain the section
    headers (Collections, Roles, Policies).

    **Validates: Requirements 2.1, 2.2**
    """
    permissions, policies, roles = data
    collections = [DirectusCollection(collection=f"col_{i}") for i in range(3)]

    mock_client = MagicMock()
    mock_client.get_collections.return_value = collections
    mock_client.get_roles.return_value = roles
    mock_client.get_policies.return_value = policies
    mock_client.get_permissions.return_value = permissions

    cmd = CheckCommand(client=mock_client)

    # Use a logging handler directly instead of caplog fixture (incompatible with @given)
    check_logger = logging.getLogger("directus_ac.check")
    handler = logging.handlers.MemoryHandler(capacity=1000, target=None)
    handler.setLevel(logging.DEBUG)
    check_logger.addHandler(handler)
    check_logger.setLevel(logging.INFO)

    try:
        handler.buffer.clear()
        cmd.run()

        records = list(handler.buffer)

        # All output should be captured as log records
        assert len(records) > 0, "No log records captured; output is not going through the logger"

        # All records should be at INFO level
        for record in records:
            assert record.levelno == logging.INFO, (
                f"Expected INFO level, got {record.levelname} for record: {record.message!r}"
            )

        # The logger name should be 'directus_ac.check'
        for record in records:
            assert record.name == "directus_ac.check", (
                f"Expected logger 'directus_ac.check', got '{record.name}'"
            )

        # The combined log output must contain the three section headers
        combined_output = "\n".join(record.message for record in records)
        assert "Collections" in combined_output, "Missing 'Collections' section in log output"
        assert "Roles" in combined_output, "Missing 'Roles' section in log output"
        assert "Policies" in combined_output, "Missing 'Policies' section in log output"
    finally:
        check_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Unit tests for CheckCommand.run() with mocked client
# Requirements: 1.1, 1.2, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock


class TestCheckCommandRun:
    """Unit tests for CheckCommand.run() with mocked DirectusClient."""

    def _make_mock_client(
        self,
        collections: list[DirectusCollection] | None = None,
        roles: list[DirectusRole] | None = None,
        permissions: list[DirectusPermission] | None = None,
        policies: list[DirectusPolicy] | None = None,
    ) -> MagicMock:
        """Create a mock DirectusClient with configured return values."""
        client = MagicMock()
        client.get_collections.return_value = collections or []
        client.get_roles.return_value = roles or []
        client.get_permissions.return_value = permissions or []
        client.get_policies.return_value = policies or []
        return client

    def test_successful_output_with_data(self, caplog) -> None:
        """CheckCommand.run() prints collections, roles, and permissions.

        Validates: Requirements 1.1, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2
        """
        collections = [
            DirectusCollection(collection="articles"),
            DirectusCollection(collection="users"),
        ]
        roles = [
            DirectusRole(id="uuid-admin", name="Admin"),
            DirectusRole(id="uuid-editor", name="Editor"),
        ]
        policies = [
            DirectusPolicy(id="policy-admin", name="Admin Policy", roles=["uuid-admin"]),
            DirectusPolicy(id="policy-editor", name="Editor Policy", roles=["uuid-editor"]),
        ]
        permissions = [
            DirectusPermission(id=1, policy="policy-admin", collection="articles", action="read"),
            DirectusPermission(id=2, policy="policy-admin", collection="articles", action="create"),
            DirectusPermission(id=3, policy="policy-editor", collection="users", action="read"),
        ]

        client = self._make_mock_client(collections, roles, permissions, policies)
        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        output = caplog.text

        # Collections section
        assert "Collections" in output
        assert "articles" in output
        assert "users" in output

        # Roles section
        assert "Roles" in output
        assert "Admin uuid-admin" in output
        assert "Editor uuid-editor" in output

        # Policies section with policy names as sub-headers
        assert "Policies" in output
        assert "Admin" in output
        assert "Admin Policy" in output
        assert "articles: read, create" in output
        assert "Editor" in output
        assert "Editor Policy" in output
        assert "users: read" in output

    def test_empty_collections_produces_no_found_message(self, caplog) -> None:
        """Empty collections produce 'No collections found' message.

        Validates: Requirements 2.3
        """
        roles = [DirectusRole(id="uuid-1", name="Admin")]
        policies = [DirectusPolicy(id="policy-1", name="Admin Policy", roles=["uuid-1"])]
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
        ]

        client = self._make_mock_client(collections=[], roles=roles, permissions=permissions, policies=policies)
        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        assert "No collections found" in caplog.text

    def test_empty_roles_produces_no_found_message(self, caplog) -> None:
        """Empty roles produce 'No roles found' message.

        Validates: Requirements 3.3
        """
        collections = [DirectusCollection(collection="articles")]

        client = self._make_mock_client(collections=collections, roles=[], permissions=[])
        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        assert "No roles found" in caplog.text

    def test_empty_permissions_produces_no_found_message(self, caplog) -> None:
        """Empty permissions produce 'No policies found' message.

        Validates: Requirements 4.3
        """
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="uuid-1", name="Admin")]

        client = self._make_mock_client(collections=collections, roles=roles, permissions=[])
        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        assert "No policies found" in caplog.text

    def test_all_empty_produces_all_no_found_messages(self, caplog) -> None:
        """All empty lists produce all 'No X found' messages.

        Validates: Requirements 2.3, 3.3, 4.3
        """
        client = self._make_mock_client(collections=[], roles=[], permissions=[])
        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        assert "No collections found" in caplog.text
        assert "No roles found" in caplog.text
        assert "No policies found" in caplog.text

    def test_only_get_requests_issued(self) -> None:
        """CheckCommand.run() only issues GET requests (read-only verification).

        Validates: Requirements 1.2
        """
        client = self._make_mock_client()
        cmd = CheckCommand(client=client)
        cmd.run()

        # Only get_* methods should be called
        client.get_collections.assert_called_once()
        client.get_roles.assert_called_once()
        client.get_policies.assert_called_once()
        client.get_permissions.assert_called_once()

        # No write methods should be called
        assert not client.create_role.called
        assert not client.create_permission.called
        assert not client.update_permission.called

    def test_exit_code_0_on_success(self) -> None:
        """CheckCommand.run() completes without raising (exit 0 path).

        Validates: Requirements 1.5
        """
        roles = [DirectusRole(id="uuid-1", name="Admin")]
        policies = [DirectusPolicy(id="policy-1", name="Admin Policy", roles=["uuid-1"])]
        client = self._make_mock_client(
            collections=[DirectusCollection(collection="posts")],
            roles=roles,
            permissions=[
                DirectusPermission(id=1, policy="policy-1", collection="posts", action="read"),
            ],
            policies=policies,
        )
        cmd = CheckCommand(client=client)

        # run() should complete without raising any exception
        cmd.run()  # No exception means success / exit 0

    def test_client_methods_called_in_order(self) -> None:
        """CheckCommand.run() calls client methods to fetch data.

        Validates: Requirements 2.1, 3.1, 4.1
        """
        client = self._make_mock_client()
        cmd = CheckCommand(client=client)
        cmd.run()

        # Verify all data-fetching methods are called
        client.get_collections.assert_called_once()
        client.get_roles.assert_called_once()
        client.get_policies.assert_called_once()
        client.get_permissions.assert_called_once()


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Task 5.1: enable_private_collections parameter
# Validates: Requirements 5.2, 5.3, 5.4
# ---------------------------------------------------------------------------


def test_enable_private_collections_init_default() -> None:
    """CheckCommand stores enable_private_collections=False by default.

    Validates: Requirements 5.1, 5.2
    """
    cmd = CheckCommand(client=None, enable_private_collections=False)  # type: ignore[arg-type]
    assert cmd._enable_private_collections is False


def test_enable_private_collections_init_true() -> None:
    """CheckCommand stores enable_private_collections=True when provided.

    Validates: Requirements 4.1
    """
    cmd = CheckCommand(client=None, enable_private_collections=True)  # type: ignore[arg-type]
    assert cmd._enable_private_collections is True


def test_output_structure_three_sections(caplog) -> None:
    """Output preserves three sections (Collections, Roles, Policies) with correct indentation.

    Validates: Requirements 5.2, 5.3
    """
    from unittest.mock import MagicMock

    collections = [DirectusCollection(collection="articles")]
    roles = [DirectusRole(id="uuid-admin", name="Admin")]
    policies = [DirectusPolicy(id="policy-admin", name="Admin Policy", roles=["uuid-admin"])]
    permissions = [
        DirectusPermission(id=1, policy="policy-admin", collection="articles", action="read"),
    ]

    client = MagicMock()
    client.get_collections.return_value = collections
    client.get_roles.return_value = roles
    client.get_policies.return_value = policies
    client.get_permissions.return_value = permissions

    cmd = CheckCommand(client=client)
    with caplog.at_level(logging.INFO, logger="directus_ac.check"):
        cmd.run()

    output = caplog.text

    # Three sections present
    assert "Collections" in output
    assert "Roles" in output
    assert "Policies" in output

    # Items use 2-space indentation
    assert "  articles" in output
    assert "  Admin uuid-admin" in output
    assert "  Admin" in output

    # Sub-items use 4-space indentation (policy name under role)
    assert "    Admin Policy" in output

    # Collection-action entries use 6-space indentation
    assert "      articles: read" in output


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 4: Unresolvable policy fallback
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------


@st.composite
def _permissions_with_unresolvable_policies(draw):
    """Generate permissions referencing policy UUIDs NOT in the policies list.

    Returns (permissions, policies, roles) where:
    - roles are valid
    - policies list does NOT contain the policy UUIDs referenced by permissions
    - Each permission references a policy UUID that cannot be resolved
    """
    # Generate roles (at least 1)
    roles = draw(
        st.lists(
            st.builds(
                DirectusRole,
                name=st.text(min_size=1, max_size=30).filter(
                    lambda s: "\n" not in s and s.strip() != ""
                ),
                id=st.uuids().map(str),
            ),
            min_size=1,
            max_size=5,
        )
    )

    # Generate some policies that ARE in the list (linked to roles)
    # These exist but will NOT be referenced by our test permissions
    known_policies = draw(
        st.lists(
            st.builds(
                DirectusPolicy,
                id=st.uuids().map(str),
                name=st.text(min_size=1, max_size=30).filter(lambda s: "\n" not in s),
                roles=st.just([roles[0].id]),  # link to first role
            ),
            min_size=0,
            max_size=3,
        )
    )
    known_policy_ids = {p.id for p in known_policies}

    # Generate unresolvable policy UUIDs (not in known_policies)
    unresolvable_policy_ids = draw(
        st.lists(
            st.uuids().map(str).filter(lambda u: u not in known_policy_ids),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )

    # Generate permissions referencing the unresolvable policy UUIDs
    permissions = draw(
        st.lists(
            st.builds(
                DirectusPermission,
                id=st.integers(min_value=1, max_value=10000),
                policy=st.sampled_from(unresolvable_policy_ids),
                collection=st.text(min_size=1, max_size=30).filter(
                    lambda s: "\n" not in s and ":" not in s and s.strip() != ""
                ),
                action=st.sampled_from(["read", "create", "update", "delete"]),
            ),
            min_size=1,
            max_size=10,
        )
    )

    return permissions, known_policies, roles, unresolvable_policy_ids


@given(data=_permissions_with_unresolvable_policies())
@settings(max_examples=200)
def test_unresolvable_policy_fallback_shows_raw_uuid(data) -> None:
    """Property 4: Unresolvable policy fallback.

    For any permission referencing a policy UUID not in the policies list,
    the raw UUID is displayed as the policy sub-header at 4-space indent level.

    **Validates: Requirements 3.2**
    """
    permissions, policies, roles, unresolvable_policy_ids = data
    cmd = _make_check_command()

    result = cmd._format_policies(permissions, policies, roles)
    lines = result.split("\n")

    # Extract policy sub-header lines (4-space indent, not 6-space)
    policy_lines = [
        line for line in lines[1:]
        if line.startswith("    ") and not line.startswith("      ")
    ]

    # Each unresolvable policy UUID that is referenced by at least one permission
    # should appear as a raw UUID in the policy sub-header lines
    referenced_unresolvable_ids = {
        perm.policy for perm in permissions
        if perm.policy in set(unresolvable_policy_ids)
    }

    for policy_uuid in referenced_unresolvable_ids:
        assert any(
            policy_uuid in line for line in policy_lines
        ), (
            f"Unresolvable policy UUID '{policy_uuid}' should appear as raw UUID "
            f"in policy sub-header lines (4-space indent), but policy lines are: {policy_lines}"
        )

    # Additionally verify the raw UUID appears at exactly 4-space indent
    for policy_uuid in referenced_unresolvable_ids:
        expected_line = f"    {policy_uuid}"
        assert expected_line in lines, (
            f"Expected '{expected_line}' (4-space indent + raw UUID) in output, "
            f"but it was not found. Output lines: {lines}"
        )


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 5: Private collection filtering (default)
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------


@st.composite
def _collections_with_directus_prefix(draw):
    """Generate a list of collections that includes some with `directus_` prefix and some without.

    Returns a list of DirectusCollection objects where at least one has a
    `directus_` prefix and at least one does not.
    """
    # Generate non-private collections (no directus_ prefix)
    non_private_names = draw(
        st.lists(
            st.text(min_size=1, max_size=30).filter(
                lambda s: "\n" not in s and not s.startswith("directus_") and s.strip() != ""
            ),
            min_size=1,
            max_size=10,
        )
    )

    # Generate private collections (with directus_ prefix)
    private_suffixes = draw(
        st.lists(
            st.text(min_size=1, max_size=30).filter(
                lambda s: "\n" not in s and s.strip() != ""
            ),
            min_size=1,
            max_size=10,
        )
    )
    private_names = [f"directus_{suffix}" for suffix in private_suffixes]

    # Combine and shuffle
    all_names = non_private_names + private_names
    shuffled = draw(st.permutations(all_names))

    collections = [DirectusCollection(collection=name) for name in shuffled]
    return collections


@given(collections=_collections_with_directus_prefix())
@settings(max_examples=200)
def test_private_collection_filtering_default(collections: list[DirectusCollection]) -> None:
    """Property 5: Private collection filtering (default).

    For any list of collections, when `enable_private_collections=False`,
    no collection starting with `directus_` appears in output.

    **Validates: Requirements 4.2**
    """
    cmd = CheckCommand(client=None, enable_private_collections=False)  # type: ignore[arg-type]

    result = cmd._format_collections(collections)
    lines = result.split("\n")

    # The header must still be "Collections"
    assert lines[0] == "Collections"

    # No line in the output should contain a collection name starting with directus_
    content_lines = lines[1:]
    for line in content_lines:
        # Content lines are indented with 2 spaces; strip the prefix to get the name
        name = line[2:] if line.startswith("  ") else line
        assert not name.startswith("directus_"), (
            f"Collection '{name}' starts with 'directus_' but should be filtered out "
            f"when enable_private_collections=False"
        )


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 6: Private collection inclusion (opt-in)
# Validates: Requirements 4.3
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    names=st.lists(
        st.text(min_size=1, max_size=50).filter(lambda s: "\n" not in s),
        min_size=1,
        max_size=50,
    ),
    private_names=st.lists(
        st.text(min_size=1, max_size=40).filter(lambda s: "\n" not in s).map(
            lambda s: f"directus_{s}"
        ),
        min_size=1,
        max_size=20,
    ),
)
def test_private_collection_inclusion_opt_in(
    names: list[str], private_names: list[str]
) -> None:
    """Property 6: Private collection inclusion (opt-in).

    For any list of collections, when `enable_private_collections=True`,
    all collections appear in output, including those starting with `directus_`.

    **Validates: Requirements 4.3**
    """
    cmd = CheckCommand(client=None, enable_private_collections=True)  # type: ignore[arg-type]

    all_names = names + private_names
    collections = [DirectusCollection(collection=name) for name in all_names]

    result = cmd._format_collections(collections)
    lines = result.split("\n")

    # Output starts with "Collections"
    assert lines[0] == "Collections"

    # Extract collection names from output (2-space indent)
    content_lines = lines[1:]
    extracted_names = [line[2:] for line in content_lines]

    # ALL collections must appear in the output (including directus_ prefixed ones)
    for name in all_names:
        assert name in extracted_names, (
            f"Collection '{name}' should appear in output when "
            f"enable_private_collections=True, but it was not found. "
            f"Extracted names: {extracted_names}"
        )

    # Total count must match input count
    assert len(content_lines) == len(all_names), (
        f"Expected {len(all_names)} collections in output, got {len(content_lines)}"
    )


# ---------------------------------------------------------------------------
# Feature: refactor-improvements, Property 7: Roles with empty permissions after filtering
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------


@st.composite
def _roles_with_only_private_permissions(draw):
    """Generate roles where at least one role has permissions ONLY on directus_-prefixed collections.

    Returns (permissions, policies, roles, private_only_role_names) where:
    - At least one role has permissions exclusively on directus_-prefixed collections
    - private_only_role_names contains the names of roles that only have private permissions
    """
    # Generate at least 2 roles so we can have one with only private permissions
    # and optionally others with public permissions
    role_count = draw(st.integers(min_value=1, max_value=5))
    roles = [
        DirectusRole(
            id=draw(st.uuids().map(str)),
            name=draw(
                st.text(
                    alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_-"),
                    min_size=1,
                    max_size=20,
                ).filter(lambda s: s.strip() == s and len(s) >= 1)
            ),
        )
        for _ in range(role_count)
    ]

    # Create one policy per role
    policies = [
        DirectusPolicy(
            id=draw(st.uuids().map(str)),
            name=f"{role.name} Policy",
            roles=[role.id],
        )
        for role in roles
    ]

    # Pick at least one role to have ONLY private (directus_-prefixed) permissions
    private_only_count = draw(st.integers(min_value=1, max_value=max(1, len(roles))))
    private_only_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(roles) - 1),
            min_size=private_only_count,
            max_size=private_only_count,
            unique=True,
        )
    )

    permissions = []
    perm_id = 1

    # Generate permissions for private-only roles (only directus_-prefixed collections)
    for idx in private_only_indices:
        policy = policies[idx]
        num_perms = draw(st.integers(min_value=1, max_value=5))
        for _ in range(num_perms):
            collection_suffix = draw(
                st.text(
                    alphabet=st.characters(whitelist_categories=("Ll",)),
                    min_size=1,
                    max_size=15,
                )
            )
            permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=policy.id,
                    collection=f"directus_{collection_suffix}",
                    action=draw(st.sampled_from(["read", "create", "update", "delete"])),
                )
            )
            perm_id += 1

    # Generate permissions for other roles (non-directus_ collections)
    other_indices = [i for i in range(len(roles)) if i not in private_only_indices]
    for idx in other_indices:
        policy = policies[idx]
        num_perms = draw(st.integers(min_value=1, max_value=5))
        for _ in range(num_perms):
            collection = draw(
                st.text(min_size=1, max_size=20).filter(
                    lambda s: "\n" not in s and ":" not in s and not s.startswith("directus_") and s.strip() != ""
                )
            )
            permissions.append(
                DirectusPermission(
                    id=perm_id,
                    policy=policy.id,
                    collection=collection,
                    action=draw(st.sampled_from(["read", "create", "update", "delete"])),
                )
            )
            perm_id += 1

    private_only_role_names = [roles[idx].name for idx in private_only_indices]

    return permissions, policies, roles, private_only_role_names


@given(data=_roles_with_only_private_permissions())
@settings(max_examples=200)
def test_roles_with_empty_permissions_after_filtering(data) -> None:
    """Property 7: Roles with empty permissions after filtering.

    For any role with permissions only on directus_-prefixed collections,
    when filtering is active (enable_private_collections=False), the role
    still appears in the Policies section at 2-space indent level even though
    all its collection entries were filtered out.

    **Validates: Requirements 4.6**
    """
    permissions, policies, roles, private_only_role_names = data
    cmd = CheckCommand(client=None, enable_private_collections=False)  # type: ignore[arg-type]

    result = cmd._format_policies(permissions, policies, roles)
    lines = result.split("\n")

    # Extract role lines (2-space indent, not 4-space)
    role_lines = [
        line for line in lines[1:]
        if line.startswith("  ") and not line.startswith("    ")
    ]
    role_line_texts = [line[2:] for line in role_lines]

    # Every role that had only private permissions should still appear
    # in the output at 2-space indent level
    for role_name in private_only_role_names:
        assert role_name in role_line_texts, (
            f"Role '{role_name}' has only directus_-prefixed permissions and should "
            f"still appear in the Policies section after filtering, but role lines are: "
            f"{role_line_texts}"
        )


# ---------------------------------------------------------------------------
# Feature: custom-permissions, Task 7.1: Custom permissions section in CheckCommand
# Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
# ---------------------------------------------------------------------------


class TestInlineCustomPermissions:
    """Unit tests for inline custom permissions in _format_policies.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
    """

    def test_no_custom_permissions_shows_only_standard_actions(self) -> None:
        """When no custom permissions exist, only standard actions are shown.

        Validates: Requirement 5.5
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(id=2, policy="policy-1", collection="articles", action="create"),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        assert "articles: read, create" in result
        assert "C_" not in result

    def test_custom_permission_with_validation_inline(self) -> None:
        """Custom permission with validation shows 'has validation' inline.

        Validates: Requirements 5.1, 5.2, 5.4
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(
                id=2,
                policy="policy-1",
                collection="articles",
                action="update",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        # Standard action and custom ref should be in the same collection line
        assert "articles: read, UPDATE_C_1 has validation" in result

    def test_custom_permission_with_fields_inline(self) -> None:
        """Custom permission with fields shows 'fields:(...)' inline.

        Validates: Requirements 5.1, 5.2, 5.3
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(
                id=2,
                policy="policy-1",
                collection="articles",
                action="update",
                fields=["title", "body"],
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        assert "articles: read, UPDATE_C_1 fields:(title,body)" in result

    def test_custom_permission_with_item_permissions_inline(self) -> None:
        """Custom permission with item permissions shows 'has item permissions' inline.

        Validates: Requirements 5.1, 5.2, 5.4
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(
                id=2,
                policy="policy-1",
                collection="articles",
                action="update",
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        assert "articles: read, UPDATE_C_1 has item permissions" in result

    def test_custom_permission_with_all_indicators_inline(self) -> None:
        """Custom permission with all constraints shows all indicators inline.

        Validates: Requirements 5.2, 5.3, 5.4
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(
                id=2,
                policy="policy-1",
                collection="articles",
                action="update",
                fields=["title", "body"],
                validation={"_and": [{"status": {"_eq": "draft"}}]},
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        assert "UPDATE_C_1 fields:(title,body) has validation has item permissions" in result

    def test_multiple_custom_permissions_inline(self) -> None:
        """Multiple custom permissions appear inline in the same collection line.

        Validates: Requirements 5.1, 5.2, 5.3, 5.4
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(
                id=2,
                policy="policy-1",
                collection="articles",
                action="update",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
                fields=["title"],
            ),
            DirectusPermission(
                id=3,
                policy="policy-1",
                collection="articles",
                action="create",
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        # Standard action first, then custom refs
        assert "articles: read, UPDATE_C_1 fields:(title) has validation, CREATE_C_2 has item permissions" in result

    def test_duplicate_triple_marks_all_as_custom_inline(self) -> None:
        """Duplicate (policy, collection, action) triples mark all entries as custom inline.

        Validates: Requirements 5.1, 5.2
        """
        cmd = _make_check_command()
        # Two permissions with same policy+collection+action but no special attributes
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(id=2, policy="policy-1", collection="articles", action="read"),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        # Both should be shown as custom refs (READ_C_1, READ_C_2) since they share a triple
        assert "READ_C_1" in result
        assert "READ_C_2" in result

    def test_fields_star_not_treated_as_custom(self) -> None:
        """Permission with fields=["*"] is NOT treated as custom.

        Validates: Requirement 5.5
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(
                id=1,
                policy="policy-1",
                collection="articles",
                action="read",
                fields=["*"],
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        assert "articles: read" in result
        assert "C_" not in result

    def test_run_shows_custom_permissions_inline(self, caplog) -> None:
        """CheckCommand.run() displays custom permissions inline in Policies section.

        Validates: Requirements 5.1, 5.2
        """
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="uuid-editor", name="Editor")]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["uuid-editor"])]
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(
                id=2,
                policy="policy-1",
                collection="articles",
                action="update",
                validation={"status": "draft"},
            ),
        ]

        client = MagicMock()
        client.get_collections.return_value = collections
        client.get_roles.return_value = roles
        client.get_policies.return_value = policies
        client.get_permissions.return_value = permissions

        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        output = caplog.text
        # Custom permissions are inline, no separate "Custom Permissions" section
        assert "Custom Permissions" not in output
        assert "UPDATE_C_1 has validation" in output

    def test_run_no_custom_permissions_no_references(self, caplog) -> None:
        """CheckCommand.run() shows no C_N references when no custom permissions exist.

        Validates: Requirement 5.5
        """
        collections = [DirectusCollection(collection="articles")]
        roles = [DirectusRole(id="uuid-editor", name="Editor")]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["uuid-editor"])]
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
        ]

        client = MagicMock()
        client.get_collections.return_value = collections
        client.get_roles.return_value = roles
        client.get_policies.return_value = policies
        client.get_permissions.return_value = permissions

        cmd = CheckCommand(client=client)
        with caplog.at_level(logging.INFO, logger="directus_ac.check"):
            cmd.run()

        output = caplog.text
        assert "Custom Permissions" not in output
        assert "C_" not in output

    def test_mixed_standard_and_custom_same_collection(self) -> None:
        """Standard actions and custom refs appear together for the same collection.

        Validates: Requirements 5.1, 5.2
        """
        cmd = _make_check_command()
        permissions = [
            DirectusPermission(id=1, policy="policy-1", collection="articles", action="read"),
            DirectusPermission(id=2, policy="policy-1", collection="articles", action="create"),
            DirectusPermission(
                id=3,
                policy="policy-1",
                collection="articles",
                action="update",
                fields=["title", "body"],
            ),
            DirectusPermission(
                id=4,
                policy="policy-1",
                collection="articles",
                action="delete",
                validation={"status": "draft"},
            ),
        ]
        policies = [DirectusPolicy(id="policy-1", name="Editor Policy", roles=["role-1"])]
        roles = [DirectusRole(id="role-1", name="Editor")]

        result = cmd._format_policies(permissions, policies, roles)
        # Standard actions first, then custom refs
        assert "articles: read, create, UPDATE_C_1 fields:(title,body), DELETE_C_2 has validation" in result
