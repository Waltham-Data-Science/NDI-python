"""Tests for ndi.query module."""

import json

import pytest

from ndi import Query


class TestQueryBasic:
    """Test basic Query construction."""

    def test_create_query_with_field(self):
        """Test creating a query with a field name."""
        q = Query("base.name")
        assert q.field == "base.name"

    def test_create_query_empty_field(self):
        """Test creating a query with empty field (for isa queries)."""
        q = Query("")
        assert q.field == ""

    def test_query_equals(self):
        """Test equals operator."""
        q = Query("base.name") == "test_doc"
        assert q.field == "base.name"
        assert q.operator == "=="
        assert q.value == "test_doc"

    def test_query_not_equals(self):
        """Test not equals operator."""
        q = Query("base.name") != "test_doc"
        assert q.operator == "!="
        assert q.value == "test_doc"

    def test_query_greater_than(self):
        """Test greater than operator."""
        q = Query("ephys.sample_rate") > 30000
        assert q.operator == ">"
        assert q.value == 30000

    def test_query_greater_than_or_equal(self):
        """Test greater than or equal operator."""
        q = Query("ephys.num_channels") >= 4
        assert q.operator == ">="
        assert q.value == 4

    def test_query_less_than(self):
        """Test less than operator."""
        q = Query("ephys.duration") < 100
        assert q.operator == "<"
        assert q.value == 100

    def test_query_less_than_or_equal(self):
        """Test less than or equal operator."""
        q = Query("count") <= 10
        assert q.operator == "<="
        assert q.value == 10

    def test_query_contains(self):
        """Test contains method."""
        q = Query("base.name").contains("electrode")
        assert q.operator == "contains"
        assert q.value == "electrode"

    def test_query_match(self):
        """Test match (regex) method."""
        q = Query("base.name").match(r"^test_\d+$")
        assert q.operator == "match"
        assert q.value == r"^test_\d+$"


class TestQueryNDISpecific:
    """Test NDI-specific query methods."""

    def test_query_isa(self):
        """Test isa method for document class checking."""
        q = Query("").isa("ndi.document.element")
        assert q.operator == "isa"
        assert q.value == "ndi.document.element"

    def test_query_depends_on(self):
        """Test depends_on method."""
        q = Query("").depends_on("element_id", "abc123")
        assert q.operator == "depends_on"
        assert q.value == ("element_id", "abc123")

    def test_query_has_field(self):
        """Test has_field method."""
        q = Query("optional_field").has_field()
        assert q.operator == "hasfield"
        assert q.value

    def test_query_has_member(self):
        """Test has_member method."""
        q = Query("tags").has_member("important")
        assert q.operator == "hasmember"
        assert q.value == "important"


class TestQueryStaticMethods:
    """Test static methods."""

    def test_query_all(self):
        """Test Query.all() returns a query matching all documents."""
        q = Query.all()
        assert q.operator == "isa"
        assert q.value == "base"

    def test_query_none(self):
        """Test Query.none() returns a query matching no documents."""
        q = Query.none()
        assert q.operator == "isa"
        # Value should be something that will never match
        assert "impossible" in q.value.lower() or len(q.value) > 20


class TestQueryFromSearch:
    """Test MATLAB-compatible from_search constructor."""

    def test_from_search_exact_string(self):
        """Test from_search with exact_string operation."""
        q = Query.from_search("base.name", "exact_string", "my_doc")
        assert q.field == "base.name"
        assert q.value == "my_doc"

    def test_from_search_regexp(self):
        """Test from_search with regexp operation."""
        q = Query.from_search("base.name", "regexp", r"test_\d+")
        assert q.operator == "match"
        assert q.value == r"test_\d+"

    def test_from_search_isa(self):
        """Test from_search with isa operation."""
        q = Query.from_search("", "isa", "ndi.document.base")
        assert q.operator == "isa"
        assert q.value == "ndi.document.base"

    def test_from_search_depends_on(self):
        """Test from_search with depends_on operation."""
        q = Query.from_search("", "depends_on", "session_id", "sess_123")
        assert q.operator == "depends_on"
        assert q.value == ("session_id", "sess_123")

    def test_from_search_lessthan(self):
        """Test from_search with lessthan operation."""
        q = Query.from_search("count", "lessthan", 10)
        assert q.operator == "<"
        assert q.value == 10

    def test_from_search_greaterthaneq(self):
        """Test from_search with greaterthaneq operation."""
        q = Query.from_search("rate", "greaterthaneq", 1000)
        assert q.operator == ">="
        assert q.value == 1000

    def test_from_search_hasfield(self):
        """Test from_search with hasfield operation."""
        q = Query.from_search("optional", "hasfield", "")
        assert q.operator == "hasfield"

    def test_from_search_contains_string(self):
        """Test from_search with contains_string operation."""
        q = Query.from_search("description", "contains_string", "electrode")
        assert q.operator == "contains"
        assert q.value == "electrode"

    def test_from_search_invalid_operation(self):
        """Test from_search with invalid operation raises error."""
        with pytest.raises(ValueError):
            Query.from_search("field", "invalid_op", "value")


