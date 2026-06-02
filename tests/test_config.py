"""Tests for config.py — YAML loading and validation (unit + property tests)."""
from __future__ import annotations

import os
import textwrap

import pytest
import yaml

from directus_ac.config import _parse_permission_set, load_config
from directus_ac.exceptions import ConfigError
from directus_ac.models import DirectusACConfig, PermissionKeyword


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path, content: str) -> str:
    """Write *content* to a temp YAML file and return its path."""
    p = tmp_path / "directus_ac.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(p)


MINIMAL_VALID_YAML = """\
    collections:
      - articles
    roles:
      - editor
    groups:
      - collections:
          - articles
        permissions:
          editor: "READ WRITE"
"""


# ---------------------------------------------------------------------------
# Unit tests — happy path
# ---------------------------------------------------------------------------

class TestLoadConfigValid:
    def test_returns_directus_ac_config(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(path)
        assert isinstance(cfg, DirectusACConfig)

    def test_collections_parsed(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(path)
        assert cfg.collections == ["articles"]

    def test_roles_parsed(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(path)
        assert cfg.roles == ["editor"]

    def test_groups_parsed(self, tmp_path):
        path = _write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(path)
        assert len(cfg.groups) == 1
        group = cfg.groups[0]
        assert group.collections == ["articles"]
        assert set(group.permissions["editor"]) == {
            PermissionKeyword.READ,
            PermissionKeyword.WRITE,
        }

    def test_all_four_keywords(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - admin
            groups:
              - collections:
                  - articles
                permissions:
                  admin: "READ WRITE UPDATE DELETE"
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert set(cfg.groups[0].permissions["admin"]) == set(PermissionKeyword)

    def test_single_keyword(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - viewer
            groups:
              - collections:
                  - articles
                permissions:
                  viewer: "READ"
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert cfg.groups[0].permissions["viewer"] == [PermissionKeyword.READ]

    def test_multiple_collections_and_roles(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
              - comments
            roles:
              - editor
              - viewer
            groups:
              - collections:
                  - articles
                  - comments
                permissions:
                  editor: "READ WRITE UPDATE DELETE"
                  viewer: "READ"
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert cfg.collections == ["articles", "comments"]
        assert cfg.roles == ["editor", "viewer"]

    def test_multiple_groups(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
              - comments
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ WRITE"
              - collections:
                  - comments
                permissions:
                  editor: "READ"
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert len(cfg.groups) == 2

    def test_duplicate_keywords_deduplicated(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ READ WRITE READ"
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        perms = cfg.groups[0].permissions["editor"]
        # Deduplicated: READ appears once, WRITE appears once
        assert perms.count(PermissionKeyword.READ) == 1
        assert perms.count(PermissionKeyword.WRITE) == 1
        assert len(perms) == 2

    def test_extra_whitespace_in_permission_set(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "  READ   WRITE  "
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert set(cfg.groups[0].permissions["editor"]) == {
            PermissionKeyword.READ,
            PermissionKeyword.WRITE,
        }

    def test_mixed_permission_set_with_custom_refs(self, tmp_path):
        """Req 3.1, 3.2: Permission_Set with keywords and ACTION_C_N refs is parsed correctly."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ WRITE UPDATE_C_1 CREATE_C_2"
            custom_permissions:
              - name: UPDATE_C_1
                policy: editor
                collection: articles
                action: update
              - name: CREATE_C_2
                policy: editor
                collection: articles
                action: create
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        group = cfg.groups[0]
        assert set(group.permissions["editor"]) == {
            PermissionKeyword.READ,
            PermissionKeyword.WRITE,
        }
        assert group.custom_permission_refs["editor"] == ["UPDATE_C_1", "CREATE_C_2"]

    def test_custom_refs_only_permission_set(self, tmp_path):
        """A Permission_Set with only ACTION_C_N refs and no standard keywords."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ_C_1"
            custom_permissions:
              - name: READ_C_1
                policy: editor
                collection: articles
                action: read
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        group = cfg.groups[0]
        assert group.permissions["editor"] == []
        assert group.custom_permission_refs["editor"] == ["READ_C_1"]

    def test_no_custom_refs_means_empty_custom_permission_refs(self, tmp_path):
        """When no C_N tokens are present, custom_permission_refs is empty."""
        path = _write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(path)
        assert cfg.groups[0].custom_permission_refs == {}


# ---------------------------------------------------------------------------
# Unit tests — error conditions
# ---------------------------------------------------------------------------

class TestLoadConfigFileNotFound:
    def test_raises_config_error(self, tmp_path):
        missing = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(ConfigError):
            load_config(missing)

    def test_error_message_contains_resolved_path(self, tmp_path):
        missing = str(tmp_path / "nonexistent.yaml")
        resolved = os.path.abspath(missing)
        with pytest.raises(ConfigError, match=resolved):
            load_config(missing)

    def test_error_message_prefix(self, tmp_path):
        missing = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(missing)


class TestLoadConfigYAMLError:
    def test_raises_config_error_on_invalid_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("key: [\nbad yaml", encoding="utf-8")
        with pytest.raises(ConfigError, match="YAML parse error"):
            load_config(str(p))

    def test_error_message_contains_line_and_column(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("key: [\nbad yaml", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"line \d+, column \d+"):
            load_config(str(p))


class TestLoadConfigMissingTopLevelKeys:
    def test_missing_all_keys(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text("{}", encoding="utf-8")
        with pytest.raises(ConfigError, match="Missing required keys"):
            load_config(str(p))

    def test_missing_collections(self, tmp_path):
        yaml_content = """\
            roles:
              - editor
            groups: []
        """
        p = tmp_path / "cfg.yaml"
        p.write_text(textwrap.dedent(yaml_content), encoding="utf-8")
        with pytest.raises(ConfigError, match="collections"):
            load_config(str(p))

    def test_missing_roles(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            groups: []
        """
        p = tmp_path / "cfg.yaml"
        p.write_text(textwrap.dedent(yaml_content), encoding="utf-8")
        with pytest.raises(ConfigError, match="roles"):
            load_config(str(p))

    def test_missing_groups(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
        """
        p = tmp_path / "cfg.yaml"
        p.write_text(textwrap.dedent(yaml_content), encoding="utf-8")
        with pytest.raises(ConfigError, match="groups"):
            load_config(str(p))

    def test_missing_two_keys_listed_in_message(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
        """
        p = tmp_path / "cfg.yaml"
        p.write_text(textwrap.dedent(yaml_content), encoding="utf-8")
        with pytest.raises(ConfigError) as exc_info:
            load_config(str(p))
        msg = str(exc_info.value)
        assert "roles" in msg
        assert "groups" in msg

    def test_non_dict_document_raises_missing_keys(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="Missing required keys"):
            load_config(str(p))


class TestLoadConfigMalformedGroup:
    def test_group_missing_collections(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - permissions:
                  editor: "READ"
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="Group at index 0 is missing key: collections"):
            load_config(path)

    def test_group_missing_permissions(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="Group at index 0 is missing key: permissions"):
            load_config(path)

    def test_second_group_malformed_reports_correct_index(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
              - collections:
                  - articles
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="Group at index 1 is missing key: permissions"):
            load_config(path)


class TestLoadConfigInvalidKeyword:
    def test_invalid_keyword_raises_config_error(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ EXECUTE"
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="Invalid permission keyword"):
            load_config(path)

    def test_error_message_contains_keyword(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ BADKW"
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="BADKW"):
            load_config(path)

    def test_error_message_contains_role(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "INVALID"
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="editor"):
            load_config(path)

    def test_error_message_contains_collection(self, tmp_path):
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "INVALID"
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="articles"):
            load_config(path)


# ---------------------------------------------------------------------------
# Unit tests — _parse_permission_set directly
# ---------------------------------------------------------------------------

class TestParsePermissionSet:
    def test_single_valid_keyword(self):
        keywords, custom_refs = _parse_permission_set("READ", role="r", collection="c")
        assert keywords == [PermissionKeyword.READ]
        assert custom_refs == []

    def test_all_keywords(self):
        keywords, custom_refs = _parse_permission_set("READ WRITE UPDATE DELETE", role="r", collection="c")
        assert set(keywords) == set(PermissionKeyword)
        assert custom_refs == []

    def test_deduplication(self):
        keywords, custom_refs = _parse_permission_set("READ READ WRITE", role="r", collection="c")
        assert keywords.count(PermissionKeyword.READ) == 1
        assert len(keywords) == 2

    def test_strips_whitespace(self):
        keywords, custom_refs = _parse_permission_set("  READ  ", role="r", collection="c")
        assert keywords == [PermissionKeyword.READ]
        assert custom_refs == []

    def test_invalid_keyword_raises(self):
        with pytest.raises(ConfigError, match="Invalid permission keyword"):
            _parse_permission_set("READ INVALID", role="myrole", collection="mycol")

    def test_invalid_keyword_message_contains_keyword(self):
        with pytest.raises(ConfigError, match="INVALID"):
            _parse_permission_set("INVALID", role="r", collection="c")

    def test_invalid_keyword_message_contains_role(self):
        with pytest.raises(ConfigError, match="myrole"):
            _parse_permission_set("BAD", role="myrole", collection="c")

    def test_invalid_keyword_message_contains_collection(self):
        with pytest.raises(ConfigError, match="mycol"):
            _parse_permission_set("BAD", role="r", collection="mycol")

    def test_lowercase_keyword_is_accepted(self):
        # The parser normalises tokens to uppercase before validation, so lowercase
        # variants of valid keywords are accepted (lenient parsing).
        keywords, custom_refs = _parse_permission_set("read", role="r", collection="c")
        assert keywords == [PermissionKeyword.READ]
        assert custom_refs == []

    def test_custom_ref_single(self):
        """ACTION_C_N tokens are recognized as custom permission references."""
        keywords, custom_refs = _parse_permission_set("READ_C_1", role="r", collection="c")
        assert keywords == []
        assert custom_refs == ["READ_C_1"]

    def test_custom_ref_multiple(self):
        """Multiple C_N tokens are collected."""
        keywords, custom_refs = _parse_permission_set("READ_C_1 READ_C_2 READ_C_3", role="r", collection="c")
        assert keywords == []
        assert custom_refs == ["READ_C_1", "READ_C_2", "READ_C_3"]

    def test_mixed_keywords_and_custom_refs(self):
        """Standard keywords and ACTION_C_N tokens can be mixed."""
        keywords, custom_refs = _parse_permission_set("READ READ_C_1 WRITE UPDATE_C_2", role="r", collection="c")
        assert set(keywords) == {PermissionKeyword.READ, PermissionKeyword.WRITE}
        assert custom_refs == ["READ_C_1", "UPDATE_C_2"]

    def test_custom_ref_deduplication(self):
        """Duplicate C_N tokens are deduplicated."""
        keywords, custom_refs = _parse_permission_set("READ_C_1 READ_C_1 READ_C_2", role="r", collection="c")
        assert custom_refs == ["READ_C_1", "READ_C_2"]

    def test_custom_ref_large_number(self):
        """C_N with large counter values are accepted."""
        keywords, custom_refs = _parse_permission_set("READ_C_999", role="r", collection="c")
        assert custom_refs == ["READ_C_999"]

    def test_invalid_c_prefix_without_digits_raises(self):
        """C_ without digits is not a valid token."""
        with pytest.raises(ConfigError, match="Invalid permission keyword"):
            _parse_permission_set("C_", role="r", collection="c")

    def test_invalid_c_prefix_with_letters_raises(self):
        """C_abc is not a valid token."""
        with pytest.raises(ConfigError, match="Invalid permission keyword"):
            _parse_permission_set("C_abc", role="r", collection="c")


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st


# Feature: directus-access-control, Property 1: Permission_Set parsing round-trip
# Validates: Requirements 6.2, 7.5
@given(st.frozensets(st.sampled_from(["READ", "WRITE", "UPDATE", "DELETE"]), min_size=1))
@settings(max_examples=100)
def test_permission_set_round_trip(keywords):
    """Serializing a set of valid keywords to a space-separated string and
    parsing it back should produce the same set of keywords."""
    # Serialize to space-separated string
    raw = " ".join(keywords)
    # Parse back
    result_keywords, result_refs = _parse_permission_set(raw, role="r", collection="c")
    # Assert same set of keywords
    assert {kw.value for kw in result_keywords} == keywords
    # No custom refs expected
    assert result_refs == []


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

from hypothesis import assume, given, settings
from hypothesis import strategies as st

VALID_KEYWORDS = frozenset(["READ", "WRITE", "UPDATE", "DELETE"])


# Feature: directus-access-control, Property 2: Invalid keywords are always rejected
# Validates: Requirements 1.7
@given(
    st.lists(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll"))),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=100)
def test_invalid_keyword_always_rejected(tokens):
    # Ensure at least one token is not a valid keyword
    assume(any(t.upper() not in VALID_KEYWORDS for t in tokens))
    raw = " ".join(tokens)
    with pytest.raises(ConfigError):
        _parse_permission_set(raw, role="r", collection="c")


# ---------------------------------------------------------------------------
# Unit tests — custom_permissions parsing
# ---------------------------------------------------------------------------

from directus_ac.config import _parse_custom_permissions
from directus_ac.models import CustomPermissionEntry


YAML_WITH_CUSTOM_PERMISSIONS = """\
    collections:
      - articles
    roles:
      - editor
    groups:
      - collections:
          - articles
        permissions:
          editor: "READ WRITE"
    custom_permissions:
      - name: UPDATE_C_1
        policy: editor
        collection: articles
        action: update
        validation:
          _and:
            - status:
                _eq: draft
        fields:
          - title
          - body
"""


class TestLoadConfigCustomPermissionsValid:
    def test_absent_custom_permissions_defaults_to_empty(self, tmp_path):
        """Req 3.3: absent key means zero custom permissions, no error."""
        path = _write_yaml(tmp_path, MINIMAL_VALID_YAML)
        cfg = load_config(path)
        assert cfg.custom_permissions == []

    def test_parses_custom_permissions_entry(self, tmp_path):
        """Req 3.1, 3.2: valid custom_permissions are parsed correctly."""
        path = _write_yaml(tmp_path, YAML_WITH_CUSTOM_PERMISSIONS)
        cfg = load_config(path)
        assert len(cfg.custom_permissions) == 1
        entry = cfg.custom_permissions[0]
        assert entry.name == "UPDATE_C_1"
        assert entry.policy == "editor"
        assert entry.collection == "articles"
        assert entry.action == "update"
        assert entry.validation == {"_and": [{"status": {"_eq": "draft"}}]}
        assert entry.fields == ["title", "body"]
        assert entry.permissions is None

    def test_action_case_insensitive(self, tmp_path):
        """Req 3.6: action comparison is case-insensitive."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: UPDATE_C_1
                policy: editor
                collection: articles
                action: UPDATE
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert cfg.custom_permissions[0].action == "update"

    def test_action_mixed_case(self, tmp_path):
        """Req 3.6: action comparison is case-insensitive (mixed case)."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: CREATE_C_1
                policy: editor
                collection: articles
                action: Create
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert cfg.custom_permissions[0].action == "create"

    def test_optional_fields_omitted(self, tmp_path):
        """Optional fields default to None when not present."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: READ_C_1
                policy: editor
                collection: articles
                action: read
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        entry = cfg.custom_permissions[0]
        assert entry.validation is None
        assert entry.fields is None
        assert entry.permissions is None

    def test_multiple_entries(self, tmp_path):
        """Multiple custom permission entries are parsed."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: CREATE_C_1
                policy: editor
                collection: articles
                action: create
              - name: DELETE_C_2
                policy: editor
                collection: articles
                action: delete
        """
        path = _write_yaml(tmp_path, yaml_content)
        cfg = load_config(path)
        assert len(cfg.custom_permissions) == 2
        assert cfg.custom_permissions[0].name == "CREATE_C_1"
        assert cfg.custom_permissions[1].name == "DELETE_C_2"


class TestLoadConfigCustomPermissionsErrors:
    def test_not_a_list_raises_config_error(self, tmp_path):
        """Req 3.5: non-list value raises ConfigError."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions: "not a list"
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="custom_permissions must be a list"):
            load_config(path)

    def test_dict_value_raises_config_error(self, tmp_path):
        """Req 3.5: dict value raises ConfigError."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              key: value
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="custom_permissions must be a list"):
            load_config(path)

    def test_missing_name_field(self, tmp_path):
        """Req 3.4: missing 'name' raises ConfigError with index and field."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - policy: editor
                collection: articles
                action: read
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 0.*missing required field: name"):
            load_config(path)

    def test_missing_policy_field(self, tmp_path):
        """Req 3.4: missing 'policy' raises ConfigError with index and field."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: C_1
                collection: articles
                action: read
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 0.*missing required field: policy"):
            load_config(path)

    def test_missing_collection_field(self, tmp_path):
        """Req 3.4: missing 'collection' raises ConfigError."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: C_1
                policy: editor
                action: read
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 0.*missing required field: collection"):
            load_config(path)

    def test_missing_action_field(self, tmp_path):
        """Req 3.4: missing 'action' raises ConfigError."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: C_1
                policy: editor
                collection: articles
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 0.*missing required field: action"):
            load_config(path)

    def test_invalid_action_value(self, tmp_path):
        """Req 3.6: invalid action raises ConfigError with index and value."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: READ_C_1
                policy: editor
                collection: articles
                action: execute
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 0.*invalid action.*execute"):
            load_config(path)

    def test_invalid_action_preserves_original_case_in_message(self, tmp_path):
        """Error message shows the original action value."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: READ_C_1
                policy: editor
                collection: articles
                action: BADACTION
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="BADACTION"):
            load_config(path)

    def test_second_entry_error_reports_correct_index(self, tmp_path):
        """Error at index 1 is reported correctly."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: READ_C_1
                policy: editor
                collection: articles
                action: read
              - name: READ_C_2
                policy: editor
                collection: articles
                action: badvalue
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 1.*invalid action.*badvalue"):
            load_config(path)

    def test_exceeds_max_entries(self, tmp_path):
        """Req 3.2: more than 500 entries raises ConfigError."""
        entries = []
        for i in range(501):
            entries.append({
                "name": f"READ_C_{i + 1}",
                "policy": "editor",
                "collection": "articles",
                "action": "read",
            })
        doc = {
            "collections": ["articles"],
            "roles": ["editor"],
            "groups": [{"collections": ["articles"], "permissions": {"editor": "READ"}}],
            "custom_permissions": entries,
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(doc), encoding="utf-8")
        with pytest.raises(ConfigError, match="at most 500"):
            load_config(str(p))

    def test_empty_name_field_raises(self, tmp_path):
        """Req 3.2: name must be 1-255 chars; empty string fails."""
        yaml_content = """\
            collections:
              - articles
            roles:
              - editor
            groups:
              - collections:
                  - articles
                permissions:
                  editor: "READ"
            custom_permissions:
              - name: ""
                policy: editor
                collection: articles
                action: read
        """
        path = _write_yaml(tmp_path, yaml_content)
        with pytest.raises(ConfigError, match="index 0.*field 'name'.*between 1 and 255"):
            load_config(path)

    def test_name_too_long_raises(self, tmp_path):
        """Req 3.2: name must be 1-255 chars; 256 chars fails."""
        long_name = "a" * 256
        doc = {
            "collections": ["articles"],
            "roles": ["editor"],
            "groups": [{"collections": ["articles"], "permissions": {"editor": "READ"}}],
            "custom_permissions": [
                {"name": long_name, "policy": "editor", "collection": "articles", "action": "read"}
            ],
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(doc), encoding="utf-8")
        with pytest.raises(ConfigError, match="index 0.*field 'name'.*between 1 and 255"):
            load_config(str(p))


# ---------------------------------------------------------------------------
# Direct unit tests — _parse_custom_permissions function
# ---------------------------------------------------------------------------


class TestParseCustomPermissionsDirect:
    """Direct tests for _parse_custom_permissions (Req 3.3, 3.4, 3.5, 3.6)."""

    def test_none_returns_empty_list(self):
        """Req 3.3: absent key (None) → empty list, no error."""
        result = _parse_custom_permissions(None)
        assert result == []

    def test_not_a_list_string_raises(self):
        """Req 3.5: string value raises ConfigError."""
        with pytest.raises(ConfigError, match="custom_permissions must be a list"):
            _parse_custom_permissions("not a list")

    def test_not_a_list_int_raises(self):
        """Req 3.5: integer value raises ConfigError."""
        with pytest.raises(ConfigError, match="custom_permissions must be a list"):
            _parse_custom_permissions(42)

    def test_not_a_list_dict_raises(self):
        """Req 3.5: dict value raises ConfigError."""
        with pytest.raises(ConfigError, match="custom_permissions must be a list"):
            _parse_custom_permissions({"key": "value"})

    def test_not_a_list_bool_raises(self):
        """Req 3.5: boolean value raises ConfigError."""
        with pytest.raises(ConfigError, match="custom_permissions must be a list"):
            _parse_custom_permissions(True)

    def test_empty_list_returns_empty(self):
        """Empty list is valid and returns empty list."""
        result = _parse_custom_permissions([])
        assert result == []

    def test_valid_entry_parsed(self):
        """Req 3.2: valid entry is parsed into CustomPermissionEntry."""
        raw = [
            {
                "name": "READ_C_1",
                "policy": "editor",
                "collection": "articles",
                "action": "read",
            }
        ]
        result = _parse_custom_permissions(raw)
        assert len(result) == 1
        assert isinstance(result[0], CustomPermissionEntry)
        assert result[0].name == "READ_C_1"
        assert result[0].policy == "editor"
        assert result[0].collection == "articles"
        assert result[0].action == "read"

    def test_valid_entry_with_optional_fields(self):
        """Optional fields (validation, fields, permissions) are parsed."""
        raw = [
            {
                "name": "UPDATE_C_1",
                "policy": "editor",
                "collection": "articles",
                "action": "update",
                "validation": {"_and": [{"status": {"_eq": "draft"}}]},
                "fields": ["title", "body"],
                "permissions": {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]},
            }
        ]
        result = _parse_custom_permissions(raw)
        assert result[0].validation == {"_and": [{"status": {"_eq": "draft"}}]}
        assert result[0].fields == ["title", "body"]
        assert result[0].permissions == {"_and": [{"author": {"_eq": "$CURRENT_USER"}}]}

    def test_optional_fields_default_to_none(self):
        """Optional fields default to None when absent."""
        raw = [
            {
                "name": "READ_C_1",
                "policy": "editor",
                "collection": "articles",
                "action": "read",
            }
        ]
        result = _parse_custom_permissions(raw)
        assert result[0].validation is None
        assert result[0].fields is None
        assert result[0].permissions is None

    def test_missing_name_raises_with_index(self):
        """Req 3.4: missing 'name' → ConfigError with index 0."""
        raw = [{"policy": "editor", "collection": "articles", "action": "read"}]
        with pytest.raises(ConfigError, match="index 0.*missing required field: name"):
            _parse_custom_permissions(raw)

    def test_missing_policy_raises_with_index(self):
        """Req 3.4: missing 'policy' → ConfigError with index 0."""
        raw = [{"name": "READ_C_1", "collection": "articles", "action": "read"}]
        with pytest.raises(ConfigError, match="index 0.*missing required field: policy"):
            _parse_custom_permissions(raw)

    def test_missing_collection_raises_with_index(self):
        """Req 3.4: missing 'collection' → ConfigError with index 0."""
        raw = [{"name": "READ_C_1", "policy": "editor", "action": "read"}]
        with pytest.raises(ConfigError, match="index 0.*missing required field: collection"):
            _parse_custom_permissions(raw)

    def test_missing_action_raises_with_index(self):
        """Req 3.4: missing 'action' → ConfigError with index 0."""
        raw = [{"name": "READ_C_1", "policy": "editor", "collection": "articles"}]
        with pytest.raises(ConfigError, match="index 0.*missing required field: action"):
            _parse_custom_permissions(raw)

    def test_missing_field_at_index_2(self):
        """Req 3.4: error at index 2 reports correct index."""
        raw = [
            {"name": "READ_C_1", "policy": "ed", "collection": "art", "action": "read"},
            {"name": "CREATE_C_2", "policy": "ed", "collection": "art", "action": "create"},
            {"name": "DELETE_C_3", "policy": "ed", "action": "delete"},  # missing collection
        ]
        with pytest.raises(ConfigError, match="index 2.*missing required field: collection"):
            _parse_custom_permissions(raw)

    def test_invalid_action_raises_with_index(self):
        """Req 3.6: invalid action → ConfigError with index and value."""
        raw = [
            {"name": "READ_C_1", "policy": "editor", "collection": "articles", "action": "execute"}
        ]
        with pytest.raises(ConfigError, match="index 0.*invalid action.*execute"):
            _parse_custom_permissions(raw)

    def test_invalid_action_at_index_1(self):
        """Req 3.6: invalid action at index 1 reports correct index."""
        raw = [
            {"name": "READ_C_1", "policy": "ed", "collection": "art", "action": "read"},
            {"name": "READ_C_2", "policy": "ed", "collection": "art", "action": "badval"},
        ]
        with pytest.raises(ConfigError, match="index 1.*invalid action.*badval"):
            _parse_custom_permissions(raw)

    def test_action_normalized_to_lowercase(self):
        """Req 3.6: action is case-insensitive, stored as lowercase."""
        raw = [
            {"name": "READ_C_1", "policy": "editor", "collection": "articles", "action": "READ"}
        ]
        result = _parse_custom_permissions(raw)
        assert result[0].action == "read"

    def test_action_mixed_case_normalized(self):
        """Req 3.6: mixed case action is normalized."""
        raw = [
            {"name": "UPDATE_C_1", "policy": "editor", "collection": "articles", "action": "Update"}
        ]
        result = _parse_custom_permissions(raw)
        assert result[0].action == "update"

    def test_all_valid_actions_accepted(self):
        """All four valid actions are accepted."""
        for action in ("create", "read", "update", "delete"):
            raw = [
                {"name": f"{action.upper()}_C_1", "policy": "ed", "collection": "art", "action": action}
            ]
            result = _parse_custom_permissions(raw)
            assert result[0].action == action

    def test_non_dict_entry_raises(self):
        """Non-dict entry in list raises ConfigError with index."""
        raw = ["not a dict"]
        with pytest.raises(ConfigError, match="index 0.*missing required field: name"):
            _parse_custom_permissions(raw)

    def test_non_string_field_value_raises(self):
        """Non-string value for required field raises ConfigError."""
        raw = [
            {"name": 123, "policy": "editor", "collection": "articles", "action": "read"}
        ]
        with pytest.raises(ConfigError, match="index 0.*missing required field: name"):
            _parse_custom_permissions(raw)

    def test_multiple_valid_entries(self):
        """Multiple valid entries are all parsed."""
        raw = [
            {"name": "READ_C_1", "policy": "ed", "collection": "art", "action": "read"},
            {"name": "CREATE_C_2", "policy": "ed", "collection": "art", "action": "create"},
            {"name": "DELETE_C_3", "policy": "ed", "collection": "com", "action": "delete"},
        ]
        result = _parse_custom_permissions(raw)
        assert len(result) == 3
        assert result[0].name == "READ_C_1"
        assert result[1].name == "CREATE_C_2"
        assert result[2].name == "DELETE_C_3"

    def test_name_matching_action_c_pattern_accepted(self):
        """Req 3.2: name matching ACTION_C_\\d+ pattern is accepted."""
        raw = [
            {"name": "READ_C_42", "policy": "ed", "collection": "art", "action": "read"}
        ]
        result = _parse_custom_permissions(raw)
        assert result[0].name == "READ_C_42"

    def test_name_not_matching_c_pattern_raises(self):
        """Req 3.2: name not matching C_\\d+ pattern raises ConfigError."""
        raw = [
            {"name": "custom_name", "policy": "ed", "collection": "art", "action": "read"}
        ]
        with pytest.raises(ConfigError, match="index 0.*invalid name.*custom_name"):
            _parse_custom_permissions(raw)

    def test_name_pattern_various_invalid(self):
        """Various invalid name patterns raise ConfigError."""
        invalid_names = ["C_", "C_1", "C_abc", "D_1", "c_1", "C1", "1_C", ""]
        for name in invalid_names:
            if name == "":
                continue  # empty string caught by length validation first
            raw = [
                {"name": name, "policy": "ed", "collection": "art", "action": "read"}
            ]
            with pytest.raises(ConfigError, match="invalid name"):
                _parse_custom_permissions(raw)
