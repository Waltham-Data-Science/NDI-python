"""
Tests for ndi.validate — Document schema validation.

Tests three-tier validation:
  1. This-class property type checking
  2. Superclass hierarchy validation
  3. Dependency reference checking
"""

from unittest.mock import MagicMock

import pytest

from ndi.validate import (
    _TYPE_VALIDATORS,
    ValidationResult,
    _check_did_uid_params,
    _check_integer_params,
    _get_schema_for_document,
    _is_timestamp,
    _load_schema,
    _schema_cache,
    _validate_depends_on,
    _validate_properties,
    validate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_schema_cache():
    """Clear the schema cache before each test."""
    _schema_cache.clear()
    yield
    _schema_cache.clear()


@pytest.fixture
def base_schema():
    """Minimal base schema matching real NDI format."""
    return {
        "classname": "base",
        "superclasses": [],
        "depends_on": [],
        "base": [
            {"name": "session_id", "type": "did_uid", "parameters": 33},
            {"name": "id", "type": "did_uid", "parameters": 33},
            {"name": "name", "type": "char", "parameters": ""},
            {"name": "datestamp", "type": "timestamp", "parameters": ""},
        ],
    }


@pytest.fixture
def element_schema():
    """Minimal element schema matching real NDI format."""
    return {
        "classname": "element",
        "superclasses": ["base"],
        "depends_on": [
            {"name": "underlying_element_id", "mustbenotempty": 0},
            {"name": "subject_id", "mustbenotempty": 1},
        ],
        "element": [
            {"name": "ndi_element_class", "type": "string", "parameters": ""},
            {"name": "name", "type": "string", "parameters": ""},
            {"name": "reference", "type": "integer", "parameters": [0, 100000, 0]},
            {"name": "type", "type": "string", "parameters": ""},
            {"name": "direct", "type": "integer", "parameters": [0, 1, 0]},
        ],
    }


def _make_doc(props):
    """Create a mock Document with the given document_properties."""
    doc = MagicMock()
    doc.document_properties = props
    return doc


# ===========================================================================
# ValidationResult
# ===========================================================================


class TestValidationResult:
    def test_initial_state(self):
        r = ValidationResult()
        assert r.is_valid is True
        assert r.errors_this == []
        assert r.errors_super == {}
        assert r.errors_depends_on == {}

    def test_bool_true(self):
        r = ValidationResult()
        assert bool(r) is True

    def test_bool_false(self):
        r = ValidationResult()
        r.is_valid = False
        assert bool(r) is False

    def test_error_message_empty(self):
        r = ValidationResult()
        assert r.error_message == ""

    def test_error_message_this_class(self):
        r = ValidationResult()
        r.errors_this = ["base.name: missing property"]
        msg = r.error_message
        assert "This-class errors:" in msg
        assert "base.name: missing property" in msg

    def test_error_message_superclass(self):
        r = ValidationResult()
        r.errors_super = {"base": ['base.id: expected type "did_uid"']}
        msg = r.error_message
        assert 'Superclass "base" errors:' in msg
        assert "did_uid" in msg

    def test_error_message_depends_on(self):
        r = ValidationResult()
        r.errors_depends_on = {
            "subject_id": "missing dependency declaration",
            "element_id": "ok",
        }
        msg = r.error_message
        assert "Dependency errors:" in msg
        assert "subject_id" in msg
        # 'ok' deps should not appear in error message
        assert "element_id" not in msg


# ===========================================================================
# Type validators
# ===========================================================================


class TestTypeValidators:
    def test_did_uid_string(self):
        assert _TYPE_VALIDATORS["did_uid"]("abc-123", "") is True

    def test_did_uid_non_string(self):
        assert _TYPE_VALIDATORS["did_uid"](123, "") is False

    def test_char_string(self):
        assert _TYPE_VALIDATORS["char"]("hello", "") is True

    def test_string_type(self):
        assert _TYPE_VALIDATORS["string"]("test", "") is True

    def test_integer_valid(self):
        assert _TYPE_VALIDATORS["integer"](42, "") is True

    def test_integer_float_whole(self):
        assert _TYPE_VALIDATORS["integer"](3.0, "") is True

    def test_integer_float_non_whole(self):
        assert _TYPE_VALIDATORS["integer"](3.5, "") is False

    def test_double_int(self):
        assert _TYPE_VALIDATORS["double"](5, "") is True

    def test_double_float(self):
        assert _TYPE_VALIDATORS["double"](3.14, "") is True

    def test_double_string(self):
        assert _TYPE_VALIDATORS["double"]("nope", "") is False

    def test_timestamp_valid(self):
        assert _TYPE_VALIDATORS["timestamp"]("2024-01-15T10:30:00Z", "") is True

    def test_timestamp_empty(self):
        assert _TYPE_VALIDATORS["timestamp"]("", "") is True

    def test_timestamp_invalid(self):
        assert _TYPE_VALIDATORS["timestamp"]("not a date", "") is False

    def test_matrix_list(self):
        assert _TYPE_VALIDATORS["matrix"]([1, 2, 3], "") is True

    def test_matrix_tuple(self):
        assert _TYPE_VALIDATORS["matrix"]((1, 2), "") is True

    def test_structure_dict(self):
        assert _TYPE_VALIDATORS["structure"]({"a": 1}, "") is True


# ===========================================================================
# Timestamp helper
# ===========================================================================


class TestIsTimestamp:
    def test_iso_format(self):
        assert _is_timestamp("2024-01-15T10:30:00Z") is True

    def test_empty_string(self):
        assert _is_timestamp("") is True

    def test_invalid(self):
        assert _is_timestamp("January 15, 2024") is False

    def test_date_only(self):
        assert _is_timestamp("2024-01-15") is False


# ===========================================================================
# Integer param checking
# ===========================================================================


class TestCheckIntegerParams:
    def test_in_range(self):
        assert _check_integer_params(5, [0, 10, 0]) is None

    def test_below_range(self):
        err = _check_integer_params(-1, [0, 10, 0])
        assert err is not None
        assert "outside range" in err

    def test_above_range(self):
        err = _check_integer_params(200000, [0, 100000, 0])
        assert err is not None
        assert "outside range" in err

    def test_at_boundary(self):
        assert _check_integer_params(0, [0, 100, 0]) is None
        assert _check_integer_params(100, [0, 100, 0]) is None

    def test_no_params(self):
        assert _check_integer_params(5, "") is None


# ===========================================================================
# did_uid param checking
# ===========================================================================


class TestCheckDidUidParams:
    def test_correct_length(self):
        uid = "a" * 33
        assert _check_did_uid_params(uid, 33) is None

    def test_wrong_length(self):
        uid = "a" * 10
        err = _check_did_uid_params(uid, 33)
        assert err is not None
        assert "expected length 33" in err

    def test_zero_param(self):
        assert _check_did_uid_params("abc", 0) is None

    def test_no_param(self):
        assert _check_did_uid_params("abc", "") is None


# ===========================================================================
# Schema loading
# ===========================================================================


class TestSchemaLoading:
    def test_load_base_schema(self):
        """Load real base_schema.json from the repo."""
        schema = _load_schema("base")
        if schema is None:
            pytest.skip("NDI schema files not available")
        assert schema["classname"] == "base"
        assert "base" in schema

    def test_load_element_schema(self):
        schema = _load_schema("element")
        if schema is None:
            pytest.skip("NDI schema files not available")
        assert schema["classname"] == "element"
        assert "base" in schema["superclasses"]

    def test_load_nonexistent_schema(self):
        result = _load_schema("nonexistent_schema_xyz")
        assert result is None

    def test_schema_caching(self):
        _schema_cache["test_cached"] = {"classname": "test_cached", "superclasses": []}
        result = _load_schema("test_cached")
        assert result["classname"] == "test_cached"

    def test_get_schema_for_document_by_definition(self, base_schema):
        """Test schema lookup via document_class.definition path."""
        _schema_cache["element"] = {"classname": "element", "element": []}
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/element.json",
                    "class_name": "ndi_document_element",
                },
            }
        )
        schema = _get_schema_for_document(doc)
        assert schema is not None
        assert schema["classname"] == "element"

    def test_get_schema_for_document_by_class_name(self):
        """Test schema lookup via document_class.class_name."""
        _schema_cache["element"] = {"classname": "element", "element": []}
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "",
                    "class_name": "ndi_document_element",
                },
            }
        )
        schema = _get_schema_for_document(doc)
        assert schema is not None

    def test_get_schema_for_document_no_class(self):
        doc = _make_doc({})
        schema = _get_schema_for_document(doc)
        assert schema is None


