"""ndi.fun.doc_lightsheet helpers: dtypeName, reduceBlocks, chooseTileShape,
chooseLevel, levelTable, makeSourceFile, viewCommand, view, BuildProfile.

MATLAB counterparts: tests/+ndi/+unittest/+fun/+doc/+lightsheet/Test*.m in
NDI-matlab. The cases and expected values mirror those files.
"""

from __future__ import annotations

import csv
import importlib
import math
import os

import numpy as np
import pydantic
import pytest

from ndi.document import ndi_document
from ndi.fun.doc_lightsheet import (
    BuildProfile,
    chooseLevel,
    chooseTileShape,
    dtypeName,
    levelTable,
    makeSourceFile,
    ndi_fun_doc_lightsheet_BuildProfile,
    reduceBlocks,
    view,
    viewCommand,
)
from ndi.session.dir import ndi_session_dir

# ---------------------------------------------------------------------------
# dtypeName (TestDtypeName)


class TestDtypeName:
    def test_both_ways(self):
        assert dtypeName("uint16", "zarr") == "<u2"
        assert dtypeName("<u2", "zarr") == "<u2"
        assert dtypeName("<u2", "matlab") == "uint16"
        assert dtypeName("uint16", "matlab") == "uint16"
        assert dtypeName("uint8", "zarr") == "|u1"
        assert dtypeName("float32", "matlab") == "single"
        assert dtypeName("<f8", "matlab") == "double"
        assert dtypeName("int16", "zarr") == "<i2"
        assert dtypeName(" Logical ", "zarr") == "|b1"
        assert dtypeName(np.dtype("<u2"), "zarr") == "<u2"

    def test_unknown_type_is_refused(self):
        with pytest.raises(ValueError, match="Unknown voxel type"):
            dtypeName("<c8", "matlab")

    def test_bad_form_is_refused(self):
        with pytest.raises(pydantic.ValidationError):
            dtypeName("uint16", "numpy")


# ---------------------------------------------------------------------------
# reduceBlocks (TestReduceBlocks)


