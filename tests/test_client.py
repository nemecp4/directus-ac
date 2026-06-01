"""Tests for client.py — DirectusClient HTTP wrapper (unit tests with mock transport).

Uses httpx's MockTransport to simulate API responses without a live Directus instance.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from directus_ac.client import DirectusClient
from directus_ac.exceptions import APIError, AuthError
from directus_ac.exceptions import ConnectionError as DirectusConnectionError
from directus_ac.models import DirectusCollection, DirectusPermission, DirectusRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler) -> DirectusClient:
    """Return a DirectusClient whose underlying httpx.Client uses a mock transport."""
    client = DirectusClient(base_url="https://directus.example.com", token="test-token")
    # Replace the internal httpx.Client with one backed by the mock transport.
    client._client = httpx.Client(
        base_url="https://directus.example.com",
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        transport=httpx.MockTransport(handler),
    )
    return client


def _json_response(data: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        content=json.dumps(data).encode(),
    )


# ---------------------------------------------------------------------------
# Task 5.1 — __init__ and shared request logic
# ---------------------------------------------------------------------------


class TestHeaders:
    """Authorization and Content-Type headers are sent on every request."""

    def test_authorization_header_sent(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": []})

        client = _make_client(handler)
        client.get_roles()

        assert len(captured) == 1
        assert captured[0].headers["Authorization"] == "Bearer test-token"

    def test_content_type_header_sent(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": []})

        client = _make_client(handler)
        client.get_roles()

        assert captured[0].headers["Content-Type"] == "application/json"


class TestConnectionErrors:
    """Network-level failures are wrapped in DirectusConnectionError."""

    def test_connect_error_raises_connection_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = _make_client(handler)
        with pytest.raises(DirectusConnectionError, match="Cannot reach Directus"):
            client.get_collections()

    def test_timeout_raises_connection_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _make_client(handler)
        with pytest.raises(DirectusConnectionError, match="Cannot reach Directus"):
            client.get_collections()

    def test_transport_error_raises_connection_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TransportError("DNS failure")

        client = _make_client(handler)
        with pytest.raises(DirectusConnectionError, match="Cannot reach Directus"):
            client.get_collections()

    def test_connection_error_message_contains_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = _make_client(handler)
        with pytest.raises(DirectusConnectionError) as exc_info:
            client.get_collections()
        assert "directus.example.com" in str(exc_info.value)


class TestAuthErrors:
    """HTTP 401 and 403 are wrapped in AuthError."""

    def test_401_raises_auth_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Unauthorized"}]}, status_code=401)

        client = _make_client(handler)
        with pytest.raises(AuthError):
            client.get_collections()

    def test_403_raises_auth_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Forbidden"}]}, status_code=403)

        client = _make_client(handler)
        with pytest.raises(AuthError):
            client.get_roles()

    def test_auth_error_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({}, status_code=401)

        client = _make_client(handler)
        with pytest.raises(AuthError, match="Authentication failed"):
            client.get_collections()


class TestAPIErrors:
    """Non-2xx responses (other than 401/403) are wrapped in APIError."""

    def test_500_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {"errors": [{"message": "Internal Server Error"}]}, status_code=500
            )

        client = _make_client(handler)
        with pytest.raises(APIError, match="500"):
            client.get_collections()

    def test_404_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Not Found"}]}, status_code=404)

        client = _make_client(handler)
        with pytest.raises(APIError, match="404"):
            client.get_roles()

    def test_api_error_includes_detail(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {"errors": [{"message": "Something went wrong"}]}, status_code=500
            )

        client = _make_client(handler)
        with pytest.raises(APIError, match="Something went wrong"):
            client.get_collections()


# ---------------------------------------------------------------------------
# Task 5.2 — API methods
# ---------------------------------------------------------------------------


class TestGetCollections:
    """get_collections() parses the data[].collection field."""

    def test_returns_list_of_collections(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [
                        {"collection": "articles", "meta": {}, "schema": {}},
                        {"collection": "comments", "meta": {}, "schema": {}},
                    ]
                }
            )

        client = _make_client(handler)
        result = client.get_collections()

        assert len(result) == 2
        assert all(isinstance(c, DirectusCollection) for c in result)
        assert result[0].collection == "articles"
        assert result[1].collection == "comments"

    def test_empty_collections(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"data": []})

        client = _make_client(handler)
        result = client.get_collections()
        assert result == []

    def test_uses_get_method(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": []})

        client = _make_client(handler)
        client.get_collections()
        assert captured[0].method == "GET"
        assert "/collections" in str(captured[0].url)

    def test_api_error_on_non_2xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Server error"}]}, status_code=500)

        client = _make_client(handler)
        with pytest.raises(APIError):
            client.get_collections()


class TestGetRoles:
    """get_roles() uses limit=-1&fields=id,name,policies.policy and parses into DirectusRole list."""

    def test_returns_list_of_roles(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [
                        {"id": "uuid-1", "name": "Editor", "policies": [{"policy": "pol-1"}]},
                        {"id": "uuid-2", "name": "Viewer", "policies": []},
                    ]
                }
            )

        client = _make_client(handler)
        result = client.get_roles()

        assert len(result) == 2
        assert all(isinstance(r, DirectusRole) for r in result)
        assert result[0].id == "uuid-1"
        assert result[0].name == "Editor"
        assert result[0].policies == ["pol-1"]
        assert result[1].policies == []

    def test_sends_limit_and_fields_params(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": []})

        client = _make_client(handler)
        client.get_roles()

        url_str = str(captured[0].url)
        assert "limit=-1" in url_str
        assert "policies.policy" in url_str

    def test_api_error_on_non_2xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Forbidden"}]}, status_code=500)

        client = _make_client(handler)
        with pytest.raises(APIError):
            client.get_roles()


class TestCreateRole:
    """create_role() POSTs {"name": name} and returns a DirectusRole."""

    def test_returns_created_role(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"data": {"id": "new-uuid", "name": "Admin"}}, status_code=200)

        client = _make_client(handler)
        result = client.create_role("Admin")

        assert isinstance(result, DirectusRole)
        assert result.id == "new-uuid"
        assert result.name == "Admin"

    def test_sends_post_with_name(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": {"id": "x", "name": "MyRole"}})

        client = _make_client(handler)
        client.create_role("MyRole")

        req = captured[0]
        assert req.method == "POST"
        assert "/roles" in str(req.url)
        body = json.loads(req.content)
        assert body == {"name": "MyRole"}

    def test_api_error_on_non_2xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Conflict"}]}, status_code=409)

        client = _make_client(handler)
        with pytest.raises(APIError):
            client.create_role("Duplicate")


class TestGetPermissions:
    """get_permissions() uses limit=-1&fields=id,policy,collection,action."""

    def test_returns_list_of_permissions(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [
                        {
                            "id": 1,
                            "policy": "policy-uuid-1",
                            "collection": "articles",
                            "action": "read",
                            "permissions": {},
                            "validation": {},
                            "presets": {},
                            "fields": ["*"],
                        },
                        {
                            "id": 2,
                            "policy": "policy-uuid-1",
                            "collection": "articles",
                            "action": "create",
                            "permissions": {},
                            "validation": {},
                            "presets": {},
                            "fields": ["*"],
                        },
                    ]
                }
            )

        client = _make_client(handler)
        result = client.get_permissions()

        assert len(result) == 2
        assert all(isinstance(p, DirectusPermission) for p in result)
        assert result[0].id == 1
        assert result[0].policy == "policy-uuid-1"
        assert result[0].collection == "articles"
        assert result[0].action == "read"

    def test_skips_permissions_with_null_policy(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [
                        {
                            "id": 1,
                            "policy": "policy-uuid-1",
                            "collection": "articles",
                            "action": "read",
                        },
                        {
                            "id": 2,
                            "policy": None,
                            "collection": "directus_users",
                            "action": "read",
                        },
                    ]
                }
            )

        client = _make_client(handler)
        result = client.get_permissions()

        assert len(result) == 1
        assert result[0].policy == "policy-uuid-1"

    def test_sends_limit_and_fields_params(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response({"data": []})

        client = _make_client(handler)
        client.get_permissions()

        url_str = str(captured[0].url)
        assert "limit=-1" in url_str
        assert "fields=" in url_str
        # Verify all required fields are requested
        for field in ("id", "policy", "collection", "action", "fields", "validation", "permissions"):
            assert field in url_str

    def test_populates_extended_attributes(self):
        """get_permissions() populates fields, validation, and permissions from API response."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [
                        {
                            "id": 10,
                            "policy": "policy-uuid-1",
                            "collection": "articles",
                            "action": "update",
                            "fields": ["title", "body"],
                            "validation": {"_and": [{"status": {"_eq": "draft"}}]},
                            "permissions": {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
                        },
                        {
                            "id": 11,
                            "policy": "policy-uuid-2",
                            "collection": "comments",
                            "action": "read",
                            "fields": None,
                            "validation": None,
                            "permissions": None,
                        },
                    ]
                }
            )

        client = _make_client(handler)
        result = client.get_permissions()

        assert len(result) == 2
        # First permission has extended attributes
        assert result[0].fields == ["title", "body"]
        assert result[0].validation == {"_and": [{"status": {"_eq": "draft"}}]}
        assert result[0].permissions == {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}
        # Second permission has None for extended attributes
        assert result[1].fields is None
        assert result[1].validation is None
        assert result[1].permissions is None

    def test_extended_attributes_default_to_none_when_absent(self):
        """When API response omits fields/validation/permissions, they default to None."""

        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": [
                        {
                            "id": 5,
                            "policy": "policy-uuid-1",
                            "collection": "articles",
                            "action": "read",
                        },
                    ]
                }
            )

        client = _make_client(handler)
        result = client.get_permissions()

        assert len(result) == 1
        assert result[0].fields is None
        assert result[0].validation is None
        assert result[0].permissions is None

    def test_api_error_on_non_2xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Error"}]}, status_code=500)

        client = _make_client(handler)
        with pytest.raises(APIError):
            client.get_permissions()