# ===========================================================================
# Property validation
# ===========================================================================


class TestValidateProperties:
    def test_valid_base_properties(self, base_schema):
        props = {
            "base": {
                "session_id": "a" * 33,
                "id": "b" * 33,
                "name": "test_doc",
                "datestamp": "2024-01-15T10:30:00Z",
            },
        }
        errors = _validate_properties(props, "base", base_schema)
        assert errors == []

    def test_missing_property(self, base_schema):
        props = {
            "base": {
                "session_id": "a" * 33,
                # missing 'id', 'name', 'datestamp'
            },
        }
        errors = _validate_properties(props, "base", base_schema)
        assert any("id" in e and "missing" in e for e in errors)

    def test_wrong_type(self, base_schema):
        props = {
            "base": {
                "session_id": "a" * 33,
                "id": "b" * 33,
                "name": 12345,  # should be char/string
                "datestamp": "2024-01-15T10:30:00Z",
            },
        }
        errors = _validate_properties(props, "base", base_schema)
        assert any("name" in e and "char" in e for e in errors)

    def test_empty_value_allowed(self, base_schema):
        props = {
            "base": {
                "session_id": "",
                "id": "",
                "name": "",
                "datestamp": "",
            },
        }
        errors = _validate_properties(props, "base", base_schema)
        assert errors == []

    def test_none_value_allowed(self, base_schema):
        props = {
            "base": {
                "session_id": None,
                "id": None,
                "name": None,
                "datestamp": None,
            },
        }
        errors = _validate_properties(props, "base", base_schema)
        assert errors == []

    def test_integer_range_valid(self, element_schema):
        props = {
            "element": {
                "ndi_element_class": "ndi.element",
                "name": "probe1",
                "reference": 5,
                "type": "n-trode",
                "direct": 0,
            },
        }
        errors = _validate_properties(props, "element", element_schema)
        assert errors == []

    def test_integer_range_invalid(self, element_schema):
        props = {
            "element": {
                "ndi_element_class": "ndi.element",
                "name": "probe1",
                "reference": -1,  # below [0, 100000]
                "type": "n-trode",
                "direct": 0,
            },
        }
        errors = _validate_properties(props, "element", element_schema)
        assert any("reference" in e and "outside range" in e for e in errors)

    def test_did_uid_length_check(self, base_schema):
        props = {
            "base": {
                "session_id": "short",  # should be 33 chars
                "id": "b" * 33,
                "name": "test",
                "datestamp": "2024-01-15T10:30:00Z",
            },
        }
        errors = _validate_properties(props, "base", base_schema)
        assert any("session_id" in e and "expected length" in e for e in errors)

    def test_missing_section(self, base_schema):
        props = {}  # no 'base' section at all
        errors = _validate_properties(props, "base", base_schema)
        # Validation reports missing properties when section is empty dict (default)
        # With empty props, doc_section = {} which means all props are "missing"
        assert len(errors) > 0

    def test_no_schema_defs(self):
        """Schema with no property definitions for this class."""
        schema = {"classname": "empty", "superclasses": []}
        errors = _validate_properties({"empty": {}}, "empty", schema)
        assert errors == []


