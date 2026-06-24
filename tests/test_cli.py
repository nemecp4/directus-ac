"""Tests for cli.py — argument parsing and pipeline orchestration (unit tests)."""

import pytest

from directus_ac.cli import build_parser


class TestCheckFlagParsing:
    """Unit tests for --check CLI argument parsing.

    Validates: Requirements 1.3, 1.4
    """

    def test_check_flag_is_recognized(self):
        """--check flag is recognized and sets args.check to True."""
        parser = build_parser()
        args = parser.parse_args(["--check", "--url", "http://localhost", "--token", "abc"])
        assert args.check is True

    def test_check_flag_defaults_to_false(self):
        """Without --check, args.check defaults to False."""
        parser = build_parser()
        args = parser.parse_args(["--url", "http://localhost", "--token", "abc"])
        assert args.check is False

    def test_check_works_alongside_url_and_token(self):
        """--check can be combined with --url and --token."""
        parser = build_parser()
        args = parser.parse_args([
            "--check",
            "--url", "http://example.com:8055",
            "--token", "my-secret-token",
        ])
        assert args.check is True
        assert args.url == "http://example.com:8055"
        assert args.token == "my-secret-token"

    def test_check_does_not_require_config(self):
        """--check does not require --config to be explicitly provided."""
        parser = build_parser()
        # Parse with --check but without --config; should not raise
        args = parser.parse_args(["--check", "--url", "http://localhost", "--token", "t"])
        assert args.check is True
        # config has a default value, so it's always present but not required
        assert args.config == "./directus_ac.yaml"

    def test_check_ignores_config_value(self):
        """--check can be provided alongside --config without conflict."""
        parser = build_parser()
        args = parser.parse_args([
            "--check",
            "--config", "custom.yaml",
            "--url", "http://localhost",
            "--token", "t",
        ])
        assert args.check is True
        assert args.config == "custom.yaml"

import sys
from unittest.mock import MagicMock, patch

import pytest

from directus_ac.cli import main


