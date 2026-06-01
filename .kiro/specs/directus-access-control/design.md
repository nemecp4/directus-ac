# Design Document: directus-access-control

## Overview

`directus_ac` is a Python command-line utility that applies declarative access control rules to a Directus instance. The tool reads a YAML configuration file, validates that all referenced collections and roles exist in the target Directus instance, optionally creates missing roles, and then applies the defined permissions via the Directus REST API.

The tool is designed to be idempotent: running it multiple times against the same configuration and Directus instance produces the same end state. Existing permissions are updated in place rather than duplicated.

### Key Design Decisions

- **Fail-fast validation**: All validation (config parsing, collection existence, role existence) is performed before any mutations are made to the Directus instance. This prevents partial application of permissions.
- **No rollback**: Once permission writes begin, failures are reported but previously applied permissions are retained. This is an explicit requirement and simplifies the implementation.
- **Directus version compatibility**: Directus v11 introduced Policies as an intermediary layer between Roles and Permissions. The requirements document targets the v10 model where permissions are assigned directly to roles. The tool will target the v10 permissions API (`/permissions` with a `role` field). Users on Directus v11+ should be aware that the tool interacts with the legacy permissions endpoint.
- **Synchronous HTTP**: The tool performs sequential API calls. Async HTTP is not needed given the workload is not concurrent.
- **`httpx` for HTTP**: Chosen over `requests` for its modern API, better timeout handling, and future-proofing for async if needed.
- **`pydantic` for validation**: Provides declarative schema validation with clear error messages for the config file.
- **`PyYAML` for YAML parsing**: Standard, widely-used YAML library for Python.

---

## Architecture

The tool follows a linear pipeline architecture with four distinct phases:

```
┌─────────────────────────────────────────────────────────────────┐
│                         directus_ac CLI                         │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐│
│  │  CLI Layer   │──▶│  Config      │──▶│  Validator           ││
│  │  (argparse)  │   │  Parser      │   │  (collections+roles) ││
│  └──────────────┘   └──────────────┘   └──────────┬───────────┘│
│                                                    │            │
│                                        ┌───────────▼───────────┐│
│                                        │  Permission Manager   ││
│                                        │  (create/update perms)││
│                                        └───────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Directus REST  │
                    │  API            │
                    │  /collections   │
                    │  /roles         │
                    │  /permissions   │
                    └─────────────────┘
```

### Execution Flow

```
1. Parse CLI arguments
2. Resolve config file path (--config or default)
3. Parse and validate YAML config file
4. Resolve Directus URL and token (CLI args > env vars)
5. Validate collections exist (GET /collections)
6. Validate roles exist (GET /roles)
   6a. If --create-roles: create missing roles (POST /roles)
7. Fetch existing permissions (GET /permissions)
8. For each role-collection-action triple in config:
   8a. If permission exists: PATCH /permissions/{id}
   8b. If permission does not exist: POST /permissions
9. Print summary (created count, updated count)
```

---

## Components and Interfaces

### Module Structure

```
directus_ac/
├── __init__.py
├── __main__.py          # Entry point: python -m directus_ac
├── cli.py               # CLI argument parsing (argparse)
├── config.py            # YAML config loading and Pydantic validation
├── client.py            # DirectusClient: HTTP wrapper around httpx
├── validator.py         # Validator: collection and role existence checks
├── permissions.py       # PermissionManager: apply permissions logic
└── models.py            # Pydantic data models
```

### `cli.py` — CLI Layer

Parses command-line arguments and orchestrates the pipeline.

```python
def build_parser() -> argparse.ArgumentParser:
    """Returns the configured argument parser."""

def main() -> None:
    """Entry point. Parses args, runs pipeline, exits with appropriate code."""
```

**Arguments:**

| Argument | Type | Description |
|---|---|---|
| `--config` | `str` (optional) | Path to config file. Default: `./directus_ac.yaml` |
| `--url` | `str` (optional) | Directus base URL. Overrides `DIRECTUS_URL` env var |
| `--token` | `str` (optional) | Directus auth token. Overrides `DIRECTUS_TOKEN` env var |
| `--create-roles` | `flag` | Create missing roles instead of failing |

### `config.py` — Config Parser

Loads and validates the YAML configuration file.

```python
def load_config(path: str) -> DirectusACConfig:
    """
    Reads the YAML file at `path`, parses it, and validates it against
    the DirectusACConfig schema. Raises ConfigError on any failure.
    """
```

