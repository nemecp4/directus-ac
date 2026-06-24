"""Pydantic data models for directus_ac.

Covers:
- PermissionKeyword enum (READ, WRITE, UPDATE, DELETE)
- GroupDefinition: a group of collections with per-role permission sets
- DirectusACConfig: top-level config file schema with length/count validators
- DirectusRole, DirectusCollection, DirectusPermission: API response models
"""
from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, field_validator


class PermissionKeyword(str, Enum):
    """Valid permission action keywords used in the config file."""

    READ = "READ"
    WRITE = "WRITE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class GroupDefinition(BaseModel):
    """A logical group that maps a set of collections to per-role permission sets.

    Each key in ``permissions`` is a role name; the value is the list of
    :class:`PermissionKeyword` values that apply to every collection in
    ``collections``.

    The ``custom_permission_refs`` field maps role names to lists of custom
    permission reference names (e.g., ``UPDATE_C_1``, ``READ_C_2``) that are
    associated with that role for the collections in this group.
    """

    collections: list[str]
    permissions: dict[str, list[PermissionKeyword]]
    custom_permission_refs: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Shared validators used by DirectusACConfig
# ---------------------------------------------------------------------------

_MAX_ITEMS = 500
_MAX_NAME_LEN = 255


def _validate_name_list(values: list[str], field_label: str) -> list[str]:
    """Validate that a list of names satisfies count and length constraints."""
    if not (1 <= len(values) <= _MAX_ITEMS):
        raise ValueError(
            f"{field_label} must contain between 1 and {_MAX_ITEMS} items, "
            f"got {len(values)}"
        )
    for name in values:
        if not (1 <= len(name) <= _MAX_NAME_LEN):
            raise ValueError(
                f"Each {field_label} name must be between 1 and {_MAX_NAME_LEN} "
                f"characters; got {len(name)!r} characters for {name!r}"
            )
    return values


class CustomPermissionEntry(BaseModel):
    """A custom permission entry for the config file.

    Represents a permission with additional constraints (validation rules,
    field restrictions, or item-level permissions) that cannot be expressed
    in the standard groups section.
    """

    name: str  # Generated Permission_Name (e.g., UPDATE_C_1, READ_C_2)
    policy: str  # Policy name (human-readable)
    collection: str
    action: str  # "create", "read", "update", "delete"
    validation: dict | None = None
    fields: list[str] | None = None
    permissions: dict | None = None  # item-level permissions

    @field_validator("name")
    @classmethod
    def validate_name_pattern(cls, v: str) -> str:
        """Ensure name follows the ACTION_C_N pattern (e.g., UPDATE_C_1, READ_C_2)."""
        if not re.match(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$", v):
            raise ValueError(
                f"CustomPermissionEntry name must follow the ACTION_C_N pattern "
                f"(e.g., UPDATE_C_1, READ_C_2); got {v!r}"
            )
        return v


class DirectusACConfig(BaseModel):
    """Top-level schema for ``directus_ac.yaml``.

    Constraints (Requirements 7.1, 7.2, 7.3):
    - ``collections``: 1–500 items, each 1–255 characters
    - ``roles``: 1–500 items, each 1–255 characters
    - ``groups``: 1–500 items
    """

    collections: list[str]
    roles: list[str]
    groups: list[GroupDefinition]
    custom_permissions: list[CustomPermissionEntry] = []

    @field_validator("collections")
    @classmethod
    def validate_collections(cls, v: list[str]) -> list[str]:
        return _validate_name_list(v, "collections")

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        return _validate_name_list(v, "roles")

    @field_validator("groups")
    @classmethod
    def validate_groups(cls, v: list[GroupDefinition]) -> list[GroupDefinition]:
        if not (1 <= len(v) <= _MAX_ITEMS):
            raise ValueError(
                f"groups must contain between 1 and {_MAX_ITEMS} items, "
                f"got {len(v)}"
            )
        return v


# ---------------------------------------------------------------------------
# Directus REST API response models
# ---------------------------------------------------------------------------


class DirectusRole(BaseModel):
    """Represents a role returned by ``GET /roles``."""

    id: str
    name: str
    policies: list[str] = []  # Policy UUIDs linked to this role


class DirectusCollection(BaseModel):
    """Represents a collection returned by ``GET /collections``.

    The ``collection`` field is the collection's name and acts as its
    identifier in the Directus API.
    """

    collection: str


class DirectusPolicy(BaseModel):
    """Represents a policy returned by ``GET /policies``."""

    id: str
    name: str
    roles: list[str] = []  # Role UUIDs linked to this policy


class DirectusPermission(BaseModel):
    """Represents a permission entry returned by ``GET /permissions``."""

    id: int
    policy: str      # Policy UUID
    collection: str
    action: str      # "read", "create", "update", "delete"
    fields: list[str] | None = None
    validation: dict | None = None
    permissions: dict | None = None  # item-level permissions
