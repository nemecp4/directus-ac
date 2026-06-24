# Requirements Document

## Introduction

This feature covers a set of CLI improvements to the `directus-ac` tool: renaming the `--check` option to `--fetch`, renaming `--config` to `--permission-file`, implementing a new `--verify` option that compares local permission configuration against the running Directus instance, and updating the README with full `--help` output.

## Glossary

- **CLI**: The `directus-ac` command-line interface defined in `directus_ac/cli.py`.
- **Permission_File**: The YAML configuration file that declares collections, roles, groups, and custom permissions for a Directus instance (previously referred to as "config").
- **Fetch_Command**: The read-only inspection command (previously `--check`) that displays current collections, roles, and permissions from a Directus instance.
- **Verify_Command**: A new command that compares permissions defined in the Permission_File against the running Directus instance and reports whether they match or differ.
- **Directus_Instance**: A running Directus server accessible via its REST API.
- **Permission_Diff**: A structured output showing differences between the locally declared permissions and the actual permissions on the Directus_Instance.

## Requirements

### Requirement 1: Rename --check to --fetch

**User Story:** As a CLI user, I want the read-only inspection option to be named `--fetch`, so that the option name clearly communicates that it fetches data from the Directus instance.

#### Acceptance Criteria

1. THE CLI SHALL accept `--fetch` as a command-line option to trigger the read-only inspection of the Directus_Instance.
2. THE CLI SHALL remove the `--check` option from the argument parser.
3. WHEN `--fetch` is provided, THE CLI SHALL execute the same read-only inspection logic previously triggered by `--check`.
4. THE CLI SHALL include `--fetch` in the mutually exclusive group with `--update` and `--generate`.

### Requirement 2: Rename --config to --permission-file

**User Story:** As a CLI user, I want the config file path option to be named `--permission-file`, so that the option name clearly describes the file's purpose.

#### Acceptance Criteria

1. THE CLI SHALL accept `--permission-file` as a command-line option specifying the path to the YAML permission file.
2. THE CLI SHALL remove the `--config` option from the argument parser.
3. THE CLI SHALL default `--permission-file` to `./directus_ac.yaml` when not specified.
4. WHEN `--permission-file` is provided, THE CLI SHALL use the specified path to load the permission configuration.

### Requirement 3: Implement --verify option

**User Story:** As a CLI user, I want a `--verify` option that compares my local permission file against the running Directus instance, so that I can confirm whether my declared permissions are in sync with the live state.

#### Acceptance Criteria

1. THE CLI SHALL accept `--verify` as a command-line option to trigger the permission verification workflow.
2. THE CLI SHALL include `--verify` in the mutually exclusive group with `--fetch`, `--update`, and `--generate`.
3. WHEN `--verify` is provided, THE Verify_Command SHALL load the Permission_File using the path specified by `--permission-file`.
4. WHEN `--verify` is provided, THE Verify_Command SHALL fetch all permissions from the Directus_Instance, including standard group permissions and custom permissions.
5. WHEN all permissions in the Permission_File match the Directus_Instance, THE Verify_Command SHALL output a message indicating permissions are in sync.
6. WHEN permissions in the Permission_File differ from the Directus_Instance, THE Verify_Command SHALL output a Permission_Diff showing the differences.
7. THE Permission_Diff SHALL indicate permissions that exist in the Permission_File but are missing from the Directus_Instance.
8. THE Permission_Diff SHALL indicate permissions that exist on the Directus_Instance but are not declared in the Permission_File.
9. THE Permission_Diff SHALL indicate permissions where the action set differs between the Permission_File and the Directus_Instance.
10. THE Permission_Diff SHALL include custom permission differences, covering validation rules, field restrictions, and item-level permissions.
11. WHEN permissions are in sync, THE CLI SHALL exit with code 0.
12. WHEN permissions differ, THE CLI SHALL exit with code 1.
13. IF the Permission_File cannot be loaded, THEN THE CLI SHALL report the error and exit with code 1.
14. IF the Directus_Instance is unreachable, THEN THE CLI SHALL report the error and exit with code 1.

### Requirement 4: Update README with full --help output

**User Story:** As a developer or user, I want the README to contain the full `--help` output in its Usage section, so that I can quickly see all available options without running the tool.

#### Acceptance Criteria

1. THE README SHALL include the complete `--help` output of the CLI in the Usage section.
2. THE README SHALL reflect the renamed options (`--fetch` instead of `--check`, `--permission-file` instead of `--config`).
3. THE README SHALL document the new `--verify` option.
4. THE README SHALL present the `--help` output inside a code block.

### Requirement 5: Internal consistency after renames

**User Story:** As a developer, I want all internal references to `--check` and `--config` to be updated throughout the codebase, so that the code is consistent with the new CLI option names.

#### Acceptance Criteria

1. THE CLI module SHALL reference `args.fetch` instead of `args.check` for the read-only inspection flag.
2. THE CLI module SHALL reference `args.permission_file` instead of `args.config` for the file path.
3. THE CLI help text and epilog SHALL reference the new option names `--fetch`, `--permission-file`, and `--verify`.
4. WHEN no mode option is provided, THE CLI SHALL print the help message and exit with code 0.
