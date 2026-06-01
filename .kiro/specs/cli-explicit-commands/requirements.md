# Requirements Document

## Introduction

Refactor the `directus-ac` CLI so that the permission-apply pipeline is no longer the default behavior. Instead, both operational modes (`--check` and `--update`) become explicit flags, and invoking `directus-ac` without either flag prints help text and exits cleanly. This makes the CLI safer by preventing accidental permission updates and clearer by surfacing both modes in the help output.

## Glossary

- **CLI**: The `directus-ac` command-line interface entry point (`directus_ac.cli:main`)
- **Parser**: The `argparse.ArgumentParser` instance that defines and parses CLI arguments
- **Update_Mode**: The operational mode triggered by `--update` that applies permissions from a config file to a Directus instance
- **Check_Mode**: The operational mode triggered by `--check` that performs read-only inspection of the current Directus access control state
- **Common_Options**: The shared CLI options `--config`, `--url`, `--token`, and `--create-roles` that apply to one or both modes
- **Help_Text**: The usage information printed by the Parser when no command flag is provided or when `--help` is used

## Requirements

### Requirement 1: No-Flag Behavior

**User Story:** As an operator, I want the CLI to print help and exit when I run it without a command flag, so that I do not accidentally apply permissions.

#### Acceptance Criteria

1. WHEN the CLI is invoked without `--check` or `--update`, THE CLI SHALL print Help_Text describing both command modes and all Common_Options to standard output
2. WHEN the CLI is invoked without `--check` or `--update`, THE CLI SHALL exit with code 0
3. WHEN the CLI is invoked with only Common_Options but without `--check` or `--update`, THE CLI SHALL print Help_Text and exit with code 0

### Requirement 2: Update Flag

**User Story:** As an operator, I want an explicit `--update` flag to apply permissions, so that the destructive operation requires deliberate intent.

#### Acceptance Criteria

1. WHEN the `--update` flag is provided, THE CLI SHALL execute the permission-apply pipeline (load config, validate collections, validate roles, apply permissions)
2. WHEN the `--update` flag is provided and the pipeline completes successfully, THE CLI SHALL print a summary of created and updated permissions to standard output and exit with code 0
3. IF the `--update` flag is provided and the pipeline encounters an error, THEN THE CLI SHALL print an error message to standard error and exit with code 1
4. WHEN the `--update` flag is provided, THE CLI SHALL accept Common_Options (`--config`, `--url`, `--token`, `--create-roles`)

### Requirement 3: Check Flag Continuity

**User Story:** As an operator, I want `--check` to continue working as before, so that my existing workflows are not disrupted.

#### Acceptance Criteria

1. WHEN the `--check` flag is provided, THE CLI SHALL perform read-only inspection of the Directus instance (collections, roles, permissions) and print results to standard output
2. WHEN the `--check` flag is provided and the inspection completes successfully, THE CLI SHALL exit with code 0
3. IF the `--check` flag is provided and an error occurs, THEN THE CLI SHALL print an error message to standard error and exit with code 1
4. WHEN the `--check` flag is provided, THE CLI SHALL accept `--url` and `--token` options for specifying connection details

### Requirement 4: Mutual Exclusivity

**User Story:** As an operator, I want the CLI to reject conflicting flags, so that I cannot accidentally trigger both modes at once.

#### Acceptance Criteria

1. WHEN both `--check` and `--update` are provided simultaneously, THE CLI SHALL print an error message indicating the flags are mutually exclusive to standard error
2. WHEN both `--check` and `--update` are provided simultaneously, THE CLI SHALL exit with code 2

### Requirement 5: Create-Roles Relevance

**User Story:** As an operator, I want `--create-roles` to only apply during updates, so that its behavior is predictable.

#### Acceptance Criteria

1. WHEN `--create-roles` is provided with `--update`, THE CLI SHALL create missing roles during the permission-apply pipeline
2. WHEN `--create-roles` is provided with `--check`, THE CLI SHALL ignore the `--create-roles` flag and proceed with the read-only inspection without error

### Requirement 6: Help Text Content

**User Story:** As an operator, I want the help text to clearly describe both modes, so that I understand how to use the CLI.

#### Acceptance Criteria

1. THE Help_Text SHALL include a description of the `--update` flag and its purpose
2. THE Help_Text SHALL include a description of the `--check` flag and its purpose
3. THE Help_Text SHALL include descriptions of all Common_Options (`--config`, `--url`, `--token`, `--create-roles`)
4. THE Help_Text SHALL indicate that one of `--check` or `--update` is required to perform an operation

### Requirement 7: Exit Codes

**User Story:** As an operator, I want consistent exit codes, so that I can use the CLI in scripts reliably.

#### Acceptance Criteria

1. THE CLI SHALL exit with code 0 on successful completion of any mode (check, update, or help display)
2. THE CLI SHALL exit with code 1 when a runtime error occurs (connection failure, authentication error, config error, API error)
3. THE CLI SHALL exit with code 2 when invalid argument combinations are provided (mutually exclusive flags)
