"""Drift guards for the vendored ``src/ndi/ndi_common/`` tree.

``ndi_common`` is copied from NDI-matlab, not authored here, so the only thing
keeping it honest is a test that pins the values a re-sync is supposed to
produce.  Two failure modes are guarded:

1. **Silent staleness** — Python keeps a value MATLAB has since changed
   (the EMPTY ontology renumbering sat undetected from the initial vendoring
   in 2026-02 until the 2026-08 catch-up).
2. **Over-eager re-sync** — a future "make it byte-for-byte identical" pass
   clobbers a *deliberate* Python adaptation and re-breaks the loader
   (bare ``Inf`` tokens are legal for MATLAB's ``jsondecode`` and illegal for
   Python's ``json``; see commit 8e4660c).

Expected values here were read from ``NDI-matlab origin/main``, not from
whatever this repo happened to contain.
"""

import json
from pathlib import Path

import pytest

import ndi

COMMON = Path(ndi.__file__).parent / "ndi_common"

# Layouts vendored from NDI-matlab origin/main ndi_common/probe/geometry/.
GEOMETRY_LAYOUTS = [
    "generic/linear16_25um.json",
    "generic/tetrode.json",
    "neuronexus/A1x32-Poly2-5mm-50s-177.json",
    "neuropixels/NP2_1shank.json",
    "ucla/UCLAd64.json",
    "ucla/UCLAe64.json",
    "ucla/UCLAf64.json",
]

REQUIRED_LAYOUT_FIELDS = [
    "probe_model",
    "manufacturer",
    "ndim",
    "unit",
    "site_locations_leftright",
    "site_locations_frontback",
    "site_locations_depth",
    "shank_id",
    "contact_shape",
]

PER_SITE_FIELDS = [
    "site_locations_leftright",
    "site_locations_frontback",
    "site_locations_depth",
    "shank_id",
]


class TestProbeGeometryLibrary:
    """MATLAB db7aee405 / 5762f371c / 3bac2f35a / 1be6aac75 (PR #849).

    The layout library is pure data: NDI-python has no ``fun.probe.geometry``
    consumer yet (that port is deferred), so these guard that the *data* ships
    and stays well-formed until the consumer lands.
    """

    def test_library_root_ships(self):
        root = COMMON / "probe" / "geometry"
        assert root.is_dir(), f"probe geometry library missing at {root}"
        assert (root / "README.md").is_file()

    @pytest.mark.parametrize("rel", GEOMETRY_LAYOUTS)
    def test_layout_ships_and_parses(self, rel):
        path = COMMON / "probe" / "geometry" / rel
        assert path.is_file(), f"vendored layout missing: {rel}"
        layout = json.loads(path.read_text())
        missing = [f for f in REQUIRED_LAYOUT_FIELDS if f not in layout]
        assert not missing, f"{rel} missing layout fields: {missing}"

    @pytest.mark.parametrize("rel", GEOMETRY_LAYOUTS)
    def test_layout_site_arrays_agree(self, rel):
        """Every per-site array — and the optional ``map`` — must describe the
        same number of sites, or ``fromLibrary`` builds a mismatched probe."""
        layout = json.loads((COMMON / "probe" / "geometry" / rel).read_text())
        n_sites = len(layout["site_locations_leftright"])
        assert n_sites > 0
        for field in PER_SITE_FIELDS:
            assert len(layout[field]) == n_sites, f"{rel}: {field} length != n_sites"
        if "map" in layout:
            assert len(layout["map"]) == n_sites, f"{rel}: map length != n_sites"

    def test_library_is_grouped_by_directory(self):
        """README documents the layout as ``geometry/<group>/<model>.json``;
        a layout dropped at the top level would not be discoverable."""
        root = COMMON / "probe" / "geometry"
        stray = [p.name for p in root.glob("*.json")]
        assert not stray, f"layouts must live in a <group>/ subdirectory, found {stray}"