class TestQueryCombination:
    """Test combining queries with AND/OR."""

    def test_query_and(self):
        """Test combining queries with AND (&)."""
        q1 = Query("base.name") == "test"
        q2 = Query("ephys.channels") > 4
        combined = q1 & q2
        # Combined query should contain both queries
        assert hasattr(combined, "queries")
        assert len(list(combined)) == 2

    def test_query_or(self):
        """Test combining queries with OR (|)."""
        q1 = Query("type") == "ephys"
        q2 = Query("type") == "digital"
        combined = q1 | q2
        assert hasattr(combined, "queries")
        assert len(list(combined)) == 2

    def test_query_complex_combination(self):
        """Test complex query combination."""
        q1 = Query("base.name") == "test"
        q2 = Query("channels") > 4
        q3 = Query("rate") >= 30000
        combined = (q1 & q2) | q3
        # Should be an OrQuery containing AndQuery and q3
        assert hasattr(combined, "queries")


class TestQueryToSearchStructure:
    """Test to_searchstructure method."""

    def test_to_searchstructure_simple(self):
        """Test converting simple query to search structure."""
        q = Query("base.name") == "test"
        ss = q.to_searchstructure()
        assert ss["field"] == "base.name"
        assert ss["operation"] == "=="
        assert ss["param1"] == "test"
        assert ss["param2"] == ""

    def test_to_searchstructure_depends_on(self):
        """Test converting depends_on query to search structure."""
        q = Query("").depends_on("element_id", "abc123")
        ss = q.to_searchstructure()
        assert ss["operation"] == "depends_on"
        assert ss["param1"] == "element_id"
        assert ss["param2"] == "abc123"


class TestQueryMATLABConstructor:
    """Test MATLAB-style Query(field, operation, param1, param2)."""

    def test_isa_constructor(self):
        """Query('', 'isa', 'base') should work like Query.from_search."""
        q = Query("", "isa", "base")
        assert q.operator == "isa"
        assert q.value == "base"
        assert q._resolved

    def test_exact_string_constructor(self):
        """Query('base.name', 'exact_string', 'test') should resolve."""
        q = Query("base.name", "exact_string", "test")
        assert q.field == "base.name"
        assert q.operator == "=="
        assert q.value == "test"

    def test_regexp_constructor(self):
        """Query('base.name', 'regexp', '.*probe.*') should resolve."""
        q = Query("base.name", "regexp", ".*probe.*")
        assert q.operator == "match"
        assert q.value == ".*probe.*"

    def test_depends_on_constructor(self):
        """Query('', 'depends_on', 'session_id', 'abc') should resolve."""
        q = Query("", "depends_on", "session_id", "abc")
        assert q.operator == "depends_on"
        assert q.value == ("session_id", "abc")

    def test_negated_constructor(self):
        """Query('', '~isa', 'base') should resolve negated."""
        q = Query("", "~isa", "base")
        assert q.operator == "~isa"
        assert q.value == "base"

    def test_matches_from_search(self):
        """MATLAB constructor should produce same result as from_search."""
        q1 = Query("", "isa", "element")
        q2 = Query.from_search("", "isa", "element")
        assert q1.field == q2.field
        assert q1.operator == q2.operator
        assert q1.value == q2.value

    def test_no_operation_still_works(self):
        """Query('base.name') should still work as before (Pythonic style)."""
        q = Query("base.name")
        assert q.field == "base.name"
        assert not q._resolved


class TestQueryJSONSerialization:
    """Test that Query objects serialize to JSON-compatible dicts."""

    def test_simple_query_json_serializable(self):
        """to_search_structure() output should be JSON serializable."""
        q = Query("base.name") == "test"
        ss = q.to_search_structure()
        result = json.dumps(ss)
        assert '"exact_string"' in result

    def test_isa_query_json_serializable(self):
        """isa query should serialize cleanly."""
        q = Query("", "isa", "base")
        ss = q.to_search_structure()
        result = json.dumps(ss)
        assert '"isa"' in result

    def test_and_query_json_serializable(self):
        """AND composite query should produce JSON-serializable list."""
        q1 = Query("base.name") == "test"
        q2 = Query("").isa("element")
        combined = q1 & q2
        ss = combined.to_search_structure()
        json.dumps(ss)  # should not raise
        assert isinstance(ss, list)
        assert len(ss) == 2

    def test_or_query_json_serializable(self):
        """OR composite query should produce JSON-serializable dict."""
        q1 = Query("type") == "ephys"
        q2 = Query("type") == "digital"
        combined = q1 | q2
        ss = combined.to_search_structure()
        json.dumps(ss)  # should not raise
        assert ss["operation"] == "or"

    def test_depends_on_json_serializable(self):
        """depends_on query should have param1/param2 in serialized form."""
        q = Query("", "depends_on", "element_id", "abc123")
        ss = q.to_search_structure()
        json.dumps(ss)  # should not raise
        assert ss["param1"] == "element_id"
        assert ss["param2"] == "abc123"
