"""Tests for ndi.fun.probe.geometry.

MATLAB counterpart: +ndi/+fun/+probe/+geometry/

The alignment tests carry the weight. NDI stores geometry per SITE and the
exported binary is ordered by CHANNEL, so a channel map is only correct if
the site->channel map is inverted the right way round. Inverting it the
wrong way writes a perfectly valid map with every electrode in the wrong
place, and a sorter given one does not complain -- it merges units that were
never neighbours. So each of these checks a coordinate landed on the channel
that records it, not merely that a file was written.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.io import loadmat

from ndi.fun.probe.geometry import get, toKilosortMap, writeKilosortMap


class FakeDocument:
    def __init__(self, doc_id, properties):
        self._id = doc_id
        self.document_properties = properties

    def id(self):
        return self._id


class FakeProbe:
    def __init__(self, channels=4):
        self._channels = channels

    def id(self):
        return "probe1"

    def elementstring(self):
        return "ctx | 1"

    def epochtable(self):
        return [{"epoch_id": "e1", "t0_t1": [[0.0, 1.0]]}], "hash"

    def readtimeseries(self, epoch=None, t0=0.0, t1=0.0, timeref=None):  # noqa: ARG002
        return np.zeros((1, self._channels)), np.zeros(1), None


class FakeSession:
    """A session answering only the two queries geometry.get makes.

    Documents are matched on the query's own operations rather than on call
    order, so a test that stores a site2channelmap for the wrong geometry
    document sees it ignored, as the real database would.
    """

    def __init__(self, docs=()):
        self.docs = list(docs)

    def database_search(self, query):
        wanted_class, wanted_dependency = _query_terms(query)
        found = []
        for doc in self.docs:
            properties = doc.document_properties
            if wanted_class and wanted_class not in properties:
                continue
            if wanted_dependency:
                name, value = wanted_dependency
                depends = {d["name"]: d["value"] for d in properties.get("depends_on", [])}
                if depends.get(name) != value:
                    continue
            found.append(doc)
        return found


def _query_terms(query):
    """Pull ('probe_geometry', ('probe_id', 'probe1')) out of a query tree."""
    wanted_class = None
    dependency = None
    for term in query.search_structure:
        if term["operation"] == "isa":
            wanted_class = term["param1"]
        elif term["operation"] == "depends_on":
            dependency = (term["param1"], term["param2"])
    return wanted_class, dependency


def geometry_doc(doc_id="geom1", *, depth, leftright, frontback=None, shank=None):
    return FakeDocument(
        doc_id,
        {
            "depends_on": [{"name": "probe_id", "value": "probe1"}],
            "probe_geometry": {
                "site_locations_depth": list(depth),
                "site_locations_leftright": list(leftright),
                "site_locations_frontback": list(frontback or []),
                "shank_id": list(shank or []),
            },
        },
    )


def map_doc(doc_id="s2c1", *, geometry_id="geom1", site_map):
    return FakeDocument(
        doc_id,
        {
            "depends_on": [
                {"name": "probe_id", "value": "probe1"},
                {"name": "probe_geometry_id", "value": geometry_id},
            ],
            "site2channelmap": {"map": list(site_map)},
        },
    )


class TestGet:
    def test_a_probe_with_no_geometry_is_reported_as_not_found(self):
        result = get(FakeSession(), FakeProbe())
        assert result.found is False
        assert result.pg is None
        assert result.map is None

    def test_the_geometry_document_is_returned_with_its_properties(self):
        doc = geometry_doc(depth=[0, 20], leftright=[0, 0])
        result = get(FakeSession([doc]), FakeProbe())
        assert result.found is True
        assert result.pg["site_locations_depth"] == [0, 20]
        assert result.pg_doc is doc

    def test_the_site_to_channel_map_is_read_when_present(self):
        session = FakeSession(
            [geometry_doc(depth=[0, 20], leftright=[0, 0]), map_doc(site_map=[2, 1])]
        )
        result = get(session, FakeProbe())
        assert result.map.tolist() == [2.0, 1.0]

    def test_a_map_belonging_to_another_geometry_is_ignored(self):
        session = FakeSession(
            [
                geometry_doc(depth=[0, 20], leftright=[0, 0]),
                map_doc(geometry_id="somewhere_else", site_map=[2, 1]),
            ]
        )
        assert get(session, FakeProbe()).map is None


class TestToKilosortMap:
    def test_it_writes_nothing_when_there_is_no_geometry(self, tmp_path):
        out = tmp_path / "channel_map.mat"
        found, _ = toKilosortMap(FakeSession(), FakeProbe(), out, verbose=0)
        assert found is False
        assert not out.exists()

    def test_each_sites_coordinates_land_on_the_channel_that_records_it(self, tmp_path):
        """The map says site 1 is on channel 3 and site 2 on channel 1, so
        site 1's depth must appear at channel 3 -- the inversion."""
        session = FakeSession(
            [
                geometry_doc(depth=[10.0, 20.0], leftright=[5.0, 6.0]),
                map_doc(site_map=[3, 1]),
            ]
        )
        out = tmp_path / "channel_map.mat"

        found, _ = toKilosortMap(session, FakeProbe(channels=4), out, verbose=0)

        assert found is True
        mat = loadmat(out)
        assert mat["ycoords"].ravel().tolist() == [20.0, 0.0, 10.0, 0.0]
        assert mat["xcoords"].ravel().tolist() == [6.0, 0.0, 5.0, 0.0]

    def test_channels_no_site_reaches_are_marked_not_connected(self, tmp_path):
        session = FakeSession(
            [geometry_doc(depth=[10.0, 20.0], leftright=[0.0, 0.0]), map_doc(site_map=[3, 1])]
        )
        out = tmp_path / "channel_map.mat"
        toKilosortMap(session, FakeProbe(channels=4), out, verbose=0)

        assert loadmat(out)["connected"].ravel().tolist() == [1, 0, 1, 0]

    def test_shank_ids_become_kcoords(self, tmp_path):
        session = FakeSession(
            [
                geometry_doc(depth=[0.0, 0.0], leftright=[0.0, 0.0], shank=[1, 2]),
                map_doc(site_map=[1, 2]),
            ]
        )
        out = tmp_path / "channel_map.mat"
        toKilosortMap(session, FakeProbe(channels=2), out, verbose=0)

        assert loadmat(out)["kcoords"].ravel().tolist() == [1.0, 2.0]

    def test_a_zero_based_map_is_shifted_up(self, tmp_path):
        """A map imported from a Kilosort file counts channels from 0.
        Taken literally it drops the last channel and shifts the rest."""
        session = FakeSession(
            [geometry_doc(depth=[10.0, 20.0], leftright=[0.0, 0.0]), map_doc(site_map=[0, 1])]
        )
        out = tmp_path / "channel_map.mat"
        toKilosortMap(session, FakeProbe(channels=2), out, verbose=0)

        assert loadmat(out)["ycoords"].ravel().tolist() == [10.0, 20.0]

    def test_no_map_and_matching_counts_assumes_site_i_is_channel_i(self, tmp_path):
        session = FakeSession([geometry_doc(depth=[10.0, 20.0], leftright=[0.0, 0.0])])
        out = tmp_path / "channel_map.mat"

        with pytest.warns(UserWarning, match="assuming site i"):
            found, _ = toKilosortMap(session, FakeProbe(channels=2), out, verbose=1)

        assert found is True
        assert loadmat(out)["ycoords"].ravel().tolist() == [10.0, 20.0]

    def test_no_map_and_mismatched_counts_falls_back_to_no_geometry(self, tmp_path):
        """Guessing here would silently place two electrodes among four
        channels; the caller's default linear map is the honest answer."""
        session = FakeSession([geometry_doc(depth=[10.0, 20.0], leftright=[0.0, 0.0])])
        out = tmp_path / "channel_map.mat"

        with pytest.warns(UserWarning, match="cannot align geometry"):
            found, _ = toKilosortMap(session, FakeProbe(channels=4), out, verbose=1)

        assert found is False
        assert not out.exists()

    def test_a_map_that_places_no_site_falls_back_to_no_geometry(self, tmp_path):
        session = FakeSession([geometry_doc(depth=[10.0], leftright=[0.0]), map_doc(site_map=[99])])
        out = tmp_path / "channel_map.mat"

        with pytest.warns(UserWarning, match="did not place any site"):
            found, _ = toKilosortMap(session, FakeProbe(channels=2), out, verbose=1)

        assert found is False
        assert not out.exists()

    def test_geometry_with_no_site_locations_falls_back(self, tmp_path):
        session = FakeSession([geometry_doc(depth=[], leftright=[])])
        out = tmp_path / "channel_map.mat"
        found, _ = toKilosortMap(session, FakeProbe(), out, verbose=0)
        assert found is False

    def test_the_horizontal_axis_can_be_frontback(self, tmp_path):
        session = FakeSession(
            [
                geometry_doc(depth=[0.0], leftright=[5.0], frontback=[9.0]),
                map_doc(site_map=[1]),
            ]
        )
        out = tmp_path / "channel_map.mat"
        toKilosortMap(session, FakeProbe(channels=1), out, horizontal_axis="frontback", verbose=0)
        assert loadmat(out)["xcoords"].ravel().tolist() == [9.0]

    def test_an_unknown_horizontal_axis_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="horizontal_axis"):
            toKilosortMap(FakeSession(), FakeProbe(), tmp_path / "m.mat", horizontal_axis="up")

    def test_num_channels_defaults_to_the_probes_own_width(self, tmp_path):
        session = FakeSession([geometry_doc(depth=[0.0], leftright=[0.0]), map_doc(site_map=[1])])
        out = tmp_path / "channel_map.mat"
        toKilosortMap(session, FakeProbe(channels=6), out, verbose=0)
        assert loadmat(out)["chanMap"].size == 6