class TestEmptyOntologyIdsMatchMatlab:
    """MATLAB 95112ae03 ("updates to EMPTY", 2026-01-30) and 64aef69fe
    ("updates for empty", 2026-02-01) renumbered the EMPTY example ids from the
    8-digit scheme to the current 7-digit one.  NDI-python vendored the
    pre-renumber values and never picked the change up.

    7 digits is also what the live resolver expects:
    ``ndi.ontology.providers.EMPTYProvider`` builds its lookup key with
    ``term.zfill(7)``, so an 8-digit example in the shipped documentation
    points at an id that provider can never resolve.
    """

    DATA_SCHEMAS = [
        "schema_documents/data/generic_file_schema.json",
        "schema_documents/data/imageStack_schema.json",
        "schema_documents/data/ontologyImage_schema.json",
        "schema_documents/data/ontologyLabel_schema.json",
    ]

    @pytest.mark.parametrize("rel", DATA_SCHEMAS)
    def test_data_schemas_use_current_empty_id(self, rel):
        text = (COMMON / rel).read_text()
        assert "EMPTY:00000090" not in text, f"{rel} still carries the pre-2026-01 EMPTY id"
        assert "EMPTY:0000002" in text, f"{rel} lost the current EMPTY id"

    def test_distance_metadata_uses_current_empty_id(self):
        rel = "schema_documents/element/distance_metadata_schema.json"
        text = (COMMON / rel).read_text()
        assert "EMPTY:0000146" not in text, f"{rel} still carries the pre-2026-02 EMPTY id"
        assert text.count("EMPTY:0000052") == 2, f"{rel} lost an EMPTY id (expected 2)"


class TestProbeTypeMapEventEntry:
    """MATLAB 22ea823d8 (2026-02-17) added the ``event`` probe type.  It predates
    the imaging/V_eta rework, so it is portable on its own even though the
    imaging renames in the same file are not.
    """

    def test_event_type_is_registered(self):
        from ndi.probe import initProbeTypeMap

        assert initProbeTypeMap().get("event") == "ndi.probe.timeseries.stimulator"

    def test_event_target_class_exists(self):
        """The map is only strings, so a bad classname fails late, at probe
        construction.  Check the target actually resolves under Python's
        naming (MATLAB ``ndi.probe.timeseries.stimulator`` ->
        ``ndi.probe.timeseries_stimulator.ndi_probe_timeseries_stimulator``)."""
        from ndi.probe.timeseries_stimulator import ndi_probe_timeseries_stimulator

        assert isinstance(ndi_probe_timeseries_stimulator, type)


class TestPythonJsonAdaptationsPreserved:
    """Do NOT re-sync these two byte-for-byte from MATLAB.

    MATLAB ships ``[-Inf,Inf,0]``.  Bare ``Inf``/``-Inf`` are not JSON, so
    ``json.load`` raises, ``_load_schema`` returns ``None``, and — before
    8e4660c made validation fail closed — every document of that class was
    reported valid with zero errors.  ``-1e309``/``1e309`` are legal JSON
    literals that overflow to the identical infinite bounds.
    """

    ADAPTED = [
        "schema_documents/apps/calculations/simple_calc_schema.json",
        "schema_documents/apps/markgarbage/valid_interval_schema.json",
    ]

    @pytest.mark.parametrize("rel", ADAPTED)
    def test_no_bare_inf_tokens(self, rel):
        text = (COMMON / rel).read_text()
        assert "Inf" not in text, (
            f"{rel} regained MATLAB's bare Inf tokens; Python's json cannot "
            "parse them and validation for this class goes dark"
        )

    @pytest.mark.parametrize("rel", ADAPTED)
    def test_ranges_round_trip_to_infinite_bounds(self, rel):
        schema = json.loads((COMMON / rel).read_text())
        # Field lists hang off a key named for the document class, so walk
        # every list-of-dicts rather than hard-coding that key.
        ranges = [
            field["parameters"]
            for value in schema.values()
            if isinstance(value, list)
            for field in value
            if isinstance(field, dict)
            and isinstance(field.get("parameters"), list)
            and len(field["parameters"]) == 3
        ]
        assert ranges, f"{rel}: expected at least one 3-element numeric range"
        for low, high, _flag in ranges:
            assert low == float("-inf"), f"{rel}: lower bound {low!r} is not -inf"
            assert high == float("inf"), f"{rel}: upper bound {high!r} is not +inf"


class TestDocumentCompanionsShip:
    """``database_documents/data/*.md`` are the human-readable companions to the
    document definitions; ``filter`` and ``pyraview`` shipped their .json
    without their .md.
    """

    @pytest.mark.parametrize("stem", ["filter", "pyraview"])
    def test_markdown_companion_ships(self, stem):
        base = COMMON / "database_documents" / "data"
        assert (base / f"{stem}.json").is_file()
        assert (base / f"{stem}.md").is_file(), f"{stem}.md companion missing"
