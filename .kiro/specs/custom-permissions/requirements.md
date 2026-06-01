# Requirements Document

## Introduction

This feature adds support for "custom permissions" to the directus-ac CLI tool. In Directus v11+, a policy can have multiple permission entries for the same collection+action combination, each with different validation rules, field-level restrictions, or item-level conditions. The current tool collapses all permissions into a single Permission_Set per role+collection, losing these custom entries. This feature introduces a `custom_permissions` top-level section in the YAML config to define custom permission entries, which are then referenced inline within the groups' permissions section alongside standard keywords (READ, WRITE, UPDATE, DELETE). Custom permissions use a simple naming pattern (`C_${COUNTER}`, e.g., `C_1`, `C_2`, `C_3`) since the policy and collection context is already present in the group and custom permission record.

## Glossary

- **CLI**: The directus-ac command-line interface tool
- **Custom_Permission**: A permission entry in Directus that has additional constraints (validation rules, field restrictions, or item-level permissions) beyond the basic action, or where the same policy+collection+action combination appears multiple times with different rules
- **Standard_Permission**: A permission entry that maps cleanly to a single action (read, create, update, delete) on a collection within a policy, with no additional constraints
- **Permission_Name**: A generated identifier for a Custom_Permission following the pattern `C_${COUNTER}` where COUNTER is a 1-based global integer (e.g., `C_1`, `C_2`, `C_3`)
- **Permission_Set**: A space-separated string of permission keywords and custom permission references assigned to a role for a group of collections (e.g., `READ WRITE C_1 C_2`)
- **DirectusPermission**: The Pydantic model representing a permission entry from the Directus API, containing id, policy, collection, action, and optionally fields, validation, and permissions (item-level) attributes
- **Generator**: The class responsible for fetching Directus state and building a DirectusACConfig
- **CheckCommand**: The class responsible for read-only inspection of Directus access control state
- **PermissionManager**: The class responsible for applying permissions from config to Directus
- **DirectusACConfig**: The top-level Pydantic model representing the YAML config file schema

## Requirements

### Requirement 1: Detect Custom Permissions

**User Story:** As a CLI user, I want the tool to distinguish custom permissions from standard permissions, so that custom permissions are not lost or collapsed during generation.

#### Acceptance Criteria

1. WHEN the Generator fetches permissions from Directus, THE Generator SHALL identify a permission as a Custom_Permission when the permission entry contains a non-null `validation` attribute, a `fields` attribute that is non-null and not equal to `["*"]`, or a non-null `permissions` (item-level) attribute
2. WHEN the Generator fetches permissions from Directus and multiple permission entries exist for the same policy+collection+action combination, THE Generator SHALL identify ALL entries in that combination as Custom_Permissions
3. WHEN a permission is identified as a Custom_Permission, THE Generator SHALL represent the Custom_Permission as a reference (e.g., `C_1`) in the Permission_Set string of the corresponding role+collection group, alongside any standard keywords
4. IF a role+collection pair has both Standard_Permissions and Custom_Permissions, THEN THE Generator SHALL include both the Standard_Permission keywords and the Custom_Permission references in the Permission_Set for that role+collection in the groups section (e.g., `READ WRITE C_1`)

---

### Requirement 2: Generate Permission Names

**User Story:** As a CLI user, I want each custom permission to have a unique generated name, so that I can reference and manage them individually in the config file.

#### Acceptance Criteria

1. WHEN a Custom_Permission is detected, THE Generator SHALL produce a Permission_Name using the pattern `C_${COUNTER}` (e.g., `C_1`, `C_2`, `C_3`)
2. THE Generator SHALL assign COUNTER values as a single global sequence starting at 1 and incrementing by 1 for each Custom_Permission across the entire config, where Custom_Permissions are ordered by their Directus permission `id` (ascending) to ensure deterministic naming across runs
3. THE Generator SHALL produce unique Permission_Name values across all Custom_Permissions within a single config (no duplicates), guaranteed by the global COUNTER sequence
4. THE Generator SHALL use the Permission_Name as the reference token when embedding custom permissions inline in the groups' Permission_Set strings