class TestWriteKilosortMap:
    def test_the_default_map_is_a_warned_about_single_column(self, tmp_path):
        out = tmp_path / "channel_map.mat"
        with pytest.warns(UserWarning, match="default single-column"):
            writeKilosortMap(out, num_channels=3, verbose=1)

        mat = loadmat(out)
        assert mat["xcoords"].ravel().tolist() == [0.0, 0.0, 0.0]
        assert mat["ycoords"].ravel().tolist() == [0.0, 20.0, 40.0]
        assert mat["connected"].ravel().tolist() == [1, 1, 1]

    def test_chan_map_is_one_based_and_chan_map_0ind_is_not(self, tmp_path):
        out = tmp_path / "channel_map.mat"
        writeKilosortMap(out, num_channels=3, verbose=0)
        mat = loadmat(out)
        assert mat["chanMap"].ravel().tolist() == [1.0, 2.0, 3.0]
        assert mat["chanMap0ind"].ravel().tolist() == [0.0, 1.0, 2.0]

    def test_supplied_coordinates_are_not_warned_about(self, tmp_path):
        import warnings

        out = tmp_path / "channel_map.mat"
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            writeKilosortMap(out, num_channels=2, xcoords=[1, 2], ycoords=[3, 4], verbose=1)
        assert loadmat(out)["xcoords"].ravel().tolist() == [1.0, 2.0]

    def test_a_wrong_length_array_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="xcoords has 2"):
            writeKilosortMap(
                tmp_path / "m.mat", num_channels=3, xcoords=[1, 2], ycoords=[1, 2, 3], verbose=0
            )

    def test_num_channels_must_be_a_positive_integer(self, tmp_path):
        with pytest.raises(ValueError, match="positive integer"):
            writeKilosortMap(tmp_path / "m.mat", num_channels=0, verbose=0)

    def test_num_channels_can_come_from_a_metadata_sidecar(self, tmp_path):
        """The sidecar next to an exported binary is the only record of the
        channel count once the export is done."""
        from ndi.fun.probe.export import write_metadata

        write_metadata(
            tmp_path / "kiasort.bin.metadata",
            epoch_sample_counts=[10],
            epoch_sample_rates=[1000.0],
            multiplier=1.0,
            num_channels=5,
            probe_name="ctx | 1",
        )
        out = tmp_path / "channel_map.mat"
        writeKilosortMap(out, verbose=0)
        assert loadmat(out)["chanMap"].size == 5

    def test_no_channel_count_anywhere_is_an_error_that_says_so(self, tmp_path):
        with pytest.raises(ValueError, match="no .metadata sidecar"):
            writeKilosortMap(tmp_path / "channel_map.mat", verbose=0)


