"""Tests for --ignore-ssl and --verbose CLI argument parsing."""

import logging
from unittest.mock import patch, MagicMock

import pytest

from directus_ac.cli import build_parser, main
from directus_ac.client import DirectusClient


class TestIgnoreSslFlagParsing:
    """Unit tests for --ignore-ssl CLI argument parsing.

    Validates: Requirements 1.1, 1.3
    """

    def test_ignore_ssl_flag_sets_true(self):
        """--ignore-ssl flag sets args.ignore_ssl to True."""
        parser = build_parser()
        args = parser.parse_args(["--ignore-ssl", "--url", "http://localhost", "--token", "abc"])
        assert args.ignore_ssl is True

    def test_ignore_ssl_defaults_to_false(self):
        """Without --ignore-ssl, args.ignore_ssl defaults to False."""
        parser = build_parser()
        args = parser.parse_args(["--url", "http://localhost", "--token", "abc"])
        assert args.ignore_ssl is False


class TestVerboseFlagParsing:
    """Unit tests for --verbose CLI argument parsing.

    Validates: Requirements 2.1
    """

    def test_verbose_flag_sets_true(self):
        """--verbose flag sets args.verbose to True."""
        parser = build_parser()
        args = parser.parse_args(["--verbose", "--url", "http://localhost", "--token", "abc"])
        assert args.verbose is True

    def test_verbose_defaults_to_false(self):
        """Without --verbose, args.verbose defaults to False."""
        parser = build_parser()
        args = parser.parse_args(["--url", "http://localhost", "--token", "abc"])
        assert args.verbose is False


class TestCombinedFlagsParsing:
    """Unit tests for combined --ignore-ssl and --verbose usage.

    Validates: Requirements 3.1, 3.2
    """

    def test_both_flags_together(self):
        """Both --ignore-ssl and --verbose together sets both to True."""
        parser = build_parser()
        args = parser.parse_args([
            "--ignore-ssl", "--verbose",
            "--url", "http://localhost",
            "--token", "abc",
        ])
        assert args.ignore_ssl is True
        assert args.verbose is True

    def test_both_flags_work_alongside_other_arguments(self):
        """Both flags work alongside --check, --url, and --token."""
        parser = build_parser()
        args = parser.parse_args([
            "--ignore-ssl",
            "--verbose",
            "--check",
            "--url", "http://example.com:8055",
            "--token", "my-secret-token",
        ])
        assert args.ignore_ssl is True
        assert args.verbose is True
        assert args.check is True
        assert args.url == "http://example.com:8055"
        assert args.token == "my-secret-token"


class TestDirectusClientVerifySsl:
    """Unit tests verifying DirectusClient passes verify to httpx.Client.

    Validates: Requirements 1.2, 1.3
    """

    def test_verify_false_when_verify_ssl_false(self):
        """httpx.Client is called with verify=False when verify_ssl=False."""
        with patch("directus_ac.client.httpx.Client") as mock_client:
            DirectusClient(base_url="http://localhost", token="t", verify_ssl=False)
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["verify"] is False

    def test_verify_true_by_default(self):
        """httpx.Client is called with verify=True when verify_ssl is not specified."""
        with patch("directus_ac.client.httpx.Client") as mock_client:
            DirectusClient(base_url="http://localhost", token="t")
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["verify"] is True

    def test_verify_true_when_verify_ssl_true(self):
        """httpx.Client is called with verify=True when verify_ssl=True explicitly."""
        with patch("directus_ac.client.httpx.Client") as mock_client:
            DirectusClient(base_url="http://localhost", token="t", verify_ssl=True)
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs["verify"] is True


class TestSslWarningLogging:
    """Unit tests verifying SSL warning is logged when --ignore-ssl is active.

    Validates: Requirements 1.4
    """

    def test_ssl_warning_logged_when_ignore_ssl_active(self, caplog):
        """SSL warning is emitted at WARNING level when --ignore-ssl is provided."""
        with patch("directus_ac.cli.DirectusClient"), \
             patch("directus_ac.cli.CheckCommand") as mock_check:
            mock_check.return_value.run.return_value = None
            with patch(
                "sys.argv",
                ["directus_ac", "--ignore-ssl", "--check", "--url", "http://localhost", "--token", "t"],
            ):
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(SystemExit):
                        main()
        assert "SSL certificate verification is disabled." in caplog.text

    def test_no_ssl_warning_when_ignore_ssl_absent(self, caplog):
        """No SSL warning is emitted when --ignore-ssl is not provided."""
        with patch("directus_ac.cli.DirectusClient"), \
             patch("directus_ac.cli.CheckCommand") as mock_check:
            mock_check.return_value.run.return_value = None
            with patch(
                "sys.argv",
                ["directus_ac", "--check", "--url", "http://localhost", "--token", "t"],
            ):
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(SystemExit):
                        main()
        assert "SSL certificate verification is disabled." not in caplog.text


class TestVerboseLogging:
    """Unit tests verifying logging level and format change when --verbose is active.

    Validates: Requirements 2.2, 2.3, 2.4, 2.5
    """

    def _reset_root_logger(self):
        """Remove all handlers from root logger to ensure test isolation."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(logging.WARNING)

    def test_verbose_sets_debug_level_and_verbose_format(self):
        """When --verbose is provided, root logger level is DEBUG and format includes levelname and name."""
        self._reset_root_logger()
        try:
            with patch("directus_ac.cli.DirectusClient"), \
                 patch("directus_ac.cli.CheckCommand") as mock_check:
                mock_check.return_value.run.return_value = None
                with patch(
                    "sys.argv",
                    ["directus_ac", "--verbose", "--check", "--url", "http://localhost", "--token", "t"],
                ):
                    with pytest.raises(SystemExit):
                        main()
            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG
            # Verify the format includes levelname and name
            assert len(root_logger.handlers) > 0
            handler = root_logger.handlers[0]
            assert "%(levelname)s" in handler.formatter._fmt
            assert "%(name)s" in handler.formatter._fmt
        finally:
            self._reset_root_logger()

    def test_no_verbose_keeps_info_level_and_plain_format(self):
        """When --verbose is not provided, root logger level is INFO and format is plain message."""
        self._reset_root_logger()
        try:
            with patch("directus_ac.cli.DirectusClient"), \
                 patch("directus_ac.cli.CheckCommand") as mock_check:
                mock_check.return_value.run.return_value = None
                with patch(
                    "sys.argv",
                    ["directus_ac", "--check", "--url", "http://localhost", "--token", "t"],
                ):
                    with pytest.raises(SystemExit):
                        main()
            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO
            # Verify the format is plain message only
            assert len(root_logger.handlers) > 0
            handler = root_logger.handlers[0]
            assert handler.formatter._fmt == "%(message)s"
        finally:
            self._reset_root_logger()
