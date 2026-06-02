# Requirements Document

## Introduction

This feature adds two new CLI options to the `directus_ac` tool: `--ignore-ssl` to disable SSL certificate verification on outgoing HTTP requests, and `--verbose` to enable debug-level logging output. These options give users better control when working against development Directus instances with self-signed certificates and when troubleshooting connectivity or permission issues.

## Glossary

- **CLI**: The `directus_ac` command-line interface built with Python `argparse`.
- **HTTP_Client**: The `httpx.Client` instance used by `DirectusClient` to communicate with the Directus API.
- **Logger**: The Python `logging` module logger used by `directus_ac` for user-facing output.
- **SSL_Verification**: The TLS certificate validation performed by `httpx` when connecting to HTTPS endpoints.

## Requirements

### Requirement 1: Ignore SSL Certificate Verification

**User Story:** As a developer working with a Directus instance that uses a self-signed certificate, I want to disable SSL certificate verification, so that I can manage permissions without certificate errors blocking my requests.

#### Acceptance Criteria

1. THE CLI SHALL accept an `--ignore-ssl` flag as an optional boolean argument.
2. WHEN `--ignore-ssl` is provided, THE HTTP_Client SHALL disable SSL_Verification for all outgoing requests.
3. WHEN `--ignore-ssl` is not provided, THE HTTP_Client SHALL perform SSL_Verification using the system default certificate store.
4. WHEN `--ignore-ssl` is provided, THE Logger SHALL emit a warning message indicating that SSL verification is disabled.

### Requirement 2: Verbose Debug Logging

**User Story:** As a developer troubleshooting permission sync issues, I want to enable verbose debug output, so that I can see detailed request and response information.

#### Acceptance Criteria

1. THE CLI SHALL accept a `--verbose` flag as an optional boolean argument.
2. WHEN `--verbose` is provided, THE Logger SHALL configure the root logging level to DEBUG.
3. WHEN `--verbose` is not provided, THE Logger SHALL remain configured at the INFO level.
4. WHEN `--verbose` is provided, THE Logger SHALL use a format that includes the log level and logger name in each message.
5. WHEN `--verbose` is not provided, THE Logger SHALL use the existing plain message format.

### Requirement 3: Combined Option Behavior

**User Story:** As a developer, I want to use both `--ignore-ssl` and `--verbose` together, so that I can troubleshoot SSL-related issues with full debug context.

#### Acceptance Criteria

1. WHEN both `--ignore-ssl` and `--verbose` are provided, THE CLI SHALL enable both features simultaneously without conflict.
2. WHEN `--verbose` is provided alongside `--ignore-ssl`, THE Logger SHALL include the SSL verification disabled warning at DEBUG level or higher.