# ======================================================================
# The library side: the layouts NDI ships, and the documents built from
# them. Sessions and documents here are REAL, unlike the fakes above: a
# probe_geometry declares a probe_id dependency that DID validates, so a
# fake probe id would test a path no caller can reach.
# ======================================================================
import json  # noqa: E402

from ndi.element import ndi_element  # noqa: E402
from ndi.fun.probe import geometry  # noqa: E402
from ndi.fun.probe.geometry import (  # noqa: E402
    EMPTY_COLUMN,
    _column,
    _document_column,
)
from ndi.query import ndi_query  # noqa: E402
from ndi.session.dir import ndi_session_dir  # noqa: E402
from ndi.subject import ndi_subject  # noqa: E402


@pytest.fixture
def session(tmp_path):
    """A session on disk with a subject to hang elements off."""
    directory = tmp_path / "sess"
    directory.mkdir(parents=True, exist_ok=True)
    s = ndi_session_dir("geometry_test", str(directory))
    subject_doc = ndi_subject("mouse@vhlab.org", "test mouse").newdocument()
    subject_doc.set_session_id(s.id())
    s.database_add(subject_doc)
    s._subject_doc = subject_doc
    return s


def make_probe(session, name="ntrodeA"):
    probe = ndi_element(
        session=session,
        name=name,
        reference=1,
        type="n-trode",
        direct=False,
        subject_id=session._subject_doc.id,
    )
    session.database_add(probe.newdocument())
    return probe


