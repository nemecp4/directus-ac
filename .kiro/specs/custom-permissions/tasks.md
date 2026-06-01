# Implementation Plan: Custom Permissions

## Overview

Extend the directus-ac CLI tool to detect, name, and inline custom permissions within the groups' Permission_Set strings, with a `custom_permissions` definitions section in the YAML config. The simplified design uses `C_COUNTER` naming (no sanitization), inline references in groups (e.g., `READ WRITE C_1`), and updated config parsing to handle mixed tokens. Implementation proceeds bottom-up: models first, then detection/naming, serialization, config loading, and command integration.

## Tasks

- [x] 1. Update models for inline custom permission references
  - [x] 1.1 Simplify generate_permission_name and update GroupDefinition model
    - Replace `generate_permission_name(policy_name, collection_name, counter)` with `generate_permission_name(counter)` that returns `C_{counter}`
    - Add `custom_permission_refs: dict[str, list[str]] = {}` field to `GroupDefinition` model (maps role name to list of C_N references)
    - Ensure `CustomPermissionEntry.name` follows the `C_N` pattern
    - _Requirements: 2.1, 2.4, 1.3_

- [x] 2. Update Generator to produce inline references in groups
  - [x] 2.1 Modify Generator.generate() to assign C_N names and populate group refs
    - Replace the existing name generation call with the simplified `generate_permission_name(counter)` (returns `C_1`, `C_2`, etc.)
    - For each custom permission, resolve its policy to role(s) and collection, then add the `C_N` reference to the corresponding group's `custom_permission_refs[role_name]` list
    - If a custom permission's collection doesn't have an existing group, create a new group for that collection with empty standard permissions and the custom ref
    - Maintain the global counter sorted by Directus permission `id` ascending
    - _Requirements: 1.3, 1.4, 2.1, 2.2, 4.1, 4.5_

  - [x] 2.2 Write property test for custom permission detection correctness (Property 1)
    - **Property 1: Custom permission detection correctness**
    - Generate random `DirectusPermission` objects with varying attribute combinations and duplicate triples; verify detection logic classifies as custom iff it has non-null validation, non-default fields, non-null permissions, or shares a (policy, collection, action) triple with another entry
    - **Validates: Requirements 1.1, 1.2**

  - [x] 2.3 Write property test for inline reference correctness (Property 2)
    - **Property 2: Inline reference correctness**
    - Generate mixed Directus states; verify groups contain correct `C_N` references in the Permission_Set for the corresponding role+collection, and every `C_N` reference has a matching entry in the `custom_permissions` definitions section
    - **Validates: Requirements 1.3, 1.4, 2.4**

  - [x] 2.4 Write property test for counter assignment determinism and uniqueness (Property 3)
    - **Property 3: Counter assignment determinism and uniqueness**
    - Generate permission sets with various IDs; verify counter is a single global sequence starting at 1, assigned by ascending permission `id`, and all generated Permission_Name values are distinct
    - **Validates: Requirements 2.2, 2.3**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Update serialize_config() for inline Permission_Set output
  - [x] 4.1 Extend serialize_config() to include C_N refs in Permission_Set strings
    - When serializing a group's permissions, append custom_permission_refs for each role after the standard keywords (e.g., `"READ WRITE C_1 C_2"`)
    - Output `custom_permissions` definitions section after `groups` when non-empty; omit entirely when empty
    - Each custom permission entry contains `name`, `policy`, `collection`, `action`, and only non-null/non-empty optional attributes (skip `{}` for dicts, `[]` for lists)
    - Maintain key order: `collections`, `roles`, `groups`, `custom_permissions`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 4.2 Write property test for serialization correctness (Property 6)
    - **Property 6: Serialization correctness**
    - Generate configs with/without custom permissions; verify YAML includes `custom_permissions` key iff custom permissions exist; key order is `collections`, `roles`, `groups`, `custom_permissions`; Permission_Set strings contain inline C_N references; each entry contains only non-null/non-empty optional attributes
    - **Validates: Requirements 4.2, 4.3, 4.4**

