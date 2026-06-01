"""Unit tests for generate_permission_name.

Tests cover:
- ACTION_C_N pattern output (Requirement 1.1)
- Action prefix is uppercased (Requirement 1.2)
- Counter values produce correct names
- Uniqueness via counter (Requirement 1.3)
"""
from __future__ import annotations

from directus_ac.generate import generate_permission_name


class TestGeneratePermissionName:
    """Tests for generate_permission_name(action, counter)."""

    def test_basic_counter(self):
        """Action 'read' with counter 1 produces READ_C_1."""
        assert generate_permission_name("read", 1) == "READ_C_1"

    def test_action_uppercased(self):
        """Action string is uppercased regardless of input casing."""
        assert generate_permission_name("read", 1) == "READ_C_1"
        assert generate_permission_name("Read", 2) == "READ_C_2"
        assert generate_permission_name("READ", 3) == "READ_C_3"

    def test_all_actions(self):
        """All four action types produce correct prefixes."""
        assert generate_permission_name("create", 1) == "CREATE_C_1"
        assert generate_permission_name("read", 2) == "READ_C_2"
        assert generate_permission_name("update", 3) == "UPDATE_C_3"
        assert generate_permission_name("delete", 4) == "DELETE_C_4"

    def test_counter_values(self):
        """Different counter values produce correct ACTION_C_N names."""
        assert generate_permission_name("update", 1) == "UPDATE_C_1"
        assert generate_permission_name("update", 2) == "UPDATE_C_2"
        assert generate_permission_name("update", 3) == "UPDATE_C_3"
        assert generate_permission_name("update", 10) == "UPDATE_C_10"
        assert generate_permission_name("update", 100) == "UPDATE_C_100"

    def test_uniqueness_via_counter(self):
        """Different counters always produce different names for same action."""
        names = [generate_permission_name("read", i) for i in range(1, 50)]
        assert len(names) == len(set(names))

    def test_format_is_action_c_counter(self):
        """Output format is always {ACTION}_C_{counter}."""
        for i in range(1, 20):
            result = generate_permission_name("delete", i)
            assert result == f"DELETE_C_{i}"
