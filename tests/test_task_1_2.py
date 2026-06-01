"""Quick verification for task 1.2 - validate_name_pattern update."""
from pydantic import ValidationError
from directus_ac.models import CustomPermissionEntry

# Test valid ACTION_C_N names
for name in ["CREATE_C_1", "READ_C_2", "UPDATE_C_3", "DELETE_C_100"]:
    e = CustomPermissionEntry(name=name, policy="p", collection="c", action="read")
    assert e.name == name, f"Should accept {name}"
    print(f"✓ Accepted: {name}")

# Test rejected old-format and invalid names
invalid_names = ["C_1", "C_2", "WRITE_C_1", "read_C_1", "UPDATE_C_", "CREATE_C_abc", "X_C_1"]
for name in invalid_names:
    try:
        CustomPermissionEntry(name=name, policy="p", collection="c", action="read")
        print(f"✗ ERROR: Should have rejected: {name}")
    except ValidationError as e:
        msg = e.errors()[0]["msg"]
        assert "ACTION_C_N" in msg, f"Error message should reference ACTION_C_N format, got: {msg}"
        print(f"✓ Rejected: {name}")

print("\nAll checks passed!")
