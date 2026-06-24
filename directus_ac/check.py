"""Read-only inspection of a Directus instance's access control state.

The :class:`CheckCommand` fetches collections, roles, policies, and permissions
from a Directus instance and prints a structured summary to stdout without
modifying any data.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from directus_ac.client import DirectusClient
from directus_ac.generate import generate_permission_name
from directus_ac.models import (
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)

logger = logging.getLogger(__name__)


class CheckCommand:
    """Read-only inspection of a Directus instance's access control state."""

    def __init__(self, client: DirectusClient, enable_private_collections: bool = False) -> None:
        self._client = client
        self._enable_private_collections = enable_private_collections

    def run(self) -> None:
        """Fetch and print collections, roles, and permissions."""
        collections = self._client.get_collections()
        roles = self._client.get_roles()
        policies = self._client.get_policies()
        permissions = self._client.get_permissions()

        logger.info(self._format_collections(collections))
        logger.info(self._format_roles(roles))
        logger.info(self._format_policies(permissions, policies, roles))

    def _format_collections(self, collections: list[DirectusCollection]) -> str:
        """Format the collections section.

        Returns a "Collections" header followed by one collection name per line,
        or "  No collections found" if the list is empty.

        When ``self._enable_private_collections`` is False (default), collections
        whose ``collection`` field starts with ``directus_`` are excluded.
        """
        lines: list[str] = ["Collections"]

        if not self._enable_private_collections:
            collections = [
                col for col in collections if not col.collection.startswith("directus_")
            ]

        if not collections:
            lines.append("  No collections found")
        else:
            for col in collections:
                lines.append(f"  {col.collection}")
        return "\n".join(lines)

    def _format_roles(self, roles: list[DirectusRole]) -> str:
        """Format the roles section.

        Returns a "Roles" header followed by one line per role with name and id
        separated by a space, or "  No roles found" if the list is empty.
        """
        lines: list[str] = ["Roles"]
        if not roles:
            lines.append("  No roles found")
        else:
            for role in roles:
                lines.append(f"  {role.name} {role.id}")
        return "\n".join(lines)

    def _format_custom_ref(self, name: str, perm: DirectusPermission) -> str:
        """Format a single custom permission reference.

        Returns only the permission name (e.g., 'UPDATE_C_3').
        """
        return name

    def _format_policies(
        self,
        permissions: list[DirectusPermission],
        policies: list[DirectusPolicy],
        roles: list[DirectusRole],
    ) -> str:
        """Format the policies section, grouped by role then by policy.

        Permissions are grouped by policy, then resolved to roles via the
        policy→role mapping. Role UUIDs are resolved to human-readable names.
        Policy UUIDs are resolved to human-readable policy names.
        If a UUID cannot be resolved, it is displayed as-is.

        Custom permissions are displayed inline alongside standard actions
        with indicators for fields, validation, and item permissions.

        Output structure:
            Policies
              RoleName
                PolicyName
                  collection: action1, action2, C_1 fields:(title,body), C_2 has validation
        """
        lines: list[str] = ["Policies"]
        if not permissions:
            lines.append("  No policies found")
            return "\n".join(lines)

        # Build policy_id -> role_ids mapping (from both directions)
        policy_to_roles: dict[str, list[str]] = {}
        # From policy side: policy.roles
        for policy in policies:
            policy_to_roles[policy.id] = list(policy.roles)
        # From role side: role.policies (supplements missing policy.roles data)
        for role in roles:
            for policy_id in role.policies:
                if policy_id not in policy_to_roles:
                    policy_to_roles[policy_id] = []
                if role.id not in policy_to_roles[policy_id]:
                    policy_to_roles[policy_id].append(role.id)

        # Build policy name lookup map
        policy_map: dict[str, str] = {policy.id: policy.name for policy in policies}

        # Build role name lookup map
        role_map: dict[str, str] = {role.id: role.name for role in roles}

        # Detect custom permissions and assign C_N names
        custom_ids = self._detect_custom_permission_ids(permissions)
        # Build a mapping from permission id -> C_N name (sorted by id ascending)
        custom_name_map: dict[int, str] = {}
        if custom_ids:
            custom_perms_sorted = sorted(
                [p for p in permissions if p.id in custom_ids],
                key=lambda p: p.id,
            )
            for counter, perm in enumerate(custom_perms_sorted, start=1):
                custom_name_map[perm.id] = generate_permission_name(perm.action, counter)

        # Build a lookup from permission id -> DirectusPermission for custom perms
        perm_by_id: dict[int, DirectusPermission] = {p.id: p for p in permissions}

        # Filter out permissions for private collections when not enabled
        if not self._enable_private_collections:
            filtered_permissions = [
                perm for perm in permissions
                if not perm.collection.startswith("directus_")
            ]
        else:
            filtered_permissions = permissions

        # Track all roles that had permissions (before filtering) so we can
        # still display them even if all their permissions were filtered out
        all_role_ids_with_permissions: list[str] = []
        for perm in permissions:
            role_ids = policy_to_roles.get(perm.policy, [])
            if not role_ids:
                role_ids = [perm.policy]
            for role_id in role_ids:
                if role_id not in all_role_ids_with_permissions:
                    all_role_ids_with_permissions.append(role_id)

        # Group filtered permissions by role and then by policy
        # role_id -> { policy_id -> { collection -> [perm_id, ...] } }
        grouped: dict[str, dict[str, dict[str, list[int]]]] = {}
        for perm in filtered_permissions:
            role_ids = policy_to_roles.get(perm.policy, [])
            if not role_ids:
                # If policy has no linked roles, group under the policy ID as role
                role_ids = [perm.policy]
            for role_id in role_ids:
                if role_id not in grouped:
                    grouped[role_id] = {}
                if perm.policy not in grouped[role_id]:
                    grouped[role_id][perm.policy] = {}
                if perm.collection not in grouped[role_id][perm.policy]:
                    grouped[role_id][perm.policy][perm.collection] = []
                grouped[role_id][perm.policy][perm.collection].append(perm.id)

        # Format output preserving insertion order
        # First output roles that have remaining permissions
        for role_id, role_policies in grouped.items():
            role_name = role_map.get(role_id, role_id)
            lines.append(f"  {role_name}")
            for policy_id, collections in role_policies.items():
                policy_name = policy_map.get(policy_id, policy_id)
                lines.append(f"    {policy_name}")
                for collection, perm_ids in collections.items():
                    # Separate standard actions from custom permission references
                    standard_actions: list[str] = []
                    custom_refs: list[str] = []
                    for pid in perm_ids:
                        if pid in custom_name_map:
                            perm_obj = perm_by_id[pid]
                            ref_str = self._format_custom_ref(
                                custom_name_map[pid], perm_obj
                            )
                            custom_refs.append(ref_str)
                        else:
                            perm_obj = perm_by_id[pid]
                            standard_actions.append(perm_obj.action)

                    # Build the comma-separated list: standard actions first, then custom refs
                    all_parts = standard_actions + custom_refs
                    actions_str = ", ".join(all_parts)
                    lines.append(f"      {collection}: {actions_str}")

        # Then output roles that had permissions but all were filtered out
        for role_id in all_role_ids_with_permissions:
            if role_id not in grouped:
                role_name = role_map.get(role_id, role_id)
                lines.append(f"  {role_name}")

        return "\n".join(lines)

    def _is_custom_permission(self, perm: DirectusPermission) -> bool:
        """Return True if the permission has non-default constraints.

        A permission is considered custom when:
        - ``validation`` is not None, OR
        - ``fields`` is not None and not equal to ``["*"]``, OR
        - ``permissions`` (item-level) is not None.
        """
        if perm.validation is not None:
            return True
        if perm.fields is not None and perm.fields != ["*"]:
            return True
        if perm.permissions is not None:
            return True
        return False

    def _detect_custom_permission_ids(
        self, permissions: list[DirectusPermission]
    ) -> set[int]:
        """Return the set of permission IDs that should be treated as custom.

        A permission is custom if:
        1. It has non-default constraints (per :meth:`_is_custom_permission`), OR
        2. It shares a (policy, collection, action) triple with at least one
           other permission entry — in which case ALL entries in that triple
           are marked as custom.
        """
        custom_ids: set[int] = set()

        # First pass: mark permissions with non-default constraints
        for perm in permissions:
            if self._is_custom_permission(perm):
                custom_ids.add(perm.id)

        # Second pass: detect duplicates by (policy, collection, action) triple
        triple_groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for perm in permissions:
            triple = (perm.policy, perm.collection, perm.action)
            triple_groups[triple].append(perm.id)

        # If multiple entries share the same triple, mark ALL as custom
        for triple, ids in triple_groups.items():
            if len(ids) > 1:
                custom_ids.update(ids)

        return custom_ids


