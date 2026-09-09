"""The tile grid is sized from the data, and the build reports as it goes.

``makePyramid`` used to tile every section 9x9. A grid is a fixed FRACTION
of the extent, so the same 9x9 that gives a mouse section 20 MB tiles gave
a real ferret hemisphere 257 MB ones -- five times the budget the grid was
sized for. ``grid`` now defaults to ``None``, which picks the grid from
where the records actually are.

What is held here is the CONTRACT, not the particular number: a denser
section gets a finer grid than a sparse one of the same extent, the bounds
are respected, an explicit grid still wins, and the document records what
was chosen so a reader never has to guess. The exact grid depends on an
estimate of tile bytes and is allowed to move.

The second half is about the BANDS. A level is now built one band of tile
rows at a time, so the sort's working set is the section divided by the
grid rather than the whole section. Bands that overlapped would
double-count and bands that left a gap would drop records, and neither
would raise anything -- so the totals are checked.
"""

import numpy as np
import pytest

from ndi.document import ndi_document
from ndi.fun.doc_gene import makeGeneList, makePyramid, readTileFile
from ndi.session.dir import ndi_session_dir


def records(n_pix, span, n_genes=8):
    """``n_pix`` x ``n_pix`` lattice points over a span x span box, all genes."""
    px, py = np.meshgrid(
        np.round(np.linspace(0, span - 1, n_pix)).astype(np.int64),
        np.round(np.linspace(0, span - 1, n_pix)).astype(np.int64),
    )
    x = np.tile(px.ravel(), n_genes)
    y = np.tile(py.ravel(), n_genes)
    gi = np.repeat(np.arange(n_genes, dtype=np.int64), px.size)
    c = np.ones(x.size, dtype=np.int64)
    return x, y, gi, c


@pytest.fixture
def fixture(tmp_path):
    # ndi_session_dir requires the directory to exist already.
    d = tmp_path / "sess"
    d.mkdir(parents=True, exist_ok=True)
    session = ndi_session_dir("gene_pg", str(d))
    sub = ndi_document(
        "subject",
        # session.id is a METHOD here, while document.id is a property.
        **{"base.session_id": session.id(), "subject.local_identifier": "pg@vhlab"},
    )
    session.database_add(sub)
    gl = makeGeneList(
        session,
        [f"ENSG{k:04d}" for k in range(8)],
        [f"g{k}" for k in range(8)],
    )
    return session, sub.id, gl


def pyr_props(doc):
    return doc.document_properties["spatialGeneExpressionPyramid"]


class TestGridIsSizedFromTheData:
    def test_auto_grid_is_used_by_default(self, fixture):
        session, subject, gl = fixture
        x, y, gi, c = records(40, 4000)
        pyr, _ = makePyramid(session, x, y, gi, c, gl, subject, binSizes=(1,))
        p = pyr_props(pyr)
        assert 3 <= p["tile_rows"] <= 64
        # readViewport reads tile_rows and tile_columns separately.
        assert p["tile_rows"] == p["tile_columns"]

    def test_denser_section_gets_a_finer_grid(self, fixture):
        """THE POINT OF THE CHANGE. Same extent, more records, so the tiles
        a fixed grid would produce are bigger and the grid has to be finer
        to hold the same byte budget. A fixed 9x9 gives these two the same
        answer, which is the bug."""
        session, subject, gl = fixture
        budget = 12 * 1024
        sparse, _ = makePyramid(
            session, *records(20, 4000), gl, subject, binSizes=(1,), tileBudgetBytes=budget
        )
        dense, _ = makePyramid(
            session, *records(120, 4000), gl, subject, binSizes=(1,), tileBudgetBytes=budget
        )
        assert pyr_props(dense)["tile_rows"] > pyr_props(sparse)["tile_rows"]

    def test_grid_range_is_respected(self, fixture):
        """An impossible budget clamps at the top of the range rather than
        running the grid away: every extra row is another 2*grid+1 files
        per level to write and upload."""
        session, subject, gl = fixture
        pyr, _ = makePyramid(
            session,
            *records(60, 4000),
            gl,
            subject,
            binSizes=(1,),
            tileBudgetBytes=1,
            gridRange=(2, 5),
        )
        assert pyr_props(pyr)["tile_rows"] == 5

    def test_explicit_grid_still_wins(self, fixture):
        session, subject, gl = fixture
        pyr, _ = makePyramid(session, *records(40, 4000), gl, subject, binSizes=(1,), grid=7)
        assert pyr_props(pyr)["tile_rows"] == 7

    def test_bad_explicit_grid_is_rejected(self, fixture):
        session, subject, gl = fixture
        with pytest.raises(ValueError, match="positive integer"):
            makePyramid(session, *records(10, 1000), gl, subject, binSizes=(1,), grid=0)


