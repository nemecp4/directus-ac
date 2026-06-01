# Requirements Document

## Introduction

This feature adds a `--generate` flag to the `directus_ac` CLI that connects to a running Directus instance, reads its existing collections, roles, and permissions via the Directus REST API, and produces a `directus_ac.yaml` configuration file that represents the current access control state. The `--generate` flag is added to the existing mutually exclusive group alongside `--check` and `--update`. This is the inverse of the existing `--update` operation: where `--update` pushes a config file into Directus, `--generate` pulls the current Directus state out into a config file.

The generated YAML must be structurally compatible with the existing `directus_ac.yaml` format so that it can be immediately used as input to the `--update` flag.

## Glossary

- **Directus**: An open-source headless CMS and data platform that wraps SQL databases with a REST/GraphQL API.
- **Collection**: A Directus entity representing a database table.
- **Role**: A Directus entity that groups users and defines their access level.
- **Group**: A logical grouping in `directus_ac.yaml` that maps a set of collections to per-role permission sets.
- **Permission**: An access control entry in Directus that grants a role the ability to perform a specific action on a collection.
- **Permission_Set**: A combination of one or more of the keywords `READ`, `WRITE`, `UPDATE`, `DELETE` that defines the allowed actions for a role on a collection.
- **Tool**: The `directus_ac` Python command-line utility described in this document.
- **Config_File**: The `directus_ac.yaml` file that contains the access control configuration.
- **Directus_API**: The Directus REST API used by the Tool to query permissions.
- **Generator**: The component of the Tool responsible for reading Directus state and producing a `DirectusACConfig` object.
- **Serializer**: The component of the Tool responsible for converting a `DirectusACConfig` object into a YAML string.
- **System_Collection**: A Directus collection whose name begins with `directus_` (e.g., `directus_users`, `directus_files`). These are internal Directus collections.

---

## Requirements

### Requirement 1: Generate Flag Entry Point

**User Story:** As a developer, I want a `--generate` flag in the `directus_ac` CLI, so that I can export the current Directus permission state into a config file without writing any code.

#### Acceptance Criteria

1. THE Tool SHALL support a `--generate` flag invoked as `directus-ac --generate`, added to the existing mutually exclusive group alongside `--check` and `--update`.
2. THE Tool SHALL accept a `--url` argument and `DIRECTUS_URL` environment variable when `--generate` is specified, using the same resolution logic as the existing `--check` and `--update` flags.
3. THE Tool SHALL accept a `--token` argument and `DIRECTUS_TOKEN` environment variable when `--generate` is specified, using the same resolution logic as the existing `--check` and `--update` flags.
4. THE Tool SHALL accept an `--output` argument when `--generate` is specified, defining the file path to write the generated YAML; when absent, THE Tool SHALL write the YAML to stdout.
5. THE Tool SHALL accept an `--include-system` flag when `--generate` is specified; when absent, THE Generator SHALL exclude System_Collections from the output.
6. IF neither `--url` nor `DIRECTUS_URL` is set, THEN THE Tool SHALL exit with a non-zero exit code and display an error message stating that the Directus URL must be provided via `--url` or the `DIRECTUS_URL` environment variable.
7. IF neither `--token` nor `DIRECTUS_TOKEN` is set, THEN THE Tool SHALL exit with a non-zero exit code and display an error message stating that the authentication token must be provided via `--token` or the `DIRECTUS_TOKEN` environment variable.
8. THE Tool SHALL update the help text epilog to mention `--generate` alongside `--check` and `--update` (e.g., "One of --check, --update, or --generate is required to perform an operation.").

---

### Requirement 2: Fetch Data from Directus API

**User Story:** As a developer, I want the tool to read all relevant data from the Directus REST API, so that the generated config accurately reflects the current permission state.

#### Acceptance Criteria

1. WHEN `--generate` is specified, THE Generator SHALL query `GET /collections` to retrieve all collection names.
2. WHEN `--generate` is specified, THE Generator SHALL query `GET /roles?limit=-1&fields=id,name` to retrieve all roles.
3. WHEN `--generate` is specified, THE Generator SHALL query `GET /permissions?limit=-1&fields=id,role,collection,action` to retrieve all permission entries.
4. IF the Directus_API returns an HTTP 401 or 403 response on any request, THEN THE Tool SHALL exit with a non-zero exit code and display an error message indicating that authentication failed.
5. IF the Directus_API is unreachable, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the target URL and the underlying network error.
6. IF the Directus_API returns a non-2xx response on any fetch request, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the HTTP status code and the error detail returned by the API.

