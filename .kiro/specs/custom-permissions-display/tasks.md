# Implementation Plan: Custom Permissions Display

## Overview

Rename the custom permission naming scheme from `C_N` to `ACTION_C_N` (e.g., `UPDATE_C_3`) and simplify the check command output to display only the permission name without field/validation/permission indicators. Changes span `generate.py`, `models.py`, `check.py`, and `config.py`.

## Tasks

- [ ] 1. Update name generation and model validation
  - [-] 1.1 Update `generate_permission_name` signature and implementation in `directus_ac/generate.py`
    - Change signature from `generate_permission_name(counter: int)` to `generate_permission_name(action: str, counter: int)`
    - Implementation: `return f"{action.upper()}_C_{counter}"`
    - Update docstring to reflect new format
    - _Requirements: 1.1, 1.2_

  - [ ] 1.2 Update `CustomPermissionEntry.validate_name_pattern` in `directus_ac/models.py`
    - Change regex from `^C_\d+$` to `^(CREATE|READ|UPDATE|DELETE)_C_\d+$`
    - Update error message to reference `ACTION_C_N` format
    - _Requirements: 2.1, 2.2_

  - [ ]* 1.3 Write property test for name generation format (Property 1)
    - **Property 1: Name generation produces valid ACTION_C_N format**
    - **Validates: Requirements 1.1, 1.2**

  - [ ]* 1.4 Write property test for name validation (Property 3)
    - **Property 3: Name validation accepts only valid ACTION_C_N patterns**
    - **Validates: Requirements 2.1, 2.2**

- [ ] 2. Update callers of `generate_permission_name`
  - [~] 2.1 Update `Generator.generate()` in `directus_ac/generate.py`
    - Pass `perm.action` as the first argument to `generate_permission_name(perm.action, counter)`
    - _Requirements: 1.1, 1.3_

  - [~] 2.2 Update `CheckCommand._format_policies()` in `directus_ac/check.py`
    - Pass `perm_obj.action` (from `perm_by_id`) as the first argument to `generate_permission_name(perm_obj.action, counter)`
    - _Requirements: 5.1, 5.2_

  - [ ]* 2.3 Write property test for counter assignment (Property 2)
    - **Property 2: Counter assignment is sequential by ascending permission ID**
    - **Validates: Requirements 1.3, 5.2**

  - [ ]* 2.4 Write property test for check command name consistency (Property 6)
    - **Property 6: Check command assigns ACTION_C_N names consistent with generate**
    - **Validates: Requirements 5.1, 5.2**

- [ ] 3. Simplify check command display
  - [~] 3.1 Simplify `_format_custom_ref` in `directus_ac/check.py`
    - Replace the method body to return only the `name` parameter
    - Remove field, validation, and item permission indicator logic
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 3.2 Write property test for format custom ref (Property 5)
    - **Property 5: Format custom ref returns only the name**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

- [ ] 4. Update config parser pattern and validation
  - [~] 4.1 Update `_CUSTOM_REF_PATTERN` in `directus_ac/config.py`
    - Change from `re.compile(r"^C_\d+$")` to `re.compile(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$")`
    - _Requirements: 6.1, 6.2_

  - [~] 4.2 Update `_parse_custom_permissions` error message in `directus_ac/config.py`
    - Change error message from `"Must match pattern C_N (e.g., C_1, C_2)"` to `"Must match pattern ACTION_C_N (e.g., UPDATE_C_1, READ_C_2)"`
    - _Requirements: 2.2, 6.2_

  - [ ]* 4.3 Write property test for Permission_Set parser (Property 7)
    - **Property 7: Permission_Set parser classifies ACTION_C_N tokens as custom refs**
    - **Validates: Requirements 6.1, 6.2**

- [~] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Integration verification
  - [~] 6.1 Wire together and verify round-trip consistency
    - Run existing tests to confirm `serialize_config` → `load_config` round-trip works with new `ACTION_C_N` names
    - Verify that generated configs with custom permissions serialize and reload correctly
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 6.2 Write property test for config round-trip (Property 4)
    - **Property 4: Config serialization round-trip preserves custom permission data**
    - **Validates: Requirements 3.1, 3.2, 3.3**

- [~] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The `_format_custom_ref` signature remains unchanged; only the body is simplified

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1", "2.2", "3.1", "4.1", "4.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.2", "4.3"] },
    { "id": 3, "tasks": ["6.1"] },
    { "id": 4, "tasks": ["6.2"] }
  ]
}
```
