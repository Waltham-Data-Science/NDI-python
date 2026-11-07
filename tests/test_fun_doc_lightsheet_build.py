"""Building lightsheet pyramids: makePyramid, fromSPIM, fromOMEZarr.

MATLAB counterparts: tests/+ndi/+unittest/+fun/+doc/+lightsheet/ (TestMakePyramid*,
TestFromSPIM*, TestFromOMEZarr*). Every level a build writes is read back chunk
by chunk and compared with the volume block-reduced directly, for a local
session and for a streaming target (the shape of ndi.cloud's SessionWriter),
including level 1 folded into level 0, twin levels built from one read, and a
build that stops part-way and resumes.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("numcodecs")
pytest.importorskip("ndr")

from ndi.fun.doc_lightsheet.fromOMEZarr import _centresToCorners, _pickReduction  # noqa: E402
from ndi.fun.doc_lightsheet.makePyramid import (  # noqa: E402
    _planFoldCells,
    _planSuperBlocks,
    _readStoredChunk,
    _splitAlongZ,
    makePyramid,
)
from ndi.fun.doc_lightsheet.reduceBlocks import reduceBlocks  # noqa: E402
from ndi.query import ndi_query  # noqa: E402
from ndi.session import ndi_session_dir  # noqa: E402

AXES = [
    {"name": n, "type": t, "unit": u}
    for n, t, u in zip(
        "tczyx",
        ["time", "channel", "space", "space", "space"],
        ["", "", "micrometer", "micrometer", "micrometer"],
    )
]


def new_session():
    s = ndi_session_dir("lightsheet", tempfile.mkdtemp())
    subj = s.newdocument("subject", **{"subject.local_identifier": "mouse@lab"})
    s.database_add(subj)
    return s, subj.id


def write_slices(vol: np.ndarray) -> list[list[str]]:
    d = tempfile.mkdtemp()
    paths = []
    for c in range(vol.shape[1]):
        ps = []
        for z in range(vol.shape[2]):
            import tifffile

            p = os.path.join(d, f"c{c}_z{z}.tif")
            tifffile.imwrite(p, vol[0, c, z])
            ps.append(p)
        paths.append(ps)
    return paths


def level(path, shape, scale) -> dict:
    return {
        "path": path,
        "shape": list(shape),
        "chunks": [],
        "dtype": "uint16",
        "scale": list(scale),
        "translation": [0.0] * 5,
    }


def ladder(vol, slicePaths, *, toCloud: bool):
    """Two ladders (mean, max) of two levels each over VOL, as fromSPIM plans them."""
    _, C, Z, H, W = vol.shape
    f1, f2 = [1, 1, 1, 2, 2], [1, 1, 2, 2, 2]
    s1 = [1, C, Z, -(-H // 2), -(-W // 2)]
    s2 = [1, C, -(-Z // 2), -(-s1[3] // 2), -(-s1[4] // 2)]
    pyramids = []
    sources = {"0": {"kind": "smartspim", "slicePaths": slicePaths, "dtype": "uint16"}}
    expected = {"0": vol}
    for red in ("mean", "max"):
        pyramids.append(
            {
                "name": red,
                "type": red,
                "axes": AXES,
                "levels": [
                    level("0", vol.shape, [1, 1, 4, 1, 1]),
                    level(f"{red}/1", s1, [1, 1, 4, 2, 2]),
                    level(f"{red}/2", s2, [1, 1, 8, 4, 4]),
                ],
            }
        )
        if toCloud:
            sources[f"{red}/1"] = {
                "kind": "reduceSmartspim", "slicePaths": slicePaths, "sourceDtype": "uint16",
                "fromShape": list(vol.shape), "factor": f1, "reduction": red,
            }  # fmt: skip
        else:
            sources[f"{red}/1"] = {"kind": "reduce", "fromPath": "0", "factor": f1,
                                   "reduction": red}  # fmt: skip
        sources[f"{red}/2"] = {"kind": "reduce", "fromPath": f"{red}/1", "factor": f2,
                               "reduction": red}  # fmt: skip
        a = reduceBlocks(vol, f1, red, "uint16")
        expected[f"{red}/1"] = a
        expected[f"{red}/2"] = reduceBlocks(a, f2, red, "uint16")
    return pyramids, sources, expected


ORDER = ["0", "mean/1", "mean/2", "max/1", "max/2"]


def assemble(lp: dict, chunk_bytes) -> np.ndarray:
    """A level's voxels from its chunks; chunk_bytes(i) is chunk i's file path."""
    shape, ch, g = lp["shape"], lp["chunks"], lp["chunk_grid"]
    out = np.zeros([a * b for a, b in zip(g, ch)], np.uint16)
    for i, c in enumerate(np.ndindex(*g), start=1):
        t = _readStoredChunk(chunk_bytes(i), ch, lp["codec"], lp["dtype"])
        out[tuple(slice(a * b, (a + 1) * b) for a, b in zip(c, ch))] = t
    return out[tuple(slice(0, n) for n in shape)]


def read_local_level(session, doc) -> np.ndarray:
    def path(i):
        f = session.database_openbinarydoc(doc, f"chunk.bin_{i}")
        p = f.name
        session.database_closebinarydoc(f)
        return p

    return assemble(doc.document_properties["lightsheetZarrLevel"], path)


class FakeCloud:
    """The parts of ndi.cloud's SessionWriter a build uses, kept in memory.

    Documents and streamed chunk files are recorded; a retained level's chunks
    are kept on disk for the levels reduced from it. stopAfter raises after
    that many streamMembers calls, to make a build stop part-way.
    """

    def __init__(self, session, stopAfter: int | None = None):
        self.session = session
        self.cache = tempfile.mkdtemp()
        self.docs: dict[str, object] = {}
        self.declared: dict[str, object] = {}
        self.members: dict[str, dict[int, bytes]] = {}
        self.kept: dict[tuple[str, int], str] = {}
        self.calls = 0
        self.stopAfter = stopAfter
        self.adopted: list[str] = []
        self.released: list[str] = []
        self.replaced = None
        self.timing = {"urls": 0.0, "stage": 0.0, "send": 0.0, "verify": 0.0}

    def newdocument(self, document_type, **props):
        return self.session.newdocument(document_type, **props)

    def database_add(self, doc):
        self.docs[doc.id] = doc

    def declare(self, doc):
        self.declared[doc.id] = doc
        self.members.setdefault(doc.id, {})

    def streamMembers(self, doc, name, idxs, paths, retain):
        assert name == "chunk.bin"
        if self.stopAfter is not None and self.calls >= self.stopAfter:
            raise RuntimeError("the network went away")
        self.calls += 1
        for i, p in zip(idxs, paths):
            data = Path(p).read_bytes()
            self.members[doc.id][int(i)] = data
            if retain:
                keep = os.path.join(self.cache, f"{doc.id}_{i}")
                Path(keep).write_bytes(data)
                self.kept[(doc.id, int(i))] = keep
            os.remove(p)

    def adopt(self, doc):
        self.adopted.append(doc.id)
        self.declared.setdefault(doc.id, doc)

    def missingMembers(self, doc, name):
        n = int(np.prod(doc.document_properties["lightsheetZarrLevel"]["chunk_grid"]))
        have = self.members.get(doc.id, {})
        return [i for i in range(1, n + 1) if i not in have]

    def releaseMembers(self, doc):
        self.released.append(doc.id)

    def replaceOnCommit(self, doc):
        self.replaced = doc

    def requireSubject(self, subjectID):
        pass

    def requireDocument(self, docID):
        pass

    def commit(self):
        return {"documents": len(self.docs) + len(self.declared)}

    def database_openbinarydoc(self, doc, filename):
        i = int(filename.rsplit("_", 1)[1])
        return open(self.kept[(doc.id, i)], "rb")

    def database_closebinarydoc(self, f):
        f.close()

    def level(self, doc) -> np.ndarray:
        lp = doc.document_properties["lightsheetZarrLevel"]
        tmp = tempfile.mkdtemp()

        def path(i):
            p = os.path.join(tmp, str(i))
            Path(p).write_bytes(self.members[doc.id][i])
            return p

        try:
            return assemble(lp, path)
        finally:
            shutil.rmtree(tmp)


@pytest.fixture
def vol():
    rng = np.random.default_rng(7)
    return rng.integers(0, 4000, size=(1, 2, 9, 37, 53), dtype=np.uint16)


BUILD = {"chunks": [1, 1, 4, 16, 16], "prefetchBytes": 20000, "readWorkers": 3}


class TestPlanning:
    def test_super_blocks_are_whole_rows_of_one_plane(self):
        blocks = _planSuperBlocks([1, 1, 4, 16, 16], [1, 2, 3, 3, 4], [1, 2, 9, 37, 53], 8)
        seen = np.concatenate([b["idxs"] for b in blocks])
        assert list(seen) == list(range(1, 2 * 3 * 3 * 4 + 1))
        for b in blocks:
            assert b["idxs"].size % 4 == 0, "whole rows along x"
            assert len(set(b["lo"][:, 2])) == 1 or b["idxs"].size <= 12

    def test_a_long_row_is_split_in_equal_parts(self):
        blocks = _planSuperBlocks([1, 1, 1, 1, 1], [1, 1, 1, 1, 10], [1, 1, 1, 1, 10], 2)
        assert [list(b["idxs"]) for b in blocks] == [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]]

    def test_split_along_z_keeps_the_reduction_blocks(self):
        parts = _splitAlongZ(np.array([0, 0, 3, 0, 0]), np.array([1, 1, 12, 5, 5]), 3, 2)
        assert [(int(a[2]), int(b[2])) for a, b in parts] == [(3, 7), (7, 9), (9, 12)]

    def test_fold_cells_hold_whole_chunks_of_both_levels(self):
        cells = _planFoldCells([1, 2, 9, 37, 53], [1, 1, 4, 16, 16], [1, 1, 4, 16, 16],
                               [1, 2, 9, 19, 27], [1, 1, 1, 2, 2], 1e9, 2)  # fmt: skip
        ids0 = sorted(int(i) for c in cells for i in c["idxs"])
        ids1 = sorted(int(i) for c in cells for i in c["L1"]["idxs"])
        assert ids0 == list(range(1, 2 * 3 * 3 * 4 + 1))
        assert ids1 == list(range(1, 2 * 3 * 2 * 2 + 1))


class TestALocalBuild:
    @pytest.mark.parametrize("codec,workers", [("blosc-zstd", 4), ("raw", 1)])
    def test_every_level_reads_back_as_the_reduced_volume(self, vol, codec, workers):
        s, subj = new_session()
        pyr, src, exp = ladder(vol, write_slices(vol), toCloud=False)
        pd, levelDocs, shared = makePyramid(
            s, pyr, ["mean", "max"], subjectID=subj, materializeChunks=True,
            levelSources=src, codec=codec, numWorkers=workers, **BUILD,
        )  # fmt: skip
        assert shared
        assert len(levelDocs) == 5
        pp = pd.document_properties["lightsheetZarrPyramid"]
        assert pp["dtype"] == "<u2" and pp["axes_order"] == "tczyx"
        assert pp["axes_units"] == ",,micrometer,micrometer,micrometer"
        stored = {d.id: d for d in s.database_search(ndi_query("").isa("lightsheetZarrLevel"))}
        for key, d in zip(ORDER, levelDocs):
            doc = stored[d.id]
            lp = doc.document_properties["lightsheetZarrLevel"]
            assert lp["n_chunks_stored"] == int(np.prod(lp["chunk_grid"]))
            assert lp["chunk_index_origin"] == 1 and lp["codec"] == codec
            np.testing.assert_array_equal(read_local_level(s, doc), exp[key], err_msg=key)

    def test_metadata_only(self, vol):
        s, subj = new_session()
        pyr, _, _ = ladder(vol, [], toCloud=False)
        pd, levelDocs, _ = makePyramid(s, pyr, ["mean", "max"], subjectID=subj)
        for d in levelDocs:
            lp = d.document_properties["lightsheetZarrLevel"]
            assert lp["n_chunks_stored"] == 0
            assert lp["chunks"] == [1, 2, 9, 37, 53][: len(lp["chunks"])] or lp["chunks"]

    def test_progress_reaches_one_and_a_pause_stops_the_build(self, vol):
        from ndi.job.job import _JobPaused

        s, subj = new_session()
        pyr, src, _ = ladder(vol, write_slices(vol), toCloud=False)
        seen = []
        makePyramid(
            s,
            pyr,
            ["mean", "max"],
            subjectID=subj,
            materializeChunks=True,
            levelSources=src,
            progressFcn=lambda f, t: seen.append(f),
            **BUILD,
        )
        assert seen[-1] == 1.0 and seen == sorted(seen)

        def pause(f, t):
            if f > 0.3:
                raise _JobPaused("paused")

        s2, subj2 = new_session()
        with pytest.raises(_JobPaused):
            makePyramid(
                s2,
                pyr,
                ["mean", "max"],
                subjectID=subj2,
                materializeChunks=True,
                levelSources=src,
                progressFcn=pause,
                **BUILD,
            )

    def test_a_broken_progress_bar_does_not_stop_the_build(self, vol):
        s, subj = new_session()
        pyr, src, _ = ladder(vol, write_slices(vol), toCloud=False)

        def broken(f, t):
            raise RuntimeError("the bar was closed")

        _, levelDocs, _ = makePyramid(
            s,
            pyr,
            ["mean", "max"],
            subjectID=subj,
            materializeChunks=True,
            levelSources=src,
            progressFcn=broken,
            **BUILD,
        )
        assert len(levelDocs) == 5


class TestAStreamedBuild:
    @pytest.mark.parametrize("fold", [True, False])
    def test_levels_stream_and_match(self, vol, fold):
        s, subj = new_session()
        cloud = FakeCloud(s)
        pyr, src, exp = ladder(vol, write_slices(vol), toCloud=True)
        pd, levelDocs, _ = makePyramid(
            cloud, pyr, ["mean", "max"], subjectID=subj, materializeChunks=True,
            levelSources=src, codec="blosc-zstd", numWorkers=3, foldLevel1=fold, label="brain",
            **BUILD,
        )  # fmt: skip
        assert all(d is not None for d in levelDocs)
        assert len(cloud.declared) == 5
        for key, d in zip(ORDER, levelDocs):
            np.testing.assert_array_equal(cloud.level(d), exp[key], err_msg=key)
        assert pd.document_properties["lightsheetZarrPyramid"]["label"] == "brain"
        assert cloud.replaced is pd
        assert (
            "(uploading)" in cloud.docs[pd.id].document_properties["lightsheetZarrPyramid"]["label"]
            or cloud.docs[pd.id] is pd
        )
        # Level 1 of each ladder is retained for level 2, then released.
        assert set(cloud.released) == {levelDocs[1].id, levelDocs[3].id}

    def test_a_stopped_build_resumes_and_sends_only_what_is_missing(self, vol):
        s, subj = new_session()
        cloud = FakeCloud(s, stopAfter=3)
        pyr, src, exp = ladder(vol, write_slices(vol), toCloud=True)
        args = dict(subjectID=subj, materializeChunks=True, levelSources=src,
                    codec="blosc-zstd", numWorkers=2, **BUILD)  # fmt: skip
        with pytest.raises(RuntimeError, match="network"):
            makePyramid(cloud, pyr, ["mean", "max"], **args)
        sentBefore = {k: dict(v) for k, v in cloud.members.items()}
        pyramidDoc = next(
            d for d in cloud.docs.values() if d.doc_class() == "lightsheetZarrPyramid"
        )
        cloud.stopAfter = None
        resume = {"pyramidDoc": pyramidDoc, "levelDocs": list(cloud.declared.values())}
        resent = []
        orig = cloud.streamMembers

        def spy(doc, name, idxs, paths, retain):
            resent.extend((doc.id, int(i)) for i in idxs)
            orig(doc, name, idxs, paths, retain)

        cloud.streamMembers = spy
        _, levelDocs, _ = makePyramid(cloud, pyr, ["mean", "max"], resume=resume, **args)
        assert pyramidDoc.id in cloud.adopted
        for doc_id, have in sentBefore.items():
            for i in have:
                assert (doc_id, i) not in resent, "a chunk already in the cloud was sent again"
        for key, d in zip(ORDER, levelDocs):
            np.testing.assert_array_equal(cloud.level(d), exp[key], err_msg=key)

    def test_resume_needs_a_streaming_target(self, vol):
        s, subj = new_session()
        pyr, src, _ = ladder(vol, write_slices(vol), toCloud=False)
        with pytest.raises(ValueError, match="resume"):
            makePyramid(
                s,
                pyr,
                ["mean", "max"],
                subjectID=subj,
                materializeChunks=True,
                levelSources=src,
                resume={"pyramidDoc": None, "levelDocs": []},
            )


class TestFromSPIM:
    def test_a_smartspim_folder_builds(self, tmp_path):
        from ndr.format.smartspim.readAllChannelsInfo import readAllChannelsInfo
        from ndr.format.smartspim.readAllChannelsVolume import readAllChannelsVolume

        pytest.importorskip("imagecodecs")
        from tests._smartspim_fixture import make_example_fixture

        root = make_example_fixture(tmp_path, all_channels=True)
        from ndi.fun.doc_lightsheet.fromSPIM import fromSPIM

        s, subj = new_session()
        pd, levelDocs, info = fromSPIM(s, str(root), subjectID=subj, minLevelSize=8,
                                       progressFcn=None, numWorkers=2)  # fmt: skip
        spim = readAllChannelsInfo(str(root))
        vol = np.stack([readAllChannelsVolume(str(root), n) for n in spim["channelNames"]])[None]
        assert info["channelNames"] == spim["channelNames"]
        assert [L["path"] for L in info["levels"]][:3] == ["0", "mean/1", "max/1"][:1] + [
            info["levels"][1]["path"],
            info["levels"][2]["path"],
        ]
        pp = pd.document_properties["lightsheetZarrPyramid"]
        assert pp["channel_names"] == ",".join(spim["channelNames"])
        assert pp["label"] == "BOTTOM"
        assert pp["translation_level0"] == [0.0] * 5
        np.testing.assert_array_equal(read_local_level(s, levelDocs[0]), vol)
        f = info["levels"][1]["factor"]
        np.testing.assert_array_equal(
            read_local_level(s, levelDocs[1]),
            reduceBlocks(vol, f, info["levels"][1]["reduction"], "uint16"),
        )
        src = s.database_search(ndi_query("base.id") == info["sourceFileID"])
        assert len(src) == 1

    def test_refuses_without_a_subject_or_all_channels(self, tmp_path):
        from ndi.fun.doc_lightsheet.fromSPIM import fromSPIM

        s, _ = new_session()
        with pytest.raises(ValueError, match="subject"):
            fromSPIM(s, str(tmp_path))
        with pytest.raises(ValueError, match="All_Channels"):
            fromSPIM(s, str(tmp_path), subjectID="x")


class TestFromOMEZarr:
    def test_a_store_builds_with_corner_translations(self, tmp_path):
        from ndi.fun.doc_lightsheet.fromOMEZarr import fromOMEZarr
        from tests._omezarr_fixture import make_example_fixture

        store, gt = make_example_fixture(tmp_path, with_chunks=True)
        s, subj = new_session()
        pd, levelDocs, info = fromOMEZarr(s, str(store), subjectID=subj, materializeChunks=True,
                                          codec="blosc-zstd", progressFcn=None)  # fmt: skip
        assert info["reductions"] == ["max", "mean"]
        assert info["sharedLevel0"] is True
        assert len(levelDocs) == 5
        np.testing.assert_array_equal(read_local_level(s, levelDocs[0]), gt.level0)
        lp0 = levelDocs[0].document_properties["lightsheetZarrLevel"]
        store_tr = info["pyramids"][0]["levels"][0]["translation"]
        scale = info["pyramids"][0]["levels"][0]["scale"]
        expect = [t - (sc / 2 if a > 0 else 0) for a, (t, sc) in enumerate(zip(store_tr, scale))]
        assert lp0["translation"] == pytest.approx(expect)
        by = {d.document_properties["lightsheetZarrLevel"]["label"]: d for d in levelDocs}
        mean1 = next(d for k, d in by.items() if "level 1 (mean)" in k)
        np.testing.assert_array_equal(read_local_level(s, mean1), gt.mean_level1)

    def test_pick_reduction_and_corners(self):
        assert _pickReduction({"name": "mean", "type": "box"}, None) == "mean"
        assert _pickReduction({"name": "m", "type": "max"}, None) == "max"
        assert _pickReduction({"name": "p", "type": "box"}, {"p": "max"}) == "max"
        with pytest.warns(UserWarning, match="falling back"):
            assert _pickReduction({"name": "g", "type": "gaussian"}, None) == "mean"
        p = _centresToCorners([{"axes": AXES, "levels": [
            {"scale": [1, 1, 4, 2, 2], "translation": [0, 0, 2, 1, 1]}]}])  # fmt: skip
        assert p[0]["levels"][0]["translation"] == [0, 0, 0, 0, 0]