class TestCredentialResolutionCheckMode:
    """Unit tests for credential resolution when --check is used.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
    """

    @patch("directus_ac.cli.CheckCommand")
    @patch("directus_ac.cli.DirectusClient")
    def test_url_arg_overrides_env_var(
        self, mock_client_cls, mock_check_cls, monkeypatch
    ):
        """--url argument takes precedence over DIRECTUS_URL env var."""
        monkeypatch.setenv("DIRECTUS_URL", "http://env-url.example.com")
        monkeypatch.setenv("DIRECTUS_TOKEN", "env-token")
        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--check", "--url", "http://arg-url.example.com"]
        )

        mock_check_instance = MagicMock()
        mock_check_cls.return_value = mock_check_instance

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_client_cls.assert_called_once_with(
            base_url="http://arg-url.example.com", token="env-token", verify_ssl=True
        )

    @patch("directus_ac.cli.CheckCommand")
    @patch("directus_ac.cli.DirectusClient")
    def test_token_arg_overrides_env_var(
        self, mock_client_cls, mock_check_cls, monkeypatch
    ):
        """--token argument takes precedence over DIRECTUS_TOKEN env var."""
        monkeypatch.setenv("DIRECTUS_URL", "http://env-url.example.com")
        monkeypatch.setenv("DIRECTUS_TOKEN", "env-token")
        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--check", "--token", "arg-token"]
        )

        mock_check_instance = MagicMock()
        mock_check_cls.return_value = mock_check_instance

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_client_cls.assert_called_once_with(
            base_url="http://env-url.example.com", token="arg-token", verify_ssl=True
        )

    def test_missing_url_no_arg_no_env_exits_1(self, monkeypatch, caplog):
        """Missing URL (no --url, no DIRECTUS_URL) exits code 1 with error to stderr."""
        monkeypatch.delenv("DIRECTUS_URL", raising=False)
        monkeypatch.setenv("DIRECTUS_TOKEN", "some-token")
        monkeypatch.setattr(sys, "argv", ["directus-ac", "--check"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        assert "URL" in caplog.text

    def test_missing_token_no_arg_no_env_exits_1(self, monkeypatch, caplog):
        """Missing token (no --token, no DIRECTUS_TOKEN) exits code 1 with error to stderr."""
        monkeypatch.setenv("DIRECTUS_URL", "http://example.com")
        monkeypatch.delenv("DIRECTUS_TOKEN", raising=False)
        monkeypatch.setattr(sys, "argv", ["directus-ac", "--check"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        assert "token" in caplog.text.lower()


class TestCheckModeErrorScenarios:
    """Unit tests for error scenarios when using --check mode.

    Validates: Requirements 1.6, 2.4, 3.4, 4.6, 6.1, 6.2, 6.3
    """

    def test_connection_error_exits_1_with_stderr(self, monkeypatch, caplog):
        """ConnectionError during --check exits with code 1 and writes error to stderr."""
        import logging
        from unittest.mock import patch

        from directus_ac.cli import main
        from directus_ac.exceptions import ConnectionError

        monkeypatch.setattr(
            "sys.argv",
            ["directus-ac", "--check", "--url", "http://unreachable.local", "--token", "t"],
        )

        with caplog.at_level(logging.ERROR):
            with patch(
                "directus_ac.cli.CheckCommand.run",
                side_effect=ConnectionError("Cannot reach Directus at http://unreachable.local: Connection refused"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        assert "Cannot reach Directus" in caplog.text
        assert "unreachable.local" in caplog.text

    def test_auth_error_exits_1_with_stderr(self, monkeypatch, caplog):
        """AuthError during --check exits with code 1 and writes error to stderr."""
        import logging
        from unittest.mock import patch

        from directus_ac.cli import main
        from directus_ac.exceptions import AuthError

        monkeypatch.setattr(
            "sys.argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "bad-token"],
        )

        with caplog.at_level(logging.ERROR):
            with patch(
                "directus_ac.cli.CheckCommand.run",
                side_effect=AuthError("Authentication failed. Verify your token."),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        assert "Authentication failed" in caplog.text

    def test_api_error_exits_1_with_stderr(self, monkeypatch, caplog):
        """APIError during --check exits with code 1 and writes error to stderr."""
        import logging
        from unittest.mock import patch

        from directus_ac.cli import main
        from directus_ac.exceptions import APIError

        monkeypatch.setattr(
            "sys.argv",
            ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"],
        )

        with caplog.at_level(logging.ERROR):
            with patch(
                "directus_ac.cli.CheckCommand.run",
                side_effect=APIError("HTTP 500 — Internal Server Error"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        assert "500" in caplog.text


class TestMutualExclusivity:
    """Unit tests for mutual exclusivity of --check and --update flags.

    Validates: Requirements 4.1, 4.2
    """

    def test_check_and_update_together_exits_2(self, monkeypatch, capsys):
        """--check and --update together exits with code 2, stderr contains 'not allowed'."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--update", "--url", "http://localhost", "--token", "t"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "not allowed" in captured.err


class TestNoFlagBehavior:
    """Unit tests for no-flag CLI behavior (prints help and exits 0).

    Validates: Requirements 1.1, 1.2, 1.3
    """

    def test_bare_invocation_exits_0_with_help(self, monkeypatch, capsys):
        """Bare invocation (no flags) exits 0 and prints help containing --check and --update."""
        monkeypatch.setattr(sys, "argv", ["directus-ac"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--check" in captured.out
        assert "--update" in captured.out

    def test_common_options_only_exits_0_with_help(self, monkeypatch, capsys):
        """Invocation with only common options (no mode flag) exits 0 and prints help."""
        monkeypatch.setattr(sys, "argv", ["directus-ac", "--config", "x.yaml"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--check" in captured.out
        assert "--update" in captured.out


class TestCreateRolesWithCheck:
    """Unit tests for --create-roles being ignored when --check is used.

    Validates: Requirements 5.2
    """

    @patch("directus_ac.cli.CheckCommand")
    @patch("directus_ac.cli.DirectusClient")
    def test_create_roles_with_check_runs_check_normally(
        self, mock_client_cls, mock_check_cls, monkeypatch
    ):
        """--check --create-roles: check runs normally, --create-roles has no effect on the check path."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--check", "--create-roles", "--url", "http://localhost", "--token", "t"],
        )

        mock_check_instance = MagicMock()
        mock_check_cls.return_value = mock_check_instance

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_client_cls.assert_called_once_with(base_url="http://localhost", token="t", verify_ssl=True)
        mock_check_cls.assert_called_once_with(client=mock_client_cls.return_value, enable_private_collections=False)
        mock_check_instance.run.assert_called_once()


class TestHelpTextContent:
    """Unit tests for help text content.

    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """

    def test_help_contains_update_description(self):
        """Help text includes a description of the --update flag."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--update" in help_text
        assert "Apply permissions" in help_text

    def test_help_contains_check_description(self):
        """Help text includes a description of the --check flag."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--check" in help_text
        assert "Read-only" in help_text

    def test_help_contains_config_description(self):
        """Help text includes a description of the --config option."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--config" in help_text

    def test_help_contains_url_description(self):
        """Help text includes a description of the --url option."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--url" in help_text
        assert "Directus base URL" in help_text

    def test_help_contains_token_description(self):
        """Help text includes a description of the --token option."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--token" in help_text
        assert "auth token" in help_text

    def test_help_contains_create_roles_description(self):
        """Help text includes a description of the --create-roles option."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--create-roles" in help_text
        assert "Create missing roles" in help_text

    def test_help_contains_epilog_one_mode_required(self):
        """Help text contains epilog indicating one mode is required."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "One of --check, --update, or --generate is required" in help_text


class TestGenerateFlagParsing:
    """Unit tests for --generate CLI argument parsing.

    Validates: Requirements 1.1, 1.4, 1.5, 1.8
    """

    def test_generate_flag_is_recognized(self):
        """--generate flag is recognized and sets args.generate to True."""
        parser = build_parser()
        args = parser.parse_args(["--generate", "--url", "http://localhost", "--token", "abc"])
        assert args.generate is True

    def test_generate_flag_defaults_to_false(self):
        """Without --generate, args.generate defaults to False."""
        parser = build_parser()
        args = parser.parse_args(["--url", "http://localhost", "--token", "abc"])
        assert args.generate is False

    def test_generate_mutually_exclusive_with_check(self, capsys):
        """--generate and --check together exits with code 2 (mutually exclusive)."""
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--generate", "--check", "--url", "http://localhost", "--token", "t"])
        assert exc_info.value.code == 2

    def test_generate_mutually_exclusive_with_update(self, capsys):
        """--generate and --update together exits with code 2 (mutually exclusive)."""
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--generate", "--update", "--url", "http://localhost", "--token", "t"])
        assert exc_info.value.code == 2

    def test_output_argument_accepted_with_generate(self):
        """--output argument is accepted when --generate is specified."""
        parser = build_parser()
        args = parser.parse_args([
            "--generate", "--url", "http://localhost", "--token", "t",
            "--output", "/tmp/output.yaml",
        ])
        assert args.output == "/tmp/output.yaml"

    def test_output_defaults_to_none(self):
        """--output defaults to None when not specified."""
        parser = build_parser()
        args = parser.parse_args(["--generate", "--url", "http://localhost", "--token", "t"])
        assert args.output is None

    def test_include_system_flag_accepted_with_generate(self):
        """--include-system flag is accepted when --generate is specified."""
        parser = build_parser()
        args = parser.parse_args([
            "--generate", "--url", "http://localhost", "--token", "t",
            "--include-system",
        ])
        assert args.include_system is True

    def test_include_system_defaults_to_false(self):
        """--include-system defaults to False when not specified."""
        parser = build_parser()
        args = parser.parse_args(["--generate", "--url", "http://localhost", "--token", "t"])
        assert args.include_system is False

    def test_epilog_mentions_generate(self):
        """Epilog text mentions --generate alongside --check and --update."""
        parser = build_parser()
        help_text = parser.format_help()
        assert "One of --check, --update, or --generate is required to perform an operation." in help_text


class TestUpdateFlag:
    """Unit tests for --update CLI flag behavior.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 5.1
    """

    @patch("directus_ac.cli.PermissionManager")
    @patch("directus_ac.cli.Validator")
    @patch("directus_ac.cli.DirectusClient")
    @patch("directus_ac.cli.load_config")
    def test_update_with_valid_credentials_executes_pipeline(
        self, mock_load_config, mock_client_cls, mock_validator_cls, mock_pm_cls, monkeypatch
    ):
        """--update with valid credentials runs the full pipeline and returns normally."""
        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--update", "--url", "http://localhost:8055", "--token", "t"]
        )

        mock_config = MagicMock()
        mock_config.collections = ["col1"]
        mock_config.roles = ["role1"]
        mock_config.custom_permissions = []
        mock_load_config.return_value = mock_config

        mock_validator = MagicMock()
        mock_validator.validate_roles.return_value = {"role1": "id1"}
        mock_validator_cls.return_value = mock_validator

        mock_client = MagicMock()
        mock_client.get_policies.return_value = []
        mock_client_cls.return_value = mock_client

        mock_pm = MagicMock()
        mock_pm.apply_permissions.return_value = (2, 1)
        mock_pm.apply_custom_permissions.return_value = (0, 0)
        mock_pm_cls.return_value = mock_pm

        # The update path returns normally on success (no sys.exit call)
        main()

        mock_load_config.assert_called_once_with("./directus_ac.yaml")
        mock_client_cls.assert_called_once_with(base_url="http://localhost:8055", token="t", verify_ssl=True)
        mock_validator.validate_collections.assert_called_once_with(["col1"])
        mock_validator.validate_roles.assert_called_once_with(
            ["role1"], False, mock_pm
        )
        mock_pm.apply_permissions.assert_called_once_with(mock_config, {"role1": "id1"})
        mock_validator.validate_custom_permissions.assert_called_once_with([], ["col1"])
        mock_pm.apply_custom_permissions.assert_called_once_with([], {})

    @patch("directus_ac.cli.load_config")
    def test_update_with_pipeline_error_exits_1(
        self, mock_load_config, monkeypatch, caplog
    ):
        """--update with a pipeline error exits with code 1 and logs the error."""
        import logging

        from directus_ac.exceptions import ConfigError

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--update", "--url", "http://localhost:8055", "--token", "t"]
        )
        mock_load_config.side_effect = ConfigError("Config file not found: ./directus_ac.yaml")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        assert "Config file not found" in caplog.text

    @patch("directus_ac.cli.PermissionManager")
    @patch("directus_ac.cli.Validator")
    @patch("directus_ac.cli.DirectusClient")
    @patch("directus_ac.cli.load_config")
    def test_update_with_create_roles_flag(
        self, mock_load_config, mock_client_cls, mock_validator_cls, mock_pm_cls, monkeypatch
    ):
        """--update --create-roles passes create_roles=True to validate_roles."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["directus-ac", "--update", "--create-roles", "--url", "http://localhost:8055", "--token", "t"],
        )

        mock_config = MagicMock()
        mock_config.collections = ["col1"]
        mock_config.roles = ["role1"]
        mock_config.custom_permissions = []
        mock_load_config.return_value = mock_config

        mock_validator = MagicMock()
        mock_validator.validate_roles.return_value = {"role1": "id1"}
        mock_validator_cls.return_value = mock_validator

        mock_client = MagicMock()
        mock_client.get_policies.return_value = []
        mock_client_cls.return_value = mock_client

        mock_pm = MagicMock()
        mock_pm.apply_permissions.return_value = (1, 0)
        mock_pm.apply_custom_permissions.return_value = (0, 0)
        mock_pm_cls.return_value = mock_pm

        # Should return normally (no SystemExit)
        main()

        # Verify create_roles=True was passed to validate_roles
        mock_validator.validate_roles.assert_called_once_with(
            ["role1"], True, mock_pm
        )


class TestGenerateWithCustomPermissions:
    """End-to-end tests for --generate with custom permissions.

    Validates: Requirements 4.1, 5.1, 6.1
    """

    @patch("directus_ac.cli.serialize_config")
    @patch("directus_ac.cli.Generator")
    @patch("directus_ac.cli.DirectusClient")
    def test_generate_includes_custom_permissions_in_output(
        self, mock_client_cls, mock_generator_cls, mock_serialize, monkeypatch, capsys
    ):
        """--generate with custom permissions in API produces YAML with custom_permissions section."""
        from directus_ac.models import (
            CustomPermissionEntry,
            DirectusACConfig,
            GroupDefinition,
            PermissionKeyword,
        )

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"]
        )

        # Build a config that includes custom permissions
        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                )
            ],
            custom_permissions=[
                CustomPermissionEntry(
                    name="UPDATE_C_1",
                    policy="editor — directus-ac",
                    collection="articles",
                    action="update",
                    validation={"_and": [{"status": {"_eq": "draft"}}]},
                    fields=["title", "body"],
                    permissions=None,
                )
            ],
        )

        mock_generator_instance = MagicMock()
        mock_generator_instance.generate.return_value = config
        mock_generator_cls.return_value = mock_generator_instance

        yaml_output = (
            "collections:\n- articles\nroles:\n- editor\ngroups:\n"
            "- collections:\n  - articles\n  permissions:\n    editor: READ\n"
            "custom_permissions:\n- name: UPDATE_C_1\n"
            "  policy: editor — directus-ac\n  collection: articles\n"
            "  action: update\n  validation:\n    _and:\n    - status:\n"
            "        _eq: draft\n  fields:\n  - title\n  - body\n"
        )
        mock_serialize.return_value = yaml_output

        main()

        captured = capsys.readouterr()
        assert "custom_permissions:" in captured.out
        assert "UPDATE_C_1" in captured.out
        assert "validation:" in captured.out
        mock_generator_instance.generate.assert_called_once()
        mock_serialize.assert_called_once_with(config)

    @patch("directus_ac.cli.serialize_config")
    @patch("directus_ac.cli.Generator")
    @patch("directus_ac.cli.DirectusClient")
    def test_generate_without_custom_permissions_omits_section(
        self, mock_client_cls, mock_generator_cls, mock_serialize, monkeypatch, capsys
    ):
        """--generate without custom permissions produces YAML without custom_permissions key."""
        from directus_ac.models import (
            DirectusACConfig,
            GroupDefinition,
            PermissionKeyword,
        )

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--generate", "--url", "http://localhost:8055", "--token", "t"]
        )

        config = DirectusACConfig(
            collections=["articles"],
            roles=["editor"],
            groups=[
                GroupDefinition(
                    collections=["articles"],
                    permissions={"editor": [PermissionKeyword.READ]},
                )
            ],
            custom_permissions=[],
        )

        mock_generator_instance = MagicMock()
        mock_generator_instance.generate.return_value = config
        mock_generator_cls.return_value = mock_generator_instance

        yaml_output = (
            "collections:\n- articles\nroles:\n- editor\ngroups:\n"
            "- collections:\n  - articles\n  permissions:\n    editor: READ\n"
        )
        mock_serialize.return_value = yaml_output

        main()

        captured = capsys.readouterr()
        assert "custom_permissions" not in captured.out


class TestUpdateWithCustomPermissions:
    """End-to-end tests for --update with custom permissions.

    Validates: Requirements 4.1, 5.1, 6.1
    """

    @patch("directus_ac.cli.PermissionManager")
    @patch("directus_ac.cli.Validator")
    @patch("directus_ac.cli.DirectusClient")
    @patch("directus_ac.cli.load_config")
    def test_update_calls_validate_and_apply_custom_permissions(
        self, mock_load_config, mock_client_cls, mock_validator_cls, mock_pm_cls, monkeypatch, caplog
    ):
        """--update with custom_permissions calls validate_custom_permissions and apply_custom_permissions."""
        import logging

        from directus_ac.models import CustomPermissionEntry, DirectusPolicy

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--update", "--url", "http://localhost:8055", "--token", "t"]
        )

        custom_perm = CustomPermissionEntry(
            name="UPDATE_C_1",
            policy="editor — directus-ac",
            collection="articles",
            action="update",
            validation={"_and": [{"status": {"_eq": "draft"}}]},
            fields=["title", "body"],
            permissions=None,
        )

        mock_config = MagicMock()
        mock_config.collections = ["articles"]
        mock_config.roles = ["editor"]
        mock_config.custom_permissions = [custom_perm]
        mock_load_config.return_value = mock_config

        mock_validator = MagicMock()
        mock_validator.validate_roles.return_value = {"editor": "role-id-1"}
        mock_validator_cls.return_value = mock_validator

        mock_client = MagicMock()
        mock_policy = MagicMock()
        mock_policy.name = "editor — directus-ac"
        mock_policy.id = "policy-id-1"
        mock_client.get_policies.return_value = [mock_policy]
        mock_client_cls.return_value = mock_client

        mock_pm = MagicMock()
        mock_pm.apply_permissions.return_value = (1, 0)
        mock_pm.apply_custom_permissions.return_value = (1, 0)
        mock_pm_cls.return_value = mock_pm

        with caplog.at_level(logging.INFO):
            main()

        # Verify validate_custom_permissions was called with the custom perms and collections
        mock_validator.validate_custom_permissions.assert_called_once_with(
            [custom_perm], ["articles"]
        )

        # Verify apply_custom_permissions was called with correct args
        mock_pm.apply_custom_permissions.assert_called_once_with(
            [custom_perm], {"editor — directus-ac": "policy-id-1"}
        )

    @patch("directus_ac.cli.PermissionManager")
    @patch("directus_ac.cli.Validator")
    @patch("directus_ac.cli.DirectusClient")
    @patch("directus_ac.cli.load_config")
    def test_update_summary_includes_custom_permission_counts(
        self, mock_load_config, mock_client_cls, mock_validator_cls, mock_pm_cls, monkeypatch, caplog
    ):
        """--update summary output includes custom permission created/updated counts."""
        import logging

        from directus_ac.models import CustomPermissionEntry

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--update", "--url", "http://localhost:8055", "--token", "t"]
        )

        custom_perms = [
            CustomPermissionEntry(
                name="UPDATE_C_1",
                policy="editor — directus-ac",
                collection="articles",
                action="update",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            ),
            CustomPermissionEntry(
                name="READ_C_2",
                policy="editor — directus-ac",
                collection="articles",
                action="read",
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ]

        mock_config = MagicMock()
        mock_config.collections = ["articles"]
        mock_config.roles = ["editor"]
        mock_config.custom_permissions = custom_perms
        mock_load_config.return_value = mock_config

        mock_validator = MagicMock()
        mock_validator.validate_roles.return_value = {"editor": "role-id-1"}
        mock_validator_cls.return_value = mock_validator

        mock_client = MagicMock()
        mock_policy = MagicMock()
        mock_policy.name = "editor — directus-ac"
        mock_policy.id = "policy-id-1"
        mock_client.get_policies.return_value = [mock_policy]
        mock_client_cls.return_value = mock_client

        mock_pm = MagicMock()
        mock_pm.apply_permissions.return_value = (2, 1)
        mock_pm.apply_custom_permissions.return_value = (2, 0)
        mock_pm_cls.return_value = mock_pm

        with caplog.at_level(logging.INFO):
            main()

        # Verify summary output includes custom permission counts
        assert "custom permissions created: 2" in caplog.text
        assert "custom permissions updated: 0" in caplog.text

    @patch("directus_ac.cli.PermissionManager")
    @patch("directus_ac.cli.Validator")
    @patch("directus_ac.cli.DirectusClient")
    @patch("directus_ac.cli.load_config")
    def test_update_with_custom_permissions_patch_existing(
        self, mock_load_config, mock_client_cls, mock_validator_cls, mock_pm_cls, monkeypatch, caplog
    ):
        """--update with existing custom permissions reports correct updated count."""
        import logging

        from directus_ac.models import CustomPermissionEntry

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--update", "--url", "http://localhost:8055", "--token", "t"]
        )

        custom_perms = [
            CustomPermissionEntry(
                name="UPDATE_C_1",
                policy="editor — directus-ac",
                collection="articles",
                action="update",
                validation={"_and": [{"status": {"_eq": "draft"}}]},
            ),
        ]

        mock_config = MagicMock()
        mock_config.collections = ["articles"]
        mock_config.roles = ["editor"]
        mock_config.custom_permissions = custom_perms
        mock_load_config.return_value = mock_config

        mock_validator = MagicMock()
        mock_validator.validate_roles.return_value = {"editor": "role-id-1"}
        mock_validator_cls.return_value = mock_validator

        mock_client = MagicMock()
        mock_policy = MagicMock()
        mock_policy.name = "editor — directus-ac"
        mock_policy.id = "policy-id-1"
        mock_client.get_policies.return_value = [mock_policy]
        mock_client_cls.return_value = mock_client

        mock_pm = MagicMock()
        mock_pm.apply_permissions.return_value = (0, 1)
        mock_pm.apply_custom_permissions.return_value = (0, 1)
        mock_pm_cls.return_value = mock_pm

        with caplog.at_level(logging.INFO):
            main()

        # Verify summary output includes updated count
        assert "custom permissions created: 0" in caplog.text
        assert "custom permissions updated: 1" in caplog.text


