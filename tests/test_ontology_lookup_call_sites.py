"""ndi.fun.doc.makeSpeciesStrainSex must actually use the ontology result.

Its three lookups each wrote the MATLAB-shaped positional unpack::

    ont_id, name = lookup(Species)          # doc.py:135, :169, :198

`OntologyResult` had `__slots__` and no `__iter__`, so every one of those
raised `TypeError` into the surrounding `except Exception`, which falls back
to using the *input string* as both id and name. Species, Strain and
biological-sex lookups had therefore never resolved, and never reported it —
the fallback made a broken lookup indistinguishable from a resolved one.

`OntologyResult` gained `__iter__` in ndi-ontology-python (MATLAB's six
outputs, in declaration order) and these call sites now read
``ont_id, name, *_``. What follows guards the seam: that the resolved id and
name reach the openMINDS objects, rather than the fallback silently standing
in for them. A mocked provider keeps this offline and deterministic.
"""

import tempfile
from unittest.mock import patch

import pytest

pytest.importorskip("openminds", reason="makeSpeciesStrainSex builds openMINDS objects")


def _result(**kw):
    from ndi.ontology import OntologyResult

    return OntologyResult(**kw)


class TestLookupResultReachesTheDocument:
    def test_species_uses_the_resolved_id_not_the_input_string(self, tmp_path):
        from ndi.fun.doc import makeSpeciesStrainSex
        from ndi.session.dir import ndi_session_dir

        session = ndi_session_dir("ref", str(tmp_path))
        resolved = _result(id="NCBITaxon:10116", name="Rattus norvegicus", prefix="NCBITaxon")

        with patch("ndi.ontology.lookup", return_value=resolved) as mock_lookup:
            docs = makeSpeciesStrainSex(session, "subj-1", Species="NCBITaxon:10116")

        assert mock_lookup.called, "the ontology was never consulted"
        blob = repr([d.document_properties for d in docs])
        assert "Rattus norvegicus" in blob, (
            "the resolved NAME did not reach the document; the except-Exception "
            "fallback substituted the input string, which is the bug this guards"
        )

    def test_the_reexported_result_supports_the_matlab_shaped_unpack(self):
        """The precise failure that made the fallback fire on every call.

        No mock: the guarantee NDI-python needs is that the class it re-exports
        at ``ndi.ontology`` is the one carrying ``__iter__``. Patching
        ``lookup`` would test the patch, not the seam.
        """
        ont_id, name, *rest = _result(
            id="X:1", name="thing", prefix="X", definition="d", short_name="X_1"
        )

        assert (ont_id, name) == ("X:1", "thing")
        assert len(rest) == 4, "MATLAB declares six outputs; four remain after id and name"

    def test_two_name_unpack_still_raises(self):
        """`id, name = lookup(...)` is still wrong, and now fails loudly.

        Python cannot copy MATLAB's "request fewer outputs than declared", so
        the old spelling raises ValueError instead of TypeError. Recorded here
        because a reader of doc.py may wonder why the `*_` is needed.
        """
        with pytest.raises(ValueError):
            _a, _b = _result(id="X:1", name="thing")

    def test_a_failed_lookup_still_falls_back(self):
        """The fallback is still correct when the lookup genuinely fails.

        Fixing the unpack must not remove the safety net for a term that truly
        cannot be resolved — only stop it from firing on every call.
        """
        from ndi.fun.doc import makeSpeciesStrainSex
        from ndi.session.dir import ndi_session_dir

        with tempfile.TemporaryDirectory() as d:
            session = ndi_session_dir("ref", d)
            with patch("ndi.ontology.lookup", side_effect=RuntimeError("no network")):
                docs = makeSpeciesStrainSex(session, "subj-2", Species="Mus musculus")

        assert "Mus musculus" in repr([doc.document_properties for doc in docs])
