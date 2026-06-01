# Requirements Document

## Introduction

This feature provides a Python command-line utility (`directus_ac`) that manages permissions for Collections (tables) in a Directus.io application. The tool reads a declarative YAML configuration file (`directus_ac.yaml`) that defines collections, roles, groups, and their associated permissions, then applies those permissions to a live Directus instance via its REST API. The tool validates that all referenced collections and roles exist before applying any changes, with an option to create missing roles automatically.

## Glossary

- **Directus**: An open-source headless CMS and data platform that wraps SQL databases with a REST/GraphQL API.
- **Collection**: A Directus entity representing a database table.
- **Role**: A Directus entity that groups users and defines their access level.
- **Group**: A logical grouping defined in `directus_ac.yaml` that maps roles to permission sets for a set of collections.
- **Permission**: An access control entry in Directus that grants a role the ability to perform specific actions on a collection.
- **Permission_Set**: A combination of one or more of the keywords `READ`, `WRITE`, `UPDATE`, `DELETE` that defines the allowed actions for a role on a collection.
- **Tool**: The `directus_ac` Python command-line utility described in this document.
- **Config_File**: The `directus_ac.yaml` file that contains the access control configuration.
- **Directus_API**: The Directus REST API used by the Tool to query and modify permissions.
- **Validator**: The component of the Tool responsible for checking that collections and roles referenced in the Config_File exist in the Directus instance.
- **Permission_Manager**: The component of the Tool responsible for applying permissions to the Directus instance via the Directus_API.

---

## Requirements

### Requirement 1: Read and Parse the Configuration File

**User Story:** As a developer, I want the tool to read a YAML configuration file, so that I can declaratively define access control rules without writing code.

#### Acceptance Criteria

1. WHEN the Tool is invoked, THE Tool SHALL read the Config_File named `directus_ac.yaml` from the current working directory unless `--config` is specified.
2. WHEN the Config_File contains a `collections` key, THE Tool SHALL parse it as a list of collection name strings.
3. WHEN the Config_File contains a `roles` key, THE Tool SHALL parse it as a list of role name strings.
4. WHEN the Config_File contains a `groups` key, THE Tool SHALL parse it as a list of group definitions, where each group contains a `collections` list and a `permissions` map of role names to Permission_Set keyword lists.
5. IF the Config_File is not found, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the resolved file path that was not found.
6. IF the Config_File contains invalid YAML syntax, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the line number and column of the parse error.
7. IF a Permission_Set value contains a keyword other than `READ`, `WRITE`, `UPDATE`, or `DELETE`, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that identifies the invalid keyword and the role and collection it was found under.
8. IF the Config_File is missing any of the required top-level keys (`collections`, `roles`, `groups`), THEN THE Tool SHALL exit with a non-zero exit code and display an error message listing each missing key.
9. IF a group definition is missing a `collections` key or a `permissions` key, THEN THE Tool SHALL exit with a non-zero exit code and display an error message identifying which group (by index or name) is malformed and which key is absent.

---

### Requirement 2: Connect to the Directus Instance

**User Story:** As a developer, I want the tool to connect to a Directus instance using configurable credentials, so that I can target different environments (development, staging, production).

#### Acceptance Criteria

1. THE Tool SHALL accept a `--url` command-line argument specifying the base URL of the Directus instance; this value takes precedence over the `DIRECTUS_URL` environment variable.
2. THE Tool SHALL accept a `--token` command-line argument specifying a static authentication token for the Directus_API; this value takes precedence over the `DIRECTUS_TOKEN` environment variable.
3. WHEN `--url` is not provided, THE Tool SHALL read the Directus instance URL from the `DIRECTUS_URL` environment variable.
4. WHEN `--token` is not provided, THE Tool SHALL read the authentication token from the `DIRECTUS_TOKEN` environment variable.
5. IF neither `--url` nor `DIRECTUS_URL` is set, THEN THE Tool SHALL exit with a non-zero exit code and display an error message stating that the Directus URL must be provided via `--url` or the `DIRECTUS_URL` environment variable.
6. IF neither `--token` nor `DIRECTUS_TOKEN` is set, THEN THE Tool SHALL exit with a non-zero exit code and display an error message stating that the authentication token must be provided via `--token` or the `DIRECTUS_TOKEN` environment variable.
7. IF the Directus_API returns an HTTP 401 or 403 response on any request, THEN THE Tool SHALL exit with a non-zero exit code and display an error message indicating that authentication failed and suggesting the token be verified.
8. IF the Directus_API is unreachable (e.g., connection refused, DNS failure, timeout), THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the target URL and the underlying network error.

---

### Requirement 3: Validate Collections Exist

**User Story:** As a developer, I want the tool to verify that all collections referenced in the configuration file exist in Directus, so that I can catch configuration mistakes before any permissions are applied.

#### Acceptance Criteria

1. WHEN the Tool starts validation, THE Validator SHALL query `GET /collections` on the Directus_API to retrieve the list of all existing collection names.
2. IF the Directus_API returns an error response when querying collections, THEN THE Validator SHALL exit with a non-zero exit code and display an error message that includes the HTTP status code and the error detail returned by the API.
3. WHEN the Validator has retrieved the existing collections, THE Validator SHALL compare each collection name in the Config_File against the retrieved list using a case-sensitive exact string match.
4. IF one or more collection names in the Config_File do not match any name in the retrieved list, THEN THE Validator SHALL collect all such missing names before exiting.
5. WHEN one or more collections are missing, THE Validator SHALL exit with a non-zero exit code and display an error message that lists every missing collection name, one per line.
6. WHEN all collections in the Config_File exist in the Directus instance, THE Validator SHALL proceed to role validation without modifying any data.