**Error conditions handled:**
- File not found → `ConfigError` with resolved path
- YAML parse error → `ConfigError` with line/column
- Missing required keys → `ConfigError` listing missing keys
- Invalid Permission_Set keywords → `ConfigError` with role, collection, keyword
- Malformed group (missing `collections` or `permissions`) → `ConfigError` with group index

### `models.py` — Data Models

Pydantic models for config validation and API response parsing.

```python
class PermissionKeyword(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

class GroupDefinition(BaseModel):
    collections: list[str]
    permissions: dict[str, list[PermissionKeyword]]

class DirectusACConfig(BaseModel):
    collections: list[str]   # 1–500 items, each 1–255 chars
    roles: list[str]         # 1–500 items, each 1–255 chars
    groups: list[GroupDefinition]  # 1–500 items

class DirectusRole(BaseModel):
    id: str
    name: str

class DirectusCollection(BaseModel):
    collection: str  # The collection name is the identifier

class DirectusPermission(BaseModel):
    id: int
    role: str        # Role UUID
    collection: str
    action: str      # "read", "create", "update", "delete"
```

### `client.py` — Directus HTTP Client

Wraps `httpx` to provide a typed interface to the Directus REST API. All HTTP errors are translated into domain-specific exceptions.

```python
class DirectusClient:
    def __init__(self, base_url: str, token: str) -> None: ...

    def get_collections(self) -> list[DirectusCollection]: ...
    def get_roles(self) -> list[DirectusRole]: ...
    def create_role(self, name: str) -> DirectusRole: ...
    def get_permissions(self) -> list[DirectusPermission]: ...
    def create_permission(self, role_id: str, collection: str, action: str) -> DirectusPermission: ...
    def update_permission(self, permission_id: int, role_id: str, collection: str, action: str) -> DirectusPermission: ...
```

**HTTP headers sent on every request:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Pagination**: The Directus API defaults to a limit of 100 items. The client will request with `limit=-1` (or paginate) to retrieve all records.

### `validator.py` — Validator

```python
class Validator:
    def __init__(self, client: DirectusClient) -> None: ...

    def validate_collections(self, config_collections: list[str]) -> None:
        """Raises ValidationError listing all missing collections."""

    def validate_roles(
        self,
        config_roles: list[str],
        create_missing: bool,
        permission_manager: "PermissionManager",
    ) -> dict[str, str]:
        """
        Validates roles exist. If create_missing=True, creates them.
        Returns a mapping of role_name -> role_id for all config roles.
        Raises ValidationError listing all missing roles (when create_missing=False).
        """
```

### `permissions.py` — Permission Manager

```python
ACTION_MAP: dict[str, str] = {
    "READ": "read",
    "WRITE": "create",
    "UPDATE": "update",
    "DELETE": "delete",
}

class PermissionManager:
    def __init__(self, client: DirectusClient) -> None: ...

    def create_role(self, name: str) -> str:
        """Creates a role and returns its ID."""

    def apply_permissions(
        self,
        config: DirectusACConfig,
        role_name_to_id: dict[str, str],
    ) -> tuple[int, int]:
        """
        Applies all permissions from config. Returns (created_count, updated_count).
        Raises PermissionError on API failure.
        """
```

**Permission lookup index**: Before applying permissions, the manager fetches all existing permissions and builds an in-memory index keyed by `(role_id, collection, action)` → `permission_id`. This enables O(1) lookup to determine create vs. update for each triple.

### Exception Hierarchy

```python
class DirectusACError(Exception):
    """Base exception for all tool errors."""

class ConfigError(DirectusACError):
    """Config file not found, invalid YAML, or schema validation failure."""

class ConnectionError(DirectusACError):
    """Network error reaching the Directus instance."""

class AuthError(DirectusACError):
    """HTTP 401 or 403 from the Directus API."""

class ValidationError(DirectusACError):
    """Collections or roles referenced in config do not exist in Directus."""

class APIError(DirectusACError):
    """Unexpected HTTP error from the Directus API."""
```

All exceptions are caught in `main()`, printed to stderr, and result in `sys.exit(1)`.

---

## Data Models

### Config File Schema

```yaml
# directus_ac.yaml
collections:
  - articles          # 1–255 chars each; 1–500 entries
  - comments

roles:
  - editor            # 1–255 chars each; 1–500 entries
  - viewer

groups:               # 1–500 entries
  - collections:
      - articles
    permissions:
      editor: "READ WRITE UPDATE DELETE"
      viewer: "READ"
  - collections:
      - comments
    permissions:
      editor: "READ WRITE UPDATE"
      viewer: "READ"
```

### Permission_Set Parsing

The `permissions` map value is a space-separated string of keywords. Parsing steps:

1. Strip leading/trailing whitespace from the string.
2. Split on whitespace.
3. Validate each token against `{READ, WRITE, UPDATE, DELETE}`.
4. Deduplicate (a keyword appearing twice is treated as once).

### Permission_Set → Directus Action Mapping

| Config keyword | Directus action |
|---|---|
| `READ` | `read` |
| `WRITE` | `create` |
| `UPDATE` | `update` |
| `DELETE` | `delete` |

### Directus API Payloads

**POST /roles**
```json
{ "name": "<role_name>" }
```

**POST /permissions**
```json
{
  "role": "<role_uuid>",
  "collection": "<collection_name>",
  "action": "<read|create|update|delete>"
}
```

**PATCH /permissions/{id}**
```json
{
  "role": "<role_uuid>",
  "collection": "<collection_name>",
  "action": "<read|create|update|delete>"
}
```

**GET /permissions** (with query params)
```
GET /permissions?limit=-1&fields=id,role,collection,action
```

**GET /roles** (with query params)
```
GET /roles?limit=-1&fields=id,name
```

**GET /collections**
```
GET /collections
```
Response: `{ "data": [{ "collection": "articles", ... }, ...] }`

### Credential Resolution

```
┌─────────────────────────────────────────────────────┐
│  Credential Resolution (URL and Token)              │
│                                                     │
│  1. Check --url / --token CLI argument              │
│     └─ If present: use it                          │
│  2. Check DIRECTUS_URL / DIRECTUS_TOKEN env var     │
│     └─ If present: use it                          │
│  3. Neither present: exit with error                │
└─────────────────────────────────────────────────────┘
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Permission_Set parsing round-trip

*For any* non-empty subset of `{READ, WRITE, UPDATE, DELETE}`, serializing the set to a space-separated string and then parsing it back should produce the same set of keywords.

**Validates: Requirements 6.2, 7.5**

### Property 2: Invalid keywords are always rejected

*For any* string that contains at least one token not in `{READ, WRITE, UPDATE, DELETE}`, parsing it as a Permission_Set should raise a `ConfigError` identifying the invalid keyword.

**Validates: Requirements 1.7**

### Property 3: Valid config round-trip

*For any* valid `DirectusACConfig` object (with collections, roles, and groups satisfying all length and count constraints), serializing it to a YAML string and parsing it back should produce an equivalent config object with identical collections, roles, and group definitions.

**Validates: Requirements 1.2, 1.3, 1.4, 7.1, 7.2, 7.3**

### Property 4: All missing names are reported (collections and roles)

*For any* config listing a set of collection names (or role names) and any set of names that exist in the Directus instance, the `ValidationError` raised by the Validator should contain exactly the set difference — every name in the config that is not in the existing set, and no names that are present.

**Validates: Requirements 3.4, 3.5, 4.4**

### Property 5: Name matching is case-sensitive

*For any* collection name or role name, a name that differs from an existing Directus name only in letter case should be treated as missing (not found), and a name that matches exactly should be treated as present.

**Validates: Requirements 3.3, 4.3**

### Property 6: Permission index lookup is correct

*For any* list of `DirectusPermission` objects with unique `(role, collection, action)` triples, building the in-memory permission index and then looking up each triple should return the correct permission ID, and looking up any triple not in the list should return `None`.

**Validates: Requirements 6.3, 6.4**

### Property 7: Action mapping covers all keywords

*For any* Permission_Set keyword in `{READ, WRITE, UPDATE, DELETE}`, the `ACTION_MAP` should map it to a unique, non-empty Directus action string, and no two keywords should map to the same action string.

**Validates: Requirements 6.2**

### Property 8: Permission application is complete

*For any* valid config and any role-to-ID mapping, the set of `(role_id, collection, action)` triples sent to the Directus API (via POST or PATCH) should equal exactly the set of triples implied by expanding all groups in the config — no triple is omitted and no extra triple is added.

**Validates: Requirements 6.1**

### Property 9: Summary counts are accurate

*For any* config applied against a known set of pre-existing permissions, the summary counts reported by the tool (created, updated) should equal the number of triples that did not exist before (created) and the number that did exist before (updated), respectively.

**Validates: Requirements 6.7**

---

## Error Handling

### Error Categories and Responses

| Error | Trigger | Exit Code | Output |
|---|---|---|---|
| Config file not found | File missing at resolved path | 1 | `Error: Config file not found: <path>` |
| YAML parse error | Invalid YAML syntax | 1 | `Error: YAML parse error at line <L>, column <C>: <msg>` |
| Missing top-level keys | `collections`, `roles`, or `groups` absent | 1 | `Error: Missing required keys: <key1>, <key2>` |
| Invalid Permission_Set keyword | Unknown token in permissions value | 1 | `Error: Invalid permission keyword '<kw>' for role '<role>' on collection '<col>'` |
| Malformed group | Group missing `collections` or `permissions` | 1 | `Error: Group at index <N> is missing key: <key>` |
| Missing Directus URL | Neither `--url` nor `DIRECTUS_URL` set | 1 | `Error: Directus URL must be provided via --url or DIRECTUS_URL` |
| Missing Directus token | Neither `--token` nor `DIRECTUS_TOKEN` set | 1 | `Error: Auth token must be provided via --token or DIRECTUS_TOKEN` |
| Network error | Connection refused, DNS failure, timeout | 1 | `Error: Cannot reach Directus at <url>: <reason>` |
| Auth failure | HTTP 401 or 403 | 1 | `Error: Authentication failed. Verify your token.` |
| API error (collections) | Non-2xx on GET /collections | 1 | `Error: Failed to fetch collections: HTTP <status> — <detail>` |
| API error (roles) | Non-2xx on GET /roles | 1 | `Error: Failed to fetch roles: HTTP <status> — <detail>` |
| Missing collections | Config references non-existent collections | 1 | `Error: Collections not found in Directus:\n  - <name1>\n  - <name2>` |
| Missing roles (no --create-roles) | Config references non-existent roles | 1 | `Error: Roles not found in Directus:\n  - <name1>\n  - <name2>` |
| Role creation failure | POST /roles returns error | 1 | `Created role: <name1>\nError: Failed to create role '<name2>': <reason>` |
| Permission apply failure | POST/PATCH /permissions returns error | 1 | `Error: Failed to apply permission for role '<r>', collection '<c>', action '<a>': <reason>` |

### Error Output Convention

- All errors are written to **stderr**.
- Progress and success messages are written to **stdout**.
- The tool always exits with code `0` on success and `1` on any error.

---

## Testing Strategy

### Dual Testing Approach

The test suite uses both example-based unit tests and property-based tests (via [Hypothesis](https://hypothesis.readthedocs.io/)).

**Unit tests** cover:
- Specific config parsing examples (valid and invalid)
- Specific CLI argument combinations
- Specific API error scenarios (mocked with `httpx` mock transport)
- Integration between Validator and PermissionManager with a mock client

**Property tests** cover the correctness properties defined above, using Hypothesis strategies to generate arbitrary valid and invalid inputs.

### Test Structure

```
tests/
├── test_config.py          # Config parsing: unit + property tests
├── test_client.py          # DirectusClient: unit tests with mock transport
├── test_validator.py       # Validator: unit tests with mock client
├── test_permissions.py     # PermissionManager: unit + property tests
├── test_cli.py             # CLI argument parsing: unit tests
└── conftest.py             # Shared fixtures
```

### Property-Based Testing Configuration

- Library: **Hypothesis** (`hypothesis` package, integrates with `pytest`)
- Minimum iterations: **100** per property test (Hypothesis default is 100; use `@settings(max_examples=100)`)
- Each property test is tagged with a comment referencing the design property:
  ```python
  # Feature: directus-access-control, Property 1: Permission_Set parsing round-trip
  @given(st.frozensets(st.sampled_from(["READ", "WRITE", "UPDATE", "DELETE"]), min_size=1))
  def test_permission_set_round_trip(keywords): ...
  ```

### Hypothesis Strategies

| Strategy | Used for |
|---|---|
| `st.sampled_from(["READ", "WRITE", "UPDATE", "DELETE"])` | Valid permission keywords |
| `st.frozensets(...)` | Subsets of valid keywords |
| `st.text(min_size=1, max_size=255)` | Collection and role names |
| `st.lists(..., min_size=1, max_size=500)` | Collections/roles lists |
| `st.text().filter(lambda s: not all(t in VALID_KEYWORDS for t in s.split()))` | Invalid Permission_Set strings |

### Mocking Strategy

- `DirectusClient` is injected as a dependency into `Validator` and `PermissionManager`, making it straightforward to substitute a mock.
- HTTP-level tests use `httpx`'s `MockTransport` to simulate API responses without a live Directus instance.
- No integration tests against a live Directus instance are included in the automated test suite; those are left for manual or CI environment testing.

### Test Dependencies

```
pytest>=8.0
hypothesis>=6.100
httpx>=0.27
pydantic>=2.0
PyYAML>=6.0
pytest-mock>=3.12
```