# ===========================================================================
# Dependency validation
# ===========================================================================


class TestValidateDependsOn:
    def test_optional_dependency_missing(self, element_schema):
        """Optional dependency (mustbenotempty=0) missing from doc is OK."""
        props = {
            "depends_on": [
                {"name": "subject_id", "value": "abc-123"},
            ],
        }
        results = _validate_depends_on(props, element_schema)
        assert results.get("underlying_element_id") == "ok"

    def test_required_dependency_missing(self, element_schema):
        """Required dependency (mustbenotempty=1) missing from doc is error."""
        props = {
            "depends_on": [
                {"name": "underlying_element_id", "value": ""},
            ],
        }
        results = _validate_depends_on(props, element_schema)
        assert "missing" in results.get("subject_id", "")

    def test_required_dependency_empty(self, element_schema):
        props = {
            "depends_on": [
                {"name": "subject_id", "value": ""},
                {"name": "underlying_element_id", "value": ""},
            ],
        }
        results = _validate_depends_on(props, element_schema)
        assert "empty" in results.get("subject_id", "")

    def test_all_dependencies_present(self, element_schema):
        props = {
            "depends_on": [
                {"name": "underlying_element_id", "value": ""},
                {"name": "subject_id", "value": "subj-id-123"},
            ],
        }
        results = _validate_depends_on(props, element_schema)
        assert results.get("subject_id") == "ok"
        assert results.get("underlying_element_id") == "ok"

    def test_database_lookup_found(self, element_schema):
        """When session is provided, check that referenced doc exists."""
        session = MagicMock()
        session.database_search.return_value = [MagicMock()]  # found
        props = {
            "depends_on": [
                {"name": "subject_id", "value": "subj-id-123"},
            ],
        }
        results = _validate_depends_on(props, element_schema, session=session)
        assert results.get("subject_id") == "ok"

    def test_database_lookup_not_found(self, element_schema):
        session = MagicMock()
        session.database_search.return_value = []  # not found
        props = {
            "depends_on": [
                {"name": "subject_id", "value": "missing-id"},
            ],
        }
        results = _validate_depends_on(props, element_schema, session=session)
        assert "not found" in results.get("subject_id", "")

    def test_no_schema_deps(self):
        """Schema with no depends_on."""
        schema = {"depends_on": []}
        props = {"depends_on": [{"name": "x", "value": "y"}]}
        results = _validate_depends_on(props, schema)
        assert results == {}


