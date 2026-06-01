# Design Document: Custom Permissions Display

## Overview

This feature modifies the custom permission naming scheme from `C_N` to `ACTION_C_N` (e.g., `UPDATE_C_3`) and simplifies the check command output to display only the permission name without field/validation/permission indicators. The changes touch five modules: `generate.py`, `models.py`, `check.py`, `config.py`, and their interactions through `serialize_config` and `load_config`.

## Architecture

The change is localized to the naming and display layers. No new modules or classes are introduced. The data flow remains:

```
Directus API → Generator → DirectusACConfig → serialize_config → YAML
YAML → load_config → DirectusACConfig → apply/check commands
```

The naming change propagates through:
1. **Generation** (`generate.py`): `generate_permission_name(counter)` → `generate_permission_name(action, counter)`
2. **Validation** (`models.py`): `CustomPermissionEntry.validate_name_pattern` regex update
3. **Serialization** (`generate.py`): `serialize_config` already uses the name field — no logic change needed once generation is updated
4. **Parsing** (`config.py`): `_CUSTOM_REF_PATTERN` and `_parse_permission_set` token classification
5. **Display** (`check.py`): `_format_custom_ref` simplified to return only the name

## Components and Interfaces

### 1. `generate_permission_name(action: str, counter: int) -> str`

**Location:** `directus_ac/generate.py`

**Current signature:** `generate_permission_name(counter: int) -> str`

**New signature:** `generate_permission_name(action: str, counter: int) -> str`

**Behavior:**
```python
def generate_permission_name(action: str, counter: int) -> str:
    """Generate a Permission_Name: {ACTION}_C_{COUNTER}.

    Parameters
    ----------
    action:
        The permission action string (e.g., "create", "read", "update", "delete").
        Will be uppercased in the output.
    counter:
        Global sequence number across all custom permissions, assigned by
        ascending Directus permission id.
    """
    return f"{action.upper()}_C_{counter}"
```

**Callers to update:**
- `Generator.generate()` in `generate.py` — pass `perm.action` as the action argument
- `CheckCommand._format_policies()` in `check.py` — pass `perm_obj.action` as the action argument

### 2. `CustomPermissionEntry.validate_name_pattern`

**Location:** `directus_ac/models.py`

**Current regex:** `^C_\d+$`

**New regex:** `^(CREATE|READ|UPDATE|DELETE)_C_\d+$`

```python
@field_validator("name")
@classmethod
def validate_name_pattern(cls, v: str) -> str:
    """Ensure name follows the ACTION_C_N pattern (e.g., UPDATE_C_1, READ_C_2)."""
    if not re.match(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$", v):
        raise ValueError(
            f"CustomPermissionEntry name must follow the ACTION_C_N pattern "
            f"(e.g., UPDATE_C_1, READ_C_2); got {v!r}"
        )
    return v
```

### 3. `_format_custom_ref` Simplification

**Location:** `directus_ac/check.py`

**Current behavior:** Returns `"C_1 fields:(title,body) has validation has item permissions"`

**New behavior:** Returns only the name string.

```python
def _format_custom_ref(self, name: str, perm: DirectusPermission) -> str:
    """Format a single custom permission reference.

    Returns only the permission name (e.g., 'UPDATE_C_3').
    """
    return name
```

### 4. `_CUSTOM_REF_PATTERN` Update in Config Parser

**Location:** `directus_ac/config.py`

**Current pattern:** `re.compile(r"^C_\d+$")`

**New pattern:** `re.compile(r"^(CREATE|READ|UPDATE|DELETE)_C_\d+$")`

The `_parse_permission_set` function uses this pattern to classify tokens. No other logic changes are needed — the pattern match already gates classification as a custom ref.

### 5. `_parse_custom_permissions` Validation Update

**Location:** `directus_ac/config.py`

The name validation check currently uses `_CUSTOM_REF_PATTERN`. After updating the pattern, this validation will automatically accept `ACTION_C_N` names and reject old `C_N` names.

Update the error message to reflect the new format:

```python
if not _CUSTOM_REF_PATTERN.match(entry["name"]):
    raise ConfigError(
        f"Custom permission at index {idx} has invalid name "
        f"'{entry['name']}'. Must match pattern ACTION_C_N "
        f"(e.g., UPDATE_C_1, READ_C_2)"
    )
```

### Modified Function Signatures

| Function | Old Signature | New Signature |
|----------|--------------|---------------|
| `generate_permission_name` | `(counter: int) -> str` | `(action: str, counter: int) -> str` |
| `_format_custom_ref` | `(self, name: str, perm: DirectusPermission) -> str` | `(self, name: str, perm: DirectusPermission) -> str` (signature unchanged, behavior simplified) |