def _reference(a, f, reduction):
    """Per-voxel block reduction: the ndr.format.omezarr.reduce semantics."""
    a = np.asarray(a, dtype=np.float64)
    outShape = [-(-n // k) for n, k in zip(a.shape, f)]
    out = np.zeros(outShape)
    for idx in np.ndindex(*outShape):
        sl = tuple(slice(i * k, min((i + 1) * k, n)) for i, k, n in zip(idx, f, a.shape))
        block = a[sl]
        out[idx] = block.mean() if reduction == "mean" else block.max()
    return out


class TestReduceBlocks:
    def test_mean_matches_reference(self):
        rng = np.random.default_rng(1)
        a = rng.integers(1, 65536, size=(5, 7, 9)).astype(np.uint16)
        got = reduceBlocks(a, [2, 2, 2], "mean", "double")
        assert got.dtype == np.float64
        np.testing.assert_allclose(got, _reference(a, [2, 2, 2], "mean"), atol=1e-2)

    def test_max_matches_reference(self):
        rng = np.random.default_rng(2)
        a = rng.integers(1, 65536, size=(6, 5, 3)).astype(np.uint16)
        got = reduceBlocks(a, [2, 2, 2], "max")
        assert got.dtype == np.uint16
        np.testing.assert_array_equal(got, _reference(a, [2, 2, 2], "max"))

    def test_partial_trailing_block(self):
        a = np.array([[1, 3, 5, 7, 9]], dtype=np.uint16)
        got = reduceBlocks(a, [1, 2], "mean", "double")
        np.testing.assert_array_equal(got, [[2, 6, 9]])

    def test_mean_into_integer_rounds_half_away(self):
        got = reduceBlocks(np.array([[1, 2]], dtype=np.uint16), [1, 2], "mean")
        assert got.dtype == np.uint16
        np.testing.assert_array_equal(got, [[2]])  # 1.5 -> 2
        # 2.5 -> 3 (MATLAB's round), where NumPy's would give 2.
        got = reduceBlocks(np.array([[2, 3]], dtype=np.uint8), [1, 2], "mean")
        np.testing.assert_array_equal(got, [[3]])

    def test_five_d_with_singletons(self):
        a = np.arange(1, 17, dtype=np.uint16).reshape(1, 2, 4, 2, 1)
        got = reduceBlocks(a, [1, 1, 2, 2, 2], "max")
        assert got.shape == (1, 2, 2, 1, 1)
        np.testing.assert_array_equal(got, _reference(a, [1, 1, 2, 2, 1], "max"))

    def test_factor_one_is_identity(self):
        a = np.arange(16, dtype=np.uint16).reshape(4, 4)
        np.testing.assert_array_equal(reduceBlocks(a, [1, 1], "mean"), a)

    def test_scalar_factor_and_extra_trailing_factors(self):
        a = np.arange(16, dtype=np.float64).reshape(4, 4)
        np.testing.assert_array_equal(reduceBlocks(a, 2, "max"), [[5, 7], [13, 15]])
        np.testing.assert_array_equal(reduceBlocks(a, [2, 2, 2], "max"), [[5, 7], [13, 15]])

    def test_out_class_single(self):
        got = reduceBlocks(np.ones((2, 2), dtype=np.uint16), [2, 2], "mean", "single")
        assert got.dtype == np.float32

    def test_too_few_factors(self):
        with pytest.raises(ValueError, match="2 entries for a 3-D"):
            reduceBlocks(np.zeros((2, 2, 2)), [2, 2], "mean")

    def test_bad_reduction(self):
        with pytest.raises(pydantic.ValidationError):
            reduceBlocks(np.zeros((2, 2)), [2, 2], "median")


# ---------------------------------------------------------------------------
# chooseTileShape (TestChooseTileShape)

B8 = 8 * 2**20


class TestChooseTileShape:
    def test_default_budget_is_32mb(self):
        assert chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint16") == [256] * 3
        assert chooseTileShape([1200, 2000, 2000], "zyx", [5, 1, 1], "uint16") == [88, 438, 438]

    def test_isotropic_uint16_hits_budget(self):
        c = chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint16", B8)
        side = (B8 / 2) ** (1 / 3)
        assert abs(c[0] - side) / side < 0.05
        assert c[0] == c[1] == c[2]
        assert 0.8 * B8 < math.prod(c) * 2 < 1.2 * B8

    def test_anisotropic_is_a_world_cube(self):
        c = chooseTileShape([1200, 2000, 2000], "zyx", [5, 1, 1], "uint16", B8)
        assert abs(c[0] * 5 - c[1]) / c[1] < 0.05
        assert c[0] < c[1]
        assert 0.7 * B8 < math.prod(c) * 2 < 1.3 * B8

    def test_channel_and_time_axes_stay_one(self):
        c = chooseTileShape([3, 1200, 2000, 2000], "czyx", [1, 1, 1, 1], "uint16", B8)
        assert c[0] == 1 and c[1] > 1
        c = chooseTileShape([10, 3, 1200, 2000, 2000], "tczyx", [1] * 5, "uint16", B8)
        assert c[:2] == [1, 1]

    def test_clamp_to_shape(self):
        assert chooseTileShape([32, 32, 32], "zyx", [1, 1, 1], "uint16", B8) == [32, 32, 32]

    def test_dtype_sizes(self):
        c16 = chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint16", B8)
        c8 = chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint8", B8)
        cf = chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "float32", B8)
        assert abs(math.prod(c8) / math.prod(c16) - 2) / 2 < 0.1
        assert math.prod(cf) < math.prod(c16)
        assert chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "<u2", B8) == c16

    def test_missing_voxel_size_falls_back(self):
        c = chooseTileShape([1200, 2000, 2000], "zyx", [0, 0, 0], "uint16", B8)
        assert c == chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint16", B8)
        assert c == chooseTileShape([1200, 2000, 2000], "zyx", None, "uint16", B8)

    def test_budget_scales(self):
        small = chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint16", 4 * 2**20)
        big = chooseTileShape([1200, 2000, 2000], "zyx", [1, 1, 1], "uint16", B8)
        assert abs(math.prod(big) / math.prod(small) - 2) / 2 < 0.1

    def test_redistribution_when_one_axis_clamps(self):
        c = chooseTileShape([8, 4096, 4096], "zyx", [1, 1, 1], "uint16", B8)
        assert c[0] == 8
        assert 0.7 * B8 < math.prod(c) * 2 < 1.3 * B8

    def test_tile_count_decreases_across_ladder(self):
        counts, sizes = [], []
        for L in range(5):
            shp = [max(1, s // 2**L) for s in (1200, 2000, 2000)]
            c = chooseTileShape(shp, "zyx", [2**L] * 3, "uint16", B8)
            counts.append(math.prod(-(-s // k) for s, k in zip(shp, c)))
            sizes.append(math.prod(c) * 2)
        assert counts == sorted(counts, reverse=True)
        assert all(b <= 1.3 * B8 for b in sizes)
        assert counts[-1] == 1

    def test_axes_shape_mismatch(self):
        with pytest.raises(ValueError, match="does not match shape length"):
            chooseTileShape([1200, 2000, 2000], "yx", [1, 1, 1], "uint16", B8)


# ---------------------------------------------------------------------------
# chooseLevel (TestChooseLevel)

FOUR = [{"level": k, "voxel_size": [0.5 * 2**k] * 3} for k in range(4)]


class TestChooseLevel:
    def test_scalar_target_picks_coarsest_meeting(self):
        idx, row = chooseLevel(FOUR, 2.0)
        assert idx == 2
        assert row["voxel_size"] == [2.0, 2.0, 2.0]

    def test_between_levels(self):
        assert chooseLevel(FOUR, 1.5)[0] == 1

    def test_finer_than_every_level_returns_finest(self):
        assert chooseLevel(FOUR, 0.1)[0] == 0

    def test_coarser_than_every_level_returns_coarsest(self):
        assert chooseLevel(FOUR, 1000)[0] == 3

    def test_per_axis_target(self):
        assert chooseLevel(FOUR, [1, 3, 3])[0] == 1

    def test_shorter_target_compares_leading_axes(self):
        assert chooseLevel(FOUR, [2, 2])[0] == 2

    def test_empty_levels(self):
        with pytest.raises(ValueError, match="empty"):
            chooseLevel([], 1.0)


# ---------------------------------------------------------------------------
# levelTable (TestLevelTable) and makeSourceFile (TestMakeSourceFile)


@pytest.fixture
def session(tmp_path):
    d = tmp_path / "sess"
    d.mkdir()
    return ndi_session_dir("lightsheet_helpers", str(d))


def _subject(S):
    sub = (
        ndi_document("subject", **{"subject.local_identifier": "lightsheet@vhlab"})
        + S.newdocument()
    )
    S.database_add(sub)
    return sub.id


def _pyramid(S):
    doc = (
        ndi_document(
            "lightsheetZarrPyramid",
            **{
                "lightsheetZarrPyramid.axes_order": "zyx",
                "lightsheetZarrPyramid.shape_level0": [16, 32, 32],
                "lightsheetZarrPyramid.voxel_size_level0": [1, 1, 1],
                "lightsheetZarrPyramid.translation_level0": [0, 0, 0],
                "lightsheetZarrPyramid.dtype": "<u2",
                "lightsheetZarrPyramid.pyramid_name": "box",
            },
        )
        + S.newdocument()
    )
    return doc.set_dependency_value("subject_id", _subject(S))


def _level(S, parent, level, reduction):
    shape = [16 >> level, 32 >> level, 32 >> level]
    doc = (
        ndi_document(
            "lightsheetZarrLevel",
            **{
                "lightsheetZarrLevel.level": level,
                "lightsheetZarrLevel.reduction_function": reduction,
                "lightsheetZarrLevel.axes_order": "zyx",
                "lightsheetZarrLevel.shape": shape,
                "lightsheetZarrLevel.chunks": shape,
                "lightsheetZarrLevel.chunk_grid": [1, 1, 1],
                "lightsheetZarrLevel.voxel_size": [2.0**level] * 3,
                "lightsheetZarrLevel.translation": [0, 0, 0],
                "lightsheetZarrLevel.dtype": "<u2",
            },
        )
        + S.newdocument()
    )
    doc = doc.set_dependency_value("lightsheetZarrPyramid_id", parent.id)
    return doc.set_dependency_value("subject_id", parent.dependency_value("subject_id"))


@pytest.fixture
def ladder(session):
    S = session
    parent = _pyramid(S)
    docs = [parent]
    # Added out of order, so the sort is tested: max/2, mean/1, none/0, ...
    for level, red in ((2, "max"), (1, "mean"), (0, "none"), (2, "mean"), (1, "max")):
        docs.append(_level(S, parent, level, red))
    S.database_add(docs)
    return S, parent


class TestLevelTable:
    def test_full_ladder_finest_first(self, ladder):
        S, parent = ladder
        rows, frame = levelTable(S, parent)
        assert len(rows) == 5
        assert rows[0]["level"] == 0 and rows[0]["reduction_function"] == "none"
        assert [r["level"] for r in rows] == sorted(r["level"] for r in rows)
        assert frame["reductions"] == ["max", "mean"]
        assert frame["axes_order"] == "zyx"
        assert frame["id"] == parent.id
        assert frame["dtype"] == "<u2"

    def test_columns_match_matlab(self, ladder):
        rows, _ = levelTable(*ladder)
        assert list(rows[0]) == [
            "level",
            "reduction_function",
            "shape",
            "chunks",
            "chunk_grid",
            "n_chunks_stored",
            "voxel_size",
            "translation",
            "dtype",
            "id",
        ]
        assert rows[0]["shape"] == [16, 32, 32]

    def test_accepts_id(self, ladder):
        S, parent = ladder
        assert len(levelTable(S, parent.id)[0]) == 5

    def test_unknown_id(self, session):
        with pytest.raises(LookupError):
            levelTable(session, "00000000-0000-0000-0000-000000000000")

    def test_reduction_filter(self, ladder):
        rows, frame = levelTable(*ladder, reduction="max")
        assert len(rows) == 3
        assert {r["reduction_function"] for r in rows} == {"none", "max"}
        assert frame["reductions"] == ["max", "mean"]  # of the full ladder

    def test_empty(self, session):
        parent = _pyramid(session)
        session.database_add(parent)
        rows, frame = levelTable(session, parent)
        assert rows == []
        assert frame["axes_order"] == "zyx"
        assert frame["reductions"] == []

    def test_feeds_choose_level(self, ladder):
        rows, _ = levelTable(*ladder, reduction="mean")
        idx, row = chooseLevel(rows, 2.0)
        assert idx == 1 and row["reduction_function"] == "mean"


class TestMakeSourceFile:
    def test_file_describe_makes_file_reference(self, session, tmp_path):
        f = tmp_path / "a.bin"
        f.write_bytes(b"abcdef")
        doc = makeSourceFile(session, str(f))
        props = doc.document_properties
        assert props["document_class"]["class_name"] == "fileReference"
        r = props["fileReference"]
        assert r["filename"] == "a.bin"
        assert r["fileSize"] == 6
        assert r["checksum"] == "e80b5017098950fc58aad83c8c14978e"
        assert r["checksumAlgorithm"] == "MD5"
        assert r["originalPath"] == str(f)
        assert r["dateUpdated"] > 700000  # a MATLAB datenum
        assert not doc.current_file_list()
        assert props["base"]["session_id"] == session.id()

    def test_file_attach_makes_generic_file(self, session, tmp_path):
        f = tmp_path / "a.bin"
        f.write_bytes(b"abcdef")
        doc = makeSourceFile(session, f, attachFile=True)
        assert doc.document_properties["document_class"]["class_name"] == "generic_file"
        assert list(doc.current_file_list()) == ["generic_file.ext"]
        session.database_add(doc)

    def _store(self, tmp_path):
        d = tmp_path / "vol.ome.zarr"
        d.mkdir()
        (d / ".zattrs").write_text('{"multiscales":[{"name":"raw","axes":[]}]}')
        return d

    def test_directory_describe_checksums_zattrs(self, session, tmp_path):
        d = self._store(tmp_path)
        r = makeSourceFile(session, str(d)).document_properties["fileReference"]
        assert r["filename"] == "vol.ome.zarr"
        from ndi.fun.file import MD5

        assert r["checksum"] == MD5(str(d / ".zattrs"))
        assert r["checksumAlgorithm"] == "MD5"
        assert r["fileSize"] == 0

    def test_attaching_a_directory_is_refused(self, session, tmp_path):
        with pytest.raises(ValueError, match="only valid for a plain file"):
            makeSourceFile(session, str(self._store(tmp_path)), attachFile=True)

    def test_missing_path(self, session):
        with pytest.raises(FileNotFoundError):
            makeSourceFile(session, "/no/such/thing.zarr")

    def test_checksum_false_leaves_fields_empty(self, session, tmp_path):
        f = tmp_path / "nochk.bin"
        f.write_bytes(b"x")
        r = makeSourceFile(session, str(f), checksum=False).document_properties["fileReference"]
        assert r["checksum"] == "" and r["checksumAlgorithm"] == ""

    def test_document_id_dependency(self, session, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        doc = makeSourceFile(session, str(f), documentID="abc_123")
        assert doc.dependency_value("document_id") == "abc_123"

    def test_described_doc_is_valid(self, session, tmp_path):
        f = tmp_path / "valid.txt"
        f.write_bytes(b"hi")
        session.database_add(makeSourceFile(session, str(f)))


# ---------------------------------------------------------------------------
# viewCommand (TestViewCommand)

LAUNCHER = "/opt/ndi test/bin/napariViewLightsheet"
SESSION = "/tmp/session1"
PYRAMID = "4126a1b2c3d4e5f6_a1b2c3d4e5f6a1b2"
POSIX = os.name != "nt"


@pytest.mark.skipif(not POSIX, reason="POSIX quoting")
class TestViewCommand:
    def test_minimal(self):
        assert (
            viewCommand(LAUNCHER, SESSION, PYRAMID)
            == f"'{LAUNCHER}' '{SESSION}' --pyramid '{PYRAMID}'"
        )

    def test_defaults_emit_no_flags(self):
        cmd = viewCommand(LAUNCHER, SESSION, PYRAMID)
        for flag in ("--channel", "--level", "--no-controls", "--reduction", "--name"):
            assert flag not in cmd

    def test_each_flag(self):
        assert "--reduction 'max'" in viewCommand(LAUNCHER, SESSION, PYRAMID, reduction="max")
        assert "--reduction 'mean'" in viewCommand(LAUNCHER, SESSION, PYRAMID, reduction="mean")
        assert "--channel 2" in viewCommand(LAUNCHER, SESSION, PYRAMID, channel=2)
        assert "--level 0" in viewCommand(LAUNCHER, SESSION, PYRAMID, level=0)
        assert "--no-controls" in viewCommand(LAUNCHER, SESSION, PYRAMID, controls=False)
        assert "--name 'my layer'" in viewCommand(LAUNCHER, SESSION, PYRAMID, name="my layer")

    def test_full_flag_surface_in_order(self):
        cmd = viewCommand(
            LAUNCHER,
            SESSION,
            PYRAMID,
            reduction="max",
            channel=1,
            level=2,
            controls=False,
            name="V1",
        )
        assert cmd == (
            f"'{LAUNCHER}' '{SESSION}' --pyramid '{PYRAMID}' --reduction 'max' "
            "--channel 1 --level 2 --no-controls --name 'V1'"
        )

    def test_single_quote_is_escaped(self):
        assert viewCommand(LAUNCHER, SESSION, PYRAMID, name="it's").endswith("'it'\\''s'")

    @pytest.mark.parametrize(
        "args,match",
        [
            (("", SESSION, PYRAMID), "launcher"),
            ((LAUNCHER, "", PYRAMID), "no directory"),
            ((LAUNCHER, SESSION, ""), "lightsheetZarrPyramid id"),
        ],
    )
    def test_empty_arguments_error(self, args, match):
        with pytest.raises(ValueError, match=match):
            viewCommand(*args)

    def test_invalid_reduction(self):
        with pytest.raises(pydantic.ValidationError):
            viewCommand(LAUNCHER, SESSION, PYRAMID, reduction="median")

    def test_flags_parse_with_the_viewer_cli(self):
        import shlex

        from ndi.gui.app.lightsheetZarr.cli import build_parser

        cmd = viewCommand(
            LAUNCHER,
            SESSION,
            PYRAMID,
            reduction="max",
            channel=3,
            level=1,
            controls=False,
            name="a b",
        )
        args = build_parser().parse_args(shlex.split(cmd)[1:])
        assert (args.session, args.pyramid, args.reduction) == (SESSION, PYRAMID, "max")
        assert (args.channel, args.level, args.controls, args.name) == (3, 1, False, "a b")


# ---------------------------------------------------------------------------
# view


class _FakeProc:
    def __init__(self, argv, env=None, stdout=None, stderr=None):
        self.argv, self.env, self.stdout = argv, env, stdout
        _FakeProc.last = self

    def wait(self):
        return 0


@pytest.fixture
def fake_popen(monkeypatch):
    mod = importlib.import_module("ndi.fun.doc_lightsheet.view")
    monkeypatch.setattr(mod.subprocess, "Popen", _FakeProc)
    return _FakeProc


class TestView:
    def test_list_mode_waits(self, fake_popen, session, monkeypatch):
        monkeypatch.delenv("NDI_LIGHTSHEET_DEBUG", raising=False)
        status = view(session, launcher="/bin/nv", verbose=False)
        assert status == 0
        assert fake_popen.last.argv == ["/bin/nv", str(session.path), "--list"]
        assert "NDI_LIGHTSHEET_DEBUG" not in fake_popen.last.env

    def test_open_runs_in_background(self, fake_popen, session):
        proc = view(
            session,
            PYRAMID,
            launcher="/bin/nv",
            reduction="mean",
            channel=2,
            controls=False,
            verbose=False,
        )
        assert isinstance(proc, _FakeProc)
        assert proc.argv == [
            "/bin/nv",
            str(session.path),
            "--pyramid",
            PYRAMID,
            "--reduction",
            "mean",
            "--channel",
            "2",
            "--no-controls",
        ]
        assert proc.env["NDI_LIGHTSHEET_DEBUG"] == "1"

    def test_session_path_override_and_log(self, fake_popen, session, tmp_path):
        log = tmp_path / "viewer.txt"
        status = view(
            session,
            PYRAMID,
            launcher="/bin/nv",
            sessionPath="/elsewhere",
            wait=True,
            debug=False,
            logFile=str(log),
            verbose=False,
        )
        assert status == 0
        assert fake_popen.last.argv[1] == "/elsewhere"
        assert log.exists()

    def test_default_launcher_falls_back_to_module(self, fake_popen, session, monkeypatch):
        mod = importlib.import_module("ndi.fun.doc_lightsheet.view")
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        view(session, PYRAMID, verbose=False)
        assert fake_popen.last.argv[1:3] == ["-m", "ndi.gui.app.lightsheetZarr.cli"]

    def test_no_session_path(self, fake_popen):
        with pytest.raises(ValueError, match="sessionPath"):
            view(object(), PYRAMID, launcher="/bin/nv", verbose=False)


# ---------------------------------------------------------------------------
# BuildProfile (TestBuildProfile)


def _row(**given):
    r = {
        "level": "Level 0 (mean)",
        "superblock": 1,
        "nSuperBlocks": 1,
        "chunks": 16,
        "workers": 1,
        "mbRead": 0,
        "mbChunks": 0,
        "mbOut": 0,
        "readWait": 0,
        "assemble": 0,
        "compress": 0,
        "workerBusy": 0,
        "upload": 0,
        "urls": 0,
        "stage": 0,
        "send": 0,
        "verify": 0,
        "progress": 0,
        "total": 0,
    }
    r.update(given)
    return r


class TestBuildProfile:
    def test_alias(self):
        assert BuildProfile is ndi_fun_doc_lightsheet_BuildProfile

    def test_summary_says_where_the_time_went(self):
        r = _row(
            readWait=4,
            assemble=1,
            compress=3,
            workers=4,
            workerBusy=6,
            upload=1.5,
            urls=0.5,
            send=1,
            progress=0.5,
            total=10,
            mbChunks=100,
            mbOut=40,
            mbRead=300,
        )
        t = BuildProfile.summarize([r, r])
        assert "2 batches" in t
        assert "read-wait 40%" in t
        assert "assemble 10%" in t
        assert "compress 30% (workers 50% busy)" in t
        assert "upload 15% (URLs 5%, staging+CRC 0%, waiting for curl 10%" in t
        assert "progress 5%, other 0%" in t
        assert "10.0 MB/s of chunks made, 4.0 MB/s compressed, 30.0 MB/s read" in t

    def test_nothing_to_say(self):
        assert BuildProfile.summarize(BuildProfile.emptyRows()) == "no batches"

    def test_each_batch_is_a_row_of_the_log(self, tmp_path):
        log = tmp_path / "profile.csv"
        p = BuildProfile(str(log), 3600)
        p.add(_row(level="Level 0 (mean)", total=2))
        p.add(_row(level="Level 0 (mean)", total=3))
        q = BuildProfile(str(log), 3600)  # a resumed build appends
        q.add(_row(level="Level 1 (max)", total=4))
        lines = log.read_text().strip().splitlines()
        assert len(lines) == 4
        assert lines[0] == ",".join(BuildProfile.FIELDS)
        assert lines[0].startswith("when,level,superblock")
        assert '"Level 1 (max)"' in lines[3]
        with open(log, newline="") as fh:
            totals = [float(r["total"]) for r in csv.DictReader(fh)]
        assert totals == [2, 3, 4]
        assert len(p.rows) == 2
        assert p.logFile == str(log)
        assert list(p.rows[0]) == list(BuildProfile.FIELDS)

    def test_level_ends_with_a_summary(self, capsys):
        p = BuildProfile("", 3600)
        p.add(_row(total=1))
        p.endLevel("Level 0 (mean)")
        assert "[profile] Level 0 (mean), whole level: 1 batches" in capsys.readouterr().out
        p.endLevel("Level 1 (mean)")
        assert capsys.readouterr().out.strip() == ""

    def test_periodic_summary_and_finish(self, capsys, tmp_path):
        p = BuildProfile(str(tmp_path / "p.csv"), 0)
        p.add(_row(total=1))
        assert "[profile] Level 0 (mean), last 0 min: 1 batches" in capsys.readouterr().out
        p.finish()
        out = capsys.readouterr().out
        assert "[profile] Whole build (this run): 1 batches" in out
        assert "Every batch is in" in out

    def test_a_row_with_the_wrong_fields_is_refused(self):
        with pytest.raises(ValueError, match="missing"):
            BuildProfile().add({"level": "x"})