class TestCheckWithCustomPermissions:
    """End-to-end tests for --check with custom permissions display.

    Validates: Requirements 4.1, 5.1, 6.1
    """

    @patch("directus_ac.cli.CheckCommand")
    @patch("directus_ac.cli.DirectusClient")
    def test_check_displays_custom_permissions_section(
        self, mock_client_cls, mock_check_cls, monkeypatch
    ):
        """--check calls CheckCommand.run() which displays custom permissions."""
        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"]
        )

        mock_check_instance = MagicMock()
        mock_check_cls.return_value = mock_check_instance

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_check_instance.run.assert_called_once()

    @patch("directus_ac.cli.DirectusClient")
    def test_check_output_includes_custom_permissions_header(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check output includes 'Custom Permissions' section when custom permissions exist."""
        import logging

        from directus_ac.models import (
            DirectusCollection,
            DirectusPermission,
            DirectusPolicy,
            DirectusRole,
        )

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"]
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
                action="update",
                fields=["title", "body"],
                validation={"_and": [{"status": {"_eq": "draft"}}]},
                permissions=None,
            ),
        ]
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        # Custom permissions are now inline (no separate "Custom Permissions" section)
        assert "Custom Permissions" not in caplog.text
        assert "articles" in caplog.text
        # No indicators should be present - only the name is shown
        assert "UPDATE_C_1" in caplog.text
        assert "fields:" not in caplog.text
        assert "has validation" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_output_omits_custom_permissions_when_none_exist(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check output omits 'Custom Permissions' section when no custom permissions exist."""
        import logging

        from directus_ac.models import (
            DirectusCollection,
            DirectusPermission,
            DirectusPolicy,
            DirectusRole,
        )

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"]
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
                id=1,
                policy="policy-1",
                collection="articles",
                action="read",
                fields=None,
                validation=None,
                permissions=None,
            ),
        ]
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        assert "Custom Permissions" not in caplog.text

    @patch("directus_ac.cli.DirectusClient")
    def test_check_output_shows_item_permissions_indicator(
        self, mock_client_cls, monkeypatch, caplog
    ):
        """--check output shows 'has item permissions' indicator for custom permissions with item-level rules."""
        import logging

        from directus_ac.models import (
            DirectusCollection,
            DirectusPermission,
            DirectusPolicy,
            DirectusRole,
        )

        monkeypatch.setattr(
            sys, "argv", ["directus-ac", "--check", "--url", "http://localhost:8055", "--token", "t"]
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
                id=1,
                policy="policy-1",
                collection="articles",
                action="read",
                fields=None,
                validation=None,
                permissions={"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            ),
        ]
        mock_client_cls.return_value = mock_client

        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        # Custom permissions are now inline (no separate "Custom Permissions" section)
        assert "Custom Permissions" not in caplog.text
        # Only name is shown, no indicators
        assert "READ_C_1" in caplog.text
        assert "has item permissions" not in caplog.text


class TestGenerateErrorHandling:
    """Unit tests for error handling in the --generate CLI branch.

    Validates: Requirements 2.4, 2.5, 2.6, 5.6
    """

    @patch("directus_ac.cli.Generator")
    @patch("directus_ac.cli.DirectusClient")
    def test_file_write_failure_exits_1_with_error_message(
        self, mock_client_cls, mock_generator_cls, monkeypatch, capsys
    ):
        """File write failure (e.g., permission denied) exits with code 1 and prints error to stderr."""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "directus-ac",
                "--generate",
                "--url", "http://localhost:8055",
                "--token", "t",
                "--output", "/nonexistent/path/output.yaml",
            ],
        )

        mock_config = MagicMock()
        mock_generator_instance = MagicMock()
        mock_generator_instance.generate.return_value = mock_config
        mock_generator_cls.return_value = mock_generator_instance

        mock_serialize = MagicMock(return_value="collections: []\nroles: []\ngroups: []\n")

        with patch("directus_ac.cli.serialize_config", mock_serialize):
            with patch(
                "builtins.open",
                side_effect=OSError(13, "Permission denied"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "/nonexistent/path/output.yaml" in captured.err
        assert "Permission denied" in captured.err

    def test_auth_failure_from_client_exits_1(self, monkeypatch, caplog):
        """AuthError during --generate exits with code 1 and logs the error."""
        import logging

        from directus_ac.exceptions import AuthError

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "directus-ac",
                "--generate",
                "--url", "http://localhost:8055",
                "--token", "bad-token",
            ],
        )

        with caplog.at_level(logging.ERROR):
            with patch(
                "directus_ac.cli.DirectusClient",
            ) as mock_client_cls:
                mock_client = MagicMock()
                mock_client_cls.return_value = mock_client

                with patch(
                    "directus_ac.cli.Generator",
                ) as mock_generator_cls:
                    mock_generator_instance = MagicMock()
                    mock_generator_instance.generate.side_effect = AuthError(
                        "Authentication failed. Verify your token."
                    )
                    mock_generator_cls.return_value = mock_generator_instance

                    with pytest.raises(SystemExit) as exc_info:
                        main()

        assert exc_info.value.code == 1
        assert "Authentication failed" in caplog.text

    def test_connection_error_from_client_exits_1(self, monkeypatch, caplog):
        """ConnectionError during --generate exits with code 1 and logs the error."""
        import logging

        from directus_ac.exceptions import ConnectionError

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "directus-ac",
                "--generate",
                "--url", "http://unreachable.local",
                "--token", "t",
            ],
        )

        with caplog.at_level(logging.ERROR):
            with patch(
                "directus_ac.cli.DirectusClient",
            ) as mock_client_cls:
                mock_client = MagicMock()
                mock_client_cls.return_value = mock_client

                with patch(
                    "directus_ac.cli.Generator",
                ) as mock_generator_cls:
                    mock_generator_instance = MagicMock()
                    mock_generator_instance.generate.side_effect = ConnectionError(
                        "Cannot reach Directus at http://unreachable.local: Connection refused"
                    )
                    mock_generator_cls.return_value = mock_generator_instance

                    with pytest.raises(SystemExit) as exc_info:
                        main()

        assert exc_info.value.code == 1
        assert "Cannot reach Directus" in caplog.text
        assert "unreachable.local" in caplog.text
