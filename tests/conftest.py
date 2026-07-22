"""Pytest configuration and fixtures for NDI tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _require_schema_document_path():
    """Fail the whole session if the bundled ndi_common document corpus is missing.

    The schema/validation tests used to wrap document creation in
    ``except FileNotFoundError: pytest.skip(...)``, so a DID-schema path or
    filename regression — exactly the cross-repo drift those tests exist to catch
    — turned them into silent no-ops. This asserts the corpus resolves ONCE, up
    front, so a missing/renamed schema directory is a hard failure instead of ten
    green skips.
    """
    from ndi.common import ndi_common_PathConstants

    doc_path = ndi_common_PathConstants.DOCUMENT_PATH
    assert doc_path.is_dir(), (
        f"ndi_common document corpus not found at {doc_path}. The bundled schema "
        f"definitions are missing or the path constant regressed; NDI document "
        f"creation is broken for every user."
    )
