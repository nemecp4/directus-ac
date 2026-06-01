# Implementation Plan: directus-check-command

## Overview

Add a `--check` CLI flag to `directus-ac` that connects to a Directus instance and prints a read-only summary of collections, roles, and permissions grouped by role. The implementation creates a new `check.py` module with a `CheckCommand` class, wires it into the existing CLI, and adds comprehensive tests.

## Tasks

- [x] 1. Create the CheckCommand module with formatting logic
  - [x] 1.1 Create `directus_ac/check.py` with `CheckCommand` class
    - Define `CheckCommand.__init__(self, client: DirectusClient)`
    - Implement `run()` method that fetches collections, roles, and permissions via the client and prints formatted output to stdout
    - Implement `_format_collections(collections)` — returns "Collections" header followed by one collection name per line, or "  No collections found" if empty
    - Implement `_format_roles(roles)` — returns "Roles" header followed by one line per role with name and id separated by a space, or "  No roles found" if empty
    - Implement `_format_permissions(permissions, roles)` — returns "Permissions" header, groups permissions by role, resolves UUIDs to names via role list (falls back to UUID), indents collection-actions under each role, or "  No permissions found" if empty
    - Preserve input ordering in all sections
    - _Requirements: 1.1, 1.2, 2.2, 2.3, 3.2, 3.3, 4.2, 4.3, 4.4, 4.5, 7.1, 7.2, 7.3, 7.4, 7.6_

  - [x] 1.2 Write property test for collections formatting
    - **Property 1: Collections section formatting**
    - **Validates: Requirements 2.2, 7.1**

  - [x] 1.3 Write property test for roles formatting
    - **Property 2: Roles section formatting**
    - **Validates: Requirements 3.2, 7.2**

  - [x] 1.4 Write property test for permission grouping structure
    - **Property 3: Permission grouping structure**
    - **Validates: Requirements 4.2, 7.3, 7.4**

  - [x] 1.5 Write property test for role UUID resolution
    - **Property 4: Role UUID resolution in permissions display**
    - **Validates: Requirements 4.4, 4.5**

  - [x] 1.6 Write property test for output order preservation
    - **Property 5: Output order preservation**
    - **Validates: Requirements 7.6**

- [x] 2. Wire CheckCommand into the CLI
  - [x] 2.1 Add `--check` flag to `build_parser()` in `cli.py`
    - Add `--check` argument with `action="store_true"`, `default=False`
    - Help text: "Read-only: display current collections, roles, and permissions"
    - _Requirements: 1.3, 1.4_

  - [x] 2.2 Add early branch in `main()` for `--check` path
    - After credential resolution (URL + token), check `args.check`
    - If true: instantiate `DirectusClient`, create `CheckCommand`, call `run()`, exit 0
    - Skip config loading, validation, and permission application
    - Wrap in existing `DirectusACError` try/except for error handling (exit 1 on error)
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 7.5, 7.7_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add unit tests for the check command
  - [x] 4.1 Write unit tests for CLI argument parsing with `--check`
    - Test `--check` flag is recognized by the parser
    - Test `--check` works alongside `--url` and `--token`
    - Test `--check` does not require `--config`
    - _Requirements: 1.3, 1.4_

  - [x] 4.2 Write unit tests for credential resolution in check mode
    - Test `--url` overrides `DIRECTUS_URL` env var
    - Test `--token` overrides `DIRECTUS_TOKEN` env var
    - Test missing URL (no arg, no env) exits with code 1 and error to stderr
    - Test missing token (no arg, no env) exits with code 1 and error to stderr
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 4.3 Write unit tests for CheckCommand.run() with mocked client
    - Test successful output with collections, roles, and permissions
    - Test empty collections/roles/permissions produce "No X found" messages
    - Test only GET requests are issued (read-only verification)
    - Test exit code 0 on success
    - _Requirements: 1.1, 1.2, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3_

  - [x] 4.4 Write unit tests for error scenarios in check mode
    - Test connection failure (ConnectionError) exits 1 with error to stderr
    - Test auth failure (AuthError) exits 1 with error to stderr
    - Test API error exits 1 with error to stderr
    - _Requirements: 1.6, 2.4, 3.4, 4.6, 6.1, 6.2, 6.3_

- [x] 5. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation reuses the existing `DirectusClient` and exception hierarchy — no new models or exceptions are needed
- Python is the implementation language (matching the existing codebase and design document)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["2.2", "1.2", "1.3", "1.4", "1.5", "1.6"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3", "4.4"] }
  ]
}
```
