"""PR7 §3.4-14: ontology providers + registry.

Uberon/NCIT were registered in the prefix map + Ontologies list but had no
provider class, so ``lookup("UBERON:heart")`` (the headline example) silently
returned nothing. This adds UBERON/NCIT/EDAM/IAO/STATO/SchemaOrg providers,
registers them, and extends ontology_list.json. Lookups hit the EBI OLS API, so
the dispatch→provider→parse chain is tested with a mocked HTTP response.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ndi.ontology as ontology
from ndi.ontology.providers import PROVIDER_REGISTRY, OLSProvider

NEW = ["Uberon", "NCIT", "EDAM", "IAO", "STATO", "SchemaOrg"]


class TestRegistry:
    @pytest.mark.parametrize("name", NEW)
    def test_provider_registered(self, name):
        cls = PROVIDER_REGISTRY.get(name)
        assert cls is not None
        assert issubclass(cls, OLSProvider)
        assert cls.ols_ontology  # has an OLS ontology slug

    def test_ontology_list_has_new_prefixes(self):
        path = (
            Path(ontology.__file__).resolve().parent.parent
            / "ndi_common"
            / "ontology"
            / "ontology_list.json"
        )
        d = json.load(open(path))
        prefixes = {m["prefix"] for m in d["prefix_ontology_mappings"]}
        names = {o["name"] for o in d["Ontologies"]}
        for n in ["EDAM", "IAO", "STATO", "SchemaOrg"]:
            assert n in prefixes, f"{n} missing from prefix_ontology_mappings"
            assert n in names, f"{n} missing from Ontologies"


class TestUberonLookupDispatch:
    """The fix: lookup('UBERON:...') must now reach a provider (was a no-op)."""

    def test_lookup_dispatches_to_uberon(self, monkeypatch):
        canned = {
            "response": {
                "docs": [
                    {
                        "obo_id": "UBERON:0000948",
                        "label": "heart",
                        "short_form": "UBERON_0000948",
                        "description": ["a hollow muscular organ"],
                        "synonym": ["chambered heart"],
                    }
                ]
            }
        }
        monkeypatch.setattr(OLSProvider, "_http_get_json", lambda self, url, params=None: canned)
        # clear any cached entry for a deterministic dispatch
        ontology._lookup_cache.clear()
        result = ontology.lookup("UBERON:0000948")
        assert result.id == "UBERON:0000948"
        assert result.name == "heart"
        assert "chambered heart" in result.synonyms

    def test_unregistered_prefix_still_empty(self):
        # a prefix with no mapping yields an empty result (unchanged behavior)
        result = ontology.lookup("NOTAPREFIX:123")
        assert result.id == ""
