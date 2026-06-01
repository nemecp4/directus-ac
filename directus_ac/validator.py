"""Validator — collection and role existence checks.

Queries the Directus API to verify that all collections and roles referenced
in the config file actually exist in the target Directus instance.  All
missing names are collected before raising so the user sees the full list in
a single error message.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from directus_ac.exceptions import ValidationError

if TYPE_CHECKING:
    from directus_ac.client import DirectusClient
    from directus_ac.models import CustomPermissionEntry


class Validator:
    """Validates that config-referenced collections and roles exist in Directus.

    Parameters
    ----------
    client:
        An initialised :class:`~directus_ac.client.DirectusClient` instance.
    """

    def __init__(self, client: "DirectusClient") -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Collection validation
    # ------------------------------------------------------------------

    def validate_collections(self, config_collections: list[str]) -> None:
        """Verify that every collection name in *config_collections* exists.

        Fetches the full list of collections from the Directus API and
        computes the set difference using **case-sensitive** exact matching.
        All missing names are collected before raising so the caller receives
        a single, complete error message.

        Parameters
        ----------
        config_collections:
            Collection names declared in the config file.

        Raises
        ------
        ValidationError
            When one or more collection names are not found in Directus.
            The message lists every missing name, one per line.
        APIError, AuthError, ConnectionError
            Propagated from the underlying HTTP client on network/API errors.
        """
        existing = {c.collection for c in self._client.get_collections()}
        missing = [name for name in config_collections if name not in existing]
        if missing:
            names_str = "\n".join(f"  - {name}" for name in missing)
            raise ValidationError(
                f"Collections not found in Directus:\n{names_str}",
                missing_names=missing,
            )

    # ------------------------------------------------------------------
    # Role validation
    # ------------------------------------------------------------------

    def validate_roles(
        self,
        config_roles: list[str],
        create_missing: bool,
        permission_manager: object,
    ) -> dict[str, str]:
        """Verify that every role name in *config_roles* exists in Directus.

        Fetches the full list of roles from the Directus API and computes the
        set difference using **case-sensitive** exact matching.

        - If *create_missing* is ``False`` and roles are missing, raises
          :class:`~directus_ac.exceptions.ValidationError` listing all missing
          role names.
        - If *create_missing* is ``True`` and roles are missing, delegates
          creation to ``permission_manager.create_role(name)`` for each
          missing role.

        Parameters
        ----------
        config_roles:
            Role names declared in the config file.
        create_missing:
            When ``True``, missing roles are created via *permission_manager*
            instead of raising an error.
        permission_manager:
            A :class:`~directus_ac.permissions.PermissionManager` instance
            (or any object with a ``create_role(name: str) -> str`` method).

        Returns
        -------
        dict[str, str]
            Mapping of ``role_name -> role_id`` for **all** config roles
            (both pre-existing and newly created).

        Raises
        ------
        ValidationError
            When *create_missing* is ``False`` and one or more role names are
            not found in Directus.
        APIError, AuthError, ConnectionError
            Propagated from the underlying HTTP client on network/API errors.
        """
        existing_roles = self._client.get_roles()
        existing_by_name: dict[str, str] = {r.name: r.id for r in existing_roles}

        missing = [name for name in config_roles if name not in existing_by_name]

        if missing and not create_missing:
            names_str = "\n".join(f"  - {name}" for name in missing)
            raise ValidationError(
                f"Roles not found in Directus:\n{names_str}",
                missing_names=missing,
            )

        # Create any missing roles when --create-roles is active.
        for name in missing:
            new_id = permission_manager.create_role(name)
            existing_by_name[name] = new_id

        # Return a mapping for every role referenced in the config.
        return {name: existing_by_name[name] for name in config_roles}

    # ------------------------------------------------------------------
    # Custom permissions validation
    # ------------------------------------------------------------------

    def validate_custom_permissions(
        self,
        custom_perms: list["CustomPermissionEntry"],
        config_collections: list[str],
    ) -> None:
        """Verify that custom permission entries reference valid policies and collections.

        Fetches the full list of policies from the Directus API and checks
        that every ``policy`` name in *custom_perms* matches an existing
        policy name.  Also checks that every ``collection`` in *custom_perms*
        is present in *config_collections*.

        All invalid references are collected before raising so the caller
        receives a single, complete error message.

        Parameters
        ----------
        custom_perms:
            Custom permission entries from the config file.
        config_collections:
            Collection names declared in the config file's top-level
            ``collections`` list.

        Raises
        ------
        ValidationError
            When one or more policy names are unresolvable or collection
            names are not in the config.  The message lists every invalid
            reference.
        APIError, AuthError, ConnectionError
            Propagated from the underlying HTTP client on network/API errors.
        """
        if not custom_perms:
            return

        # Fetch existing policies and build a set of known policy names.
        existing_policies = self._client.get_policies()
        known_policy_names: set[str] = {p.name for p in existing_policies}

        # Build a set of known collection names from the config.
        known_collections: set[str] = set(config_collections)

        # Collect all invalid references (deduplicated, preserving order).
        unknown_policies: list[str] = []
        seen_policies: set[str] = set()
        unknown_collections: list[str] = []
        seen_collections: set[str] = set()

        for entry in custom_perms:
            if entry.policy not in known_policy_names and entry.policy not in seen_policies:
                unknown_policies.append(entry.policy)
                seen_policies.add(entry.policy)
            if entry.collection not in known_collections and entry.collection not in seen_collections:
                unknown_collections.append(entry.collection)
                seen_collections.add(entry.collection)

        # Build a combined error message if any problems were found.
        messages: list[str] = []
        all_missing: list[str] = []

        if unknown_policies:
            policy_lines = "\n".join(f"  - {name}" for name in unknown_policies)
            messages.append(
                f"Custom permissions reference unknown policies:\n{policy_lines}"
            )
            all_missing.extend(unknown_policies)

        if unknown_collections:
            collection_lines = "\n".join(f"  - {col}" for col in unknown_collections)
            messages.append(
                f"Custom permissions reference unknown collections:\n{collection_lines}"
            )
            all_missing.extend(unknown_collections)

        if messages:
            raise ValidationError(
                "\n".join(messages),
                missing_names=all_missing,
            )
