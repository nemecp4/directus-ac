"""YAML config loading and validation for directus_ac.

Provides :func:`load_config` which reads a YAML file, validates its structure,
parses Permission_Set strings, and returns a :class:`~directus_ac.models.DirectusACConfig`.

All failures raise :class:`~directus_ac.exceptions.ConfigError` with a
human-readable message suitable for writing to stderr.
"""
from __future__ import annotations

import os
import re
from typing import Any

import yaml

from directus_ac.exceptions import ConfigError
from directus_ac.models import (
    CustomPermissionEntry,
    DirectusACConfig,
    GroupDefinition,
    PermissionKeyword,
)

# Required top-level keys in the config file.
_REQUIRED_KEYS = ("collections", "roles", "groups")

# Valid keyword strings for quick membership tests.
_VALID_KEYWORDS: frozenset[str] = frozenset(kw.value for kw in PermissionKeyword)

# Pattern for custom permission references (e.g., CREATE_C_1, READ_C_2).
_CUSTOM_REF_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z]+_C_\d+$")

# Valid action values for custom permissions (case-insensitive).
_VALID_ACTIONS: frozenset[str] = frozenset(("create", "read", "update", "delete"))

# Limits for custom permissions.
_MAX_CUSTOM_PERMISSIONS = 500
_MAX_FIELD_LEN = 255
_MIN_FIELD_LEN = 1

# Required fields for each custom permission entry.
_CUSTOM_PERMISSION_REQUIRED_FIELDS = ("name", "policy", "collection", "action")


def _parse_permission_set(
    raw: Any,
    role: str,
    collection: str,
) -> tuple[list[PermissionKeyword], list[str]]:
    """Parse a space-separated Permission_Set string into keywords and custom refs.

    Steps (per design doc §Permission_Set Parsing):
    1. Strip leading/trailing whitespace.
    2. Split on whitespace.
    3. Classify each token as a standard keyword (READ, WRITE, UPDATE, DELETE)
       or a custom permission reference (matching ``C_\\d+`` pattern).
    4. Deduplicate while preserving first-seen order within each category.

    Returns:
        A tuple of (keywords, custom_refs) where keywords is a deduplicated list
        of :class:`PermissionKeyword` values and custom_refs is a deduplicated
        list of custom permission reference strings (e.g., ["C_1", "C_2"]).

    Raises:
        ConfigError: If any token is neither a valid keyword nor a custom ref.
    """
    if not isinstance(raw, str):
        raw = str(raw)

    tokens = raw.strip().split()
    seen_keywords: dict[str, PermissionKeyword] = {}
    seen_refs: dict[str, str] = {}
    for token in tokens:
        upper = token.upper()
        if upper in _VALID_KEYWORDS:
            if upper not in seen_keywords:
                seen_keywords[upper] = PermissionKeyword(upper)
        elif _CUSTOM_REF_PATTERN.match(token):
            if token not in seen_refs:
                seen_refs[token] = token
        else:
            raise ConfigError(
                f"Invalid permission keyword '{token}' for role '{role}' on collection '{collection}'"
            )
    return list(seen_keywords.values()), list(seen_refs.values())


def _parse_groups(raw_groups: Any) -> list[GroupDefinition]:
    """Validate and parse the raw ``groups`` list from the YAML document.

    Raises:
        ConfigError: If any group is missing ``collections`` or ``permissions``,
            or if a Permission_Set value contains an invalid keyword.
    """
    if not isinstance(raw_groups, list):
        raise ConfigError("'groups' must be a list")

    groups: list[GroupDefinition] = []
    for idx, group in enumerate(raw_groups):
        if not isinstance(group, dict):
            raise ConfigError(f"Group at index {idx} is missing key: collections")

        # Check for required group keys.
        for key in ("collections", "permissions"):
            if key not in group:
                raise ConfigError(f"Group at index {idx} is missing key: {key}")

        raw_permissions: Any = group["permissions"]
        if not isinstance(raw_permissions, dict):
            raise ConfigError(f"Group at index {idx} is missing key: permissions")

        # Parse each role's Permission_Set string.
        parsed_permissions: dict[str, list[PermissionKeyword]] = {}
        parsed_custom_refs: dict[str, list[str]] = {}
        for role, perm_value in raw_permissions.items():
            # Determine a representative collection name for error messages.
            raw_collections = group.get("collections", [])
            collection_label = (
                raw_collections[0]
                if isinstance(raw_collections, list) and raw_collections
                else str(raw_collections)
            )
            keywords, custom_refs = _parse_permission_set(
                perm_value, role=str(role), collection=collection_label
            )
            parsed_permissions[role] = keywords
            if custom_refs:
                parsed_custom_refs[role] = custom_refs

        groups.append(
            GroupDefinition(
                collections=group["collections"],
                permissions=parsed_permissions,
                custom_permission_refs=parsed_custom_refs,
            )
        )

    return groups