# ===========================================================================
# Full validate()
# ===========================================================================


class TestValidate:
    def test_validate_no_schema(self):
        """Document with no matching schema passes (can't validate)."""
        doc = _make_doc({"document_class": {"definition": "", "class_name": ""}})
        result = validate(doc)
        assert result.is_valid is True

    def test_validate_valid_base_document(self, base_schema):
        _schema_cache["base"] = base_schema
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/base.json",
                    "class_name": "base",
                },
                "base": {
                    "session_id": "a" * 33,
                    "id": "b" * 33,
                    "name": "my_doc",
                    "datestamp": "2024-01-15T10:30:00Z",
                },
            }
        )
        result = validate(doc)
        assert result.is_valid is True
        assert result.errors_this == []

    def test_validate_invalid_type(self, base_schema):
        _schema_cache["base"] = base_schema
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/base.json",
                    "class_name": "base",
                },
                "base": {
                    "session_id": 12345,  # wrong type — should be string
                    "id": "b" * 33,
                    "name": "my_doc",
                    "datestamp": "2024-01-15T10:30:00Z",
                },
            }
        )
        result = validate(doc)
        assert result.is_valid is False
        assert any("session_id" in e for e in result.errors_this)

    def test_validate_element_with_superclass(self, base_schema, element_schema):
        _schema_cache["base"] = base_schema
        _schema_cache["element"] = element_schema
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/element.json",
                    "class_name": "element",
                },
                "base": {
                    "session_id": "a" * 33,
                    "id": "b" * 33,
                    "name": "my_element",
                    "datestamp": "2024-01-15T10:30:00Z",
                },
                "element": {
                    "ndi_element_class": "ndi.element",
                    "name": "probe1",
                    "reference": 1,
                    "type": "n-trode",
                    "direct": 0,
                },
                "depends_on": [
                    {"name": "underlying_element_id", "value": ""},
                    {"name": "subject_id", "value": "subj-abc-123"},
                ],
            }
        )
        result = validate(doc)
        assert result.is_valid is True

    def test_validate_element_missing_required_dep(self, base_schema, element_schema):
        _schema_cache["base"] = base_schema
        _schema_cache["element"] = element_schema
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/element.json",
                    "class_name": "element",
                },
                "base": {
                    "session_id": "a" * 33,
                    "id": "b" * 33,
                    "name": "my_element",
                    "datestamp": "2024-01-15T10:30:00Z",
                },
                "element": {
                    "ndi_element_class": "ndi.element",
                    "name": "probe1",
                    "reference": 1,
                    "type": "n-trode",
                    "direct": 0,
                },
                "depends_on": [
                    {"name": "underlying_element_id", "value": ""},
                    {"name": "subject_id", "value": ""},  # required but empty
                ],
            }
        )
        result = validate(doc)
        assert result.is_valid is False
        assert "subject_id" in result.errors_depends_on
        assert "empty" in result.errors_depends_on["subject_id"]

    def test_validate_superclass_error(self, base_schema, element_schema):
        _schema_cache["base"] = base_schema
        _schema_cache["element"] = element_schema
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/element.json",
                    "class_name": "element",
                },
                "base": {
                    "session_id": 99999,  # wrong type for base
                    "id": "b" * 33,
                    "name": "elem",
                    "datestamp": "2024-01-15T10:30:00Z",
                },
                "element": {
                    "ndi_element_class": "ndi.element",
                    "name": "probe1",
                    "reference": 1,
                    "type": "n-trode",
                    "direct": 0,
                },
                "depends_on": [
                    {"name": "subject_id", "value": "subj-123"},
                ],
            }
        )
        result = validate(doc)
        assert result.is_valid is False
        assert "base" in result.errors_super

    def test_validate_missing_superclass_schema(self, element_schema):
        """When superclass schema can't be loaded."""
        element_schema["superclasses"] = ["nonexistent_super_xyz"]
        _schema_cache["element"] = element_schema
        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/element.json",
                },
                "element": {
                    "ndi_element_class": "ndi.element",
                    "name": "probe1",
                    "reference": 1,
                    "type": "n-trode",
                    "direct": 0,
                },
                "depends_on": [
                    {"name": "subject_id", "value": "subj-123"},
                ],
            }
        )
        result = validate(doc)
        assert result.is_valid is False
        assert "nonexistent_super_xyz" in result.errors_super


# ===========================================================================
# Document.validate() integration
# ===========================================================================


class TestDocumentValidateIntegration:
    def test_document_validate_returns_result(self, base_schema):
        """Document.validate() should return a ValidationResult."""
        _schema_cache["base"] = base_schema

        doc = _make_doc(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/base.json",
                    "class_name": "base",
                },
                "base": {
                    "session_id": "a" * 33,
                    "id": "b" * 33,
                    "name": "test",
                    "datestamp": "2024-01-15T10:30:00Z",
                },
            }
        )
        # Call via the module function directly
        result = validate(doc)
        assert isinstance(result, ValidationResult)
        assert bool(result) is True


# ===========================================================================
# Module-level imports
# ===========================================================================


class TestModuleImport:
    def test_import_validate_from_ndi(self):
        import ndi

        assert hasattr(ndi, "validate")

    def test_import_validate_function(self):
        from ndi.validate import validate

        assert callable(validate)

    def test_import_validation_result(self):
        from ndi.validate import ValidationResult

        assert ValidationResult is not None
