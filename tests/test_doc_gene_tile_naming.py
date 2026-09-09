"""Tile files are named from ONE, because a DID file series is one-based.

did.document/addFileSeries takes "ONE-BASED member numbers" and refuses
anything else -- "Member indices must be positive integers (one-based)" --
so the first member of a series is NAME_1. The pyramid writer named its
first tile tile.bin_0, which put every pyramid a step outside the
convention its storage layer assumes.

That is not cosmetic. NDI-matlab's uploader walks a legacy NAME# series as
NAME1, NAME2, ... and treats the first name that is not there as the end of
the series, because that gap was the only termination signal available. A
zero-based pyramid therefore begins at a name the walk never probes.

The tile INDEX stays zero-based: it is a grid position, and index_order
defines it as row*tile_columns + column. Only the file SUFFIX moves, and
the document records which origin it used so that pyramids written before
this keep opening.
"""

import unittest

from ndi.fun.doc_gene import TILE_INDEX_ORIGIN, tileFileName


class TestTheOriginIsOne(unittest.TestCase):
    def test_the_convention_is_one_based(self):
        self.assertEqual(TILE_INDEX_ORIGIN, 1)

    def test_the_first_tile_of_a_new_document_is_file_one(self):
        self.assertEqual(tileFileName({"tile_index_origin": 1}, 0), "tile.bin_1")

    def test_no_new_document_ever_names_a_file_zero(self):
        names = {tileFileName({"tile_index_origin": 1}, i) for i in range(200)}
        self.assertNotIn("tile.bin_0", names)

    def test_the_index_is_still_the_grid_position(self):
        # row 3, column 4 of a 10-wide level is index 34, file 35.
        self.assertEqual(tileFileName({"tile_index_origin": 1}, 3 * 10 + 4), "tile.bin_35")

    def test_names_stay_dense_in_the_suffix(self):
        self.assertEqual(
            [tileFileName({"tile_index_origin": 1}, i) for i in range(3)],
            ["tile.bin_1", "tile.bin_2", "tile.bin_3"],
        )


class TestOlderPyramidsStillOpen(unittest.TestCase):
    """The origin is READ, never guessed.

    A sparse pyramid whose first tile is empty has no tile.bin_0 under
    either convention, so the stored names cannot distinguish the two. A
    guess that got it wrong would shift every tile by one -- an image that
    is quietly wrong rather than one that is missing, which is the worse
    of the two failures.
    """

    def test_a_document_with_no_origin_recorded_is_read_as_zero_based(self):
        self.assertEqual(tileFileName({}, 0), "tile.bin_0")
        self.assertEqual(tileFileName({}, 70), "tile.bin_70")

    def test_an_explicit_zero_is_honoured(self):
        self.assertEqual(tileFileName({"tile_index_origin": 0}, 12), "tile.bin_12")

    def test_the_two_conventions_disagree_by_exactly_one(self):
        for i in (0, 1, 70, 4999):
            old = tileFileName({}, i)
            new = tileFileName({"tile_index_origin": 1}, i)
            self.assertEqual(int(new.rsplit("_", 1)[1]) - int(old.rsplit("_", 1)[1]), 1)

    def test_an_unusable_value_does_not_raise_mid_render(self):
        # A malformed document should not take down a viewer that is part
        # way through building a layer; it reads as the legacy origin.
        for junk in (None, "", "banana", [1]):
            self.assertEqual(tileFileName({"tile_index_origin": junk}, 4), "tile.bin_4")


class TestTheDocumentRecordsIt(unittest.TestCase):
    def test_the_definition_carries_the_origin(self):
        import json
        from pathlib import Path

        import ndi

        root = Path(ndi.__file__).parent
        d = json.loads(
            (
                root / "ndi_common/database_documents/data/spatialGeneExpressionTiles.json"
            ).read_text()
        )
        self.assertEqual(d["spatialGeneExpressionTiles"]["tile_index_origin"], 1)

    def test_the_schema_declares_it(self):
        import json
        from pathlib import Path

        import ndi

        root = Path(ndi.__file__).parent
        s = json.loads(
            (
                root / "ndi_common/schema_documents/data/spatialGeneExpressionTiles_schema.json"
            ).read_text()
        )
        names = [f["name"] for f in s["spatialGeneExpressionTiles"]]
        self.assertIn("tile_index_origin", names)