- [x] 5. Update config loader to parse mixed Permission_Set tokens
  - [x] 5.1 Extend _parse_permission_set to handle C_\d+ tokens
    - Update `_parse_permission_set` to accept tokens matching `C_\d+` pattern in addition to standard keywords (READ, WRITE, UPDATE, DELETE)
    - Standard keywords are stored in `GroupDefinition.permissions` as before
    - Custom references (C_N tokens) are stored in `GroupDefinition.custom_permission_refs` for the corresponding role
    - Invalid tokens (neither a keyword nor matching `C_\d+`) still raise ConfigError
    - _Requirements: 3.1, 3.2, 1.3_

  - [x] 5.2 Verify _parse_custom_permissions handles the updated schema
    - Ensure existing `_parse_custom_permissions` validates `name` field matches `C_\d+` pattern (optional strictness) and all other required fields
    - Ensure `custom_permissions` key absent → empty list, not a list → ConfigError, missing fields → ConfigError with index
    - _Requirements: 3.3, 3.4, 3.5, 3.6_

  - [x] 5.3 Write property test for config parsing round-trip (Property 4)
    - **Property 4: Config parsing round-trip**
    - Generate valid configs with custom permissions and inline references in groups; verify serialize→parse produces equivalent config (same custom_permissions entries, same Permission_Set contents including custom references)
    - **Validates: Requirements 3.1, 3.2**

  - [x] 5.4 Write property test for invalid entry detection (Property 5)
    - **Property 5: Invalid custom permission entry detection**
    - Generate entries with missing required fields or invalid action values; verify ConfigError is raised with correct message identifying the problem and entry index
    - **Validates: Requirements 3.4, 3.6, 8.3**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Update CheckCommand for inline display
  - [x] 7.1 Modify _format_policies to show custom permissions inline
    - Remove the separate `_format_custom_permissions` method and "Custom Permissions" section
    - In `_format_policies`, detect custom permissions and show their `C_N` references inline alongside standard actions in the comma-separated list per collection (e.g., `articles: read, create, C_1, C_2`)
    - Append `fields:(field1,field2)` to the reference when `fields` is non-null
    - Append `has validation` when `validation` is non-null
    - Append `has item permissions` when `permissions` (item-level) is non-null
    - When no custom permissions exist, display only standard actions without any custom references
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 7.2 Write property test for check command inline display (Property 7)
    - **Property 7: Check command inline display with indicators**
    - Generate custom permissions with various attribute combinations; verify policies section output shows C_N references inline alongside standard actions with correct indicators
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

- [x] 8. Update PermissionManager and Validator
  - [x] 8.1 Verify apply_custom_permissions handles the updated naming
    - Ensure `apply_custom_permissions` works correctly with `C_N` named entries
    - Resolve policy names to IDs, match existing custom permissions for update vs create, apply via POST/PATCH
    - Return (created_count, updated_count) as separate counts
    - Raise APIError with Permission_Name (C_N), collection, action, and detail on failure
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 8.2 Write property test for update command correctness (Property 8)
    - **Property 8: Update command create/update correctness**
    - Generate custom permission entries + existing Directus state; verify create/update counts match POST/PATCH operations performed
    - **Validates: Requirements 6.1, 6.2, 6.4**

  - [x] 8.3 Verify validate_custom_permissions works with updated model
    - Ensure validator checks policy names are resolvable and collections are in config
    - Ensure ALL invalid references are collected before raising a single ValidationError
    - _Requirements: 8.1, 8.2_

  - [x] 8.4 Write property test for validation batch error collection (Property 9)
    - **Property 9: Validation batch error collection**
    - Generate entries with invalid policy/collection references; verify all errors are collected before raising a single ValidationError
    - **Validates: Requirements 8.1, 8.2**

- [x] 9. Wire everything through CLI and integration tests
  - [x] 9.1 Update CLI update path for custom permissions
    - After standard permission validation, call `validator.validate_custom_permissions(config.custom_permissions, config.collections)`
    - After standard permission application, call `permission_manager.apply_custom_permissions(config.custom_permissions, policy_name_to_id)`
    - Include custom permission counts in summary output: "custom permissions created: N, custom permissions updated: M"
    - _Requirements: 6.4_

  - [x] 9.2 Write integration tests for end-to-end flows
    - Test `--generate` with mocked API containing custom permissions → verify inline C_N references in groups and definitions section
    - Test `--update` with mocked API verifying correct POST/PATCH calls for custom permissions
    - Test `--check` output format with custom permissions displayed inline in policies section
    - _Requirements: 4.1, 5.1, 6.1_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (9 properties total)
- The project uses Hypothesis for property-based testing (already in requirements-dev.txt)
- Key changes from previous tasks: simplified C_COUNTER naming (no sanitization), inline references in groups' Permission_Set strings, updated GroupDefinition with `custom_permission_refs` field, mixed token parsing in config loader, inline display in check command (no separate section)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "4.1"] },
    { "id": 3, "tasks": ["4.2", "5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "5.4", "7.1"] },
    { "id": 5, "tasks": ["7.2", "8.1", "8.3"] },
    { "id": 6, "tasks": ["8.2", "8.4", "9.1"] },
    { "id": 7, "tasks": ["9.2"] }
  ]
}
```
