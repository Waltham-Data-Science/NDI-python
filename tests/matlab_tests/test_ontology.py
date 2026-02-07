"""
Port of MATLAB ndi.unittest.ontology.* tests.

MATLAB source files:
  +ontology/TestOntologyLookup.m -> TestOntologyLookup

Tests for:
- ndi.ontology.lookup() with mocked providers
- ndi.ontology.lookup() with live network (when available)
- ndi.ontology.OntologyResult
- ndi.ontology.clear_cache()

The ontology tests REQUIRE network access for live tests.
Mocked tests run without network.
"""

import socket

import pytest

from ndi.ontology import OntologyResult, lookup, clear_cache


# ---------------------------------------------------------------------------
# Network availability check
# ---------------------------------------------------------------------------

def _can_reach_network() -> bool:
    """Check if we can reach the internet for live ontology lookups."""
    try:
        socket.create_connection(('www.ebi.ac.uk', 443), timeout=3)
        return True
    except (OSError, socket.timeout):
        return False


requires_network = pytest.mark.skipif(
    not _can_reach_network(),
    reason='No network access for ontology lookup',
)


# ===========================================================================
# TestOntologyResult
# ===========================================================================

class TestOntologyResult:
    """Test the OntologyResult data class."""

    def test_result_creation(self):
        """OntologyResult can be created with defaults."""
        result = OntologyResult()
        assert result.id == ''
        assert result.name == ''
        assert result.prefix == ''
        assert result.definition == ''
        assert result.synonyms == []

    def test_result_with_values(self):
        """OntologyResult stores provided values."""
        result = OntologyResult(
            id='NCBITaxon:10090',
            name='Mus musculus',
            prefix='NCBITaxon',
            definition='House mouse',
        )
        assert result.id == 'NCBITaxon:10090'
        assert result.name == 'Mus musculus'
        assert result.prefix == 'NCBITaxon'

    def test_result_bool_empty(self):
        """Empty result is falsy."""
        result = OntologyResult()
        assert not result

    def test_result_bool_nonempty(self):
        """Result with id is truthy."""
        result = OntologyResult(id='CL:0000540')
        assert result

    def test_result_to_dict(self):
        """to_dict() returns a plain dict representation."""
        result = OntologyResult(id='CL:0000540', name='neuron')
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d['id'] == 'CL:0000540'
        assert d['name'] == 'neuron'

    def test_result_repr(self):
        """repr includes id and name."""
        result = OntologyResult(id='CL:0000540', name='neuron')
        r = repr(result)
        assert 'CL:0000540' in r
        assert 'neuron' in r


# ===========================================================================
# TestOntologyLookup - Mocked
# ===========================================================================

class TestOntologyLookupMocked:
    """Port of ndi.unittest.ontology.TestOntologyLookup (mocked).

    Tests lookup() behavior without requiring network access.
    """

    def test_lookup_returns_ontology_result(self):
        """lookup() always returns an OntologyResult object.

        MATLAB equivalent: TestOntologyLookup.testLookupReturnType
        """
        # Looking up a term with no network will return an empty result
        # (providers catch exceptions and return empty OntologyResult)
        result = lookup('EMPTY:anything')
        assert isinstance(result, OntologyResult)

    def test_lookup_no_colon_returns_empty(self):
        """lookup() returns empty result for strings without colon.

        MATLAB equivalent: TestOntologyLookup (edge case)
        """
        result = lookup('no_colon_here')
        assert isinstance(result, OntologyResult)
        assert not result  # falsy for empty result

    def test_lookup_unknown_prefix_returns_empty(self):
        """lookup() returns empty result for unknown prefix.

        MATLAB equivalent: TestOntologyLookup (edge case)
        """
        result = lookup('UNKNOWNPREFIX:12345')
        assert isinstance(result, OntologyResult)
        assert not result

    def test_lookup_clear_cache(self):
        """lookup('clear') clears the internal cache.

        MATLAB equivalent: TestOntologyLookup.testClearCache
        """
        result = lookup('clear')
        assert isinstance(result, OntologyResult)
        assert not result  # clear returns empty result

    def test_clear_cache_function(self):
        """clear_cache() function clears the cache without error.

        MATLAB equivalent: TestOntologyLookup.testClearCache
        """
        clear_cache()  # Should not raise


# ===========================================================================
# TestOntologyLookup - Live network
# ===========================================================================

class TestOntologyLookupLive:
    """Port of ndi.unittest.ontology.TestOntologyLookup (live network).

    These tests require network access and hit real ontology APIs.
    """

    @requires_network
    def test_lookup_ncbi_taxonomy(self):
        """Live: look up 'NCBITaxon:10090' (mouse).

        MATLAB equivalent: TestOntologyLookup.testNCBITaxon
        """
        # Clear cache first to ensure fresh lookup
        clear_cache()

        result = lookup('NCBITaxon:10090')
        assert isinstance(result, OntologyResult)
        assert result  # should be truthy (found something)
        # The name should contain 'Mus musculus' or 'mouse'
        assert result.name, 'Should have a non-empty name'

    @requires_network
    def test_lookup_cell_ontology(self):
        """Live: look up 'CL:0000540' (neuron).

        MATLAB equivalent: TestOntologyLookup.testCLLookup
        """
        clear_cache()

        result = lookup('CL:0000540')
        assert isinstance(result, OntologyResult)
        assert result
        assert result.name, 'Should have a non-empty name'

    @requires_network
    def test_lookup_invalid_term(self):
        """Live: looking up a non-existent term returns empty or partial result.

        MATLAB equivalent: TestOntologyLookup.testInvalidTerm
        """
        clear_cache()

        # A valid prefix but non-existent ID -- should return empty
        result = lookup('CL:9999999')
        assert isinstance(result, OntologyResult)
        # May or may not find something, but should not raise

    @requires_network
    def test_lookup_caching(self):
        """Live: second lookup uses cached result.

        MATLAB equivalent: TestOntologyLookup.testCaching
        """
        clear_cache()

        result1 = lookup('NCBITaxon:10090')
        result2 = lookup('NCBITaxon:10090')

        # Both should return the same data
        assert result1.id == result2.id
        assert result1.name == result2.name
