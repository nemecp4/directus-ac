# Implementation Plan: CLI Refactor & Verify

## Overview

Refactor the CLI by renaming `--check` → `--fetch` and `--config` → `--permission-file`, add a new `--verify` command that compares local permissions against a live Directus instance, update all tests, and refresh the README. Implementation is in Python using the existing project structure (argparse, pydantic, dataclasses, pytest, hypothesis).

## Tasks

- [ ] 1. Rename CLI options and update argument parser
  - [ ] 1.1 Rename `--check` to `--fetch` and `--config` to `--permission-file` in `directus_ac/cli.py`
    - Rename the `--check` argument to `--fetch` in `build_parser()`, keeping `action="store_true"`
    - Rename `--config` to `--permission-file`, keeping `default="./directus_ac.yaml"`; argparse stores this as `args.permission_file`
    - Add `--verify` to the mutually exclusive mode group with `action="store_true"`
    - Update the epilog to reference `--fetch`, `--permission-file`, and `--verify`
    - Update the dispatch logic in `main()`: replace `args.check` with `args.fetch`, replace `args.config` with `args.permission_file`
    - Add the `--verify` dispatch branch (initially just a placeholder that imports and calls `VerifyCommand`)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 5.1, 5.2, 5.3, 5.4_

  - [ ] 1.2 Update `tests/test_cli.py` to reflect renamed options
    - Replace all references to `args.check` with `args.fetch`
    - Replace all references to `args.config` with `args.permission_file`
    - Replace all `"--check"` strings in `sys.argv` lists with `"--fetch"`
    - Replace all `"--config"` strings in `sys.argv` lists with `"--permission-file"`
    - Update help text assertions (epilog, flag descriptions) to expect new names
    - Add a test that `--verify` is in the mutually exclusive group (exits 2 when combined with `--fetch`)
    - _Requirements: 1.1, 1.2, 1.4, 2.1, 2.2, 5.1, 5.2, 5.3_

