# directus-ac

A Python CLI utility that applies declarative access control rules to a [Directus](https://directus.io) instance. Define your collections, roles, and permissions in a YAML file — `directus-ac` validates everything and applies it via the Directus REST API.

The tool is **idempotent**: running it multiple times produces the same end state. Existing permissions are updated in place rather than duplicated.

---

## Installation

```bash
pip install directus-ac
```

Or install from source:

```bash
git clone https://github.com/your-org/directus-ac
cd directus-ac
pip install .
```

**Requirements:** Python 3.11+

---

## Quick Start

1. Create a `directus_ac.yaml` file in your working directory (see [Configuration](#configuration)).
2. Set your Directus credentials:
   ```bash
   export DIRECTUS_URL=https://your-directus-instance.example.com
   export DIRECTUS_TOKEN=your-static-token
   ```
3. Run:
   ```bash
   directus-ac
   ```

---

## Usage

```
directus-ac [--config PATH] [--url URL] [--token TOKEN] [--create-roles]
```

### Options

| Option | Description |
|---|---|
| `--config PATH` | Path to the YAML config file. Defaults to `./directus_ac.yaml`. |
| `--url URL` | Base URL of the Directus instance. Overrides the `DIRECTUS_URL` environment variable. |
| `--token TOKEN` | Static authentication token. Overrides the `DIRECTUS_TOKEN` environment variable. |
| `--create-roles` | Automatically create any roles defined in the config that do not yet exist in Directus. Without this flag, missing roles cause the tool to exit with an error. |

### Environment Variables

| Variable | Description |
|---|---|
| `DIRECTUS_URL` | Base URL of the Directus instance (e.g. `https://cms.example.com`). |
| `DIRECTUS_TOKEN` | Static API token with admin-level access to manage permissions. |

CLI arguments take precedence over environment variables.

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | All permissions applied successfully. |
| `1` | An error occurred (config invalid, network failure, API error, etc.). |

---

## Configuration

The config file is a YAML document with three required top-level keys.

```yaml
# directus_ac.yaml

collections:
  - articles
  - comments
  - tags

roles:
  - editor
  - viewer
  - moderator

groups:
  - collections:
      - articles
      - tags
    permissions:
      editor: "READ WRITE UPDATE DELETE"
      viewer: "READ"

  - collections:
      - comments
    permissions:
      editor: "READ WRITE UPDATE"
      moderator: "READ UPDATE DELETE"
      viewer: "READ"
```

### `collections`

A list of Directus collection names that this config manages. Each name must exist in the target Directus instance (validated before any changes are made).

- 1–500 entries
- Each name: 1–255 characters

### `roles`

A list of Directus role names referenced in the `groups` section. By default, all roles must already exist in Directus. Use `--create-roles` to create missing ones automatically.

- 1–500 entries
- Each name: 1–255 characters

### `groups`

A list of permission groups. Each group maps a set of collections to per-role permission sets.

- 1–500 entries
- Each group has:
  - `collections` — list of collection names the permissions apply to
  - `permissions` — map of role name → permission set string

### Permission Sets

A permission set is a space-separated string of one or more of the following keywords:

| Keyword | Directus action |
|---|---|
| `READ` | `read` |
| `WRITE` | `create` |
| `UPDATE` | `update` |
| `DELETE` | `delete` |

Examples: `"READ"`, `"READ WRITE"`, `"READ WRITE UPDATE DELETE"`

Duplicate keywords are silently deduplicated.

---

## How It Works

The tool runs a linear, fail-fast pipeline:

1. **Parse config** — reads and validates `directus_ac.yaml`
2. **Resolve credentials** — from CLI args or environment variables
3. **Validate collections** — queries `GET /collections` and checks every name in the config exists (case-sensitive)
4. **Validate roles** — queries `GET /roles` and checks every name in the config exists (case-sensitive); creates missing roles if `--create-roles` is set
5. **Apply permissions** — fetches all existing permissions, then for each role-collection-action triple:
   - Updates the existing permission entry if one already exists (`PATCH /permissions/{id}`)
   - Creates a new permission entry if none exists (`POST /permissions`)
6. **Print summary** — reports how many permissions were created and updated

No changes are made to Directus until all validation passes. If a permission write fails mid-run, previously applied permissions are retained (no rollback).

---

## Examples

### Apply permissions using environment variables

```bash
export DIRECTUS_URL=https://cms.example.com
export DIRECTUS_TOKEN=my-admin-token
directus-ac
```

### Use a custom config file

```bash
directus-ac --config ./config/production.yaml
```

### Bootstrap a new environment (create missing roles)

```bash
directus-ac --url https://staging.example.com --token my-token --create-roles
```

### Typical output

```
Created role: moderator
Applied permissions: 12 created, 3 updated.
```

### Error output (stderr)

```
Error: Collections not found in Directus:
  - legacy_posts
  - archived_items
```

```
Error: Roles not found in Directus (use --create-roles to create them):
  - editor
  - viewer
```

---

## Error Reference

| Situation | Message |
|---|---|
| Config file not found | `Error: Config file not found: ./directus_ac.yaml` |
| Invalid YAML | `Error: YAML parse error at line 12, column 3: ...` |
| Missing required keys | `Error: Missing required keys: roles, groups` |
| Invalid permission keyword | `Error: Invalid permission keyword 'MANAGE' for role 'editor' on collection 'articles'` |
| Directus URL not set | `Error: Directus URL must be provided via --url or DIRECTUS_URL` |
| Token not set | `Error: Auth token must be provided via --token or DIRECTUS_TOKEN` |
| Network unreachable | `Error: Cannot reach Directus at https://cms.example.com: Connection refused` |
| Auth failure | `Error: Authentication failed. Verify your token.` |
| Missing collections | `Error: Collections not found in Directus:\n  - name1\n  - name2` |
| Missing roles | `Error: Roles not found in Directus:\n  - name1\n  - name2` |
| Permission apply failure | `Error: Failed to apply permission for role 'editor', collection 'articles', action 'read': ...` |

---

## Development

### Install dev dependencies

```bash
pip install -e .
pip install -r requirements-dev.txt
```

### Run tests

```bash
pytest
```

The test suite uses [Hypothesis](https://hypothesis.readthedocs.io/) for property-based testing alongside standard unit tests.

### Run as a module

```bash
python3 -m directus_ac --help
```

---

## Compatibility

Targets the Directus **v11+** permissions model, where permissions are assigned to **Policies**, which are then linked to **Roles**. The tool automatically resolves or creates policies for each role and manages permissions through the `/permissions` and `/policies` endpoints.

Users on Directus v10 or earlier should use an older version of this tool, as v10 used a direct `role` field on permissions which is no longer supported.
