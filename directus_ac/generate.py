"""Generate a DirectusACConfig from a running Directus instance.

This module provides the :class:`Generator` class that fetches collections,
roles, policies, and permissions from the Directus REST API and assembles them
into a :class:`~directus_ac.models.DirectusACConfig` object.

In Directus v11+, permissions are linked to Policies, which are linked to Roles.
The generator resolves this chain to produce a role-centric config.

It also provides :func:`serialize_config` for converting a config object into
a YAML string compatible with :func:`~directus_ac.config.load_config`.
"""
from __future__ import annotations

from collections import defaultdict

import yaml

from directus_ac.client import DirectusClient
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusACConfig,
    DirectusPermission,
    GroupDefinition,
    PermissionKeyword,
)

REVERSE_ACTION_MAP: dict[str, PermissionKeyword] = {
    "read": PermissionKeyword.READ,
    "create": PermissionKeyword.WRITE,
    "update": PermissionKeyword.UPDATE,
    "delete": PermissionKeyword.DELETE,
}

KEYWORD_ORDER: list[PermissionKeyword] = [
    PermissionKeyword.READ,
    PermissionKeyword.WRITE,
    PermissionKeyword.UPDATE,
    PermissionKeyword.DELETE,
]


def generate_permission_name(action: str, counter: int) -> str:
    """Generate a Permission_Name: {ACTION}_C_{COUNTER}.

    Parameters
    ----------
    action:
        The permission action string (e.g., "create", "read", "update", "delete").
        Will be uppercased in the output.
    counter:
        Global sequence number across all custom permissions, assigned by
        ascending Directus permission id.
    """
    return f"{action.upper()}_C_{counter}"