---

### Requirement 4: Validate Roles Exist

**User Story:** As a developer, I want the tool to verify that all roles referenced in the configuration file exist in Directus, so that I can catch configuration mistakes before any permissions are applied.

#### Acceptance Criteria

1. WHEN the Tool starts role validation, THE Validator SHALL query `GET /roles` on the Directus_API to retrieve the list of all existing role names.
2. IF the Directus_API returns an error response when querying roles, THEN THE Validator SHALL exit with a non-zero exit code and display an error message that includes the HTTP status code and the error detail returned by the API.
3. WHEN the Validator has retrieved the existing roles, THE Validator SHALL compare each role name in the Config_File against the retrieved list using a case-sensitive exact string match.
4. IF one or more role names in the Config_File do not match any name in the retrieved list and `--create-roles` is not specified, THEN THE Validator SHALL collect all such missing names, exit with a non-zero exit code, and display an error message that lists every missing role name, one per line.
5. WHEN `--create-roles` is specified and one or more roles are missing, THE Validator SHALL pass the list of missing role names to the Permission_Manager for creation before proceeding to permission application.
6. WHEN all roles in the Config_File exist in the Directus instance, THE Validator SHALL proceed to permission application without modifying any data.

---

### Requirement 5: Create Missing Roles on Demand

**User Story:** As a developer, I want the option to automatically create missing roles, so that I can bootstrap a new Directus environment from a configuration file without manual setup.

#### Acceptance Criteria

1. THE Tool SHALL accept a `--create-roles` command-line flag; when absent, the Tool SHALL NOT create any roles.
2. WHEN `--create-roles` is specified and one or more roles in the Config_File do not exist in the Directus instance, THE Permission_Manager SHALL create each missing role via `POST /roles` on the Directus_API before applying permissions.
3. WHEN `--create-roles` is not specified and one or more roles in the Config_File do not exist in the Directus instance, THE Tool SHALL exit with a non-zero exit code and display an error message listing all missing role names, one per line.
4. WHEN a role is created successfully, THE Tool SHALL display a message that includes the name of the role that was created (e.g., `Created role: <role_name>`).
5. IF the Directus_API returns an error while creating a role, THEN THE Tool SHALL display success messages for all roles created prior to the failure, then exit with a non-zero exit code and display an error message that identifies the role that failed to be created and the error returned by the Directus_API.

---

### Requirement 6: Apply Permissions

**User Story:** As a developer, I want the tool to apply the permissions defined in the configuration file to the Directus instance, so that access control rules are enforced consistently.

#### Acceptance Criteria

1. WHEN all validations pass, THE Permission_Manager SHALL apply permissions for each role-collection-action combination defined in the Config_File groups.
2. WHEN applying permissions, THE Permission_Manager SHALL map each Permission_Set keyword to the corresponding Directus permission action: `READ` to `read`, `WRITE` to `create`, `UPDATE` to `update`, `DELETE` to `delete`.
3. WHEN a permission entry for a given role, collection, and action combination already exists in the Directus instance, THE Permission_Manager SHALL update that existing permission entry via `PATCH /permissions/{id}` rather than creating a duplicate.
4. WHEN a permission entry for a given role, collection, and action combination does not exist in the Directus instance, THE Permission_Manager SHALL create a new permission entry via `POST /permissions` on the Directus_API.
5. IF the Directus_API returns an error while applying a permission, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that identifies the role, collection, action, and the error reason returned by the API.
6. WHEN the Tool exits due to a permission application error, permissions applied before the failure SHALL be retained in the Directus instance (no rollback is performed).
7. WHEN all permissions have been applied successfully, THE Tool SHALL display a summary message indicating the total number of permissions created and the total number of permissions updated.

---

### Requirement 7: Configuration File Format

**User Story:** As a developer, I want a well-defined YAML schema for the configuration file, so that I can write and maintain access control rules clearly.

#### Acceptance Criteria

1. THE Config_File SHALL support a top-level `collections` key containing a list of 1 to 500 collection name strings, where each name is between 1 and 255 characters.
2. THE Config_File SHALL support a top-level `roles` key containing a list of 1 to 500 role name strings, where each name is between 1 and 255 characters.
3. THE Config_File SHALL support a top-level `groups` key containing a list of 1 to 500 group objects.
4. WHEN defining a group, THE Config_File SHALL support a `collections` key within the group containing a list of collection names that the group's permissions apply to.
5. WHEN defining a group, THE Config_File SHALL support a `permissions` key within the group containing a map where each key is a role name and each value is a Permission_Set string composed exclusively of the tokens `READ`, `WRITE`, `UPDATE`, and `DELETE`, separated by spaces (e.g., `"READ"`, `"READ WRITE"`, `"READ WRITE UPDATE DELETE"`).
6. WHEN the Tool is invoked with `--config <path>`, THE Tool SHALL read the Config_File from the specified path instead of the default `directus_ac.yaml` in the current working directory.
7. IF the path provided via `--config` does not exist or is not readable, THEN THE Tool SHALL exit with a non-zero exit code and display an error message that includes the specified path and the reason it could not be read.
8. IF the Config_File fails YAML parsing, is missing required top-level keys, contains invalid Permission_Set values, or references role or collection names that violate the length constraints, THEN THE Tool SHALL exit with a non-zero exit code and display an error message identifying the specific validation failure.
