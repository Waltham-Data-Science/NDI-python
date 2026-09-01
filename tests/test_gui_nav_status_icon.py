"""Tests for ndi.gui.nav.status_icon.

MATLAB counterpart: ndi.gui.nav.statusIcon

This one is fully checkable without a display, and without an imaging
library: the badge is rendered from a built-in bitmap font and encoded with
the standard library, so these tests decode the PNG by hand rather than
importing Pillow -- the module promises to work without an imaging stack, and
a test that needed one would not be testing that promise.
"""

from __future__ import annotations

import os
import shutil
import struct
import zlib

import pytest

from ndi.gui.cloud_colors import cloud_colors
from ndi.gui.nav.status_icon import (
    BADGE_VERSION,
    CELL_H,
    CELL_W,
    GAP,
    PAD_LR,
    PAD_TB,
    SCALE,
    cache_dir,
    glyph_letter,
    glyph_mask,
    render_badge,
    state_color,
    status_icon,
    statusIcon,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """Each test starts with an empty badge cache.

    Without this, a test asserting "the file was rendered" would pass on a
    file some earlier test left behind.
    """
    shutil.rmtree(cache_dir(), ignore_errors=True)
    yield
    shutil.rmtree(cache_dir(), ignore_errors=True)


# ----------------------------------------------------------------------
# a minimal PNG reader, so the tests need no imaging library
# ----------------------------------------------------------------------
def read_png(path):
    """Return (width, height, pixels) where pixels[(x, y)] = (r, g, b, a)."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"

    pos = 8
    width = height = None
    idat = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(tag + payload) & 0xFFFFFFFF, f"bad CRC on {tag!r}"
        if tag == b"IHDR":
            width, height, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", payload)
            assert (depth, ctype, comp, filt, interlace) == (8, 6, 0, 0, 0)
        elif tag == b"IDAT":
            idat += payload
        pos += 12 + length

    raw = zlib.decompress(idat)
    stride = width * 4
    pixels = {}
    for y in range(height):
        start = y * (stride + 1)
        assert raw[start] == 0, "expected filter type 0"
        row = raw[start + 1 : start + 1 + stride]
        for x in range(width):
            pixels[(x, y)] = tuple(row[x * 4 : x * 4 + 4])
    return width, height, pixels


def as_bytes(color):
    return tuple(min(255, max(0, int(v * 255 + 0.5))) for v in color)


class TestStateColor:
    @pytest.mark.parametrize(
        "state,attr",
        [
            ("ingested", "ok_green"),
            ("linked", "warn_amber"),
            ("none", "neutral_grey"),
            ("incloud", "light_blue"),
        ],
    )
    def test_known_states(self, state, attr):
        assert state_color(state) == getattr(cloud_colors(), attr)

    @pytest.mark.parametrize("state", ["unknown", "notincloud", "", "wat", "INGESTED "])
    def test_unknown_states_draw_nothing(self, state):
        """None, not a default colour: inventing one would assert a status
        the caller never reported."""
        assert state_color(state) is None

    def test_matching_is_case_insensitive(self):
        assert state_color("Ingested") == state_color("ingested")


class TestGlyphLetter:
    def test_ingested_is_double_coded_as_a_capital(self):
        assert glyph_letter("ingestion", "i", "ingested") == "I"

    def test_incloud_is_double_coded_as_a_capital(self):
        assert glyph_letter("cloud", "c", "incloud") == "C"

    def test_other_states_keep_the_lowercase_default(self):
        assert glyph_letter("ingestion", "i", "linked") == "i"
        assert glyph_letter("ingestion", "i", "none") == "i"

    def test_double_coding_does_not_leak_across_dimensions(self):
        """'ingested' on the cloud dimension is not a capital C."""
        assert glyph_letter("cloud", "c", "ingested") == "c"


class TestGlyphMask:
    def test_shape(self):
        m = glyph_mask("I")
        assert len(m) == CELL_H
        assert all(len(row) == CELL_W for row in m)

    def test_capital_i_differs_from_lowercase_i(self):
        """The accessibility property: ingested vs not is distinguishable by
        SHAPE, so the badge does not rely on colour alone."""
        assert glyph_mask("I") != glyph_mask("i")

    def test_capital_i_has_serif_bars(self):
        m = glyph_mask("I")
        assert all(m[0]) and all(m[-1])

    def test_capital_c_differs_from_lowercase_c(self):
        assert glyph_mask("C") != glyph_mask("c")

    def test_unknown_glyph_raises(self):
        with pytest.raises(ValueError, match="No bitmap defined"):
            glyph_mask("z")


class TestRenderBadge:
    def test_single_glyph_geometry(self):
        _, _, w, h = render_badge(["I"], [cloud_colors().ok_green])
        assert w == PAD_LR + CELL_W * SCALE + PAD_LR
        assert h == CELL_H * SCALE + 2 * PAD_TB

    def test_two_glyphs_add_a_gap(self):
        _, _, w1, _ = render_badge(["I"], [cloud_colors().ok_green])
        _, _, w2, _ = render_badge(["I", "C"], [cloud_colors().ok_green, cloud_colors().light_blue])
        assert w2 == w1 + CELL_W * SCALE + GAP

    def test_empty_renders_nothing(self):
        rgb, alpha, w, h = render_badge([], [])
        assert (len(rgb), len(alpha), w, h) == (0, 0, 0, 0)

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            render_badge(["I", "C"], [cloud_colors().ok_green])

    def test_lit_pixel_count_is_the_mask_times_scale_squared(self):
        """Upscaling is integer, so every lit cell becomes exactly SCALE^2
        pixels -- an off-by-one in the scaling would show up here."""
        for letter in ("i", "I", "c", "C", "m"):
            cells = sum(sum(row) for row in glyph_mask(letter))
            _, alpha, _, _ = render_badge([letter], [cloud_colors().ok_green])
            assert sum(1 for a in alpha if a) == cells * SCALE * SCALE, letter


class TestStatusIcon:
    def test_empty_status_returns_empty_string(self):
        assert status_icon({}) == ""

    def test_all_unknown_returns_empty_string(self):
        """A freshly-listed node carries no icon until a status is computed."""
        assert status_icon({"ingestion": "unknown", "cloud": "notincloud"}) == ""

    def test_unrecognised_fields_are_ignored(self):
        assert status_icon({"bookkeeping": "whatever"}) == ""

    def test_writes_a_valid_png(self):
        path = status_icon({"ingestion": "ingested"})
        assert os.path.isfile(path)
        w, h, px = read_png(path)
        assert (w, h) == (12, 16)

    def test_the_glyph_is_painted_in_the_state_colour(self):
        path = status_icon({"ingestion": "ingested"})
        _, _, px = read_png(path)
        lit = {(p[0], p[1], p[2]) for p in px.values() if p[3]}
        assert lit == {as_bytes(cloud_colors().ok_green)}

    def test_background_is_transparent(self):
        path = status_icon({"ingestion": "ingested"})
        w, h, px = read_png(path)
        assert px[(0, 0)][3] == 0
        assert px[(w - 1, h - 1)][3] == 0

    def test_linked_and_none_use_their_own_colours(self):
        for state, attr in (("linked", "warn_amber"), ("none", "neutral_grey")):
            path = status_icon({"ingestion": state})
            _, _, px = read_png(path)
            lit = {(p[0], p[1], p[2]) for p in px.values() if p[3]}
            assert lit == {as_bytes(getattr(cloud_colors(), attr))}, state

    def test_two_dimensions_composite_left_to_right(self):
        path = status_icon({"ingestion": "ingested", "cloud": "incloud"})
        w, h, px = read_png(path)
        assert (w, h) == (24, 16)
        left = {(p[0], p[1], p[2]) for (x, _), p in px.items() if p[3] and x < 12}
        right = {(p[0], p[1], p[2]) for (x, _), p in px.items() if p[3] and x >= 12}
        assert left == {as_bytes(cloud_colors().ok_green)}
        assert right == {as_bytes(cloud_colors().light_blue)}

    def test_dimension_order_is_fixed_not_dict_order(self):
        """The badge must not depend on the caller's key order, or two nodes
        with the same status could get different icons."""
        a = status_icon({"ingestion": "ingested", "cloud": "incloud"})
        b = status_icon({"cloud": "incloud", "ingestion": "ingested"})
        assert a == b

    def test_filename_carries_the_version_and_the_key(self):
        path = status_icon({"ingestion": "ingested"})
        name = os.path.basename(path)
        assert name == f"navstatus_{BADGE_VERSION}_ingestion=ingested.png"

    def test_different_statuses_get_different_files(self):
        a = status_icon({"ingestion": "ingested"})
        b = status_icon({"ingestion": "linked"})
        assert a != b
        assert os.path.isfile(a) and os.path.isfile(b)

    def test_cached_on_second_call(self):
        """Same path, and NOT re-rendered -- checked by mtime, since a path
        match alone would also hold if the file were rewritten."""
        a = status_icon({"ingestion": "ingested"})
        first = os.stat(a).st_mtime_ns
        os.utime(a, ns=(first - 10**9, first - 10**9))
        stamped = os.stat(a).st_mtime_ns

        b = status_icon({"ingestion": "ingested"})
        assert b == a
        assert os.stat(b).st_mtime_ns == stamped

    def test_rendering_is_byte_deterministic(self):
        """What makes the cache safe: the same status always produces the
        same bytes, so a cached file is never stale for the wrong reason."""
        path = status_icon({"ingestion": "ingested"})
        first = open(path, "rb").read()
        os.unlink(path)
        again = status_icon({"ingestion": "ingested"})
        assert open(again, "rb").read() == first

    def test_ingested_and_linked_differ_in_shape_not_only_colour(self):
        """Convert both to a lit/unlit mask and compare: if the only
        difference were the colour, these would be equal."""
        pa = status_icon({"ingestion": "ingested"})
        pb = status_icon({"ingestion": "linked"})
        _, _, a = read_png(pa)
        _, _, b = read_png(pb)
        mask_a = {xy for xy, p in a.items() if p[3]}
        mask_b = {xy for xy, p in b.items() if p[3]}
        assert mask_a != mask_b

    def test_matlab_cased_alias(self):
        assert statusIcon is status_icon

    def test_state_values_may_be_non_strings(self):
        """Callers pass whatever a status command produced."""
        assert status_icon({"ingestion": 3}) == ""
