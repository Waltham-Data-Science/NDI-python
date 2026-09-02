"""ndi.ontology is a re-export of the ndi_ontology distribution.

The provider tests live in ndi-ontology-python alongside the implementation.
Keeping a second copy here is exactly what let NDI-python's ontology data
drift from MATLAB's before the split (17 registered prefixes against 22), so
they are not duplicated back.

What NDI-python still owns is the seam: that ``from ndi.ontology import
lookup`` resolves at all, and that it resolves to the *same* objects
``ndi_ontology`` exposes rather than a parallel copy with its own registry and
cache. Everything below tests the seam, not the lookups.
"""

import ndi_ontology


class TestReexportIdentity:
    """ndi.ontology must be the same implementation, not a copy of it."""

    def test_lookup_is_ndi_ontology_lookup(self):
        from ndi.ontology import lookup

        assert lookup is ndi_ontology.lookup

    def test_result_type_is_ndi_ontology_result_type(self):
        from ndi.ontology import OntologyResult

        assert OntologyResult is ndi_ontology.OntologyResult

    def test_clear_cache_is_ndi_ontology_clear_cache(self):
        from ndi.ontology import clearCache

        assert clearCache is ndi_ontology.clearCache

    def test_providers_submodule_resolves(self):
        from ndi.ontology import providers

        assert providers is ndi_ontology.providers

    def test_providers_importable_as_a_submodule_path(self):
        """`from ndi.ontology.providers import X` must work, not just attribute access."""
        from ndi.ontology.providers import PROVIDER_REGISTRY, CLProvider

        assert CLProvider is ndi_ontology.providers.CLProvider
        assert PROVIDER_REGISTRY is ndi_ontology.providers.PROVIDER_REGISTRY

    def test_single_provider_registry(self):
        """One registry, so a provider registered anywhere is visible everywhere."""
        from ndi.ontology.providers import PROVIDER_REGISTRY

        assert PROVIDER_REGISTRY is ndi_ontology.providers.PROVIDER_REGISTRY
        assert "CL" in PROVIDER_REGISTRY

    def test_all_exports(self):
        from ndi.ontology import __all__

        for name in ("OntologyResult", "lookup", "clearCache"):
            assert name in __all__


class TestDataFilesMovedOut:
    """The ontology data files must not come back into this tree.

    They resolve from inside the ndi_ontology package now. A copy re-vendored
    under ndi_common would be read by nothing and would silently drift from
    ndi-ontology-matlab, which is the failure this split ended.
    """

    def test_ontology_list_not_in_ndi_common(self):
        from ndi.common import ndi_common_PathConstants

        stale = ndi_common_PathConstants.COMMON_FOLDER / "ontology" / "ontology_list.json"
        assert not stale.exists(), f"ontology_list.json is back in NDI-python: {stale}"

    def test_ndic_not_in_ndi_common(self):
        from ndi.common import ndi_common_PathConstants

        stale = ndi_common_PathConstants.COMMON_FOLDER / "controlled_vocabulary" / "NDIC.txt"
        assert not stale.exists(), f"NDIC.txt is back in NDI-python: {stale}"

    def test_lookup_reads_the_packaged_data(self):
        """A local (non-network) lookup, proving the dependency ships its data.

        NDIC is the only file-backed provider, so this is the one lookup that
        fails if ndi_ontology is installed without its data files.
        """
        from ndi.ontology import lookup

        result = lookup("NDIC:1")
        assert result.id, "NDIC lookup returned nothing; ndi_ontology data files missing"
        assert result.name