class Generator:
    """Fetches Directus state and builds a DirectusACConfig.

    Parameters
    ----------
    client:
        An authenticated :class:`DirectusClient` instance.
    include_system:
        When ``False`` (default), collections whose names start with
        ``directus_`` are excluded from the generated config.
    """

    def __init__(self, client: DirectusClient, include_system: bool = False) -> None:
        self._client = client
        self._include_system = include_system

    def _is_custom_permission(self, perm: DirectusPermission) -> bool:
        """Return True if the permission has non-default constraints.

        A permission is considered custom when:
        - ``validation`` is not None, OR
        - ``fields`` is not None and not equal to ``["*"]``, OR
        - ``permissions`` (item-level) is not None.

        Note: Duplicate detection (multiple entries sharing the same
        policy+collection+action triple) is handled separately in
        :meth:`_detect_custom_permission_ids`.
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

    def generate(self) -> DirectusACConfig:
        """Fetch data from Directus and build a DirectusACConfig.

        Steps:
        1. Fetch collections, roles, policies, permissions from client.
        2. Filter collections based on include_system flag.
        3. Build policy_id -> role_ids mapping and role_id -> name mapping.
        4. Classify permissions as custom or standard.
        5. Filter standard permissions: skip unknown policy IDs, skip excluded
           collections, skip unknown action strings.
        6. Group standard permissions by collection.
        7. For each collection group, build a GroupDefinition with per-role
           Permission_Sets.
        8. Collect custom permissions into CustomPermissionEntry list.
        9. Assemble and return DirectusACConfig.

        Returns an empty config (empty collections, roles, groups) if no
        permissions remain after filtering.
        """
        # Step 1: Fetch data from Directus
        collections = self._client.get_collections()
        roles = self._client.get_roles()
        policies = self._client.get_policies()
        permissions = self._client.get_permissions()

        # Step 2: Build set of allowed collection names
        allowed_collections: set[str] = set()
        for col in collections:
            if self._include_system or not col.collection.startswith("directus_"):
                allowed_collections.add(col.collection)

        # Step 3: Build mappings
        # policy_id -> list of role_ids (from both directions)
        policy_to_role_ids: dict[str, list[str]] = {}
        # From policy side: policy.roles
        for policy in policies:
            policy_to_role_ids[policy.id] = list(policy.roles)
        # From role side: role.policies (supplements missing policy.roles data)
        for role in roles:
            for policy_id in role.policies:
                if policy_id not in policy_to_role_ids:
                    policy_to_role_ids[policy_id] = []
                if role.id not in policy_to_role_ids[policy_id]:
                    policy_to_role_ids[policy_id].append(role.id)

        # role_id -> role_name
        role_id_to_name: dict[str, str] = {role.id: role.name for role in roles}

        # policy_id -> policy_name (for resolving custom permission policy names)
        policy_id_to_name: dict[str, str] = {p.id: p.name for p in policies}

        # Step 4: Classify permissions as custom or standard
        custom_permission_ids = self._detect_custom_permission_ids(permissions)

        # Step 5: Filter standard permissions and resolve to roles
        # Group by (collection, role_name) -> set of keywords
        collection_role_keywords: dict[str, dict[str, set[PermissionKeyword]]] = defaultdict(
            lambda: defaultdict(set)
        )

        for perm in permissions:
            # Skip custom permissions from standard grouping
            if perm.id in custom_permission_ids:
                continue

            # Resolve policy to role IDs
            role_ids = policy_to_role_ids.get(perm.policy, [])
            if not role_ids:
                continue

            # Skip permissions referencing excluded collections
            if perm.collection not in allowed_collections:
                continue

            # Skip permissions with unknown action strings
            keyword = REVERSE_ACTION_MAP.get(perm.action)
            if keyword is None:
                continue

            # Add to each role linked through this policy
            for role_id in role_ids:
                if role_id not in role_id_to_name:
                    continue
                role_name = role_id_to_name[role_id]
                collection_role_keywords[perm.collection][role_name].add(keyword)

        # Step 6: Collect custom permissions into CustomPermissionEntry list
        # Use a global counter (sorted by permission id ascending) to ensure uniqueness
        custom_perms_list = [perm for perm in permissions if perm.id in custom_permission_ids]
        custom_perms_list.sort(key=lambda p: p.id)

        custom_permission_entries: list[CustomPermissionEntry] = []
        # Track mapping from C_N name to (role_names, collection) for group population
        custom_ref_assignments: list[tuple[str, list[str], str]] = []  # (C_N, role_names, collection)

        counter = 0
        for perm in custom_perms_list:
            # Resolve policy ID to policy name; skip if unresolvable (Req 4.5)
            policy_name = policy_id_to_name.get(perm.policy)
            if policy_name is None:
                continue

            # Resolve policy to role(s); skip if no roles found (Req 4.5)
            role_ids = policy_to_role_ids.get(perm.policy, [])
            role_names = [
                role_id_to_name[rid]
                for rid in role_ids
                if rid in role_id_to_name
            ]
            if not role_names:
                continue

            counter += 1
            name = generate_permission_name(counter)
            entry = CustomPermissionEntry(
                name=name,
                policy=policy_name,
                collection=perm.collection,
                action=perm.action,
                validation=perm.validation,
                fields=perm.fields,
                permissions=perm.permissions,
            )
            custom_permission_entries.append(entry)
            custom_ref_assignments.append((name, role_names, perm.collection))

        # Step 7-8: Build groups and collect used collections/roles
        if not collection_role_keywords and not custom_permission_entries:
            # Return empty config if no permissions remain after filtering.
            # Use model_construct to bypass Pydantic validators that require
            # at least 1 item in each list.
            return DirectusACConfig.model_construct(
                collections=[], roles=[], groups=[], custom_permissions=[]
            )

        used_collections: list[str] = []
        used_roles: set[str] = set()
        groups: list[GroupDefinition] = []

        # Build a lookup from collection -> group index for populating custom refs
        collection_to_group_idx: dict[str, int] = {}

        for collection_name in sorted(collection_role_keywords.keys()):
            role_permissions = collection_role_keywords[collection_name]
            used_collections.append(collection_name)

            # Build permissions dict for this group
            permissions_dict: dict[str, list[PermissionKeyword]] = {}
            for role_name in sorted(role_permissions.keys()):
                keywords = role_permissions[role_name]
                # Sort keywords in canonical order
                ordered_keywords = [kw for kw in KEYWORD_ORDER if kw in keywords]
                permissions_dict[role_name] = ordered_keywords
                used_roles.add(role_name)

            groups.append(
                GroupDefinition(
                    collections=[collection_name],
                    permissions=permissions_dict,
                )
            )
            collection_to_group_idx[collection_name] = len(groups) - 1

        # Step 8: Populate custom_permission_refs on groups
        for ref_name, role_names, collection in custom_ref_assignments:
            # Skip collections not in allowed set
            if collection not in allowed_collections:
                continue

            if collection not in collection_to_group_idx:
                # Create a new group for this collection with empty standard permissions
                groups.append(
                    GroupDefinition(
                        collections=[collection],
                        permissions={},
                        custom_permission_refs={},
                    )
                )
                collection_to_group_idx[collection] = len(groups) - 1
                if collection not in used_collections:
                    used_collections.append(collection)

            group = groups[collection_to_group_idx[collection]]
            for role_name in role_names:
                used_roles.add(role_name)
                if role_name not in group.custom_permission_refs:
                    group.custom_permission_refs[role_name] = []
                group.custom_permission_refs[role_name].append(ref_name)

        used_collections.sort()

        # If we have custom permissions but no standard groups, we still need
        # a valid config structure
        if not groups and custom_permission_entries:
            return DirectusACConfig.model_construct(
                collections=used_collections,
                roles=sorted(used_roles),
                groups=[],
                custom_permissions=custom_permission_entries,
            )

        # Step 9: Assemble DirectusACConfig
        return DirectusACConfig(
            collections=used_collections,
            roles=sorted(used_roles),
            groups=groups,
            custom_permissions=custom_permission_entries,
        )


def serialize_config(config: DirectusACConfig) -> str:
    """Serialize a DirectusACConfig to a YAML string.

    Formatting rules:
    - Top-level keys in order: collections, roles, groups, custom_permissions.
    - Permission_Set values are space-separated strings (e.g., "READ WRITE C_1 C_2"),
      not YAML lists.
    - No leading/trailing whitespace in Permission_Set strings.
    - Keywords appear in canonical order: READ, WRITE, UPDATE, DELETE, followed
      by custom permission references (C_N) in their list order.
    - The custom_permissions section is included only when non-empty.

    The output is compatible with load_config(): parsing the output with
    load_config produces an equivalent DirectusACConfig.
    """
    # Build groups as plain dicts with Permission_Set strings
    groups_data: list[dict] = []
    for group in config.groups:
        permissions_data: dict[str, str] = {}

        # Collect all role names that appear in either permissions or custom_permission_refs
        all_roles = set(group.permissions.keys()) | set(group.custom_permission_refs.keys())

        for role_name in sorted(all_roles):
            # Standard keywords in canonical order
            keywords = group.permissions.get(role_name, [])
            ordered = [kw.value for kw in KEYWORD_ORDER if kw in keywords]

            # Append custom permission refs for this role
            custom_refs = group.custom_permission_refs.get(role_name, [])
            parts = ordered + custom_refs

            permissions_data[role_name] = " ".join(parts)

        groups_data.append({
            "collections": group.collections,
            "permissions": permissions_data,
        })

    # Build top-level dict with keys in canonical order
    data: dict = {
        "collections": config.collections,
        "roles": config.roles,
        "groups": groups_data,
    }

    # Add custom_permissions section only when non-empty
    if config.custom_permissions:
        custom_perms_data: list[dict] = []
        for entry in config.custom_permissions:
            entry_data: dict = {
                "name": entry.name,
                "policy": entry.policy,
                "collection": entry.collection,
                "action": entry.action,
            }
            # Only include optional attributes that are non-null and non-empty
            if entry.validation is not None and entry.validation != {}:
                entry_data["validation"] = entry.validation
            if entry.fields is not None and entry.fields != []:
                entry_data["fields"] = entry.fields
            if entry.permissions is not None and entry.permissions != {}:
                entry_data["permissions"] = entry.permissions
            custom_perms_data.append(entry_data)
        data["custom_permissions"] = custom_perms_data

    return yaml.dump(data, default_flow_style=False, sort_keys=False)
