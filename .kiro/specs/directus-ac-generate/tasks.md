# Implementation Plan: directus-ac-generate

## Overview

Implement the `--generate` flag for `directus_ac` that reads the current access control state from a running Directus instance and produces a `directus_ac.yaml` configuration file. This adds a `Generator` class and `serialize_config()` function in a new `directus_ac/generate.py` module, and extends the CLI with `--generate`, `--output`, and `--include-system` arguments.

## Tasks

- [x] 1. Implement `generate.py` — Generator and Serializer
  - [x] 1.1 Implement `REVERSE_ACTION_MAP` and `Generator` class
    - Create `directus_ac/generate.py` module
    - Define `REVERSE_ACTION_MAP: dict[str, PermissionKeyword]` mapping `"read"→READ`, `"create"→WRITE`, `"update"→UPDATE`, `"delete"→DELETE`
    - Define `KEYWORD_ORDER` list for canonical ordering: `[READ, WRITE, UPDATE, DELETE]`
    - Implement `Generator.__init__(self, client: DirectusClient, include_system: bool = False)`
    - Implement `Generator.generate(self) -> DirectusACConfig`:
      - Fetch collections, roles, permissions from client
      - Filter system collections (names starting with `directus_`) when `include_system=False`
      - Build `role_id_to_name` map from fetched roles
      - Skip permissions referencing unknown role IDs (orphan exclusion)
      - Skip permissions referencing excluded collections
      - Skip permissions with unknown action strings
      - Group remaining permissions by collection
      - For each collection, build a `GroupDefinition` with per-role `list[PermissionKeyword]`
      - Assemble `DirectusACConfig` with only collections/roles that have permissions
      - Return empty config (empty lists) if no permissions remain after filtering
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 6.3_

  - [x] 1.2 Implement `serialize_config()` function
    - Implement `serialize_config(config: DirectusACConfig) -> str`
    - Build plain dict with top-level keys in order: `collections`, `roles`, `groups`
    - Convert each group's `permissions` values from `list[PermissionKeyword]` to space-separated strings in canonical order (READ WRITE UPDATE DELETE)
    - Use `yaml.dump()` with `default_flow_style=False` and `sort_keys=False`
    - Ensure no leading/trailing whitespace in Permission_Set strings
    - Output must be parseable by `load_config()` to produce an equivalent `DirectusACConfig`
    - _Requirements: 5.1, 5.2, 5.3, 6.2_

- [x] 2. Update CLI — Add `--generate`, `--output`, `--include-system`
  - [x] 2.1 Update `build_parser()` in `directus_ac/cli.py`
    - Add `--generate` to the existing mutually exclusive group alongside `--check` and `--update`
    - Add `--output` argument (default: `None`, help: file path for generated YAML)
    - Add `--include-system` flag (default: `False`, help: include system collections)
    - Update epilog to: `"One of --check, --update, or --generate is required to perform an operation."`
    - _Requirements: 1.1, 1.4, 1.5, 1.8_

  - [x] 2.2 Add `--generate` branch in `main()`
    - Update the `if not args.check and not args.update` guard to include `args.generate`
    - Add `elif args.generate:` branch after the existing `elif args.update:` block
    - Resolve URL and token using existing logic (arg → env var → error exit)
    - Instantiate `DirectusClient(base_url=url, token=token)`
    - Instantiate `Generator(client, include_system=args.include_system)`
    - Call `generator.generate()` to get `DirectusACConfig`
    - Call `serialize_config(config)` to get YAML string
    - If `args.output`: write YAML to file (create/overwrite), catch `OSError` → print error with path and reason, exit 1
    - If no `args.output`: write YAML to stdout
    - Import `Generator` and `serialize_config` from `directus_ac.generate`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 5.4, 5.5, 5.6_