def _parse_custom_permissions(raw: Any) -> list[CustomPermissionEntry]:
    """Validate and parse the raw ``custom_permissions`` value from the YAML document.

    Args:
        raw: The value associated with the ``custom_permissions`` key, or None
            if the key was absent.

    Returns:
        A list of validated :class:`CustomPermissionEntry` instances.

    Raises:
        ConfigError: If the value is not a list, exceeds 500 entries, or any
            entry is missing required fields, has invalid action, or violates
            field length constraints.
    """
    if raw is None:
        return []

    if not isinstance(raw, list):
        raise ConfigError("custom_permissions must be a list")

    if len(raw) > _MAX_CUSTOM_PERMISSIONS:
        raise ConfigError(
            f"custom_permissions must contain at most {_MAX_CUSTOM_PERMISSIONS} entries, "
            f"got {len(raw)}"
        )

    entries: list[CustomPermissionEntry] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConfigError(
                f"Custom permission at index {idx} is missing required field: name"
            )

        # Check required fields.
        for field in _CUSTOM_PERMISSION_REQUIRED_FIELDS:
            if field not in entry:
                raise ConfigError(
                    f"Custom permission at index {idx} is missing required field: {field}"
                )

        # Validate field lengths for string fields.
        for field in _CUSTOM_PERMISSION_REQUIRED_FIELDS:
            value = entry[field]
            if not isinstance(value, str):
                raise ConfigError(
                    f"Custom permission at index {idx} is missing required field: {field}"
                )
            if not (_MIN_FIELD_LEN <= len(value) <= _MAX_FIELD_LEN):
                raise ConfigError(
                    f"Custom permission at index {idx}: field '{field}' must be "
                    f"between {_MIN_FIELD_LEN} and {_MAX_FIELD_LEN} characters, "
                    f"got {len(value)}"
                )

        # Validate name matches ACTION_C_\d+ pattern.
        if not _CUSTOM_REF_PATTERN.match(entry["name"]):
            raise ConfigError(
                f"Custom permission at index {idx} has invalid name "
                f"'{entry['name']}'. Must match pattern ACTION_C_N (e.g., UPDATE_C_1, READ_C_2)"
            )

        # Validate action value (case-insensitive).
        action_value = entry["action"].lower()
        if action_value not in _VALID_ACTIONS:
            raise ConfigError(
                f"Custom permission at index {idx} has invalid action "
                f"'{entry['action']}'. Must be one of: create, read, update, delete"
            )

        # Build the entry with normalized action.
        entries.append(
            CustomPermissionEntry(
                name=entry["name"],
                policy=entry["policy"],
                collection=entry["collection"],
                action=action_value,
                validation=entry.get("validation"),
                fields=entry.get("fields"),
                permissions=entry.get("permissions"),
            )
        )

    return entries


def load_config(path: str) -> DirectusACConfig:
    """Read the YAML file at *path*, validate it, and return a :class:`DirectusACConfig`.

    Args:
        path: Filesystem path to the ``directus_ac.yaml`` config file.

    Returns:
        A fully validated :class:`DirectusACConfig` instance.

    Raises:
        ConfigError: On any of the following conditions:

        - The file does not exist (message: ``Config file not found: <resolved_path>``).
        - The file contains invalid YAML syntax
          (message: ``YAML parse error at line <L>, column <C>: <msg>``).
        - The document is missing required top-level keys
          (message: ``Missing required keys: <key1>, <key2>``).
        - A group definition is missing ``collections`` or ``permissions``
          (message: ``Group at index <N> is missing key: <key>``).
        - A Permission_Set value contains an invalid keyword
          (message: ``Invalid permission keyword '<kw>' for role '<role>' on collection '<col>'``).
    """
    resolved = os.path.abspath(path)

    # --- 1. Read the file ---------------------------------------------------
    try:
        with open(resolved, encoding="utf-8") as fh:
            raw_text = fh.read()
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {resolved}")

    # --- 2. Parse YAML -------------------------------------------------------
    try:
        document: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        # Extract line/column from the mark if available.
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1   # yaml uses 0-based lines
            column = mark.column + 1
            problem = getattr(exc, "problem", str(exc))
            raise ConfigError(
                f"YAML parse error at line {line}, column {column}: {problem}"
            ) from exc
        raise ConfigError(f"YAML parse error: {exc}") from exc

    if not isinstance(document, dict):
        raise ConfigError("Missing required keys: collections, roles, groups")

    # --- 3. Check for required top-level keys --------------------------------
    missing = [key for key in _REQUIRED_KEYS if key not in document]
    if missing:
        raise ConfigError(f"Missing required keys: {', '.join(missing)}")

    # --- 4. Parse groups (validates Permission_Set tokens) -------------------
    groups = _parse_groups(document["groups"])

    # --- 5. Parse custom_permissions (optional) -----------------------------
    custom_permissions = _parse_custom_permissions(document.get("custom_permissions"))

    # --- 6. Build and return the validated config ----------------------------
    return DirectusACConfig(
        collections=document["collections"],
        roles=document["roles"],
        groups=groups,
        custom_permissions=custom_permissions,
    )
