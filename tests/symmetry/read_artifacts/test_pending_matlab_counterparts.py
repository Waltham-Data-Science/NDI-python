"""Tripwire for the PENDING_MATLAB_COUNTERPART table.

``PENDING_MATLAB_COUNTERPART`` exempts a handful of symmetry surfaces from
``NDI_SYMMETRY_REQUIRE_ARTIFACTS`` because the MATLAB side that produces their
artifacts is not merged anywhere yet.  An exemption with no expiry date is how
a temporary gap becomes a permanent blind spot, so the table gets a tripwire:
the moment the MATLAB producer lands and the artifact appears, this test fails
and names the entry to delete.

The failure is the point.  It is the signal that a surface which has never been
compared across languages *can* now be compared, and that the strict gate
should be taking it over.
"""

from tests.symmetry.conftest import (
    MATLAB_ARTIFACTS,
    PENDING_MATLAB_COUNTERPART,
)


def test_pending_matlab_counterparts_are_still_missing():
    """Every pending entry must still be unproducible, or leave the table."""
    arrived = [
        (rel, why)
        for rel, why in PENDING_MATLAB_COUNTERPART.items()
        if (MATLAB_ARTIFACTS / rel).is_file()
    ]
    assert not arrived, (
        "These MATLAB artifacts are listed as PENDING but now exist, so their\n"
        "surfaces are no longer exempt from NDI_SYMMETRY_REQUIRE_ARTIFACTS.\n"
        "Delete their entries from PENDING_MATLAB_COUNTERPART in\n"
        "tests/symmetry/conftest.py so the strict gate covers them:\n"
        + "\n".join(f"  {rel}\n    (was: {why})" for rel, why in arrived)
    )


def test_pending_entries_are_documented():
    """A bare path with no rationale is a suppression; require the reason."""
    undocumented = [rel for rel, why in PENDING_MATLAB_COUNTERPART.items() if not why.strip()]
    assert not undocumented, (
        "PENDING_MATLAB_COUNTERPART entries must say which producer is missing "
        "and where it lives:\n" + "\n".join(f"  {rel}" for rel in undocumented)
    )