- [ ] 2. Implement VerifyCommand and diff engine
  - [ ] 2.1 Create `directus_ac/verify.py` with data models and normalisation functions
    - Define `PermissionTriple` dataclass with fields: `role`, `collection`, `action`, `fields`, `validation`, `permissions`
    - Define `PermissionDiffEntry` dataclass with fields: `role`, `collection`, `action`, `diff_type`, `detail`
    - Define `PermissionDiff` dataclass with fields: `in_sync`, `entries`
    - Implement `build_local_triples(config: DirectusACConfig) -> list[PermissionTriple]`:
      - Expand groups: for each group, for each collection, for each role/keywords pair, emit a triple per keyword (mapping WRITE→create, READ→read, UPDATE→update, DELETE→delete)
      - For custom permissions referenced via `custom_permission_refs`, look up the `CustomPermissionEntry` by name and emit a triple including metadata (fields, validation, permissions)
    - Implement `build_remote_triples(permissions, policies, roles) -> list[PermissionTriple]`:
      - Build policy→role mapping from policies and roles
      - For each permission, resolve its policy to role name(s) and emit a triple per role
      - Include metadata (fields, validation, permissions) when non-default
    - Implement `compute_diff(local, remote) -> PermissionDiff`:
      - Key triples by `(role, collection, action)`
      - Triples in local but not remote → `missing_remote`
      - Triples in remote but not local → `missing_local`
      - Triples in both but with different metadata → `action_mismatch`
      - Set `in_sync = len(entries) == 0`
    - _Requirements: 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

  - [ ] 2.2 Implement `VerifyCommand` class in `directus_ac/verify.py`
    - Constructor takes `client: DirectusClient` and `config: DirectusACConfig`
    - `run()` method:
      - Fetches permissions, policies, roles from client
      - Calls `build_local_triples(config)` and `build_remote_triples(...)`
      - Calls `compute_diff(local, remote)`
      - Returns `PermissionDiff`
    - _Requirements: 3.3, 3.4, 3.5_

  - [ ] 2.3 Wire `--verify` dispatch in `directus_ac/cli.py`
    - In `main()`, add the `elif args.verify:` branch after the `args.fetch` branch
    - Load config via `load_config(args.permission_file)`
    - Instantiate `DirectusClient` and `VerifyCommand`
    - Call `verify_cmd.run()` and get the `PermissionDiff`
    - Print output (in-sync message or formatted diff)
    - Exit 0 if `in_sync`, exit 1 if differences found
    - _Requirements: 3.1, 3.3, 3.5, 3.6, 3.11, 3.12, 3.13, 3.14_

  - [ ]* 2.4 Write property test for mutual exclusion of mode flags
    - **Property 1: Mutual exclusion of mode flags**
    - **Validates: Requirements 1.4, 3.2**
    - Create `tests/test_cli_mutual_exclusion_property.py`
    - Use Hypothesis to generate all pairs from {`--fetch`, `--update`, `--generate`, `--verify`} and assert argparse raises SystemExit(2)
    - `@settings(max_examples=100)`

  - [ ]* 2.5 Write property test for identical permissions → in-sync
    - **Property 2: Identical permissions produce in-sync result**
    - **Validates: Requirements 3.5**
    - Create `tests/test_verify_insync_property.py`
    - Use Hypothesis to generate arbitrary `DirectusACConfig` instances, build both local and (identical) remote triples, assert `compute_diff` returns `in_sync=True` and empty entries
    - `@settings(max_examples=100)`

  - [ ]* 2.6 Write property test for set difference completeness
    - **Property 3: Set difference completeness**
    - **Validates: Requirements 3.6, 3.7, 3.8**
    - Create `tests/test_verify_diff_completeness_property.py`
    - Use Hypothesis to generate two arbitrary lists of `PermissionTriple`, assert every local-only triple appears as `missing_remote`, every remote-only triple appears as `missing_local`, and `in_sync=False` when sets differ
    - `@settings(max_examples=100)`

  - [ ]* 2.7 Write property test for metadata mismatch detection
    - **Property 4: Metadata mismatch detection**
    - **Validates: Requirements 3.9, 3.10**
    - Create `tests/test_verify_metadata_mismatch_property.py`
    - Use Hypothesis to generate triples sharing the same key but differing metadata, assert `action_mismatch` entries appear
    - `@settings(max_examples=100)`

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Unit tests for VerifyCommand and output formatting
  - [ ] 4.1 Write unit tests for `build_local_triples`, `build_remote_triples`, and `compute_diff`
    - Create `tests/test_verify.py`
    - Test `build_local_triples` with a config containing groups and custom permissions
    - Test `build_remote_triples` with mocked API data (permissions, policies, roles)
    - Test `compute_diff` with known inputs: identical sets → in-sync, differing sets → correct entries
    - Test edge case: empty config vs empty remote → in-sync
    - Test metadata mismatch: same triple key but different fields/validation → action_mismatch
    - _Requirements: 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

  - [ ] 4.2 Write unit tests for `--verify` CLI integration
    - Add tests in `tests/test_cli.py` (or a new `tests/test_cli_verify.py`)
    - Test `--verify` dispatches to `VerifyCommand.run()` (mock client and config)
    - Test exit code 0 when in-sync
    - Test exit code 1 when differences found
    - Test config file not found → error + exit 1
    - Test connection error → error + exit 1
    - _Requirements: 3.1, 3.5, 3.11, 3.12, 3.13, 3.14_

- [ ] 5. Update README documentation
  - [ ] 5.1 Update `README.md` Usage section with new `--help` output
    - Replace the existing Usage section content with the full `--help` output from the refactored CLI
    - Ensure the output shows `--fetch` (not `--check`), `--permission-file` (not `--config`), and `--verify`
    - Present the `--help` output inside a code block
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The `WRITE` keyword in the config maps to the `create` action in Directus API when building triples

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.4"] },
    { "id": 3, "tasks": ["2.3", "2.5", "2.6", "2.7"] },
    { "id": 4, "tasks": ["4.1", "4.2"] },
    { "id": 5, "tasks": ["5.1"] }
  ]
}
```
