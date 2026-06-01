"""
Exception hierarchy for directus_ac.

All exceptions carry a human-readable message suitable for writing to stderr.
The main entry point catches any DirectusACError and prints its message before
exiting with code 1.
"""


class DirectusACError(Exception):
    """Base exception for all directus_ac errors."""


class ConfigError(DirectusACError):
    """
    Raised when the config file cannot be read or fails validation.

    Covers:
    - File not found (Requirement 1.5)
    - Invalid YAML syntax (Requirement 1.6)
    - Invalid Permission_Set keyword (Requirement 1.7)
    - Missing required top-level keys (Requirement 1.8)
    - Malformed group definition (Requirement 1.9)
    """


class ConnectionError(DirectusACError):
    """
    Raised when the Directus instance is unreachable.

    Covers network-level failures such as connection refused, DNS resolution
    failure, or request timeout (Requirement 2.8).
    """


class AuthError(DirectusACError):
    """
    Raised when the Directus API returns HTTP 401 or 403.

    Indicates that the supplied token is missing, expired, or lacks the
    required permissions (Requirement 2.7).
    """


class ValidationError(DirectusACError):
    """
    Raised when collections or roles referenced in the config do not exist
    in the Directus instance.

    Covers:
    - Missing collections (Requirements 3.2, 3.5)
    - Missing roles when --create-roles is not specified (Requirements 4.2, 4.4)

    Attributes
    ----------
    missing_names:
        The exact set of names that were not found.  Stored separately so
        callers (and tests) can inspect them without parsing the message string.
    """

    def __init__(self, message: str, missing_names: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_names: list[str] = missing_names if missing_names is not None else []


class APIError(DirectusACError):
    """
    Raised for unexpected HTTP errors from the Directus API that are not
    covered by AuthError or ValidationError.

    Covers:
    - Non-2xx responses on GET /collections or GET /roles (Requirements 3.2, 4.2)
    - Errors while creating a role (Requirement 5.5)
    - Errors while applying a permission (Requirement 6.5)
    """