def give_channels(probe, n):
    """Make PROBE answer with N channels, as a real n-trode probe would.

    Faking the epoch table and getchanneldevinfo rather than channelCount
    keeps the real counting code in the path being tested.
    """
    probe.epochtable = lambda: ([{"epoch_id": "e1"}], None)
    probe.getchanneldevinfo = lambda epoch: ("dev", 1, "ai", list(range(n)))
    return probe


def count(session, doc_type):
    return len(session.database_search(ndi_query("").isa(doc_type)))


class TestListLibrary:
    def test_every_layout_is_group_slash_model(self):
        names = geometry.list_library()
        assert "generic/tetrode" in names
        assert all("/" in name for name in names)

    def test_a_group_lists_bare_model_names(self):
        assert "tetrode" in geometry.list_library("generic")

    def test_the_order_is_stable(self):
        """MATLAB's dir order is the filesystem's. The Electrode Map app shows
        this list to a user, so it is sorted rather than left to the machine."""
        names = geometry.list_library()
        assert names == sorted(names)

    def test_an_unknown_group_says_so(self):
        with pytest.raises(ValueError, match="nosuchgroup"):
            geometry.list_library("nosuchgroup")

    def test_no_library_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(geometry, "library_root", lambda: tmp_path / "absent")
        assert geometry.list_library() == []


class TestReadLibrary:
    def test_an_exact_name_reads(self):
        layout, path = geometry.read_library("generic/tetrode")
        assert layout["probe_model"] == "tetrode"
        assert len(layout["site_locations_leftright"]) == 4
        assert path.endswith("tetrode.json")

    def test_a_bare_model_is_searched_across_groups(self):
        layout, _ = geometry.read_library("tetrode")
        assert layout["probe_model"] == "tetrode"

    def test_a_missing_layout_says_so(self):
        with pytest.raises(ValueError, match="not found"):
            geometry.read_library("generic/nosuchlayout")

    def test_an_ambiguous_bare_name_says_which_to_use(self, tmp_path, monkeypatch):
        for group in ("labA", "labB"):
            directory = tmp_path / group
            directory.mkdir(parents=True)
            (directory / "shared.json").write_text(
                json.dumps({"site_locations_leftright": [0], "site_locations_depth": [0]}),
                encoding="utf-8",
            )
        monkeypatch.setattr(geometry, "library_root", lambda: tmp_path)
        with pytest.raises(ValueError, match="ambiguous"):
            geometry.read_library("shared")


