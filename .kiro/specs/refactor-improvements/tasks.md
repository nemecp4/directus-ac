# Implementation Plan: Refactor Improvements

## Overview

Implement four targeted improvements to the `check` command: rename the section header from "Permissions" to "Policies", replace `print()` with `logging.info()`, display human-readable policy names, and add `--enable-private-collections` CLI flag. Changes touch `check.py`, `cli.py`, and `tests/test_check.py`.

## Tasks

- [x] 1. Rename section header and method, replace print with logging
  - [x] 1.1 Rename `_format_permissions` to `_format_policies` and change section header to "Policies"
    - Rename the method `_format_permissions` to `_format_policies` in `directus_ac/check.py`
    - Change the first line of the output from `"Permissions"` to `"Policies"`
    - Change the empty-state message from `"No permissions found"` to `"No policies found"`
    - Update the `run()` method to call `_format_policies` instead of `_format_permissions`
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Replace all `print()` calls with `logger.info()` in `check.py`
    - Add `import logging` and `logger = logging.getLogger(__name__)` at module level
    - Replace the three `print()` calls in `run()` with `logger.info()` calls
    - Verify no `print()` calls remain in `check.py`
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 1.3 Write property test for section header naming (Property 1)
    - **Property 1: Section header naming**
    - Verify that for any set of permissions/policies/roles, the output section header is always "Policies", never "Permissions"
    - **Validates: Requirements 1.1, 1.2**

  - [x] 1.4 Write property test for output via logging only (Property 2)
    - **Property 2: Output via logging only**
    - Use `ast` module to verify `check.py` contains zero `print()` calls
    - Capture log records at INFO level for `directus_ac.check` logger and verify output content
    - **Validates: Requirements 2.1, 2.2**

- [x] 2. Implement human-readable policy names in Policies section
  - [x] 2.1 Display policy name as sub-header instead of grouping only by role
    - In `_format_policies`, resolve each permission's policy UUID to its `DirectusPolicy.name` field
    - Display each policy as a sub-header (3-space or 4-space indent) under its role, with collection-action entries beneath
    - If a policy UUID cannot be resolved, display the raw UUID string as fallback
    - When multiple policies exist for the same role, show each as a separate sub-header
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 2.2 Write property test for policy name resolution (Property 3)
    - **Property 3: Policy name resolution**
    - For any set of permissions with associated policies that have known names, verify the output displays the human-readable policy name, never a numeric `id`
    - **Validates: Requirements 3.1, 3.3**

  - [x] 2.3 Write property test for unresolvable policy fallback (Property 4)
    - **Property 4: Unresolvable policy fallback**
    - For any permission referencing a policy UUID not in the policies list, verify the raw UUID is displayed
    - **Validates: Requirements 3.2**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add `--enable-private-collections` CLI flag and filtering logic
  - [x] 4.1 Add `--enable-private-collections` argument to CLI parser
    - Add `--enable-private-collections` as a `store_true` flag defaulting to `False` in `build_parser()` in `directus_ac/cli.py`
    - Pass `enable_private_collections=args.enable_private_collections` to `CheckCommand` constructor in the `--check` path
    - _Requirements: 4.1, 5.1_

  - [x] 4.2 Update `CheckCommand.__init__` to accept `enable_private_collections` parameter
    - Add `enable_private_collections: bool = False` parameter to `__init__`
    - Store as `self._enable_private_collections`
    - _Requirements: 4.1_

  - [x] 4.3 Implement collection filtering in `_format_collections`
    - When `self._enable_private_collections` is `False`, filter out collections whose `collection` field starts with `directus_`
    - When `True`, include all collections
    - If all collections are filtered out, display "No collections found"
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 4.4 Implement permission filtering in `_format_policies`
    - When `self._enable_private_collections` is `False`, exclude permission entries for collections starting with `directus_`
    - If a role has no remaining permission entries after filtering, still display the role name without collection entries beneath it
    - _Requirements: 4.5, 4.6_

  - [x] 4.5 Write property test for private collection filtering (Property 5)
    - **Property 5: Private collection filtering (default)**
    - For any list of collections, when `enable_private_collections=False`, no collection starting with `directus_` appears in output
    - **Validates: Requirements 4.2**

  - [x] 4.6 Write property test for private collection inclusion (Property 6)
    - **Property 6: Private collection inclusion (opt-in)**
    - For any list of collections, when `enable_private_collections=True`, all collections appear in output
    - **Validates: Requirements 4.3**

  - [x] 4.7 Write property test for roles with empty permissions after filtering (Property 7)
    - **Property 7: Roles with empty permissions after filtering**
    - For any role with permissions only on `directus_`-prefixed collections, when filtering is active, the role still appears in the Policies section
    - **Validates: Requirements 4.6**

- [x] 5. Update existing tests and verify backward compatibility
  - [x] 5.1 Update existing tests in `tests/test_check.py` to reflect new behavior
    - Update all assertions referencing `"Permissions"` header to `"Policies"`
    - Update tests to capture log output instead of `capsys` stdout (use `caplog` fixture or logging capture)
    - Update `_format_permissions` references to `_format_policies`
    - Add test for `enable_private_collections` parameter in `CheckCommand.__init__`
    - Verify output structure preserves three sections (Collections, Roles, Policies) with correct indentation
    - _Requirements: 5.2, 5.3, 5.4_

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The existing `logging.basicConfig` in `cli.py` already configures INFO-level output to stdout with `%(message)s` format, so no changes needed there beyond passing the new flag

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "4.1", "4.2"] },
    { "id": 3, "tasks": ["4.3", "4.4"] },
    { "id": 4, "tasks": ["4.5", "4.6", "4.7", "5.1"] }
  ]
}
```
