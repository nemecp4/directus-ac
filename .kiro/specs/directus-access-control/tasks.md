# Implementation Plan: directus-access-control

## Overview

Implement `directus_ac`, a Python CLI utility that reads a declarative YAML configuration file and applies access control permissions to a Directus instance via its REST API. The implementation follows a linear pipeline: parse config → resolve credentials → validate collections/roles → apply permissions. The tool is idempotent and fail-fast.

## Tasks

- [x] 1. Set up project structure and core data models
  - Create the `directus_ac/` package directory with `__init__.py` and `__main__.py`
  - Create `pyproject.toml` (or `setup.py`) with dependencies: `httpx>=0.27`, `pydantic>=2.0`, `PyYAML>=6.0`
  - Create `tests/` directory with `conftest.py` and empty test module stubs
  - Create `requirements-dev.txt` with test dependencies: `pytest>=8.0`, `hypothesis>=6.100`, `pytest-mock>=3.12`
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 1.1 Implement `models.py` — Pydantic data models
    - Define `PermissionKeyword` enum with `READ`, `WRITE`, `UPDATE`, `DELETE`
    - Define `GroupDefinition` model with `collections: list[str]` and `permissions: dict[str, list[PermissionKeyword]]`
    - Define `DirectusACConfig` model with `collections`, `roles`, `groups` fields and length/count validators (1–500 items, 1–255 chars per name)
    - Define `DirectusRole`, `DirectusCollection`, `DirectusPermission` API response models
    - _Requirements: 1.2, 1.3, 1.4, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 1.2 Write property test for `DirectusACConfig` round-trip (Property 3)
    - **Property 3: Valid config round-trip**
    - Generate arbitrary valid `DirectusACConfig` objects using Hypothesis strategies (`st.text(min_size=1, max_size=255)`, `st.lists(..., min_size=1, max_size=500)`)
    - Serialize to YAML and parse back; assert the result equals the original
    - **Validates: Requirements 1.2, 1.3, 1.4, 7.1, 7.2, 7.3**

- [x] 2. Implement `config.py` — YAML config loading and validation
  - [x] 2.1 Implement `load_config(path: str) -> DirectusACConfig`
    - Handle `FileNotFoundError` → raise `ConfigError` with resolved path (Requirement 1.5, 7.7)
    - Handle `yaml.YAMLError` → raise `ConfigError` with line/column (Requirement 1.6)
    - Handle missing top-level keys → raise `ConfigError` listing each missing key (Requirement 1.8)
    - Handle malformed group (missing `collections` or `permissions`) → raise `ConfigError` with group index (Requirement 1.9)
    - Handle invalid `PermissionKeyword` tokens → raise `ConfigError` with keyword, role, collection (Requirement 1.7)
    - Parse `permissions` map values as space-separated strings: strip, split, deduplicate, validate (Requirement 7.5)
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 7.5, 7.7, 7.8_

  - [x] 2.2 Write property test for Permission_Set parsing round-trip (Property 1)
    - **Property 1: Permission_Set parsing round-trip**
    - Generate non-empty subsets of `{READ, WRITE, UPDATE, DELETE}` using `st.frozensets(st.sampled_from([...]), min_size=1)`
    - Serialize to space-separated string, parse back, assert same set of keywords
    - **Validates: Requirements 6.2, 7.5**

  - [x] 2.3 Write property test for invalid keyword rejection (Property 2)
    - **Property 2: Invalid keywords are always rejected**
    - Generate strings containing at least one token not in `{READ, WRITE, UPDATE, DELETE}` using `st.text().filter(...)`
    - Assert `load_config` (or the parsing sub-function) raises `ConfigError` identifying the invalid keyword
    - **Validates: Requirements 1.7**

- [x] 3. Implement exception hierarchy in `exceptions.py`
  - Define `DirectusACError(Exception)` base class
  - Define `ConfigError`, `ConnectionError`, `AuthError`, `ValidationError`, `APIError` subclasses
  - Ensure all subclasses carry a human-readable message suitable for stderr output
  - _Requirements: 1.5, 1.6, 1.7, 1.8, 1.9, 2.5, 2.6, 2.7, 2.8, 3.2, 3.5, 4.2, 4.4, 5.5, 6.5_

