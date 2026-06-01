# Requirements Document

## Introduction

This feature improves the custom permissions display in the Directus access control tool by making two changes:
1. Renaming the custom permission naming scheme from `C_N` to `ACTION_C_N` format (e.g., `UPDATE_C_3`), where the action is prepended in uppercase to the existing counter-based name. This change applies everywhere: config YAML storage, the data model, and all outputs.
2. Simplifying the check command output for custom permissions to display only the name (e.g., `UPDATE_C_3`) without any field indicators, validation indicators, or item permission indicators.

## Glossary

- **System**: The directus_ac CLI tool and its modules (generate, check, config, models)
- **Custom_Permission_Name**: The identifier assigned to a custom permission entry, following the `ACTION_C_N` pattern (e.g., `UPDATE_C_3`, `READ_C_1`)
- **Action_Prefix**: The uppercase action string prepended to the custom permission name; one of `CREATE`, `READ`, `UPDATE`, `DELETE`
- **Check_Command**: The read-only inspection command that displays the current state of a Directus instance's access control configuration
- **Config_YAML**: The `directus_ac.yaml` configuration file that stores collections, roles, groups, and custom permissions
- **Permission_Set**: A space-separated string in the config YAML that lists standard keywords and custom permission references for a role on a collection group
- **Custom_Permission_Entry**: A model representing a permission with additional constraints (validation rules, field restrictions, or item-level permissions)

## Requirements

### Requirement 1: Custom Permission Name Generation

**User Story:** As a user, I want custom permission names to include the action prefix, so that I can immediately identify what action a custom permission applies to from its name alone.

#### Acceptance Criteria

1. WHEN the System generates a custom permission name, THE System SHALL produce a name in the format `{ACTION}_C_{COUNTER}` where `{ACTION}` is the uppercase action string and `{COUNTER}` is the sequential integer.
2. THE System SHALL use one of the following values for the Action_Prefix: `CREATE`, `READ`, `UPDATE`, `DELETE`.
3. WHEN the System assigns counters to custom permissions, THE System SHALL use a global counter incremented sequentially across all custom permissions sorted by ascending Directus permission ID.

### Requirement 2: Custom Permission Name Validation

**User Story:** As a user, I want the system to validate that custom permission names follow the new format, so that invalid names are rejected early.

#### Acceptance Criteria

1. THE System SHALL validate that each Custom_Permission_Name matches the pattern `^(CREATE|READ|UPDATE|DELETE)_C_\d+$`.
2. IF a Custom_Permission_Name does not match the required pattern, THEN THE System SHALL raise a validation error with a message indicating the expected format.

### Requirement 3: Config YAML Storage Format

**User Story:** As a user, I want the config YAML to store custom permission names in the new `ACTION_C_N` format, so that the stored configuration is consistent with all other outputs.

#### Acceptance Criteria

1. WHEN the System serializes a config to YAML, THE System SHALL write custom permission names in the `ACTION_C_N` format in the `custom_permissions` section.
2. WHEN the System serializes a config to YAML, THE System SHALL write custom permission references in Permission_Set strings using the `ACTION_C_N` format.
3. WHEN the System loads a config from YAML, THE System SHALL recognize custom permission references matching the `^(CREATE|READ|UPDATE|DELETE)_C_\d+$` pattern in Permission_Set strings.

### Requirement 4: Check Command Custom Permission Display

**User Story:** As a user, I want the check command to display only the custom permission name without any additional indicators, so that the output is concise and easy to read.

#### Acceptance Criteria

1. WHEN the Check_Command formats a custom permission reference for output, THE System SHALL display only the Custom_Permission_Name string.
2. WHEN the Check_Command formats a custom permission reference for output, THE System SHALL omit field restriction indicators.
3. WHEN the Check_Command formats a custom permission reference for output, THE System SHALL omit validation indicators.
4. WHEN the Check_Command formats a custom permission reference for output, THE System SHALL omit item permission indicators.

### Requirement 5: Check Command Name Generation Consistency

**User Story:** As a user, I want the check command to use the same `ACTION_C_N` naming format when detecting and labeling custom permissions from a live Directus instance, so that the output matches the config format.

#### Acceptance Criteria

1. WHEN the Check_Command detects custom permissions from a Directus instance, THE System SHALL assign names using the `ACTION_C_N` format based on each permission's action field.
2. WHEN the Check_Command generates custom permission names, THE System SHALL use the same global counter logic as the generate command (sorted by ascending permission ID).

### Requirement 6: Config Loading Backward Compatibility Pattern

**User Story:** As a user, I want the config loader to correctly parse the new `ACTION_C_N` reference pattern in Permission_Set strings, so that configs with the new format load without errors.

#### Acceptance Criteria

1. WHEN the System parses a Permission_Set string, THE System SHALL classify tokens matching `^(CREATE|READ|UPDATE|DELETE)_C_\d+$` as custom permission references.
2. IF a token in a Permission_Set string does not match a standard keyword or the custom permission reference pattern, THEN THE System SHALL raise a ConfigError with a message identifying the invalid token.
