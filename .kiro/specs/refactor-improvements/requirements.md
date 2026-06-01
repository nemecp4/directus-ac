# Requirements Document

## Introduction

This document specifies requirements for four targeted improvements to the `directus_ac` CLI tool's `check` command: renaming the output section header from "Permissions" to "Policies", replacing `print()` calls with the Python logging module, displaying human-readable policy names instead of numeric IDs, and adding a `--enable-private-collections` CLI flag to optionally include `directus_`-prefixed system collections in the output.

## Glossary

- **Check_Command**: The read-only inspection mode of the `directus_ac` CLI tool, invoked via `--check`, that fetches and displays the access control state of a Directus instance.
- **CLI_Parser**: The argument parsing component (`cli.py`) that registers command-line flags and routes execution to the appropriate command.
- **Policies_Section**: The output section of the check command that displays permissions grouped by role, with policy identifiers as sub-headers.
- **Private_Collection**: A Directus system collection whose name starts with the `directus_` prefix.
- **Policy_Name**: The human-readable `name` field of a `DirectusPolicy` object, as opposed to its numeric `id` or UUID.
- **Logger**: A Python `logging.Logger` instance obtained via `logging.getLogger(__name__)` used for all output in the check module.

## Requirements

### Requirement 1: Rename Section Header to "Policies"

**User Story:** As a user of the check command, I want the permissions section to be labeled "Policies", so that the output aligns with Directus v11+ terminology.

#### Acceptance Criteria

1. WHEN the Check_Command formats the policies section output, THE Check_Command SHALL use "Policies" as the first line of that section
2. THE Check_Command SHALL NOT use "Permissions" as the first line of any section in its output
3. IF the policies section contains no entries, THEN THE Check_Command SHALL display "No policies found" as the empty-state message within that section

### Requirement 2: Replace print() with Logging Module

**User Story:** As a developer, I want all output in the check module to use the Python logging module, so that output is consistent with the rest of the application and can be controlled via logging configuration.

#### Acceptance Criteria

1. THE Check_Command module SHALL obtain a Logger via `logging.getLogger(__name__)` and emit all formatted output (collections, roles, policies sections) using that Logger at INFO level
2. THE Check_Command module SHALL contain zero calls to the built-in `print()` function
3. WHEN the CLI configures logging with `basicConfig(level=INFO, stream=stdout, format="%(message)s")`, THE Logger output SHALL appear on stdout with no additional prefix or formatting beyond the message content
4. WHEN a test captures log records at INFO level for the `directus_ac.check` logger, THE captured records SHALL contain the same section text (Collections, Roles, Policies) that was previously emitted via print()

### Requirement 3: Display Human-Readable Policy Names

**User Story:** As a user of the check command, I want to see human-readable policy names in the Policies section, so that I can understand which policy governs each set of permissions without looking up UUIDs.

#### Acceptance Criteria

1. WHEN formatting the Policies_Section, THE Check_Command SHALL resolve each policy UUID referenced in permission entries to its corresponding Policy_Name by matching against the list of policies retrieved from the Directus instance
2. IF a policy UUID cannot be resolved to a Policy_Name because it is not present in the retrieved policies list, THEN THE Check_Command SHALL display the raw UUID string as the policy identifier in the output
3. THE Policies_Section SHALL NOT display numeric `id` fields as policy identifiers
4. WHEN multiple policies exist for the same role, THE Check_Command SHALL display each policy as a separate sub-header under that role, with its own set of collection-action entries beneath it

### Requirement 4: Add --enable-private-collections CLI Flag

**User Story:** As a user of the check command, I want an opt-in flag to include system collections in the output, so that I can inspect `directus_`-prefixed collections when needed while keeping the default output clean.

#### Acceptance Criteria

1. THE CLI_Parser SHALL accept a `--enable-private-collections` boolean flag that defaults to `False` and requires no argument value
2. WHEN `--enable-private-collections` is not provided, THE Check_Command SHALL exclude all collections whose names start with the case-sensitive prefix `directus_` from the Collections section
3. WHEN `--enable-private-collections` is provided, THE Check_Command SHALL include all collections regardless of prefix in the Collections section
4. IF all collections returned by the server start with the prefix `directus_` and `--enable-private-collections` is not provided, THEN THE Check_Command SHALL display "No collections found" in the Collections section
5. WHEN `--enable-private-collections` is not provided, THE Check_Command SHALL exclude permission entries for collections whose names start with the case-sensitive prefix `directus_` from the Policies section
6. IF a role has no remaining permission entries after filtering collections that start with `directus_` and `--enable-private-collections` is not provided, THEN THE Check_Command SHALL still display that role name without any collection entries beneath it in the Policies section

### Requirement 5: Backward Compatibility

**User Story:** As an existing user of the check command, I want the tool to behave the same by default (aside from cosmetic header changes), so that my workflows are not disrupted.

#### Acceptance Criteria

1. THE CLI_Parser SHALL default `--enable-private-collections` to `False` when the flag is not specified
2. WHEN `--enable-private-collections` is not provided and no other new flags are specified, THE Check_Command SHALL produce output that differs from the pre-refactor version only in: the section header name ("Policies" instead of "Permissions"), the policy identifier format (human-readable Policy_Name instead of numeric ID or UUID), and the exclusion of Private_Collections from the Collections and Policies sections
3. WHEN `--enable-private-collections` is not provided, THE Check_Command SHALL preserve the output structure of three sequential sections (Collections, Roles, Policies) with two-space indentation for items and four-space indentation for sub-items, matching the pre-refactor layout
4. THE Check_Command SHALL preserve the same exit code behavior as the pre-refactor version: exit code 0 on success and exit code 1 on any connection, authentication, or API error
