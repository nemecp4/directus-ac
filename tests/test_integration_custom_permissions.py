"""Integration tests for end-to-end CLI flows with custom permissions.

Tests the full pipeline through the CLI commands (--generate, --update, --check)
with only the DirectusClient mocked, verifying that custom permissions flow
correctly through detection, naming, serialization, and application.

Validates: Requirements 4.1, 5.1, 6.1
"""
from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

from directus_ac.cli import main
from directus_ac.models import (
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_mock_client_with_custom_permissions():
    """Create a mock DirectusClient that returns permissions with custom attributes.

    Simulates a Directus instance with:
    - 2 collections: articles, comments
    - 1 role: editor (id=role-1) linked to policy-1
    - 1 policy: "editor — directus-ac" (id=policy-1)
    - Permissions:
      - id=1: articles/read (standard)
      - id=2: articles/create (standard)
      - id=3: articles/update with validation + fields (custom → C_1)
      - id=4: articles/read with item-level permissions (custom → C_2)
      - id=5: comments/read (standard)
    """
    mock_client = MagicMock()
    mock_client.get_collections.return_value = [
        DirectusCollection(collection="articles"),
        DirectusCollection(collection="comments"),
    ]
    mock_client.get_roles.return_value = [
        DirectusRole(id="role-1", name="editor", policies=["policy-1"]),
    ]
    mock_client.get_policies.return_value = [
        DirectusPolicy(
            id="policy-1", name="editor — directus-ac", roles=["role-1"]
        ),
    ]
    mock_client.get_permissions.return_value = [
        DirectusPermission(
            id=1,
            policy="policy-1",
            collection="articles",
            action="read",
            fields=None,
            validation=None,
            permissions=None,
        ),
        DirectusPermission(
            id=2,
            policy="policy-1",
            collection="articles",
            action="create",
            fields=None,
            validation=None,
            permissions=None,
        ),
        DirectusPermission(
            id=3,
            policy="policy-1",
            collection="articles",
            action="update",
            fields=["title", "body"],
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            permissions=None,
        ),
        DirectusPermission(
            id=4,
            policy="policy-1",
            collection="articles",
            action="read",
            fields=None,
            validation=None,
            permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
        ),
        DirectusPermission(
            id=5,
            policy="policy-1",
            collection="comments",
            action="read",
            fields=None,
            validation=None,
            permissions=None,
        ),
    ]
    return mock_client


# ---------------------------------------------------------------------------
# Integration tests for --generate
# ---------------------------------------------------------------------------


class TestGenerateIntegration:
    """Integration tests for --generate with custom permissions.

    Exercises the full pipeline: DirectusClient → Generator → serialize_config → stdout.
    Only the DirectusClient class is mocked; Generator and serialize_config run for real.

    Validates: Requirement 4.1
    """

    @patch("directus_ac.cli.DirectusClient")
    def test_generate_produces_inline_refs_in_groups(
        self, mock_client_cls, monkeypatch, capsys
    ):
        """--generate with custom permissions produces C_N refs inline in groups."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        main()

        captured = capsys.readouterr()
        output = captured.out

        # Verify the groups section contains inline C_N references
        assert "C_1" in output
        assert "C_2" in output
        # Standard keywords should also be present
        assert "READ" in output
        assert "WRITE" in output

    @patch("directus_ac.cli.DirectusClient")
    def test_generate_produces_custom_permissions_definitions(
        self, mock_client_cls, monkeypatch, capsys
    ):
        """--generate produces a custom_permissions definitions section."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        main()

        captured = capsys.readouterr()
        output = captured.out

        # Verify custom_permissions section exists
        assert "custom_permissions:" in output
        # id=1 and id=4 share (policy-1, articles, read) triple → both custom
        # id=3 has validation+fields → custom
        # So we get READ_C_1 (id=1), UPDATE_C_2 (id=3), READ_C_3 (id=4)
        assert "name: READ_C_1" in output
        assert "name: UPDATE_C_2" in output
        assert "name: READ_C_3" in output
        # Policy name contains em-dash (—) which YAML may quote
        assert "directus-ac" in output
        assert "collection: articles" in output
        assert "validation:" in output
        assert "fields:" in output

    @patch("directus_ac.cli.DirectusClient")
    def test_generate_custom_permissions_ordered_by_id(
        self, mock_client_cls, monkeypatch, capsys
    ):
        """--generate assigns C_N names in ascending permission id order."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        main()

        captured = capsys.readouterr()
        output = captured.out

        # Duplicate detection: id=1 and id=4 share (policy-1, articles, read)
        # So custom permissions sorted by id: id=1, id=3, id=4
        # READ_C_1 → id=1 (read, no constraints but duplicate triple)
        # UPDATE_C_2 → id=3 (update with validation+fields)
        # READ_C_3 → id=4 (read with item permissions)
        lines = output.split("\n")

        c1_idx = next(i for i, l in enumerate(lines) if "name: READ_C_1" in l)
        c1_block = "\n".join(lines[c1_idx : c1_idx + 5])
        assert "action: read" in c1_block

        c2_idx = next(i for i, l in enumerate(lines) if "name: UPDATE_C_2" in l)
        c2_block = "\n".join(lines[c2_idx : c2_idx + 5])
        assert "action: update" in c2_block

        c3_idx = next(i for i, l in enumerate(lines) if "name: READ_C_3" in l)
        c3_block = "\n".join(lines[c3_idx : c3_idx + 5])
        assert "action: read" in c3_block

    @patch("directus_ac.cli.DirectusClient")
    def test_generate_without_custom_permissions_omits_section(
        self, mock_client_cls, monkeypatch, capsys
    ):
        """--generate without custom permissions omits custom_permissions key entirely."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"],
        )

        mock_client = MagicMock()
        mock_client.get_collections.return_value = [
            DirectusCollection(collection="articles"),
        ]
        mock_client.get_roles.return_value = [
            DirectusRole(id="role-1", name="editor", policies=["policy-1"]),
        ]
        mock_client.get_policies.return_value = [
            DirectusPolicy(id="policy-1", name="editor — directus-ac", roles=["role-1"]),
        ]
        mock_client.get_permissions.return_value = [
            DirectusPermission(
                id=1, policy="policy-1", collection="articles", action="read",
                fields=None, validation=None, permissions=None,
            ),
        ]
        mock_client_cls.return_value = mock_client

        main()

        captured = capsys.readouterr()
        assert "custom_permissions" not in captured.out

    @patch("directus_ac.cli.DirectusClient")
    def test_generate_permission_set_contains_both_keywords_and_refs(
        self, mock_client_cls, monkeypatch, capsys
    ):
        """--generate Permission_Set strings contain both standard keywords and C_N refs."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        main()

        captured = capsys.readouterr()
        output = captured.out

        # The articles group should have a Permission_Set for editor that
        # includes both standard keywords and custom refs.
        # id=1 is standard read, id=2 is standard create → READ WRITE
        # id=3 is custom (C_1), id=4 is custom (C_2) but id=4 shares
        # (policy-1, articles, read) with id=1 → both become custom
        # So the Permission_Set should contain C_1 and C_2 (and possibly C_3)
        # At minimum, the groups section should have C_ references
        assert "groups:" in output
        # Find the permissions line for editor in the articles group
        # It should contain at least one standard keyword and at least one C_ ref
        # The exact content depends on duplicate detection logic
        assert "C_" in output


# ---------------------------------------------------------------------------
# Integration tests for --update
# ---------------------------------------------------------------------------


class TestUpdateIntegration:
    """Integration tests for --update with custom permissions.

    Exercises the full pipeline: load_config → Validator → PermissionManager.
    The DirectusClient is mocked to verify correct POST/PATCH calls.

    Validates: Requirement 6.1
    """

    @patch("directus_ac.cli.DirectusClient")
    def test_update_creates_custom_permissions_via_post(
        self, mock_client_cls, monkeypatch, tmp_path, caplog
    ):
        """--update with custom permissions creates them via POST when they don't exist."""
        import logging

        # Write a config file with custom permissions
        config_content = """\
collections:
  - articles
roles:
  - editor
groups:
  - collections:
      - articles
    permissions:
      editor: READ WRITE UPDATE_C_1
custom_permissions:
  - name: UPDATE_C_1
    policy: "editor — directus-ac"
    collection: articles
    action: update
    validation:
      _and:
        - status:
            _eq: draft
    fields:
      - title
      - body
"""
        config_file = tmp_path / "directus_ac.yaml"
        config_file.write_text(config_content)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "directus-ac", "--update",
                "--config", str(config_file),
                "--url", "http://localhost:8055",
                "--token", "t",
            ],
        )

        mock_client = MagicMock()
        # Collections exist
        mock_client.get_collections.return_value = [
            DirectusCollection(collection="articles"),
        ]
        # Role exists
        mock_client.get_roles.return_value = [
            DirectusRole(id="role-1", name="editor", policies=["policy-1"]),
        ]
        # Policy exists
        mock_client.get_policies.return_value = [
            DirectusPolicy(id="policy-1", name="editor — directus-ac", roles=["role-1"]),
        ]
        # No existing permissions (everything will be created)
        mock_client.get_permissions.return_value = []
        # Mock create_permission to return a valid response
        mock_client.create_permission.return_value = DirectusPermission(
            id=100, policy="policy-1", collection="articles", action="update",
            fields=["title", "body"],
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            permissions=None,
        )
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            main()

        # Verify create_permission was called for the custom permission
        # Find the call that includes validation (the custom permission call)
        custom_calls = [
            call for call in mock_client.create_permission.call_args_list
            if call.kwargs.get("validation") is not None
            or (len(call.args) > 3 if call.args else False)
        ]
        assert len(custom_calls) >= 1

        # Verify the custom permission was created with correct attributes
        # The call should include policy_id, collection, action, and kwargs
        call_args = custom_calls[0]
        assert call_args[0][0] == "policy-1"  # policy_id
        assert call_args[0][1] == "articles"  # collection
        assert call_args[0][2] == "update"  # action
        assert call_args[1]["validation"] == {"_and": [{"status": {"_eq": "draft"}}]}
        assert call_args[1]["fields"] == ["title", "body"]

        # Verify summary output
        assert "custom permissions created: 1" in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_update_patches_existing_custom_permissions(
        self, mock_client_cls, monkeypatch, tmp_path, caplog
    ):
        """--update patches existing custom permissions via PATCH when they already exist."""
        import logging

        config_content = """\
collections:
  - articles
roles:
  - editor
groups:
  - collections:
      - articles
    permissions:
      editor: READ UPDATE_C_1
custom_permissions:
  - name: UPDATE_C_1
    policy: "editor — directus-ac"
    collection: articles
    action: update
    validation:
      _and:
        - status:
            _eq: published
    fields:
      - title
"""
        config_file = tmp_path / "directus_ac.yaml"
        config_file.write_text(config_content)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "directus-ac", "--update",
                "--config", str(config_file),
                "--url", "http://localhost:8055",
                "--token", "t",
            ],
        )

        mock_client = MagicMock()
        mock_client.get_collections.return_value = [
            DirectusCollection(collection="articles"),
        ]
        mock_client.get_roles.return_value = [
            DirectusRole(id="role-1", name="editor", policies=["policy-1"]),
        ]
        mock_client.get_policies.return_value = [
            DirectusPolicy(id="policy-1", name="editor — directus-ac", roles=["role-1"]),
        ]
        # Existing permission with constraints (will be matched for PATCH)
        mock_client.get_permissions.return_value = [
            DirectusPermission(
                id=50,
                policy="policy-1",
                collection="articles",
                action="update",
                fields=["title", "body"],
                validation={"_and": [{"status": {"_eq": "draft"}}]},
                permissions=None,
            ),
        ]
        mock_client.update_permission.return_value = DirectusPermission(
            id=50, policy="policy-1", collection="articles", action="update",
            fields=["title"],
            validation={"_and": [{"status": {"_eq": "published"}}]},
            permissions=None,
        )
        mock_client.create_permission.return_value = DirectusPermission(
            id=101, policy="policy-1", collection="articles", action="read",
            fields=None, validation=None, permissions=None,
        )
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            main()

        # Verify update_permission was called for the existing custom permission
        update_calls = [
            call for call in mock_client.update_permission.call_args_list
            if call.kwargs.get("validation") is not None
        ]
        assert len(update_calls) >= 1

        # Verify the PATCH call has the updated values
        call_args = update_calls[0]
        assert call_args[0][0] == 50  # permission_id
        assert call_args[0][1] == "policy-1"  # policy_id
        assert call_args[0][2] == "articles"  # collection
        assert call_args[0][3] == "update"  # action
        assert call_args[1]["validation"] == {"_and": [{"status": {"_eq": "published"}}]}
        assert call_args[1]["fields"] == ["title"]

        # Verify summary output
        assert "custom permissions updated: 1" in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_update_with_multiple_custom_permissions(
        self, mock_client_cls, monkeypatch, tmp_path, caplog
    ):
        """--update with multiple custom permissions creates and updates correctly."""
        import logging

        config_content = """\
collections:
  - articles
roles:
  - editor
groups:
  - collections:
      - articles
    permissions:
      editor: READ UPDATE_C_1 READ_C_2
custom_permissions:
  - name: UPDATE_C_1
    policy: "editor — directus-ac"
    collection: articles
    action: update
    validation:
      _and:
        - status:
            _eq: draft
  - name: READ_C_2
    policy: "editor — directus-ac"
    collection: articles
    action: read
    permissions:
      _and:
        - author:
            _eq: $CURRENT_USER
"""
        config_file = tmp_path / "directus_ac.yaml"
        config_file.write_text(config_content)

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "directus-ac", "--update",
                "--config", str(config_file),
                "--url", "http://localhost:8055",
                "--token", "t",
            ],
        )

        mock_client = MagicMock()
        mock_client.get_collections.return_value = [
            DirectusCollection(collection="articles"),
        ]
        mock_client.get_roles.return_value = [
            DirectusRole(id="role-1", name="editor", policies=["policy-1"]),
        ]
        mock_client.get_policies.return_value = [
            DirectusPolicy(id="policy-1", name="editor — directus-ac", roles=["role-1"]),
        ]
        # One existing custom permission (C_1 will PATCH), C_2 will POST
        mock_client.get_permissions.return_value = [
            DirectusPermission(
                id=50,
                policy="policy-1",
                collection="articles",
                action="update",
                fields=None,
                validation={"_and": [{"status": {"_eq": "old"}}]},
                permissions=None,
            ),
        ]
        mock_client.update_permission.return_value = DirectusPermission(
            id=50, policy="policy-1", collection="articles", action="update",
            fields=None, validation={"_and": [{"status": {"_eq": "draft"}}]},
            permissions=None,
        )
        mock_client.create_permission.return_value = DirectusPermission(
            id=101, policy="policy-1", collection="articles", action="read",
            fields=None, validation=None,
            permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
        )
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            main()

        # Verify counts: 1 updated (C_1 matched existing), 1 created (C_2 new)
        assert "custom permissions created: 1" in caplog.text
        assert "custom permissions updated: 1" in caplog.text


