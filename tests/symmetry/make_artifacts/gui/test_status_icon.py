"""Write this language's statusIcon badge artifacts.

MATLAB counterpart:
    tests/+ndi/+symmetry/+makeArtifacts/+gui/statusIcon.m

Renders every case in :mod:`tests.symmetry.gui.status_icon_cases` under

    <tempdir>/NDI/symmetryTest/pythonArtifacts/gui/statusIcon/
             testStatusIconArtifacts/

as ``<name>.png``, plus an index recording which cases produced a badge at
all. The MATLAB counterpart writes the same case names under
``matlabArtifacts/``. Like the VHSB battery, what crosses the language
boundary is the binary itself -- but it is compared by PIXEL rather than by
byte, because the two ports use different PNG encoders. See the case module.

Each badge is decoded straight back and checked against the battery's own
reference rendering before being published, so a generator that draws the
wrong picture fails HERE rather than looking like a cross-language
divergence later.
"""

from __future__ import annotations

import struct
import zlib

from ndi.gui.nav.status_icon import BADGE_VERSION
from tests.symmetry.conftest import PYTHON_ARTIFACTS
from tests.symmetry.gui import status_icon_cases as cases

ARTIFACT_DIR = PYTHON_ARTIFACTS / "gui" / "statusIcon" / "testStatusIconArtifacts"

#: The eight cases that draw something and the three that deliberately do not.
EXPECTED_BADGE_COUNT = 8
EXPECTED_CASE_COUNT = 11


def _encode_rgba_png(width, height, pixels, filters):
    """Encode an RGBA PNG applying FILTERS[y] to scanline y.

    Test scaffolding for :func:`test_decoder_handles_every_filter_type`. It
    exists to produce, without MATLAB, the one thing MATLAB's ``imwrite``
    writes and this port's encoder never does: scanlines under filter types
    1-4. The port's own encoder always writes type 0, so a decoder bug in the
    other four types would otherwise stay invisible until it met a real
    MATLAB badge in CI.
    """
    stride = width * 4
    flat = bytearray()
    for px in pixels:
        flat += bytes(px)

    raw = bytearray()
    prev = bytearray(stride)
    for y in range(height):
        line = flat[y * stride : (y + 1) * stride]
        ftype = filters[y]
        enc = bytearray()
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = prev[i]
            upleft = prev[i - 4] if i >= 4 else 0
            if ftype == 0:
                v = line[i]
            elif ftype == 1:
                v = line[i] - left
            elif ftype == 2:
                v = line[i] - up
            elif ftype == 3:
                v = line[i] - ((left + up) >> 1)
            elif ftype == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upleft)
                v = line[i] - pred
            else:
                raise ValueError(ftype)
            enc.append(v & 0xFF)
        raw.append(ftype)
        raw += enc
        prev = line

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


class TestStatusIconMakeArtifacts:
    """Mirror of ndi.symmetry.makeArtifacts.gui.statusIcon."""

    def test_status_icon_artifacts(self):
        badges = cases.write_cases(ARTIFACT_DIR)

        names = cases.case_names()
        assert len(names) == EXPECTED_CASE_COUNT, f"Expected {EXPECTED_CASE_COUNT} cases."
        assert (
            sum(badges.values()) == EXPECTED_BADGE_COUNT
        ), f"Expected {EXPECTED_BADGE_COUNT} cases to draw a badge, got {sorted(k for k, v in badges.items() if v)}"

        # The three no-badge cases are the point of statusIcon returning "":
        # a case that quietly started drawing something would otherwise just
        # look like an extra file nobody compares.
        for name in names:
            path = ARTIFACT_DIR / f"{name}.png"
            if cases.draws_badge(name):
                assert badges[name], f"{name}: status_icon returned '' but a badge was expected"
                assert path.is_file(), f"{name}.png was not written"
            else:
                assert not badges[name], f"{name}: status_icon drew a badge where none was expected"
                assert not path.exists(), f"{name}.png was written for a no-badge case"

        # Decode each one back with this language's reader before publishing.
        problems = []
        for name in names:
            if not badges[name]:
                continue
            for problem in cases.compare_to_expectation(name, ARTIFACT_DIR / f"{name}.png"):
                problems.append(f"{name}: {problem}")
        assert not problems, "Python did not draw what the battery expects:\n  " + "\n  ".join(
            problems
        )

        assert (ARTIFACT_DIR / cases.INDEX_FILE).is_file()

    def test_badge_version_is_level_with_matlab(self):
        """A one-sided BADGE_VERSION bump means one cache key, two pictures.

        Caught here as a named failure rather than as a pixel mismatch on
        every case, which is what it would otherwise look like. The read side
        additionally compares the version each language actually wrote.
        """
        assert BADGE_VERSION == cases.EXPECTED_BADGE_VERSION, (
            f"status_icon.BADGE_VERSION is {BADGE_VERSION!r} but the battery expects "
            f"{cases.EXPECTED_BADGE_VERSION!r}. Both ports must bump together."
        )
        # The constant is what builds the cache filename, and the filename is
        # what the two ports can collide on, so pin the path too -- that is
        # the only handle MATLAB has, its BADGEVERSION being a local.
        from ndi.gui.nav.status_icon import status_icon

        cases.clear_badge_cache()
        path = status_icon({"ingestion": "ingested"})
        assert cases.badge_version_from_path(path) == cases.EXPECTED_BADGE_VERSION

    def test_decoder_handles_every_filter_type(self, tmp_path):
        """The battery's PNG decoder must survive adaptive filtering.

        This port's encoder always writes filter type 0, so the minimal
        reader in tests/test_gui_nav_status_icon.py gets away with assuming
        it. MATLAB's ``imwrite`` chooses a filter per scanline, and a decoder
        that only understood type 0 would throw on a perfectly good MATLAB
        badge -- a red battery for a reason that has nothing to do with
        whether the two pictures agree.

        Encoding the same image under every filter type and decoding it back
        proves that path without needing MATLAB on the runner.
        """
        want = cases.expected_image("bothMixed")
        assert want is not None
        width, height, pixels = want

        for ftype in range(5):
            blob = _encode_rgba_png(width, height, pixels, [ftype] * height)
            path = tmp_path / f"filterProbe{ftype}.png"
            path.write_bytes(blob)
            try:
                got_w, got_h, got_px = cases.decode_png(path)
                assert (got_w, got_h) == (width, height), f"filter {ftype}: size changed"
                assert got_px == pixels, f"filter {ftype}: pixels did not survive the round trip"
            finally:
                path.unlink()

        # Mixed filters per scanline, which is what an adaptive encoder
        # actually emits -- a decoder can pass every uniform case and still
        # get the inter-scanline state (the `prev` row) wrong.
        mixed = [y % 5 for y in range(height)]
        blob = _encode_rgba_png(width, height, pixels, mixed)
        path = tmp_path / "filterProbeMixed.png"
        path.write_bytes(blob)
        try:
            got_w, got_h, got_px = cases.decode_png(path)
            assert (got_w, got_h) == (width, height)
            assert got_px == pixels, "mixed per-scanline filters did not survive the round trip"
        finally:
            path.unlink()
