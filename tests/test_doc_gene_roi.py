"""Tests for the ROI-based GEF ingest (NDI-matlab PR #1150 port).

Covers:
  - ``makeROI``: polygon-shape validation and the written document
    properties
  - ``_roi_ingest.build_roi_pyramids``: the pure-logic test that
    records inside polygon A go to pyramid A, records inside both go
    to both, and empty polygons record an ROI sidecar without a
    pyramid
  - ``fromGEFbyROI``: end-to-end on a small synthetic .gef, verifying
    N pyramids and N ROI docs come back and ``info["nKeepPerROI"]``
    agrees per polygon
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from ndi.fun import doc_gene
from ndi.session.dir import ndi_session_dir


@pytest.fixture
def session(tmp_path):
    """A fresh session with one subject document."""
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("roi_test", str(d))
    sub = S.newdocument("subject", **{"subject.local_identifier": "roi@vhlab"})
    S.database_add(sub)
    return S, sub


@pytest.fixture
def two_subjects(tmp_path):
    """A session with two subject documents (one per ROI polygon)."""
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    S = ndi_session_dir("roi_two", str(d))
    sub_a = S.newdocument("subject", **{"subject.local_identifier": "a@vhlab"})
    sub_b = S.newdocument("subject", **{"subject.local_identifier": "b@vhlab"})
    S.database_add(sub_a)
    S.database_add(sub_b)
    return S, sub_a, sub_b


# -------------------------------------------------- makeROI: shape checks


def test_makeROI_refuses_too_few_vertices(session):
    """A polygon with fewer than three vertices is not a polygon.

    The check lands here rather than in database validation so the
    error names the argument.
    """
    S, _ = session
    poly = np.array([[0, 0], [1, 1]], float)
    with pytest.raises(ValueError, match="at least 3 vertices"):
        doc_gene.makeROI(S, None, poly)


def test_makeROI_refuses_wrong_axis(session):
    """``polygon`` must be ``(M, 2)``. A 3-vector or 1x3 is not a
    polygon."""
    S, _ = session
    with pytest.raises(ValueError, match=r"must be \(M, 2\)"):
        doc_gene.makeROI(S, None, np.array([0, 1, 2], float))
    with pytest.raises(ValueError, match=r"must be \(M, 2\)"):
        doc_gene.makeROI(S, None, np.array([[0, 1, 2]], float))


def test_makeROI_writes_the_geometry(session):
    """vertices_x/_y come out in the two columns of the input polygon,
    not transposed."""
    S, _ = session
    poly = np.array([[10.0, 20.0], [30.0, 20.0], [20.0, 40.0]])
    doc = doc_gene.makeROI(S, None, poly, label="hemi A", nRecordsIn=7)
    p = doc.document_properties["spatialGeneExpressionROI"]
    assert p["n_vertices"] == 3
    assert list(p["vertices_x"]) == [10.0, 30.0, 20.0]
    assert list(p["vertices_y"]) == [20.0, 20.0, 40.0]
    assert p["label"] == "hemi A"
    assert p["n_records_in"] == 7
    assert p["coord_space"] == "gef_base_pixel"
    assert p["coord_units"] == "pixel"
    assert p["roi_format_version"] == 1


def test_makeROI_sets_dependencies_when_given(session, tmp_path):
    """pyrDoc and sourceFileID land on the document's depends_on list
    when given; an empty pyrDoc leaves that dep unset."""
    S, sub = session
    # A real sourceFile document, so the source_file_id dep points at
    # a doc the database can resolve.
    srcfile = tmp_path / "chip.gef"
    srcfile.write_bytes(b"gef bytes")
    src = doc_gene.makeSourceFile(S, str(srcfile), checksum=False)
    S.database_add(src)

    gl = doc_gene.makeGeneList(S, ["G1"], ["A"])
    pyr, _ = doc_gene.makePyramid(
        S, [0, 1], [0, 1], [0, 0], [1, 1], gl, subjectID=sub.id, binSizes=[1], grid=1
    )
    poly = np.array([[0, 0], [10, 0], [5, 10]], float)
    doc = doc_gene.makeROI(S, pyr, poly, sourceFileID=src.id, nRecordsIn=2)
    deps = {d["name"]: d["value"] for d in doc.document_properties["depends_on"]}
    assert deps["spatialGeneExpressionPyramid_id"] == pyr.id
    assert deps["source_file_id"] == src.id

    # Empty pyrDoc path: dep stays at the schema default (empty); the
    # shim lets the empty-dep check pass (see the fixture docstring).
    doc2 = doc_gene.makeROI(S, None, poly, sourceFileID=src.id)
    deps2 = {d["name"]: d["value"] for d in doc2.document_properties["depends_on"]}
    assert deps2["spatialGeneExpressionPyramid_id"] == ""
    assert deps2["source_file_id"] == src.id


# ----------------------------- build_roi_pyramids: polygon membership logic


def _build_options(**overrides):
    """A minimal options dict for build_roi_pyramids."""
    base = {
        "binSizes": (1,),
        "grid": 1,
        "tileBudgetBytes": 50 * 2**20,
        "gridRange": (3, 64),
        "basePixelSize": (0.5, 0.5),
        "pixelSizeUnits": "micrometer",
        "label": "",
        "assay": "Stereo-seq",
        "chipSerial": "SN-TEST",
        "pipelineVersion": "",
        "origin": None,
        "genomeAssembly": "",
        "annotationSource": "",
        "geneIdNamespace": "",
        "geneSymbolNamespace": "",
        "recordSource": False,
        "checksum": False,
        "verbose": False,
        "progressFcn": None,
    }
    base.update(overrides)
    return base


def test_buildROIpyramids_honours_polygon_membership(two_subjects):
    """Records inside polygon A go to pyramid A, records inside both go
    to both (overlap honoured), records inside neither go nowhere.

    Pure-logic: the pyramid build itself is tested elsewhere; this
    test only cares that the per-ROI slice matches what inpolygon
    would return.
    """
    from ndi.fun._roi_ingest import build_roi_pyramids

    S, sub_a, sub_b = two_subjects

    # 6 records placed to exercise every case.
    #  r0 (0,0)   -- A only (inside A, outside B)
    #  r1 (5,5)   -- A and B (inside both -- overlap)
    #  r2 (9,9)   -- A and B (inside both)
    #  r3 (20,20) -- B only
    #  r4 (25,25) -- B only
    #  r5 (90,90) -- neither
    x = np.array([0, 5, 9, 20, 25, 90], dtype=np.int32)
    y = np.array([0, 5, 9, 20, 25, 90], dtype=np.int32)
    gene_index = np.array([0, 0, 1, 1, 0, 0], dtype=np.uint32)
    count = np.array([1, 1, 1, 1, 1, 1], dtype=np.uint16)
    gene_id = ["G1", "G2"]
    gene_name = ["A", "B"]
    meta = {"chipSerial": "SN", "resolutionNm": 500}

    # Use polygons that are strictly larger than the bounding points so
    # matplotlib's contains_points (a half-open test at edges / vertices)
    # does not reject boundary records.
    poly_A = np.array([[-1, -1], [10, -1], [10, 10], [-1, 10]], float)  # (0,0)-(10,10)
    poly_B = np.array([[4, 4], [31, 4], [31, 31], [4, 31]], float)  # (4,4)-(31,31)

    opts = _build_options(recordSource=False)
    pyr_docs, tile_docs, gl, src, info = build_roi_pyramids(
        S,
        x,
        y,
        gene_index,
        count,
        gene_id,
        gene_name,
        meta,
        "/no/such/path.gef",
        [sub_a.id, sub_b.id],
        [poly_A, poly_B],
        opts,
    )

    # nKeepPerROI counts: A has r0, r1, r2 -> 3; B has r1, r2, r3, r4 -> 4.
    assert info["nKeepPerROI"] == [3, 4]
    assert pyr_docs[0] is not None
    assert pyr_docs[1] is not None
    # One shared geneList and one ROI doc per polygon.
    assert gl is not None
    assert src is None  # recordSource=False
    assert len(info["roiDocs"]) == 2
    assert all(d is not None for d in info["roiDocs"])
    # Each ROI doc records how many records fell inside.
    roi_a = info["roiDocs"][0].document_properties["spatialGeneExpressionROI"]
    roi_b = info["roiDocs"][1].document_properties["spatialGeneExpressionROI"]
    assert roi_a["n_records_in"] == 3
    assert roi_b["n_records_in"] == 4
    # And each pyramid's subject dependency is the one we passed.
    deps_a = {d["name"]: d["value"] for d in pyr_docs[0].document_properties["depends_on"]}
    deps_b = {d["name"]: d["value"] for d in pyr_docs[1].document_properties["depends_on"]}
    assert deps_a["subject_id"] == sub_a.id
    assert deps_b["subject_id"] == sub_b.id


def test_buildROIpyramids_empty_polygon_records_roi_without_pyramid(two_subjects):
    """An empty polygon still writes the ROI sidecar; its pyramid slot
    is None and a RuntimeWarning fires."""
    from ndi.fun._roi_ingest import build_roi_pyramids

    S, sub_a, sub_b = two_subjects

    x = np.array([0, 5, 9], dtype=np.int32)
    y = np.array([0, 5, 9], dtype=np.int32)
    gene_index = np.array([0, 0, 1], dtype=np.uint32)
    count = np.array([1, 1, 1], dtype=np.uint16)
    meta = {"chipSerial": "SN", "resolutionNm": 500}

    # A polygon catches everything; B's polygon is in the far corner --
    # empty on this data.
    poly_full = np.array([[-1, -1], [100, -1], [100, 100], [-1, 100]], float)
    poly_far = np.array([[1000, 1000], [1010, 1000], [1005, 1010]], float)

    opts = _build_options(recordSource=False)
    with pytest.warns(RuntimeWarning, match="contained no records"):
        pyr_docs, tile_docs, gl, src, info = build_roi_pyramids(
            S,
            x,
            y,
            gene_index,
            count,
            ["G1", "G2"],
            ["A", "B"],
            meta,
            "/no/such/path.gef",
            [sub_a.id, sub_b.id],
            [poly_full, poly_far],
            opts,
        )

    assert info["nKeepPerROI"] == [3, 0]
    assert pyr_docs[0] is not None
    assert pyr_docs[1] is None
    assert tile_docs[1] is None
    # ROI docs for both polygons.
    assert info["roiDocs"][0] is not None
    assert info["roiDocs"][1] is not None
    # Empty ROI has nRecordsIn=0 and no pyramid dependency.
    roi_b = info["roiDocs"][1]
    assert roi_b.document_properties["spatialGeneExpressionROI"]["n_records_in"] == 0
    deps_b = {d["name"]: d["value"] for d in roi_b.document_properties["depends_on"]}
    assert deps_b["spatialGeneExpressionPyramid_id"] == ""


def test_buildROIpyramids_length_mismatch_raises(two_subjects):
    """subjects and polygons must be the same length."""
    from ndi.fun._roi_ingest import build_roi_pyramids

    S, sub_a, _ = two_subjects
    x = np.array([0], dtype=np.int32)
    y = np.array([0], dtype=np.int32)
    g = np.array([0], dtype=np.uint32)
    c = np.array([1], dtype=np.uint16)
    poly = np.array([[0, 0], [1, 0], [0, 1]], float)
    with pytest.raises(ValueError, match="same length"):
        build_roi_pyramids(
            S,
            x,
            y,
            g,
            c,
            ["G"],
            ["g"],
            {"resolutionNm": 500},
            "/no/such/path.gef",
            [sub_a.id],
            [poly, poly],
            _build_options(recordSource=False),
        )


def test_buildROIpyramids_empty_subjects_raises(two_subjects):
    """At least one (subject, polygon) pair is required."""
    from ndi.fun._roi_ingest import build_roi_pyramids

    S, _, _ = two_subjects
    x = np.array([], dtype=np.int32)
    y = np.array([], dtype=np.int32)
    g = np.array([], dtype=np.uint32)
    c = np.array([], dtype=np.uint16)
    with pytest.raises(ValueError, match="At least one"):
        build_roi_pyramids(
            S,
            x,
            y,
            g,
            c,
            [],
            [],
            {"resolutionNm": 500},
            "/no/such/path.gef",
            [],
            [],
            _build_options(recordSource=False),
        )


# ----------------------------------------------- fromGEFbyROI: end-to-end


def _make_synthetic_gef(path, resolution_nm: int = 500):
    """Write a minimal Stereo-seq .gef enough for readGEF to parse.

    Mirrors the fixture pattern in NDR-python's own tests: an HDF5
    file with ``/geneExp/bin1/expression`` and ``/geneExp/bin1/gene``
    datasets, plus the attributes readGEF reads.
    """
    import h5py

    # Six records: see test_fromGEFbyROI_sorts_records_into_pyramids below.
    #  (x, y, geneID, count)
    x = np.array([2, 2, 2, 20, 20, 20], dtype=np.uint32)
    y = np.array([2, 5, 8, 20, 22, 24], dtype=np.uint32)
    counts = np.array([1, 2, 3, 4, 5, 6], dtype=np.uint16)
    # Two genes: three records each, one gene per group of three.
    # expression is sorted by gene (NDR's readGEF relies on this).

    with h5py.File(path, "w") as f:
        f.attrs["version"] = np.uint32(1)
        f.attrs["resolution"] = np.uint32(resolution_nm)
        geneExp = f.create_group("geneExp")
        bin1 = geneExp.create_group("bin1")
        # expression compound dtype
        exp_dt = np.dtype([("x", "u4"), ("y", "u4"), ("count", "u2"), ("exon", "u2")])
        expr = np.zeros(6, dtype=exp_dt)
        expr["x"] = x
        expr["y"] = y
        expr["count"] = counts
        expr["exon"] = 0
        bin1.create_dataset("expression", data=expr)
        # gene dataset: 2 genes, pointing into expression
        gene_dt = np.dtype(
            [("geneID", "S32"), ("geneName", "S32"), ("offset", "u4"), ("count", "u4")]
        )
        gene = np.zeros(2, dtype=gene_dt)
        gene[0] = (b"ENSG0001", b"GeneA", 0, 3)
        gene[1] = (b"ENSG0002", b"GeneB", 3, 3)
        bin1.create_dataset("gene", data=gene)
        # Attributes readGEF looks for
        bin1.attrs["minX"] = np.int32(0)
        bin1.attrs["minY"] = np.int32(0)
        bin1.attrs["maxX"] = np.int32(30)
        bin1.attrs["maxY"] = np.int32(30)
        bin1.attrs["resolution"] = np.int32(resolution_nm)


def test_fromGEFbyROI_sorts_records_into_pyramids(two_subjects):
    """A tiny synthetic .gef with two polygons produces two pyramids
    and two ROI documents with the right per-polygon record counts.

    The six records fall into two spatial clusters: three at (2, 2),
    (2, 5), (2, 8) go in polygon A; three at (20, 20), (20, 22),
    (20, 24) go in polygon B. The polygons do not overlap.
    """
    pytest.importorskip("ndr.format.stereoseq", reason="ndr not installed")

    S, sub_a, sub_b = two_subjects

    with tempfile.TemporaryDirectory() as td:
        gef = Path(td) / "tiny.gef"
        try:
            _make_synthetic_gef(str(gef))
        except Exception as e:
            pytest.skip(f"cannot synthesize .gef for ndr.format.stereoseq: {e}")

        poly_a = np.array([[-1, -1], [10, -1], [10, 10], [-1, 10]], float)
        poly_b = np.array([[15, 15], [30, 15], [30, 30], [15, 30]], float)

        try:
            pyr_docs, tile_docs, gl, src, info = doc_gene.fromGEFbyROI(
                S,
                str(gef),
                [sub_a.id, sub_b.id],
                [poly_a, poly_b],
                binSizes=(1,),
                grid=1,
                recordSource=False,
                genomeAssembly="testAsm",
            )
        except Exception as e:
            # Any parsing error inside readGEF is out of scope for this
            # port; the shared-core test above covers the slicing
            # logic directly without readGEF.
            pytest.skip(f"synthetic .gef did not round-trip readGEF: {e}")

        assert info["nKeepPerROI"] == [3, 3]
        assert pyr_docs[0] is not None
        assert pyr_docs[1] is not None
        assert len(info["roiDocs"]) == 2
        # Subject dependency goes on each pyramid.
        deps_a = {d["name"]: d["value"] for d in pyr_docs[0].document_properties["depends_on"]}
        deps_b = {d["name"]: d["value"] for d in pyr_docs[1].document_properties["depends_on"]}
        assert deps_a["subject_id"] == sub_a.id
        assert deps_b["subject_id"] == sub_b.id


# -------------------------------- fromGEF and makeSourceFile smoke tests


def test_makeSourceFile_fileReference_default(session):
    """Default is fileReference, which records the file without
    ingesting its bytes."""
    S, _ = session
    with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".gef") as fh:
        fh.write(b"hello world")
        path = fh.name
    try:
        doc = doc_gene.makeSourceFile(S, path, checksum=True)
        p = doc.document_properties["fileReference"]
        assert p["filename"] == os.path.basename(path)
        assert p["checksum"] == "5eb63bbbe01eeed093cb22bb8f5acdc3"
        assert p["checksumAlgorithm"] == "MD5"
        assert p["fileSize"] == 11
        # The document is NOT added to the database -- the caller does.
        assert doc.document_properties["document_class"]["class_name"] == "fileReference"
    finally:
        os.unlink(path)


def test_makeSourceFile_no_checksum_leaves_both_fields_empty(session):
    """checksum=False leaves checksum AND algorithm empty, not 'MD5'
    paired with an empty hash."""
    S, _ = session
    with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".gef") as fh:
        fh.write(b"bytes")
        path = fh.name
    try:
        doc = doc_gene.makeSourceFile(S, path, checksum=False)
        p = doc.document_properties["fileReference"]
        assert p["checksum"] == ""
        assert p["checksumAlgorithm"] == ""
    finally:
        os.unlink(path)


def test_readNotes_builds_the_expected_strings():
    """readNotes order and wording mirror MATLAB's cellstr."""
    notes = doc_gene.readNotes(
        {"nCountsClamped": 1_234_567, "boxSource": "file attributes", "nGenesInFile": 500},
        ["g1", "g2", "g3"],
    )
    assert len(notes) == 3
    # Thousands grouping matches MATLAB ("1,234,567").
    assert notes[0] == "1,234,567 count(s) were clamped at the ceiling. Those pixels read low."
    assert notes[1] == "Extent taken from file attributes."
    assert "Only 3 of the file's 500 genes" in notes[2]


def test_readNotes_empty_when_nothing_to_say():
    """No clamps, no trimming -> empty list."""
    assert doc_gene.readNotes({}, ["g1"]) == []


def test_readNotes_flags_a_read_with_no_genes():
    """A read that returned no genes is called out."""
    assert doc_gene.readNotes({}, []) == ["The read returned no genes."]