---

### Requirement 3: Custom Permissions Config Section

**User Story:** As a CLI user, I want custom permissions defined in a dedicated section of the YAML config, so that their detailed attributes (validation, fields, permissions) are clearly specified and referenced by the groups.

#### Acceptance Criteria

1. THE CLI SHALL accept an optional top-level `custom_permissions` key in the YAML config file, where the value is a list of permission definition mappings that are referenced by Permission_Name from within the groups' Permission_Set strings
2. WHEN the `custom_permissions` key is present and contains a non-empty list, THE config loader SHALL parse each entry as a mapping containing required fields `name` (string matching `C_${COUNTER}` pattern), `policy` (string, 1–255 characters), `collection` (string, 1–255 characters), `action` (one of `create`, `read`, `update`, `delete`), and optional fields `validation` (mapping), `fields` (list of strings), and `permissions` (mapping), with a maximum of 500 entries in the list
3. WHEN the `custom_permissions` key is absent, THE config loader SHALL treat the config as having zero custom permissions and not raise an error
4. IF a `custom_permissions` entry is missing the `name`, `policy`, `collection`, or `action` field, THEN THE config loader SHALL raise a ConfigError with a message identifying the missing field name and the zero-based entry index
5. IF the `custom_permissions` value is not a list, THEN THE config loader SHALL raise a ConfigError with a message indicating that `custom_permissions` must be a list
6. IF a `custom_permissions` entry contains an `action` value that is not one of `create`, `read`, `update`, or `delete`, THEN THE config loader SHALL raise a ConfigError with a message identifying the invalid action value and the entry index

---

### Requirement 4: Generate Command Custom Permissions Output

**User Story:** As a CLI user, I want `--generate` to include custom permissions inline in the groups and defined in the `custom_permissions` section, so that the generated config fully represents the Directus state.

#### Acceptance Criteria

1. WHEN the Generator produces a config and at least one permission entry is classified as a Custom_Permission, THE Generator SHALL include the Custom_Permission references (e.g., `C_1`, `C_2`) inline in the Permission_Set strings of the corresponding role+collection groups alongside standard keywords
2. WHEN a Custom_Permission is serialized in the `custom_permissions` section, THE Serializer SHALL output the `name` as the `C_${COUNTER}` identifier, the `policy` attribute as the human-readable policy name, the `collection` attribute as the collection name, the `action` attribute as the Directus action string (e.g., `read`, `create`, `update`, `delete`), and any `validation`, `fields`, or `permissions` attribute whose value is not null and not empty (where empty means `{}` for objects or `[]` for lists)
3. WHEN no permission entries have non-default `validation`, `fields`, or `permissions` attributes, THE Generator SHALL omit the `custom_permissions` key from the output YAML entirely and the groups' Permission_Set strings SHALL contain only standard keywords
4. THE Serializer SHALL output the `custom_permissions` section after the `groups` section in the YAML file, maintaining the key order: `collections`, `roles`, `groups`, `custom_permissions`
5. WHEN a Custom_Permission references a policy that cannot be resolved to a known policy name, THE Generator SHALL skip that permission entry and continue processing

---

### Requirement 5: Check Command Custom Permissions Display

**User Story:** As a CLI user, I want `--check` to display custom permissions inline with standard permissions in the policies section, so that I can see the full access control state at a glance.

#### Acceptance Criteria