if __name__ == "__main__":
    unittest.main()


class TestARealPyramidRoundTrips(unittest.TestCase):
    """Build one, then read it back through the two readers that exist."""

    def setUp(self):
        import tempfile

        from ndi.fun.doc_gene import makeGeneList, makePyramid
        from ndi.session.dir import ndi_session_dir

        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        S = ndi_session_dir("tile_naming", self.dir)
        sub = S.newdocument("subject", **{"subject.local_identifier": "tn@vhlab"})
        S.database_add(sub)
        gl = makeGeneList(S, ["ENSL0001", "ENSL0002", "ENSL0003", "ENSL0004"], ["a", "b", "c", "d"])
        # Coordinates chosen so the grid has HOLES: every point sits in the
        # upper-left tile, so the other three are never written. A sparse
        # series is the normal case, not the exotic one.
        x = [1000, 1001, 1002, 1003]
        y = [2000, 2001, 2002, 2003]
        self.pyr, self.tiles = makePyramid(
            S,
            x,
            y,
            [0, 1, 2, 3],
            [2, 3, 5, 7],
            gl,
            subjectID=sub.id,
            binSizes=[1],
            grid=2,
            basePixelSize=(0.5, 0.5),
        )
        self.S = S

    def test_the_first_written_tile_is_file_one(self):
        stored = self.tiles[0].current_file_list()
        self.assertIn("tile.bin_1", stored)
        self.assertNotIn("tile.bin_0", stored)

    def test_the_document_records_the_origin_it_used(self):
        props = self.tiles[0].document_properties["spatialGeneExpressionTiles"]
        self.assertEqual(props["tile_index_origin"], 1)

    def test_the_series_is_sparse_which_is_why_walking_it_cannot_terminate(self):
        # This 2x2 grid stores tiles 1 and 4 and nothing between them. A
        # walk that counts 1, 2, ... and treats the first absent name as the
        # end of the series finds the HOLE at 2 and never reaches 4 -- which
        # is precisely how NDI-matlab's uploader lost 426 of a pyramid's 450
        # tile files while reporting success.
        stored = sorted(n for n in self.tiles[0].current_file_list() if n.startswith("tile.bin_"))
        self.assertEqual(stored, ["tile.bin_1", "tile.bin_4"])

        walked = []
        j = 1
        while f"tile.bin_{j}" in stored:
            walked.append(f"tile.bin_{j}")
            j += 1
        self.assertEqual(walked, ["tile.bin_1"])  # stops one in, at the hole

    def test_current_file_list_finds_every_member_including_past_the_hole(self):
        # The replacement for walking: ask the document, which records the
        # names that were actually added.
        stored = sorted(n for n in self.tiles[0].current_file_list() if n.startswith("tile.bin_"))
        self.assertEqual(len(stored), 2)
        props = self.tiles[0].document_properties["spatialGeneExpressionTiles"]
        self.assertEqual(props["n_tiles_stored"], len(stored))

    def test_the_counts_come_back_through_readViewport(self):
        from ndi.fun.doc_gene import readViewport

        img, info = readViewport(self.S, self.pyr, 1, density=False)
        self.assertEqual(info["tiles_read"], 2)
        self.assertEqual(float(img.sum()), float(2 + 3 + 5 + 7))

    def test_the_same_pyramid_reads_wrong_if_the_origin_is_ignored(self):
        # Pin the reason the origin is recorded: pretend the document said
        # nothing, and the reader looks for a name that is not there.
        from ndi.fun.doc_gene import tileFileName

        props = self.tiles[0].document_properties["spatialGeneExpressionTiles"]
        stored = set(self.tiles[0].current_file_list())
        self.assertIn(tileFileName(props, 0), stored)
        self.assertNotIn(tileFileName({}, 0), stored)
