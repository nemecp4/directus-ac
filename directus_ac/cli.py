"""CLI argument parsing and pipeline orchestration for directus_ac."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from directus_ac.check import CheckCommand
from directus_ac.client import DirectusClient
from directus_ac.config import load_config
from directus_ac.exceptions import DirectusACError
from directus_ac.generate import Generator, serialize_config
from directus_ac.permissions import PermissionManager
from directus_ac.validator import Validator

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser for directus_ac.

    Arguments
    ---------
    --config : str
        Path to the YAML config file. Default: ``./directus_ac.yaml``.
    --url : str
        Directus base URL. Overrides the ``DIRECTUS_URL`` environment variable.
    --token : str
        Directus auth token. Overrides the ``DIRECTUS_TOKEN`` environment variable.
    --create-roles : flag
        When set, missing roles are created instead of raising an error.
    """
    parser = argparse.ArgumentParser(
        description="Manage Directus access control permissions declaratively.",
        epilog="One of --check, --update, or --generate is required to perform an operation.",
    )

    parser.add_argument(
        "--config",
        default="./directus_ac.yaml",
        help="Path to the YAML config file (default: ./directus_ac.yaml)",
    )

    parser.add_argument(
        "--url",
        default=None,
        help="Directus base URL (overrides DIRECTUS_URL env var)",
    )

    parser.add_argument(
        "--token",
        default=None,
        help="Directus auth token (overrides DIRECTUS_TOKEN env var)",
    )

    parser.add_argument(
        "--create-roles",
        action="store_true",
        default=False,
        help="Create missing roles instead of failing",
    )

    parser.add_argument(
        "--ignore-ssl",
        action="store_true",
        default=False,
        help="Disable SSL certificate verification for HTTPS connections",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable debug-level logging output",
    )

    # Mutually exclusive mode group
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Read-only: display current collections, roles, and permissions",
    )
    mode.add_argument(
        "--update",
        action="store_true",
        default=False,
        help="Apply permissions from config to the Directus instance",
    )
    mode.add_argument(
        "--generate",
        action="store_true",
        default=False,
        help="Generate a config file from the current Directus state",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="File path for generated YAML (used with --generate)",
    )

    parser.add_argument(
        "--include-system",
        action="store_true",
        default=False,
        help="Include system collections (used with --generate)",
    )

    parser.add_argument(
        "--enable-private-collections",
        action="store_true",
        default=False,
        help="Include directus_ system collections in --check output",
    )

    return parser


def main() -> None:
    """Entry point. Parses args, runs pipeline, exits with appropriate code."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.check and not args.update and not args.generate:
        parser.print_help()
        sys.exit(0)

    # Configure logging based on verbosity
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s:%(name)s: %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )

    if args.ignore_ssl:
        logger.warning("SSL certificate verification is disabled.")

    try:
        # Resolve Directus URL
        url = args.url or os.environ.get("DIRECTUS_URL")
        if not url:
            logger.error(
                "Error: Directus URL must be provided via --url or DIRECTUS_URL"
            )
            sys.exit(1)

        # Resolve Directus token
        token = args.token or os.environ.get("DIRECTUS_TOKEN")
        if not token:
            logger.error(
                "Error: Auth token must be provided via --token or DIRECTUS_TOKEN"
            )
            sys.exit(1)

        # --check path: read-only inspection, skip config loading
        if args.check:
            client = DirectusClient(base_url=url, token=token, verify_ssl=not args.ignore_ssl)
            check_cmd = CheckCommand(
                client=client,
                enable_private_collections=args.enable_private_collections,
            )
            check_cmd.run()
            sys.exit(0)

        elif args.update:
            # Load and validate config
            config = load_config(args.config)

            # Instantiate components
            client = DirectusClient(base_url=url, token=token, verify_ssl=not args.ignore_ssl)
            validator = Validator(client=client)
            permission_manager = PermissionManager(client=client)

            # Validate collections
            validator.validate_collections(config.collections)

            # Validate roles
            role_name_to_id = validator.validate_roles(
                config.roles, args.create_roles, permission_manager
            )

            # Validate custom permissions
            validator.validate_custom_permissions(
                config.custom_permissions, config.collections
            )

            # Apply permissions
            created, updated = permission_manager.apply_permissions(
                config, role_name_to_id
            )

            # Apply custom permissions
            policies = client.get_policies()
            policy_name_to_id = {p.name: p.id for p in policies}
            custom_created, custom_updated = (
                permission_manager.apply_custom_permissions(
                    config.custom_permissions, policy_name_to_id
                )
            )

            # Print summary
            logger.info(
                "Applied permissions: %d created, %d updated.", created, updated
            )
            logger.info(
                "custom permissions created: %d, custom permissions updated: %d",
                custom_created,
                custom_updated,
            )

        elif args.generate:
            client = DirectusClient(base_url=url, token=token, verify_ssl=not args.ignore_ssl)
            generator = Generator(client, include_system=args.include_system)
            config = generator.generate()
            yaml_str = serialize_config(config)

            if args.output:
                try:
                    with open(args.output, "w") as f:
                        f.write(yaml_str)
                except OSError as exc:
                    print(
                        f"Error: Could not write to '{args.output}': {exc.strerror}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            else:
                sys.stdout.write(yaml_str)

    except DirectusACError as exc:
        logger.error("%s", exc)
        sys.exit(1)