- [x] 3. Checkpoint — Ensure core implementation is correct
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Property-based tests for Generator and Serializer
  - [x] 4.1 Write property test for serialization round-trip
    - **Property 1: Serialization round-trip**
    - Generate random valid `DirectusACConfig` objects using Hypothesis strategies (non-empty collections, roles, groups with valid Permission_Set subsets)
    - Serialize with `serialize_config()`, write to temp file, parse with `load_config()`
    - Assert the parsed config is equivalent to the original (same collections, roles, and group permissions)
    - **Validates: Requirements 5.1, 5.2, 5.3, 6.2**

  - [x] 4.2 Write property test for system collection filter correctness
    - **Property 2: System collection filter correctness**
    - Generate random collection lists (mix of `directus_`-prefixed and non-system names) and random permissions referencing those collections
    - Run Generator with `include_system=False`: assert no `directus_`-prefixed collections in output
    - Run Generator with `include_system=True`: assert all collections with permissions are included
    - Mock `DirectusClient` to return the generated data
    - **Validates: Requirements 3.1, 3.2, 4.9**

  - [x] 4.3 Write property test for completeness invariant
    - **Property 3: Completeness invariant**
    - Generate random sets of roles, collections, and permissions (after filtering)
    - Run Generator, verify `config.collections` equals exactly the set of collection names appearing in at least one permission
    - Verify `config.roles` equals exactly the set of role names appearing in at least one permission
    - **Validates: Requirements 4.1, 4.2, 6.3**

  - [x] 4.4 Write property test for grouping correctness
    - **Property 4: Grouping correctness**
    - Generate random permissions, run Generator
    - Assert exactly one group per distinct collection
    - Assert each group's `collections` field is a single-element list
    - Assert each group's `permissions` map correctly reflects all role-action pairs for that collection
    - **Validates: Requirements 4.3, 4.4, 4.5, 4.7**

  - [x] 4.5 Write property test for orphan permission exclusion
    - **Property 5: Orphan permission exclusion**
    - Generate permissions where some reference role IDs not present in the roles list
    - Run Generator, assert orphan permissions are excluded from output
    - Assert no references to orphan role IDs in the resulting config
    - **Validates: Requirements 4.8**

  - [x] 4.6 Write property test for idempotency
    - **Property 6: Idempotency**
    - Generate a consistent Directus state (collections, roles, permissions)
    - Run Generator to produce config
    - Expand the generated config into `(role_id, collection, action)` triples
    - Compare against the original permission set; assert zero diff (no creates, no updates needed)
    - **Validates: Requirements 6.1**

- [x] 5. Unit tests for CLI and edge cases
  - [x] 5.1 Write unit tests for CLI argument parsing
    - Test `--generate` is in mutually exclusive group with `--check` and `--update`
    - Test `--output` argument is accepted when `--generate` is specified
    - Test `--include-system` flag is accepted when `--generate` is specified
    - Test updated epilog text
    - _Requirements: 1.1, 1.4, 1.5, 1.8_

  - [x] 5.2 Write unit tests for Generator with mocked client
    - Test basic generation with known collections, roles, permissions
    - Test system collection filtering (exclude `directus_*` by default)
    - Test orphan permission handling (unknown role IDs skipped)
    - Test empty permissions list produces empty config
    - Test all-system-collections with `include_system=False` produces empty config
    - Test action mapping for all 4 Directus actions
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1–4.9_

  - [x] 5.3 Write unit tests for serialize_config edge cases
    - Test single collection with single role and single permission
    - Test multiple permissions combined into space-separated string
    - Test canonical keyword ordering (READ before WRITE before UPDATE before DELETE)
    - Test output is valid YAML parseable by `load_config()`
    - _Requirements: 5.1, 5.2, 5.3, 6.2_

  - [x] 5.4 Write unit tests for error handling in `--generate` branch
    - Test file write failure (permission denied) exits with error message
    - Test auth failure from client propagates correctly
    - Test connection error from client propagates correctly
    - _Requirements: 2.4, 2.5, 2.6, 5.6_

- [x] 6. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- Checkpoints at tasks 3 and 6 ensure incremental validation
- Property tests (Properties 1–6) validate universal correctness guarantees using Hypothesis
- Unit tests validate specific examples, edge cases, and error conditions
- The `Generator` reuses the existing `DirectusClient` methods (`get_collections`, `get_roles`, `get_permissions`)
- No new data models are needed; the feature reuses `DirectusACConfig`, `GroupDefinition`, and `PermissionKeyword`
- `serialize_config()` uses manual dict construction (not Pydantic `.model_dump()`) to control key ordering and Permission_Set formatting

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4"] }
  ]
}
```
