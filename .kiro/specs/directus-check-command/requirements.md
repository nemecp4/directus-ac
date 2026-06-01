# Requirements Document

## Introduction

The `--check` command is a new CLI option for `directus-ac` that connects to a Directus instance and retrieves a read-only overview of the current access control state. It lists all permission groups (existing permission entries grouped by role and collection), all collections, and all roles. This provides operators with a quick way to audit the current state of a Directus instance without making any changes.

## Glossary

- **CLI**: The `directus-ac` command-line interface entry point
- **Directus_Instance**: A running Directus server accessible via its REST API
- **Check_Command**: The `--check` CLI option that triggers the read-only inspection mode
- **Permission_Entry**: A single permission record in Directus linking a role, collection, and action
- **Permission_Group**: A logical grouping of permission entries by role, showing which actions each role has on each collection
- **Collection**: A Directus collection (analogous to a database table)
- **Role**: A Directus role that can be assigned permissions
- **DirectusClient**: The existing HTTP client module that communicates with the Directus REST API

## Requirements

### Requirement 1: Check Command CLI Option

**User Story:** As an operator, I want a `--check` CLI option, so that I can inspect the current access control state of a Directus instance without applying any changes.

#### Acceptance Criteria

1. WHEN the `--check` flag is provided, THE CLI SHALL connect to the Directus_Instance and print to stdout the list of collections, roles, and permissions currently configured on the instance, grouped by role
2. WHEN the `--check` flag is provided, THE CLI SHALL issue only read operations (GET requests) to the Directus_Instance and SHALL NOT create, update, or delete any data
3. THE CLI SHALL accept the `--check` flag alongside `--url` and `--token` options for specifying connection details
4. WHEN the `--check` flag is provided without a `--config` file, THE CLI SHALL display the current access control state without requiring a configuration file
5. WHEN the `--check` flag is provided and the connection to the Directus_Instance succeeds, THE CLI SHALL exit with code 0
6. IF the `--check` flag is provided and the connection to the Directus_Instance fails, THEN THE CLI SHALL print an error message indicating the connection failure and exit with code 1

### Requirement 2: List All Collections

**User Story:** As an operator, I want to see all collections in the Directus instance, so that I can verify which collections exist.

#### Acceptance Criteria

1. WHEN the `--check` flag is provided, THE CLI SHALL retrieve all collections from the Directus_Instance via `GET /collections`
2. WHEN collections are retrieved, THE CLI SHALL print each collection name on a separate line to standard output, one collection per line
3. WHEN no collections exist, THE CLI SHALL print a message indicating no collections were found to standard output and exit with code 0
4. IF the Directus_Instance is unreachable or returns an authentication error during a `--check` operation, THEN THE CLI SHALL print an error message to standard error and exit with a non-zero exit code

### Requirement 3: List All Roles

**User Story:** As an operator, I want to see all roles in the Directus instance, so that I can verify which roles are configured.

#### Acceptance Criteria

1. WHEN the `--check` flag is provided, THE CLI SHALL retrieve all roles from the Directus_Instance via `GET /roles`
2. WHEN roles are retrieved, THE CLI SHALL display one line per role to standard output, each line containing the role name and its identifier separated by a space
3. WHEN no roles exist, THE CLI SHALL display a message indicating no roles were found to standard output and exit with code 0
4. IF the Directus_Instance is unreachable or returns an authentication error during role retrieval, THEN THE CLI SHALL display an error message to standard error and exit with a non-zero exit code

### Requirement 4: List All Permission Groups

**User Story:** As an operator, I want to see all permissions grouped by role, so that I can audit which actions each role has on each collection.

#### Acceptance Criteria

1. WHEN the `--check` flag is provided, THE CLI SHALL retrieve all permission entries from the Directus instance via `GET /permissions` and all roles via `GET /roles`
2. WHEN permission entries are retrieved, THE CLI SHALL group them by role and, for each role, list each collection with its associated actions, printing the output to stdout with one role section per group
3. WHEN no permission entries exist, THE CLI SHALL print a message indicating no permissions were found to stdout and exit with code 0
4. WHEN displaying permissions, THE CLI SHALL resolve role UUIDs to human-readable role names by matching against the retrieved roles list
5. IF a permission entry references a role UUID that cannot be resolved to a name, THEN THE CLI SHALL display that role using its UUID as the identifier
6. IF the Directus API returns an error or is unreachable during the `--check` operation, THEN THE CLI SHALL print an error message to stderr and exit with a non-zero exit code

### Requirement 5: Connection Credential Resolution

**User Story:** As an operator, I want to provide Directus connection details via CLI arguments or environment variables, so that I can use `--check` in different environments.

#### Acceptance Criteria

1. WHEN the `--check` flag is provided with a `--url` argument, THE CLI SHALL use the `--url` value as the Directus URL, ignoring the `DIRECTUS_URL` environment variable
2. WHEN the `--check` flag is provided without a `--url` argument, THE CLI SHALL use the `DIRECTUS_URL` environment variable as the Directus URL
3. WHEN the `--check` flag is provided with a `--token` argument, THE CLI SHALL use the `--token` value as the authentication token, ignoring the `DIRECTUS_TOKEN` environment variable
4. WHEN the `--check` flag is provided without a `--token` argument, THE CLI SHALL use the `DIRECTUS_TOKEN` environment variable as the authentication token
5. IF the Directus URL is not provided via `--url` argument and the `DIRECTUS_URL` environment variable is either unset or empty, THEN THE CLI SHALL exit with code 1 and write an error message indicating the URL is missing to standard error
6. IF the authentication token is not provided via `--token` argument and the `DIRECTUS_TOKEN` environment variable is either unset or empty, THEN THE CLI SHALL exit with code 1 and write an error message indicating the token is missing to standard error

### Requirement 6: Error Handling

**User Story:** As an operator, I want clear error messages when the check command fails, so that I can diagnose connectivity or authentication issues.

#### Acceptance Criteria

1. IF the Directus_Instance is unreachable due to connection refusal, DNS resolution failure, or request timeout (30 seconds), THEN THE CLI SHALL exit with code 1 and display a connection error message including the instance URL to standard error
2. IF the Directus API returns HTTP 401 or 403, THEN THE CLI SHALL exit with code 1 and display an authentication error message to standard error
3. IF the Directus API returns a non-success HTTP status other than 401 or 403, THEN THE CLI SHALL exit with code 1 and display an error message including the HTTP status code and the response message to standard error

### Requirement 7: Output Formatting

**User Story:** As an operator, I want the check output to be clearly structured, so that I can quickly understand the access control state.

#### Acceptance Criteria

1. THE CLI SHALL display collections as a list of names to stdout, preceded by a line containing the exact text "Collections"
2. THE CLI SHALL display roles as a list of names to stdout, preceded by a line containing the exact text "Roles"
3. THE CLI SHALL display permission groups to stdout, preceded by a line containing the exact text "Permissions"
4. WHEN displaying permissions grouped by role, THE CLI SHALL print the role name on its own line followed by each collection and its associated actions indented beneath the role name, with one collection-actions entry per line
5. THE CLI SHALL exit with code 0 after successfully writing all sections to stdout
6. THE CLI SHALL display each item within a section on its own line, in the order they appear in the configuration file
7. IF the CLI cannot retrieve data from the Directus instance during the check operation, THEN THE CLI SHALL print an error message to stderr and exit with code 1
