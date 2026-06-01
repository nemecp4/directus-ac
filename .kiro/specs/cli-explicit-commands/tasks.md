# Implementation Plan: CLI Explicit Commands

## Overview

Refactor `directus_ac/cli.py` so that both `--check` and `--update` are explicit flags in a mutually exclusive group, bare invocation prints help and exits 0, and all existing tests are updated to account for the new behavior.

## Tasks

- [x] 1. Refactor `build_parser()` to add `--update` and mutually exclusive group
  - [x] 1.1 Add `--update` flag and move `--check` into a mutually exclusive group
    - Open `directus_ac/cli.py` and modify `build_parser()`
    - Create a mutually exclusive group via `parser.add_mutually_exclusive_group()`
    - Move the existing `--check` argument into the group
    - Add `--update` as a `store_true` flag with help text: `"Apply permissions from config to the Directus instance"`
    - Update parser `description` to `"Manage Directus access control permissions declaratively."`
    - Add `epilog="One of --check or --update is required to perform an operation."`
    - _Requirements: 4.1, 4.2, 6.1, 6.2, 6.3, 6.4_

- [x] 2. Refactor `main()` to add no-flag guard and `--update` routing
  - [x] 2.1 Add no-flag guard that prints help and exits 0
    - In `main()`, after `args = parser.parse_args()`, add a check: if neither `args.check` nor `args.update` is set, call `parser.print_help()` and `sys.exit(0)`
    - Store the parser in a local variable so `print_help()` can be called after parsing
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 2.2 Route `--update` flag to the existing permission-apply pipeline
    - Wrap the existing pipeline code (load config, validate, apply) in an `elif args.update:` branch
    - The pipeline logic itself does not change — only the conditional routing
    - Ensure `--create-roles` is still respected in the update path
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.1_

- [x] 3. Update and add tests in `test_cli.py`
  - [x] 3.1 Update existing tests to pass `--update` or `--check` where needed
    - Review `TestCheckFlagParsing` — existing tests already pass `--check`, so they should still work
    - Review `TestCredentialResolutionCheckMode` — these already use `--check`, should still pass
    - Review `TestCheckModeErrorScenarios` — these already use `--check`, should still pass
    - Run the test suite to confirm existing tests pass with the refactored parser
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Add tests for no-flag behavior
    - Test bare invocation (no flags): assert exits 0, stdout contains `--check` and `--update`
    - Test common options only (`--config x.yaml`): assert exits 0, stdout contains help text
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 3.3 Add tests for `--update` flag
    - Test `--update` with valid credentials (mock pipeline): assert pipeline executes, exits 0
    - Test `--update` with pipeline error: assert exits 1, error on stderr
    - Test `--update --create-roles`: assert `args.create_roles` is True and pipeline uses it
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 5.1_

  - [x] 3.4 Add test for mutual exclusivity
    - Test `--check --update` together: assert exits 2, stderr contains "not allowed"
    - _Requirements: 4.1, 4.2_

  - [x] 3.5 Add test for `--create-roles` ignored with `--check`
    - Test `--check --create-roles`: assert check runs normally, `--create-roles` has no effect
    - _Requirements: 5.2_

  - [x] 3.6 Add test for help text content
    - Assert help output contains descriptions for `--update`, `--check`, `--config`, `--url`, `--token`, `--create-roles`
    - Assert help output contains epilog indicating one mode is required
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- No property-based tests are included — the design explicitly states PBT does not apply to this CLI flag refactor
- Each task references specific requirements for traceability
- Existing `--check` tests should pass without modification since `--check` remains valid
- The mutual exclusivity is handled by argparse's built-in mechanism (exit code 2)
- Checkpoints ensure incremental validation

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6"] }
  ]
}
```