class TestColumns:
    """The 0x1-not-0x0 rule, which is the one thing document validation is
    strict about here."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, []),
            ([], []),
            (EMPTY_COLUMN, []),
            (3, [3.0]),
            ([1, 2], [1.0, 2.0]),
            ([[1], [2]], [1.0, 2.0]),
        ],
    )
    def test_as_column_flattens(self, value, expected):
        assert list(_column(value)) == expected

    def test_an_empty_column_is_document_shaped(self):
        assert _document_column([]) == EMPTY_COLUMN
        assert _document_column([1, 2]) == [1.0, 2.0]


class TestFromStruct:
    def test_it_writes_a_document_the_database_accepts(self, session):
        """The whole point of the column shaping: a layout with no contour and
        no contact width has empty optional fields, and a document carrying a
        0x0 empty is rejected by validation."""
        probe = make_probe(session)
        layout, _ = geometry.read_library("generic/tetrode")
        pg_doc, s2c_doc, _ = geometry.from_struct(session, probe, layout, verbose=0)
        assert pg_doc is not None
        assert s2c_doc is None
        assert count(session, "probe_geometry") == 1

    def test_missing_site_locations_are_an_error(self, session):
        probe = make_probe(session)
        with pytest.raises(ValueError, match="site_locations_leftright"):
            geometry.from_struct(session, probe, {"probe_model": "x"}, add=False, verbose=0)

    def test_mismatched_site_lists_are_an_error(self, session):
        probe = make_probe(session)
        with pytest.raises(ValueError, match="same number"):
            geometry.from_struct(
                session,
                probe,
                {"site_locations_leftright": [0, 1], "site_locations_depth": [0]},
                add=False,
                verbose=0,
            )

    def test_the_defaults_are_filled_per_site(self, session):
        probe = make_probe(session)
        pg_doc, _, _ = geometry.from_struct(
            session,
            probe,
            {"site_locations_leftright": [0, 1, 2], "site_locations_depth": [0, 10, 20]},
            verbose=0,
        )
        pg = pg_doc.document_properties["probe_geometry"]
        assert list(_column(pg["site_locations_frontback"])) == [0.0, 0.0, 0.0]
        assert list(_column(pg["shank_id"])) == [1.0, 1.0, 1.0]
        assert pg["unit"] == "um"
        assert pg["ndim"] == 2

    def test_a_map_creates_the_site_to_channel_document(self, session):
        probe = make_probe(session)
        _, s2c_doc, _ = geometry.from_struct(
            session,
            probe,
            {"site_locations_leftright": [0, 1], "site_locations_depth": [0, 10]},
            map=[7, 8],
            verbose=0,
        )
        assert s2c_doc is not None
        assert count(session, "site2channelmap") == 1

    def test_a_map_of_the_wrong_length_is_an_error(self, session):
        probe = make_probe(session)
        with pytest.raises(ValueError, match="one element per site"):
            geometry.from_struct(
                session,
                probe,
                {"site_locations_leftright": [0, 1], "site_locations_depth": [0, 10]},
                map=[7],
                add=False,
                verbose=0,
            )

    def test_add_false_writes_nothing(self, session):
        probe = make_probe(session)
        layout, _ = geometry.read_library("generic/tetrode")
        geometry.from_struct(session, probe, layout, add=False, verbose=0)
        assert count(session, "probe_geometry") == 0

    def test_a_channel_mismatch_is_reported_and_not_fatal(self, session):
        """Advisory: a probe can legitimately record a subset of a layout's
        sites, so the assignment still happens."""
        probe = give_channels(make_probe(session), 9)
        layout, _ = geometry.read_library("generic/tetrode")
        with pytest.warns(UserWarning, match="do not match"):
            _, _, info = geometry.from_struct(session, probe, layout, verbose=0)
        assert info["channel_mismatch"] is True
        assert info["n_sites"] == 4
        assert info["n_channels"] == 9
        assert count(session, "probe_geometry") == 1

    def test_the_check_can_be_skipped(self, session):
        probe = give_channels(make_probe(session), 9)
        layout, _ = geometry.read_library("generic/tetrode")
        _, _, info = geometry.from_struct(session, probe, layout, check_channels=False, verbose=0)
        assert info["channel_mismatch"] is False
        assert info["n_channels"] is None


class TestFromLibrary:
    def test_a_shipped_map_becomes_a_site2channelmap(self, session):
        """Some fixed-headstage layouts ship their wiring; a geometry-only
        layout must not invent one."""
        probe = make_probe(session)
        _, s2c_doc, _ = geometry.from_library(
            session, probe, "neuronexus/A1x32-Poly2-5mm-50s-177", verbose=0
        )
        assert s2c_doc is not None
        assert count(session, "site2channelmap") == 1

    def test_a_geometry_only_layout_gets_no_map(self, session):
        probe = make_probe(session)
        _, s2c_doc, _ = geometry.from_library(session, probe, "generic/tetrode", verbose=0)
        assert s2c_doc is None
        assert count(session, "site2channelmap") == 0

    def test_a_supplied_map_beats_the_shipped_one(self, session):
        probe = make_probe(session)
        supplied = list(range(1, 33))
        geometry.from_library(
            session, probe, "neuronexus/A1x32-Poly2-5mm-50s-177", map=supplied, verbose=0
        )
        assert list(geometry.get(session, probe).map) == [float(v) for v in supplied]

    def test_map_is_not_written_as_a_geometry_field(self, session):
        """'map' is a layout field, not a probe_geometry field."""
        probe = make_probe(session)
        pg_doc, _, _ = geometry.from_library(
            session, probe, "neuronexus/A1x32-Poly2-5mm-50s-177", verbose=0
        )
        assert "map" not in pg_doc.document_properties["probe_geometry"]

    def test_replace_overwrites_rather_than_stacking(self, session):
        probe = make_probe(session)
        geometry.from_library(session, probe, "generic/tetrode", verbose=0)
        geometry.from_library(
            session, probe, "neuronexus/A1x32-Poly2-5mm-50s-177", replace=True, verbose=0
        )
        assert count(session, "probe_geometry") == 1
        assert geometry.get(session, probe).pg["probe_model"] == "A1x32-Poly2-5mm-50s-177-A32"

    def test_replace_takes_the_old_map_with_it(self, session):
        """A site2channelmap depends on the geometry it maps; leaving it behind
        would strand a document depending on one that no longer exists."""
        probe = make_probe(session)
        geometry.from_library(session, probe, "neuronexus/A1x32-Poly2-5mm-50s-177", verbose=0)
        geometry.from_library(session, probe, "generic/tetrode", replace=True, verbose=0)
        assert count(session, "site2channelmap") == 0

    def test_without_replace_both_remain(self, session):
        probe = make_probe(session)
        geometry.from_library(session, probe, "generic/tetrode", verbose=0)
        geometry.from_library(session, probe, "generic/linear16_25um", verbose=0)
        assert count(session, "probe_geometry") == 2


class TestPlot:
    def test_it_draws_a_library_layout(self):
        import matplotlib

        matplotlib.use("Agg")
        handles = geometry.plot("generic/tetrode")
        assert handles["sites"] is not None
        assert len(handles["labels"]) == 4
        assert handles["ax"].get_title() == "generic/tetrode"

    def test_the_axis_labels_carry_the_unit(self):
        import matplotlib

        matplotlib.use("Agg")
        handles = geometry.plot("generic/tetrode")
        assert handles["ax"].get_xlabel() == "Left/Right (um)"
        assert handles["ax"].get_ylabel() == "Depth (um)"

    def test_it_draws_a_probe_geometry_document(self, session):
        import matplotlib

        matplotlib.use("Agg")
        probe = make_probe(session)
        pg_doc, _, _ = geometry.from_library(session, probe, "generic/tetrode", verbose=0)
        handles = geometry.plot(pg_doc)
        assert len(handles["labels"]) == 4

    def test_something_else_entirely_says_so(self):
        with pytest.raises(ValueError, match="library name"):
            geometry.plot(42)


class TestMatlabSpellings:
    def test_the_matlab_names_reach_the_same_functions(self):
        assert geometry.listLibrary is geometry.list_library
        assert geometry.readLibrary is geometry.read_library
        assert geometry.fromLibrary is geometry.from_library
        assert geometry.fromStruct is geometry.from_struct