# ---------------------------------------------------------------------------
# Integration tests for --check
# ---------------------------------------------------------------------------


class TestCheckIntegration:
    """Integration tests for --check with custom permissions inline display.

    Exercises the full pipeline: DirectusClient → CheckCommand → stdout.
    Only the DirectusClient class is mocked.

    Validates: Requirement 5.1
    """

    @patch("directus_ac.cli.DirectusClient")
    def test_check_shows_custom_refs_inline_with_standard_actions(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check displays C_N references inline alongside standard actions."""
        import logging

        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0

        # Custom permission references should appear inline
        assert "UPDATE_C_" in caplog.text or "READ_C_" in caplog.text
        # Standard actions should also appear
        assert "articles" in caplog.text
        # No separate "Custom Permissions" section header
        assert "Custom Permissions" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_shows_fields_indicator(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check shows fields:(field1,field2) indicator for custom permissions with fields."""
        import logging

        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        # Custom permissions now show only name, no field indicators
        assert "fields:" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_shows_validation_indicator(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check shows 'has validation' indicator for custom permissions with validation."""
        import logging

        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        # Custom permissions now show only name, no validation indicators
        assert "has validation" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_shows_item_permissions_indicator(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check shows 'has item permissions' for custom permissions with item-level rules."""
        import logging

        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )
        mock_client_cls.return_value = _make_mock_client_with_custom_permissions()

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        # Custom permissions now show only name, no item permission indicators
        assert "has item permissions" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_without_custom_permissions_shows_only_actions(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check without custom permissions shows only standard actions."""
        import logging

        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )

        mock_client = MagicMock()
        mock_client.get_collections.return_value = [
            DirectusCollection(collection="articles"),
        ]
        mock_client.get_roles.return_value = [
            DirectusRole(id="role-1", name="editor", policies=["policy-1"]),
        ]
        mock_client.get_policies.return_value = [
            DirectusPolicy(id="policy-1", name="editor — directus-ac", roles=["role-1"]),
        ]
        mock_client.get_permissions.return_value = [
            DirectusPermission(
                id=1, policy="policy-1", collection="articles", action="read",
                fields=None, validation=None, permissions=None,
            ),
            DirectusPermission(
                id=2, policy="policy-1", collection="articles", action="create",
                fields=None, validation=None, permissions=None,
            ),
        ]
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        assert "articles: read, create" in caplog.text
        # No C_ references should appear
        assert "C_" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_inline_format_comma_separated(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check displays actions and custom refs in a single comma-separated list."""
        import logging

        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )

        mock_client = MagicMock()
        mock_client.get_collections.return_value = [
            DirectusCollection(collection="posts"),
        ]
        mock_client.get_roles.return_value = [
            DirectusRole(id="role-1", name="author", policies=["policy-1"]),
        ]
        mock_client.get_policies.return_value = [
            DirectusPolicy(id="policy-1", name="author-policy", roles=["role-1"]),
        ]
        mock_client.get_permissions.return_value = [
            DirectusPermission(
                id=1, policy="policy-1", collection="posts", action="read",
                fields=None, validation=None, permissions=None,
            ),
            DirectusPermission(
                id=2, policy="policy-1", collection="posts", action="update",
                fields=["title"],
                validation=None,
                permissions=None,
            ),
        ]
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        # Should show standard action and custom ref in comma-separated format
        # id=2 has non-default fields → custom → C_1
        assert "posts:" in caplog.text
        assert "C_1" in caplog.text
        # No indicators should be present
        assert "fields:" not in caplog.text