### Constants Changed

| Constant | Location | Old Value | New Value |
|----------|----------|-----------|-----------|
| `_CUSTOM_REF_PATTERN` | `config.py` | `r"^C_\d+$"` | `r"^(CREATE\|READ\|UPDATE\|DELETE)_C_\d+$"` |

## Data Models

No new data models are introduced. The `CustomPermissionEntry` model retains its fields; only the `name` field validation regex changes.

**CustomPermissionEntry.name field:**
- Old valid values: `C_1`, `C_2`, `C_3`, ...
- New valid values: `CREATE_C_1`, `READ_C_2`, `UPDATE_C_3`, `DELETE_C_4`, ...

## Error Handling

### Validation Errors

- **Invalid name in model:** `ValueError` raised by Pydantic validator with message: `"CustomPermissionEntry name must follow the ACTION_C_N pattern (e.g., UPDATE_C_1, READ_C_2); got '<value>'"`
- **Invalid token in Permission_Set:** `ConfigError` raised with message: `"Invalid permission keyword '<token>' for role '<role>' on collection '<collection>'"`
- **Invalid name in config YAML:** `ConfigError` raised with message: `"Custom permission at index <N> has invalid name '<name>'. Must match pattern ACTION_C_N (e.g., UPDATE_C_1, READ_C_2)"`

### Edge Cases

- **Action string casing:** `generate_permission_name` uppercases the action, so `"read"`, `"Read"`, `"READ"` all produce `READ_C_N`.
- **Unknown action strings:** The generator already skips permissions with unknown actions (via `REVERSE_ACTION_MAP`). Custom permissions with unknown actions are skipped during generation.

## Testing Strategy

### Unit Tests
- Verify `generate_permission_name("read", 1)` returns `"READ_C_1"` (specific example)
- Verify `CustomPermissionEntry` rejects old-format names like `"C_1"` with a `ValueError`
- Verify `_format_custom_ref` returns only the name for a permission with all indicators set
- Verify `_parse_permission_set` raises `ConfigError` for tokens like `"INVALID_C_1"` or `"C_1"` (old format)

### Property Tests
- Properties 1–7 below are tested with Hypothesis (minimum 100 iterations each)
- Generators produce random valid actions, counters, permission lists, and config objects
- Round-trip property (Property 4) uses `serialize_config` → temp file → `load_config`

### Integration Tests
- End-to-end: generate config from a mock Directus instance, serialize, reload, verify names
- Check command output verification against a known permission set

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Name generation produces valid ACTION_C_N format

*For any* valid action string (one of "create", "read", "update", "delete", in any casing) and any positive integer counter, `generate_permission_name(action, counter)` SHALL produce a string matching the pattern `^(CREATE|READ|UPDATE|DELETE)_C_\d+$` where the action prefix is the uppercased action and the numeric suffix equals the counter.

**Validates: Requirements 1.1, 1.2**

### Property 2: Counter assignment is sequential by ascending permission ID

*For any* list of custom permissions with distinct IDs, the counter values assigned by the generator SHALL be a contiguous sequence starting at 1, ordered by ascending permission ID.

**Validates: Requirements 1.3, 5.2**

### Property 3: Name validation accepts only valid ACTION_C_N patterns

*For any* string, `CustomPermissionEntry.validate_name_pattern` SHALL accept it if and only if it matches `^(CREATE|READ|UPDATE|DELETE)_C_\d+$`.

**Validates: Requirements 2.1, 2.2**

### Property 4: Config serialization round-trip preserves custom permission data

*For any* valid `DirectusACConfig` containing custom permissions with `ACTION_C_N` names, serializing with `serialize_config` and then loading with `load_config` SHALL produce an equivalent config where all custom permission names, Permission_Set references, and associated data are preserved.

**Validates: Requirements 3.1, 3.2, 3.3**

### Property 5: Format custom ref returns only the name

*For any* custom permission name and any `DirectusPermission` object (regardless of its `fields`, `validation`, or `permissions` values), `_format_custom_ref(name, perm)` SHALL return exactly the name string with no additional content.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

### Property 6: Check command assigns ACTION_C_N names consistent with generate

*For any* set of permissions detected as custom by the check command, the assigned names SHALL use the `ACTION_C_N` format with the action derived from each permission's action field, and the counter SHALL follow the same global sequential logic as the generate command.

**Validates: Requirements 5.1, 5.2**

### Property 7: Permission_Set parser classifies ACTION_C_N tokens as custom refs

*For any* Permission_Set string containing tokens that match `^(CREATE|READ|UPDATE|DELETE)_C_\d+$`, the parser SHALL classify those tokens as custom permission references (not as standard keywords or invalid tokens).

**Validates: Requirements 6.1, 6.2**