1. WHEN the CheckCommand encounters Custom_Permissions for a role+collection, THE CheckCommand SHALL display the Custom_Permission references (e.g., `C_1`, `C_2`) inline alongside standard action names in the policies section output for that role+collection
2. WHEN displaying permissions for a collection under a policy, THE CheckCommand SHALL show both standard actions and Custom_Permission references in a single comma-separated list (e.g., `collection: read, create, C_1, C_2`)
3. WHEN a Custom_Permission has non-null `fields`, THE CheckCommand SHALL append to the Custom_Permission reference a comma-separated list of the restricted field names enclosed in parentheses, prefixed with "fields:" (e.g., `C_1 fields:(title,body)`)
4. WHEN a Custom_Permission has non-null `validation` or non-null `permissions` (item-level), THE CheckCommand SHALL append to the Custom_Permission reference an indicator showing which constraints are present (e.g., "has validation", "has item permissions")
5. WHEN no Custom_Permissions exist, THE CheckCommand SHALL display only standard actions in the policies section without any custom permission references or separate section

---

### Requirement 6: Update Command Custom Permissions Application

**User Story:** As a CLI user, I want `--update` to create or update custom permissions from the config, so that my declarative config fully controls the Directus state.

#### Acceptance Criteria

1. WHEN the PermissionManager processes the `custom_permissions` section, THE PermissionManager SHALL resolve each entry's `policy` name to a policy_id using the existing policy lookup, then create the Custom_Permission entry in Directus via `POST /permissions` with the resolved policy_id, collection, action, and any non-null validation, fields, or permissions attributes
2. WHEN a Custom_Permission already exists in Directus (matched by resolved policy_id, collection, and action where the existing entry also has non-null validation, fields, or permissions attributes), THE PermissionManager SHALL update the existing entry via `PATCH /permissions/{id}` with the validation, fields, and permissions values from the config rather than creating a duplicate
3. IF the Directus API returns an error while applying a Custom_Permission, THEN THE PermissionManager SHALL raise an APIError with a message including the Permission_Name, the collection, the action, and the underlying error detail from the API response
4. WHEN the update completes, THE PermissionManager SHALL include custom permission counts as separate "custom permissions created" and "custom permissions updated" integer values in the summary output, distinct from the standard permission counts
5. IF a `custom_permissions` entry references a policy name that cannot be resolved to an existing policy_id, THEN THE PermissionManager SHALL raise an APIError with a message identifying the unresolvable policy name and the Permission_Name of the failing entry

---

### Requirement 7: Fetch Extended Permission Attributes from API

**User Story:** As a CLI user, I want the Directus client to retrieve the full permission payload including validation and field restrictions, so that custom permissions can be accurately detected and reproduced.

#### Acceptance Criteria

1. WHEN the DirectusClient fetches permissions, THE DirectusClient SHALL include the query parameter `fields` with the value `id,policy,collection,action,fields,validation,permissions` in the `GET /permissions?limit=-1` request
2. THE DirectusPermission model SHALL include an optional `fields` attribute of type list of strings that defaults to None when the attribute is absent or null in the API response
3. THE DirectusPermission model SHALL include an optional `validation` attribute of type dictionary that defaults to None when the attribute is absent or null in the API response
4. THE DirectusPermission model SHALL include an optional `permissions` attribute of type dictionary that defaults to None when the attribute is absent or null in the API response
5. WHEN the DirectusClient constructs DirectusPermission instances from the API response, THE DirectusClient SHALL populate the `fields`, `validation`, and `permissions` attributes from the corresponding response item values

---

### Requirement 8: Custom Permissions Config Validation

**User Story:** As a CLI user, I want the config loader to validate custom permission entries, so that malformed entries are caught before attempting to apply them.

#### Acceptance Criteria

1. WHEN a `custom_permissions` entry references a policy name not resolvable to an existing policy fetched from the Directus instance, THE Validator SHALL collect the unresolvable policy name and raise a ValidationError listing all unresolvable policy names after checking all entries
2. WHEN a `custom_permissions` entry references a collection not present in the config file's top-level `collections` list, THE Validator SHALL collect the unknown collection and raise a ValidationError listing all unknown collections after checking all entries
3. IF a `custom_permissions` entry contains an `action` value that does not match one of `read`, `create`, `update`, or `delete` (case-insensitive comparison), THEN THE config loader SHALL raise a ConfigError identifying the invalid action value and the entry index
