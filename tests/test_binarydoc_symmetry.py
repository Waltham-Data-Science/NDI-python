"""database_openbinarydoc must answer to the MATLAB attribute name.

MATLAB's returns an ndi.database.binarydoc carrying ``fullpathfilename``
-- session.m uses it itself, as the key for its autoclose listeners.
Python returned a bare file object, so code written against the documented
MATLAB API broke here even though the path was present all along under a
different name.
"""

from __future__ import annotations

import pytest

from ndi.document import ndi_document
from ndi.session.dir import ndi_session_dir

PAYLOAD = b"binary payload for the symmetry test\x00\xff"


@pytest.fixture
def session_with_binary(tmp_path):
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("bin_test", str(d))

    payload = tmp_path / "payload.bin"
    payload.write_bytes(PAYLOAD)

    doc = ndi_document("data/generic_file") + S.newdocument()
    # generic_file.json ships "" for two double fields whose schema allows no
    # empty value (parameters [0,10000000,1] -- three entries, so can-be-empty
    # is off), so a blank generic_file document cannot be added in either
    # language. The defect is in the shared ndi_common JSON and is reported
    # upstream; worked around here rather than patched in NDI-python's copy.
    # See docs/developer_notes/DEPENDENCY_DRIFT_2026-08.md.
    doc.document_properties["generic_file"]["dateCreated"] = 0
    doc.document_properties["generic_file"]["dateUpdated"] = 0
    doc = doc.add_file("generic_file.ext", str(payload))
    S.database_add(doc)
    return S, doc, "generic_file.ext"


def test_handle_carries_fullpathfilename(session_with_binary):
    S, doc, name = session_with_binary
    fh = S.database_openbinarydoc(doc, name)
    try:
        assert hasattr(fh, "fullpathfilename"), (
            "MATLAB's binarydoc exposes fullpathfilename; code written "
            "against that API must work here too"
        )
        assert fh.fullpathfilename == fh.name
        assert fh.fullpathfilename.endswith(name)
    finally:
        S.database_closebinarydoc(fh)


def test_handle_is_still_an_ordinary_file_object(session_with_binary):
    """The attribute is additive. Every existing caller reads bytes from
    this object and must be unaffected."""
    S, doc, name = session_with_binary
    fh = S.database_openbinarydoc(doc, name)
    try:
        assert fh.read() == PAYLOAD
    finally:
        S.database_closebinarydoc(fh)


def test_path_can_be_reopened_by_name(session_with_binary):
    """The whole point: a caller can hand the path to something that
    wants a filename rather than a handle."""
    S, doc, name = session_with_binary
    fh = S.database_openbinarydoc(doc, name)
    path = fh.fullpathfilename
    S.database_closebinarydoc(fh)
    # Reopened by path alone, with no handle and no session involved.
    with open(path, "rb") as f2:
        assert f2.read() == PAYLOAD