class TestCreatePermission:
    """create_permission() POSTs policy/collection/action payload."""

    def test_returns_created_permission(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": {
                        "id": 42,
                        "policy": "policy-uuid-1",
                        "collection": "articles",
                        "action": "read",
                    }
                }
            )

        client = _make_client(handler)
        result = client.create_permission("policy-uuid-1", "articles", "read")

        assert isinstance(result, DirectusPermission)
        assert result.id == 42
        assert result.policy == "policy-uuid-1"
        assert result.collection == "articles"
        assert result.action == "read"

    def test_sends_correct_payload(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response(
                {"data": {"id": 1, "policy": "p", "collection": "c", "action": "a"}}
            )

        client = _make_client(handler)
        client.create_permission("policy-uuid", "my_collection", "update")

        req = captured[0]
        assert req.method == "POST"
        assert "/permissions" in str(req.url)
        body = json.loads(req.content)
        assert body == {
            "policy": "policy-uuid",
            "collection": "my_collection",
            "action": "update",
        }

    def test_api_error_on_non_2xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Bad Request"}]}, status_code=400)

        client = _make_client(handler)
        with pytest.raises(APIError):
            client.create_permission("p", "c", "read")


class TestUpdatePermission:
    """update_permission() PATCHes /permissions/{id} with policy/collection/action."""

    def test_returns_updated_permission(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {
                    "data": {
                        "id": 7,
                        "policy": "policy-uuid-2",
                        "collection": "comments",
                        "action": "delete",
                    }
                }
            )

        client = _make_client(handler)
        result = client.update_permission(7, "policy-uuid-2", "comments", "delete")

        assert isinstance(result, DirectusPermission)
        assert result.id == 7
        assert result.action == "delete"

    def test_sends_patch_to_correct_url(self):
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return _json_response(
                {"data": {"id": 99, "policy": "p", "collection": "c", "action": "read"}}
            )

        client = _make_client(handler)
        client.update_permission(99, "policy-uuid", "articles", "read")

        req = captured[0]
        assert req.method == "PATCH"
        assert "/permissions/99" in str(req.url)
        body = json.loads(req.content)
        assert body == {
            "policy": "policy-uuid",
            "collection": "articles",
            "action": "read",
        }

    def test_api_error_on_non_2xx(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"errors": [{"message": "Not Found"}]}, status_code=404)

        client = _make_client(handler)
        with pytest.raises(APIError):
            client.update_permission(999, "p", "c", "read")