---

### Requirement 3: Filter Collections

**User Story:** As a developer, I want the tool to filter out internal Directus system collections by default, so that the generated config focuses on my application's data model.

#### Acceptance Criteria

1. WHEN `--include-system` is not specified, THE Generator SHALL exclude any collection whose name begins with `directus_` from the generated output.
2. WHEN `--include-system` is specified, THE Generator SHALL include all collections returned by the API, including those whose names begin with `directus_`.
3. WHEN no non-system collections exist and `--include-system` is not specified, THE Generator SHALL write an empty `collections` list and an empty `groups` list to the output.

---

### Requirement 4: Build Config Structure from Permissions

**User Story:** As a developer, I want the generated YAML to group permissions logically, so that the output is readable and compatible with the `--update` flag.

#### Acceptance Criteria

1. THE Generator SHALL populate the top-level `collections` list with the names of all collections that appear in at least one permission entry (after applying the system collection filter).
2. THE Generator SHALL populate the top-level `roles` list with the names of all roles that appear in at least one permission entry.
3. THE Generator SHALL group permissions by collection, producing one `Group` per collection that has at least one permission entry.
4. WHEN building each `Group`, THE Generator SHALL set the `collections` field to a single-element list containing that collection's name.
5. WHEN building each `Group`, THE Generator SHALL set the `permissions` map with one entry per role that has at least one permission on that collection, where the value is the Permission_Set string for that role-collection pair.
6. THE Generator SHALL map Directus action strings back to Permission_Set keywords: `read` to `READ`, `create` to `WRITE`, `update` to `UPDATE`, `delete` to `DELETE`.
7. WHEN a role has multiple actions on a collection, THE Generator SHALL combine them into a single space-separated Permission_Set string (e.g., `"READ WRITE UPDATE DELETE"`).
8. WHEN a permission entry references a role ID that does not correspond to any role returned by `GET /roles`, THE Generator SHALL skip that permission entry and continue processing.
9. WHEN a permission entry references a collection that is excluded by the system collection filter, THE Generator SHALL skip that permission entry.

---

### Requirement 5: Serialize to YAML

**User Story:** As a developer, I want the generated output to be valid YAML that conforms to the `directus_ac.yaml` schema, so that I can use it directly with the `--update` flag.

#### Acceptance Criteria

1. THE Serializer SHALL produce a YAML document with the top-level keys `collections`, `roles`, and `groups` in that order.
2. THE Serializer SHALL represent each group's `permissions` values as space-separated Permission_Set strings (e.g., `"READ WRITE"`), not as YAML lists.
3. THE Serializer SHALL produce output that, when parsed by the existing `load_config` function, produces an equivalent `DirectusACConfig` object.
4. WHEN `--output` is specified, THE Tool SHALL write the YAML to the file at the given path, creating the file if it does not exist and overwriting it if it does.
5. WHEN `--output` is not specified, THE Tool SHALL write the YAML to stdout.
6. IF writing to the output file fails (e.g., permission denied, invalid path), THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the output path and the reason for the failure.

---

### Requirement 6: Idempotency and Round-Trip Compatibility

**User Story:** As a developer, I want the generate-then-apply cycle to be idempotent, so that running `directus-ac --generate` followed by `directus-ac --update` does not change the Directus state.

#### Acceptance Criteria

1. WHEN the generated `directus_ac.yaml` is applied to the same Directus instance using `directus-ac --update`, THE Tool SHALL report zero permissions created and zero permissions updated (assuming no external changes occurred between generate and apply).
2. THE Generator SHALL produce Permission_Set strings using only the tokens `READ`, `WRITE`, `UPDATE`, and `DELETE`, separated by single spaces, with no leading or trailing whitespace.
3. THE Generator SHALL include only roles and collections that have at least one permission entry in the output, so that the generated config does not reference roles or collections with no permissions.
