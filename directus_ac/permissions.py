"""Permission Manager for directus_ac.

Handles role creation, policy management, and permission application
(create/update) against the Directus REST API (v11+).

In Directus v11, permissions are linked to Policies, which are then linked
to Roles. This module manages the Role → Policy → Permission chain.
"""
from __future__ import annotations

import logging

from directus_ac.client import DirectusClient
from directus_ac.exceptions import APIError
from directus_ac.models import CustomPermissionEntry, DirectusACConfig

logger = logging.getLogger(__name__)

ACTION_MAP: dict[str, str] = {
    "READ": "read",
    "WRITE": "create",
    "UPDATE": "update",
    "DELETE": "delete",
}


class PermissionManager:
    """Manages role creation, policy resolution, and permission application.

    Parameters
    ----------
    client:
        An authenticated :class:`DirectusClient` instance.
    """

    def __init__(self, client: DirectusClient) -> None:
        self._client = client

    def create_role(self, name: str) -> str:
        """Create a role in Directus and return its ID.

        Parameters
        ----------
        name:
            Human-readable role name.

        Returns
        -------
        str
            The UUID of the newly created role.

        Raises
        ------
        APIError
            If the Directus API returns an error.
        """
        role = self._client.create_role(name)
        logger.info("Created role: %s", name)
        return role.id

    def resolve_policies(
        self, role_name_to_id: dict[str, str]
    ) -> dict[str, str]:
        """Resolve or create a policy for each role.

        For each role, looks for an existing policy linked to that role.
        If none exists, creates a new policy named after the role.

        Parameters
        ----------
        role_name_to_id:
            Mapping of role names to their Directus UUIDs.

        Returns
        -------
        dict[str, str]
            Mapping of role_id to policy_id.
        """
        existing_policies = self._client.get_policies()

        # Build role_id -> policy_id from existing policies
        role_id_to_policy_id: dict[str, str] = {}
        for policy in existing_policies:
            for role_id in policy.roles:
                if role_id not in role_id_to_policy_id:
                    role_id_to_policy_id[role_id] = policy.id

        # Create policies for roles that don't have one
        id_to_name = {v: k for k, v in role_name_to_id.items()}
        for role_name, role_id in role_name_to_id.items():
            if role_id not in role_id_to_policy_id:
                policy = self._client.create_policy(
                    name=f"{role_name} — directus-ac",
                    role_id=role_id,
                )
                role_id_to_policy_id[role_id] = policy.id
                logger.info("Created policy for role: %s", role_name)

        return role_id_to_policy_id

    def apply_permissions(
        self,
        config: DirectusACConfig,
        role_name_to_id: dict[str, str],
    ) -> tuple[int, int]:
        """Apply all permissions from config to the Directus instance.

        Resolves policies for each role, fetches existing permissions, builds
        an in-memory index, then creates or updates each permission triple
        derived from the config groups.

        Parameters
        ----------
        config:
            The parsed configuration containing group definitions.
        role_name_to_id:
            Mapping of role names to their Directus UUIDs.

        Returns
        -------
        tuple[int, int]
            ``(created_count, updated_count)``

        Raises
        ------
        APIError
            If the Directus API returns an error while applying a permission.
            The error message includes the role, collection, and action that
            failed.
        """
        # Resolve policies for each role
        role_id_to_policy_id = self.resolve_policies(role_name_to_id)

        # Fetch all existing permissions and build lookup index
        existing_permissions = self._client.get_permissions()
        index: dict[tuple[str, str, str], int] = {}
        for perm in existing_permissions:
            key = (perm.policy, perm.collection, perm.action)
            index[key] = perm.id

        created_count = 0
        updated_count = 0

        # Expand groups into (policy_id, collection, action) triples and apply
        for group in config.groups:
            for collection in group.collections:
                for role_name, keywords in group.permissions.items():
                    role_id = role_name_to_id[role_name]
                    policy_id = role_id_to_policy_id[role_id]
                    for keyword in keywords:
                        action = ACTION_MAP[keyword.value]
                        lookup_key = (policy_id, collection, action)

                        try:
                            if lookup_key in index:
                                permission_id = index[lookup_key]
                                self._client.update_permission(
                                    permission_id, policy_id, collection, action
                                )
                                updated_count += 1
                            else:
                                self._client.create_permission(
                                    policy_id, collection, action
                                )
                                created_count += 1
                        except APIError as exc:
                            raise APIError(
                                f"Failed to apply permission for role "
                                f"'{role_name}', collection '{collection}', "
                                f"action '{action}': {exc}"
                            ) from exc

        return (created_count, updated_count)

    def apply_custom_permissions(
        self,
        custom_perms: list[CustomPermissionEntry],
        policy_name_to_id: dict[str, str],
    ) -> tuple[int, int]:
        """Apply custom permissions from config to the Directus instance.

        Resolves policy names to IDs, fetches existing permissions to determine
        whether to create or update, then applies each custom permission entry.

        Parameters
        ----------
        custom_perms:
            List of custom permission entries from the config.
        policy_name_to_id:
            Mapping of policy names to their Directus UUIDs.

        Returns
        -------
        tuple[int, int]
            ``(created_count, updated_count)``

        Raises
        ------
        APIError
            If a policy name cannot be resolved, or if the Directus API
            returns an error while applying a custom permission.
        """
        if not custom_perms:
            return (0, 0)

        # Fetch existing permissions and build index for matching
        # Match by (policy_id, collection, action) where the existing entry
        # has non-null constraints (validation, fields, or permissions)
        existing_permissions = self._client.get_permissions()
        custom_index: dict[tuple[str, str, str], int] = {}
        for perm in existing_permissions:
            has_constraints = (
                perm.validation is not None
                or (perm.fields is not None and perm.fields != ["*"])
                or perm.permissions is not None
            )
            if has_constraints:
                key = (perm.policy, perm.collection, perm.action)
                custom_index[key] = perm.id

        created_count = 0
        updated_count = 0

        for entry in custom_perms:
            # Resolve policy name to ID
            policy_id = policy_name_to_id.get(entry.policy)
            if policy_id is None:
                raise APIError(
                    f"Cannot resolve policy '{entry.policy}' for custom "
                    f"permission '{entry.name}'"
                )

            lookup_key = (policy_id, entry.collection, entry.action)

            try:
                if lookup_key in custom_index:
                    # Update existing custom permission
                    permission_id = custom_index[lookup_key]
                    self._client.update_permission(
                        permission_id,
                        policy_id,
                        entry.collection,
                        entry.action,
                        validation=entry.validation,
                        fields=entry.fields,
                        permissions=entry.permissions,
                    )
                    updated_count += 1
                else:
                    # Create new custom permission
                    self._client.create_permission(
                        policy_id,
                        entry.collection,
                        entry.action,
                        validation=entry.validation,
                        fields=entry.fields,
                        permissions=entry.permissions,
                    )
                    created_count += 1
            except APIError as exc:
                raise APIError(
                    f"Failed to apply custom permission '{entry.name}' "
                    f"(collection '{entry.collection}', action "
                    f"'{entry.action}'): {exc}"
                ) from exc

        return (created_count, updated_count)