- [x] 4. Checkpoint — Ensure models, config parsing, and exceptions are correct
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement `client.py` — Directus HTTP client
  - [x] 5.1 Implement `DirectusClient.__init__` and shared request logic
    - Accept `base_url: str` and `token: str`
    - Set `Authorization: Bearer <token>` and `Content-Type: application/json` headers on every request
    - Wrap `httpx.ConnectError`, `httpx.TimeoutException`, and DNS failures → raise `ConnectionError` with URL and reason (Requirement 2.8)
    - Wrap HTTP 401/403 responses → raise `AuthError` (Requirement 2.7)
    - Wrap other non-2xx responses → raise `APIError` with status code and detail
    - _Requirements: 2.7, 2.8_

  - [x] 5.2 Implement `get_collections()`, `get_roles()`, `create_role()`, `get_permissions()`, `create_permission()`, `update_permission()`
    - `GET /collections` — parse `data[].collection` field (Requirement 3.1)
    - `GET /roles?limit=-1&fields=id,name` — parse into `list[DirectusRole]` (Requirement 4.1)
    - `POST /roles` with `{"name": name}` — return `DirectusRole` (Requirement 5.2)
    - `GET /permissions?limit=-1&fields=id,role,collection,action` — parse into `list[DirectusPermission]` (Requirement 6.3, 6.4)
    - `POST /permissions` with role/collection/action payload (Requirement 6.4)
    - `PATCH /permissions/{id}` with role/collection/action payload (Requirement 6.3)
    - Raise `APIError` with HTTP status and detail on non-2xx for each endpoint (Requirements 3.2, 4.2, 5.5, 6.5)
    - _Requirements: 3.1, 3.2, 4.1, 4.2, 5.2, 5.5, 6.3, 6.4, 6.5_

- [x] 6. Implement `validator.py` — collection and role validation
  - [x] 6.1 Implement `Validator.validate_collections(config_collections: list[str]) -> None`
    - Call `client.get_collections()` to retrieve existing names
    - Compute set difference using case-sensitive exact match (Requirement 3.3)
    - Collect all missing names before raising (Requirement 3.4)
    - Raise `ValidationError` listing every missing collection name (Requirement 3.5)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 6.2 Write property test for missing-names reporting — collections (Property 4)
    - **Property 4: All missing names are reported (collections)**
    - Generate arbitrary config collection name lists and arbitrary existing-name sets using `st.lists(st.text(min_size=1, max_size=255))`
    - Assert `ValidationError` contains exactly the set difference (no omissions, no extras)
    - **Validates: Requirements 3.4, 3.5**

  - [x] 6.3 Write property test for case-sensitive name matching (Property 5)
    - **Property 5: Name matching is case-sensitive**
    - Generate a name and a case-variant of it; assert the variant is treated as missing while the exact name is treated as present
    - **Validates: Requirements 3.3, 4.3**

  - [x] 6.4 Implement `Validator.validate_roles(config_roles, create_missing, permission_manager) -> dict[str, str]`
    - Call `client.get_roles()` to retrieve existing roles
    - Compute set difference using case-sensitive exact match (Requirement 4.3)
    - If `create_missing=False` and roles are missing: raise `ValidationError` listing all missing role names (Requirement 4.4)
    - If `create_missing=True` and roles are missing: delegate creation to `permission_manager.create_role()` for each missing role (Requirement 4.5)
    - Return `dict[role_name -> role_id]` for all config roles (Requirement 5.2)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 6.5 Write property test for missing-names reporting — roles (Property 4)
    - **Property 4: All missing names are reported (roles)**
    - Same strategy as 6.2 but applied to role names
    - Assert `ValidationError` contains exactly the set difference
    - **Validates: Requirements 4.4**

