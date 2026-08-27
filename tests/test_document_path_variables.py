"""Superclass definitions name their target through a path VARIABLE.

MATLAB registers each one as a DID global (ndi.common.PathConstants), so
``$NDIDOCUMENTPATH`` and ``$NDICALCDOCUMENTPATH`` both resolve there. In
NDI-python they resolve to the same folder, because ndi_install.py copies
each dependency's ``ndi_common`` tree into NDI-python's own.

Resolution used to strip only ``$NDIDOCUMENTPATH``, leaving
``$NDICALCDOCUMENTPATH/...`` as a literal path that could not be found --
and a missing superclass was skipped silently, so the document came back
simply lacking everything that superclass defined, including its
``depends_on``. Nothing failed; the properties were just absent.
"""

from __future__ import annotations

import pytest

from ndi.common import ndi_common_PathConstants
from ndi.document import _definition_to_doc_type, ndi_document

CALC_DOC = ndi_common_PathConstants.COMMON_FOLDER / "database_documents" / "calc"
needs_calc = pytest.mark.skipif(
    not CALC_DOC.is_dir(),
    reason="NDIcalc-vis-matlab documents are installed by ndi_install.py",
)


@pytest.mark.parametrize(
    "definition,expected",
    [
        ("$NDIDOCUMENTPATH/element.json", "element"),
        ("$NDIDOCUMENTPATH/data/geneList.json", "data/geneList"),
        ("$NDICALCDOCUMENTPATH/vision/contrast_tuning.json", "vision/contrast_tuning"),
        ("$NDICALCSCHEMAPATH/calc/x_schema.json", "calc/x_schema"),
        ("plain/path.json", "plain/path"),
    ],
)
def test_every_path_variable_is_stripped(definition, expected):
    assert _definition_to_doc_type(definition) == expected


@needs_calc
def test_calc_document_gains_its_calc_superclass_properties():
    """The regression this exists for.

    contrasttuning_calc declares two superclasses, one under each path
    variable. With only $NDIDOCUMENTPATH resolved it came back missing
    'contrast_tuning' and 'depends_on' -- silently, because an unfound
    superclass was skipped without complaint.
    """
    d = ndi_document("calc/contrasttuning_calc")
    props = d.document_properties
    assert "base" in props
    assert "calculator" in props, "from $NDIDOCUMENTPATH/calculator.json"
    assert "contrast_tuning" in props, "from $NDICALCDOCUMENTPATH/vision/contrast_tuning.json"
    assert "depends_on" in props, (
        "depends_on comes from the calc-specific superclass; losing it means "
        "the document cannot record what it was computed from"
    )


@needs_calc
@pytest.mark.parametrize(
    "doc_type",
    [
        "calc/contrastsensitivity_calc",
        "calc/contrasttuning_calc",
        "calc/hartley_calc",
        "calc/oridirtuning_calc",
        "calc/spatial_frequency_tuning_calc",
        "calc/speedtuning_calc",
        "calc/temporal_frequency_tuning_calc",
    ],
)
def test_every_calc_document_resolves_base(doc_type):
    """All seven, not just the six that were failing.

    They failed with KeyError: 'base' because calculator.json -- their
    common superclass, added to NDI-matlab and never copied here -- was
    missing, so nothing in the chain contributed a base section.
    """
    d = ndi_document(doc_type)
    assert "base" in d.document_properties
    assert d.id


@needs_calc
def test_unresolvable_superclass_warns(tmp_path, monkeypatch):
    """A superclass that cannot be found must say so.

    Silence is what let two separate sync gaps present as the same
    confusing KeyError far from either cause.
    """
    import json

    folder = ndi_common_PathConstants.COMMON_FOLDER / "database_documents"
    bad = folder / "_tmp_broken_superclass.json"
    bad.write_text(
        json.dumps(
            {
                "document_class": {
                    "definition": "$NDIDOCUMENTPATH/_tmp_broken_superclass.json",
                    "validation": "",
                    "class_name": "_tmp_broken_superclass",
                    "property_list_name": "_tmp_broken_superclass",
                    "class_version": 1,
                    # A REAL superclass alongside the broken one, so the document
                    # still gets its base section. Otherwise construction dies on
                    # the missing base before the warning can be observed -- which
                    # is itself the old failure mode, not the one under test.
                    "superclasses": [
                        {"definition": "$NDIDOCUMENTPATH/base.json"},
                        {"definition": "$NDIDOCUMENTPATH/no_such_doc.json"},
                    ],
                },
                "_tmp_broken_superclass": {},
            }
        )
    )
    try:
        with pytest.warns(RuntimeWarning, match="could not be resolved"):
            ndi_document("_tmp_broken_superclass")
    finally:
        bad.unlink()


# =========================================================================
# Bare class names
# =========================================================================


@pytest.mark.parametrize(
    "bare,in_subdir",
    [
        ("image", "data/image"),
        ("generic_file", "data/generic_file"),
        ("imageStack", "data/imageStack"),
    ],
)
def test_bare_class_name_resolves_like_matlab(bare, in_subdir):
    """MATLAB resolves a bare name against the whole document tree.

    Only the top level used to be tried here, so ndi.document('image')
    failed while ndi.document('data/image') worked -- a difference
    affecting every document in a subdirectory, and one that forced
    otherwise-symmetric code to diverge at the call site.
    """
    a = ndi_document(bare)
    b = ndi_document(in_subdir)
    assert a.doc_class() == b.doc_class()
    assert sorted(a.document_properties) == sorted(b.document_properties)


def test_explicit_path_is_not_searched_elsewhere():
    """A caller who gave a path meant that file.

    Searching the tree for an explicit path would let 'data/subject'
    silently return the top-level subject.json, which is a different
    document.
    """
    with pytest.raises(FileNotFoundError):
        ndi_document("data/subject")


def test_unknown_type_still_raises():
    with pytest.raises(FileNotFoundError):
        ndi_document("no_such_document_type_anywhere")