class TestBandsPartitionTheRecords:
    def test_counts_are_conserved_across_bands(self, fixture, tmp_path):
        """A level is built one band of tile rows at a time. 8 genes over a
        37x37 lattice tiled 5x5, so the band bounds land mid-lattice rather
        than on it."""
        session, subject, gl = fixture
        x, y, gi, _ = records(37, 4000)
        c = np.arange(1, x.size + 1, dtype=np.int64)
        _, tiles = makePyramid(session, x, y, gi, c, gl, subject, binSizes=(1, 8), grid=5)
        for k, d in enumerate(tiles):
            total = 0
            for name in d.current_file_list():
                if not name.startswith("tile.bin_"):
                    continue
                fh = session.database_openbinarydoc(d, name)
                try:
                    t = readTileFile(fh)
                finally:
                    session.database_closebinarydoc(fh)
                total += int(np.sum(t["count"].astype(np.int64)))
            assert total == int(c.sum()), f"level {k} lost or duplicated counts across bands"

    def test_every_record_reaches_a_tile(self, fixture):
        """A gap between bands would silently drop records rather than
        raise, so the record count is checked as well as the totals."""
        session, subject, gl = fixture
        x, y, gi, c = records(23, 3000)
        _, tiles = makePyramid(session, x, y, gi, c, gl, subject, binSizes=(1,), grid=4)
        d = tiles[0]
        n = 0
        for name in d.current_file_list():
            if not name.startswith("tile.bin_"):
                continue
            fh = session.database_openbinarydoc(d, name)
            try:
                n += int(readTileFile(fh)["count"].size)
            finally:
                session.database_closebinarydoc(fh)
        # bin1 over a lattice: no two records share a (pixel, gene) pair, so
        # nothing collapses and the count must come back whole.
        assert n == x.size


class TestProgressReporting:
    def test_reports_within_the_build(self, fixture):
        """The pyramid is the slow half of an ingest -- 951 s of a 971 s
        ferret build -- and reported only at its ends, so minutes of it
        looked like a hang."""
        session, subject, gl = fixture
        seen = []
        makePyramid(
            session,
            *records(20, 4000),
            gl,
            subject,
            binSizes=(1, 2),
            grid=2,
            progressFcn=lambda f, t: seen.append((f, t)),
        )
        fracs = [f for f, _ in seen]
        texts = [t for _, t in seen]
        assert len(seen) > 4, "a two-level build must report more than its two endpoints"
        assert 0.0 <= min(fracs) and max(fracs) <= 1.0
        # A progress bar that jumps back reads as a bug.
        assert fracs == sorted(fracs)
        assert any("Level 1 of 2" in t for t in texts)
        assert any("Level 2 of 2" in t for t in texts)
        assert any("tile row" in t for t in texts)

    def test_reports_the_grid_it_chose(self, fixture):
        """The file COUNT is a cost the choice cannot see, so it is said
        out loud: a caller who minds it raises the budget or fixes grid."""
        session, subject, gl = fixture
        seen = []
        makePyramid(
            session,
            *records(20, 4000),
            gl,
            subject,
            binSizes=(1,),
            progressFcn=lambda f, t: seen.append(t),
        )
        assert any("files per level" in t for t in seen)

    def test_silent_with_no_handle(self, fixture):
        """Most callers have no display and should not have to pass a
        do-nothing handle."""
        session, subject, gl = fixture
        makePyramid(session, *records(10, 1000), gl, subject, binSizes=(1,), grid=2)