- [x] 7. Implement `permissions.py` — Permission Manager
  - [x] 7.1 Implement `PermissionManager.create_role(name: str) -> str`
    - Call `client.create_role(name)` and return the new role's ID
    - Print `Created role: <name>` to stdout on success (Requirement 5.4)
    - On `APIError`, print success messages for all previously created roles, then re-raise (Requirement 5.5)
    - _Requirements: 5.2, 5.4, 5.5_

  - [x] 7.2 Implement `PermissionManager.apply_permissions(config, role_name_to_id) -> tuple[int, int]`
    - Define `ACTION_MAP = {"READ": "read", "WRITE": "create", "UPDATE": "update", "DELETE": "delete"}` (Requirement 6.2)
    - Fetch all existing permissions via `client.get_permissions()` and build in-memory index `(role_id, collection, action) -> permission_id` (Requirement 6.3, 6.4)
    - Expand all groups in config into `(role_id, collection, action)` triples
    - For each triple: if in index → `client.update_permission(id, ...)`, else → `client.create_permission(...)` (Requirements 6.3, 6.4)
    - On `APIError`: raise `PermissionError` with role, collection, action, and reason (Requirement 6.5)
    - Return `(created_count, updated_count)` (Requirement 6.7)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 7.3 Write property test for ACTION_MAP coverage (Property 7)
    - **Property 7: Action mapping covers all keywords**
    - Assert every keyword in `{READ, WRITE, UPDATE, DELETE}` maps to a unique, non-empty string in `ACTION_MAP`
    - **Validates: Requirements 6.2**

  - [x] 7.4 Write property test for permission index lookup correctness (Property 6)
    - **Property 6: Permission index lookup is correct**
    - Generate lists of `DirectusPermission` objects with unique `(role, collection, action)` triples using Hypothesis
    - Build the index and assert each triple returns the correct ID; assert absent triples return `None`
    - **Validates: Requirements 6.3, 6.4**

  - [x] 7.5 Write property test for permission application completeness (Property 8)
    - **Property 8: Permission application is complete**
    - Generate a valid config and role-to-ID mapping; mock the client
    - Assert the set of `(role_id, collection, action)` triples sent to the API equals exactly the expansion of all groups in the config
    - **Validates: Requirements 6.1**

  - [x] 7.6 Write property test for summary count accuracy (Property 9)
    - **Property 9: Summary counts are accurate**
    - Generate a config and a known set of pre-existing permissions; mock the client
    - Assert `(created_count, updated_count)` equals the number of new vs. pre-existing triples
    - **Validates: Requirements 6.7**

- [x] 8. Checkpoint — Ensure validator and permission manager tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement `cli.py` — CLI argument parsing and pipeline orchestration
  - [x] 9.1 Implement `build_parser() -> argparse.ArgumentParser`
    - Add `--config` (default `./directus_ac.yaml`) (Requirements 1.1, 7.6)
    - Add `--url` (overrides `DIRECTUS_URL` env var) (Requirements 2.1, 2.3)
    - Add `--token` (overrides `DIRECTUS_TOKEN` env var) (Requirements 2.2, 2.4)
    - Add `--create-roles` flag (Requirements 5.1)
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 5.1, 7.6_

  - [x] 9.2 Implement `main() -> None` — pipeline orchestration
    - Resolve config path from `--config` or default (Requirement 1.1)
    - Call `load_config(path)` (Requirement 1.1–1.9)
    - Resolve URL: `--url` → `DIRECTUS_URL` → exit with error (Requirements 2.1, 2.3, 2.5)
    - Resolve token: `--token` → `DIRECTUS_TOKEN` → exit with error (Requirements 2.2, 2.4, 2.6)
    - Instantiate `DirectusClient`, `Validator`, `PermissionManager`
    - Call `validator.validate_collections(config.collections)` (Requirement 3.1–3.6)
    - Call `validator.validate_roles(config.roles, args.create_roles, permission_manager)` (Requirement 4.1–4.6)
    - Call `permission_manager.apply_permissions(config, role_name_to_id)` (Requirement 6.1–6.7)
    - Print summary: `Applied permissions: <N> created, <M> updated.` to stdout (Requirement 6.7)
    - Catch all `DirectusACError` subclasses → print to stderr → `sys.exit(1)` (all error requirements)
    - _Requirements: 1.1, 2.1–2.8, 3.1–3.6, 4.1–4.6, 5.1–5.5, 6.1–6.7, 7.6, 7.7_

- [x] 10. Wire entry point and finalize packaging
  - Add `[project.scripts]` entry in `pyproject.toml`: `directus-ac = "directus_ac.cli:main"` (or equivalent)
  - Ensure `python -m directus_ac` works via `__main__.py` calling `main()`
  - _Requirements: 1.1, 2.1, 2.2, 5.1, 7.6_

- [x] 11. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- Checkpoints at tasks 4, 8, and 11 ensure incremental validation
- Property tests (Properties 1–9) validate universal correctness guarantees using Hypothesis
- Unit tests validate specific examples, edge cases, and error conditions
- All errors are written to stderr; progress and success messages to stdout
- The tool exits with code `0` on success and `1` on any error
- `DirectusClient` is injected as a dependency into `Validator` and `PermissionManager` for easy mocking in tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "5.1"] },
    { "id": 3, "tasks": ["5.2"] },
    { "id": 4, "tasks": ["6.1", "7.1", "7.2", "9.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "6.4", "7.3", "7.4", "7.5", "7.6"] },
    { "id": 6, "tasks": ["6.5", "9.2"] },
    { "id": 7, "tasks": ["10"] }
  ]
}
```
