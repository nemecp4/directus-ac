"""Directus HTTP client.

Wraps ``httpx`` to provide a typed interface to the Directus REST API.
All HTTP errors are translated into domain-specific exceptions from
:mod:`directus_ac.exceptions`.

Note: ``ConnectionError`` here refers to the custom exception defined in
``exceptions.py``, not Python's built-in ``ConnectionError``.
"""
from __future__ import annotations

from typing import Any

import httpx

from directus_ac.exceptions import (
    APIError,
    AuthError,
)
from directus_ac.exceptions import ConnectionError as DirectusConnectionError
from directus_ac.models import (
    DirectusCollection,
    DirectusPermission,
    DirectusPolicy,
    DirectusRole,
)


class DirectusClient:
    """Synchronous HTTP client for the Directus REST API.

    Parameters
    ----------
    base_url:
        Base URL of the Directus instance, e.g. ``https://directus.example.com``.
    token:
        Static auth token (Directus admin or user token).
    verify_ssl:
        Whether to verify SSL certificates. Defaults to ``True``.
    """

    def __init__(self, base_url: str, token: str, *, verify_ssl: bool = True) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            verify=verify_ssl,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request and return the parsed JSON body.

        Raises
        ------
        DirectusConnectionError
            On network-level failures (connection refused, DNS, timeout).
        AuthError
            On HTTP 401 or 403.
        APIError
            On any other non-2xx HTTP response.
        """
        url = f"{self._base_url}{path}"
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json,
            )
        except httpx.ConnectError as exc:
            raise DirectusConnectionError(
                f"Cannot reach Directus at {url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise DirectusConnectionError(
                f"Cannot reach Directus at {url}: request timed out"
            ) from exc
        except httpx.TransportError as exc:
            # Catches remaining transport-level errors (e.g. DNS failures
            # that surface as a generic TransportError on some platforms).
            raise DirectusConnectionError(
                f"Cannot reach Directus at {url}: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise AuthError("Authentication failed. Verify your token.")

        if not response.is_success:
            # Try to extract a detail message from the Directus error envelope.
            try:
                body = response.json()
                detail = (
                    body.get("errors", [{}])[0].get("message", response.text)
                    if isinstance(body, dict)
                    else response.text
                )
            except Exception:
                detail = response.text
            raise APIError(
                f"HTTP {response.status_code} — {detail}"
            )

        return response.json()

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_collections(self) -> list[DirectusCollection]:
        """Fetch all collections from ``GET /collections``.

        Returns
        -------
        list[DirectusCollection]
            All collections available in the Directus instance.

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        body = self._request("GET", "/collections")
        return [DirectusCollection(collection=item["collection"]) for item in body["data"]]

    def get_roles(self) -> list[DirectusRole]:
        """Fetch all roles from ``GET /roles``.

        Requests nested ``policies.policy`` to resolve the many-to-many
        junction table (directus_access) into actual policy UUIDs.

        Returns
        -------
        list[DirectusRole]

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        body = self._request(
            "GET", "/roles", params={"limit": -1, "fields": "id,name,policies.policy"}
        )
        results = []
        for item in body["data"]:
            # Normalize policies: API may return list of objects like [{"policy": "uuid"}]
            raw_policies = item.get("policies") or []
            if raw_policies and isinstance(raw_policies[0], dict):
                policy_ids = [
                    r.get("policy", r.get("id", ""))
                    for r in raw_policies
                    if r.get("policy") or r.get("id")
                ]
            else:
                policy_ids = raw_policies
            results.append(DirectusRole(id=item["id"], name=item["name"], policies=policy_ids))
        return results

    def create_role(self, name: str) -> DirectusRole:
        """Create a new role via ``POST /roles``.

        Parameters
        ----------
        name:
            Human-readable role name.

        Returns
        -------
        DirectusRole
            The newly created role including its assigned UUID.

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        body = self._request("POST", "/roles", json={"name": name})
        return DirectusRole(**body["data"])

    def get_permissions(self) -> list[DirectusPermission]:
        """Fetch all permissions from ``GET /permissions?limit=-1``.

        Requests extended fields (validation, fields, permissions) to support
        custom permission detection.  Filters out permissions with null policy
        values (system/admin permissions not linked to any policy).

        Returns
        -------
        list[DirectusPermission]

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        body = self._request(
            "GET",
            "/permissions",
            params={
                "limit": -1,
                "fields": "id,policy,collection,action,fields,validation,permissions",
            },
        )
        results = []
        for item in body["data"]:
            # Skip permissions without a policy (system/admin permissions)
            if not item.get("policy"):
                continue
            results.append(DirectusPermission(
                id=item["id"],
                policy=item["policy"],
                collection=item["collection"],
                action=item["action"],
                fields=item.get("fields"),
                validation=item.get("validation"),
                permissions=item.get("permissions"),
            ))
        return results

    def create_permission(
        self, policy_id: str, collection: str, action: str,
        *,
        validation: dict | None = None,
        fields: list[str] | None = None,
        permissions: dict | None = None,
    ) -> DirectusPermission:
        """Create a new permission via ``POST /permissions``.

        Parameters
        ----------
        policy_id:
            UUID of the policy.
        collection:
            Collection name.
        action:
            Directus action string: ``"read"``, ``"create"``, ``"update"``, or ``"delete"``.
        validation:
            Optional validation rules for the permission.
        fields:
            Optional field-level restrictions.
        permissions:
            Optional item-level permission rules.

        Returns
        -------
        DirectusPermission

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        payload: dict[str, Any] = {
            "policy": policy_id,
            "collection": collection,
            "action": action,
        }
        if validation is not None:
            payload["validation"] = validation
        if fields is not None:
            payload["fields"] = fields
        if permissions is not None:
            payload["permissions"] = permissions
        body = self._request(
            "POST",
            "/permissions",
            json=payload,
        )
        return DirectusPermission(**body["data"])

    def update_permission(
        self, permission_id: int, policy_id: str, collection: str, action: str,
        *,
        validation: dict | None = None,
        fields: list[str] | None = None,
        permissions: dict | None = None,
    ) -> DirectusPermission:
        """Update an existing permission via ``PATCH /permissions/{id}``.

        Parameters
        ----------
        permission_id:
            Numeric ID of the permission to update.
        policy_id:
            UUID of the policy.
        collection:
            Collection name.
        action:
            Directus action string.
        validation:
            Optional validation rules for the permission.
        fields:
            Optional field-level restrictions.
        permissions:
            Optional item-level permission rules.

        Returns
        -------
        DirectusPermission

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        payload: dict[str, Any] = {
            "policy": policy_id,
            "collection": collection,
            "action": action,
        }
        if validation is not None:
            payload["validation"] = validation
        if fields is not None:
            payload["fields"] = fields
        if permissions is not None:
            payload["permissions"] = permissions
        body = self._request(
            "PATCH",
            f"/permissions/{permission_id}",
            json=payload,
        )
        return DirectusPermission(**body["data"])

    # ------------------------------------------------------------------
    # Policy methods (Directus v11+)
    # ------------------------------------------------------------------

    def get_policies(self) -> list[DirectusPolicy]:
        """Fetch all policies from ``GET /policies``.

        Requests nested ``roles.role`` to resolve the many-to-many junction
        table into actual role UUIDs.

        Returns
        -------
        list[DirectusPolicy]

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        body = self._request(
            "GET",
            "/policies",
            params={"limit": -1, "fields": "id,name,roles.role"},
        )
        results = []
        for item in body["data"]:
            # Normalize roles: API returns list of objects like [{"role": "uuid"}]
            raw_roles = item.get("roles") or []
            if raw_roles and isinstance(raw_roles[0], dict):
                roles = [r.get("role", r.get("id", "")) for r in raw_roles if r.get("role") or r.get("id")]
            else:
                roles = raw_roles
            results.append(DirectusPolicy(id=item["id"], name=item["name"], roles=roles))
        return results

    def create_policy(self, name: str, role_id: str) -> DirectusPolicy:
        """Create a new policy linked to a role via ``POST /policies``.

        Parameters
        ----------
        name:
            Human-readable policy name.
        role_id:
            UUID of the role to link this policy to.

        Returns
        -------
        DirectusPolicy
            The newly created policy including its assigned UUID.

        Raises
        ------
        DirectusConnectionError, AuthError, APIError
        """
        body = self._request(
            "POST",
            "/policies",
            json={"name": name, "roles": [role_id]},
        )
        data = body["data"]
        # Normalize roles field: may come back as list of UUIDs or objects
        roles = data.get("roles", [])
        if roles and isinstance(roles[0], dict):
            roles = [r.get("role", r.get("id", "")) for r in roles]
        return DirectusPolicy(id=data["id"], name=data["name"], roles=roles)
