"""ndi.gui.nav.status_icon - cached badge icon for a navigator session node.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/statusIcon.m``

BADGE GRAMMAR: the letter names the check, the colour names the state.

Each status dimension is drawn as one letter glyph -- ``ingestion`` as "i",
``cloud`` as "c" -- coloured from the shared palette:

    ingested   -> ok_green      (good / complete)
    linked     -> warn_amber    (partial / attention)
    none       -> neutral_grey  (not yet / absent)
    incloud    -> light_blue    (linked to NDI Cloud)
    unknown    -> not drawn

Two states are additionally DOUBLE-CODED BY SHAPE: ``ingested`` draws a
capital "I" and ``incloud`` a capital "C", so those states are
distinguishable without relying on colour. That is an accessibility property,
not decoration, and the tests pin it.

A dimension whose state is unknown or missing contributes no glyph; when
every dimension is unknown the badge is empty and ``""`` is returned, so a
freshly-listed node carries no icon until a status command computes one.

NO IMAGING DEPENDENCY
MATLAB renders from a built-in bitmap font precisely so the badge needs "no
toolboxes and no display" and is safe to call in headless tests. This port
keeps that property: the PNG is encoded here with ``zlib`` and ``struct``
from the standard library rather than through Pillow, which is not a declared
dependency of this package (it arrives only via matplotlib, and matplotlib is
in the ``tutorials`` extra). A badge renderer that quietly required an
imaging stack would break the one guarantee the MATLAB docstring makes about
it.

The output is byte-deterministic in the status, which is what makes the
on-disk cache safe: the same status always produces the same bytes, so a
cached file is never stale for the wrong reason.
"""

from __future__ import annotations

import os
import struct
import tempfile
import zlib
from collections.abc import Mapping, Sequence

from ..cloud_colors import cloud_colors

__all__ = [
    "status_icon",
    "statusIcon",
    "render_badge",
    "glyph_mask",
    "state_color",
    "glyph_letter",
    "cache_dir",
    "BADGE_VERSION",
    "DIMENSIONS",
]

#: Bumped when the glyph rendering changes, so cached PNGs written by an
#: older renderer are not reused for the same status key. MATLAB is at v2
#: (ingested moved from a lowercase "i" to a capital "I"); this port starts
#: level with it rather than at v1, so the two caches cannot disagree about
#: what a given filename contains.
BADGE_VERSION = "v2"

#: The status dimensions this badge knows how to draw, in drawing order.
#: Add a pair to extend the badge; the letter must exist in GLYPH_ART.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("ingestion", "i"),
    ("cloud", "c"),
)

# Badge geometry, in the units MATLAB uses.
SCALE = 2  # integer upscaling of the 5x7 bitmap cells
PAD_TB = 1  # transparent rows above and below the glyphs
PAD_LR = 1  # transparent columns at the far left and right
GAP = 2  # transparent columns between adjacent glyphs
CELL_W = 5
CELL_H = 7

#: The bitmap font. "#" is a lit pixel. Case-sensitive: lowercase "i" and
#: capital "I" are deliberately distinct glyphs.
GLYPH_ART: dict[str, tuple[str, ...]] = {
    "i": (
        "..#..",
        ".....",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
    ),
    # Serifed capital I: top and bottom bars plus a centre stem, clearly
    # distinct in shape from the lowercase "i".
    "I": (
        "#####",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "#####",
    ),
    # Lowercase "c" is not currently drawn -- the cloud dimension only draws
    # its "incloud" state, as a capital "C" -- but is defined so a future
    # secondary cloud state can use it.
    "c": (
        ".....",
        ".....",
        ".####",
        "#....",
        "#....",
        "#....",
        ".####",
    ),
    "C": (
        ".###.",
        "#...#",
        "#....",
        "#....",
        "#....",
        "#...#",
        ".###.",
    ),
    "m": (
        ".....",
        ".....",
        "#####",
        "#.#.#",
        "#.#.#",
        "#.#.#",
        "#.#.#",
    ),
}


def state_color(state: str) -> tuple[float, float, float] | None:
    """The palette colour for a state, or None when nothing should be drawn.

    Returning None rather than a default colour is the whole mechanism for
    "unknown draws nothing": an unrecognised state is indistinguishable from
    an unknown one, and inventing a colour for it would assert a status the
    caller never reported.
    """
    c = cloud_colors()
    return {
        "ingested": c.ok_green,
        "linked": c.warn_amber,
        "none": c.neutral_grey,
        "incloud": c.light_blue,
    }.get(str(state).lower())


def glyph_letter(field: str, default_letter: str, state: str) -> str:
    """The glyph for a dimension's state, applying the shape double-coding."""
    if field.lower() == "ingestion" and str(state).lower() == "ingested":
        return "I"
    if field.lower() == "cloud" and str(state).lower() == "incloud":
        return "C"
    return default_letter


def glyph_mask(letter: str) -> list[list[bool]]:
    """The CELL_H x CELL_W bitmap for a supported glyph."""
    art = GLYPH_ART.get(letter)
    if art is None:
        raise ValueError(f"No bitmap defined for badge glyph {letter!r}.")
    return [[ch == "#" for ch in row] for row in art]


def cache_dir() -> str:
    """The folder holding rendered, reusable badge PNGs."""
    return os.path.join(tempfile.gettempdir(), "ndi_navstatus")


def render_badge(
    letters: Sequence[str], colors: Sequence[tuple[float, float, float]]
) -> tuple[bytearray, bytearray, int, int]:
    """Composite LETTERS, each in its colour, into one RGBA image.

    Returns ``(rgb, alpha, width, height)`` with ``rgb`` a flat H*W*3
    bytearray and ``alpha`` a flat H*W bytearray -- 255 where a glyph pixel
    is painted, 0 elsewhere, so the badge is transparent between and around
    the glyphs.
    """
    n = len(letters)
    if n != len(colors):
        raise ValueError("letters and colors must be the same length.")
    if n == 0:
        return bytearray(), bytearray(), 0, 0

    gw = CELL_W * SCALE
    gh = CELL_H * SCALE
    height = gh + 2 * PAD_TB
    width = PAD_LR + n * gw + (n - 1) * GAP + PAD_LR

    rgb = bytearray(height * width * 3)
    alpha = bytearray(height * width)

    x = PAD_LR
    for letter, color in zip(letters, colors):
        mask = glyph_mask(letter)
        # Round-half-away-from-zero on the scaled channel, matching MATLAB's
        # uint8(round(color * 255)).
        rv, gv, bv = (min(255, max(0, int(v * 255 + 0.5))) for v in color)
        for r in range(gh):
            src_row = mask[r // SCALE]
            row = PAD_TB + r
            for cc in range(gw):
                if not src_row[cc // SCALE]:
                    continue
                col = x + cc
                idx = (row * width + col) * 3
                rgb[idx] = rv
                rgb[idx + 1] = gv
                rgb[idx + 2] = bv
                alpha[row * width + col] = 255
        x += gw + GAP

    return rgb, alpha, width, height


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _encode_png(rgb: bytes, alpha: bytes, width: int, height: int) -> bytes:
    """Encode an RGBA PNG from flat RGB and alpha planes.

    Written out rather than delegated to an imaging library so this module
    keeps MATLAB's "no toolboxes" guarantee (see the module docstring).
    Filter type 0 on every scanline, and a fixed compression level, so the
    bytes are reproducible for a given input.
    """
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0 (None)
        for col in range(width):
            i = (row * width + col) * 3
            raw += rgb[i : i + 3]
            raw.append(alpha[row * width + col])

    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,  # bit depth
        6,  # colour type 6 = truecolour with alpha
        0,  # deflate
        0,  # adaptive filtering
        0,  # no interlace
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def status_icon(status: Mapping[str, str]) -> str:
    """The file path of a badge PNG summarising STATUS, or ``""``.

    ``status`` maps dimension names to state strings, e.g.
    ``{"ingestion": "ingested"}``. Unknown keys are ignored, so callers may
    pass extra bookkeeping fields.

    The rendered PNG is deterministic in ``status``, so it is cached on disk
    under a per-user temp folder and reused: repeated calls with the same
    status return the same path without re-rendering.
    """
    letters: list[str] = []
    colors: list[tuple[float, float, float]] = []
    key_parts: list[str] = []

    for field, letter in DIMENSIONS:
        if field not in status:
            continue
        state = str(status[field])
        color = state_color(state)
        if color is None:
            continue  # unknown / unrecognised -> nothing to draw
        letters.append(glyph_letter(field, letter, state))
        colors.append(color)
        key_parts.append(f"{field}={state}")

    if not letters:
        return ""

    key = "_".join(key_parts)
    directory = cache_dir()
    path = os.path.join(directory, f"navstatus_{BADGE_VERSION}_{key}.png")
    if os.path.isfile(path):
        return path

    rgb, alpha, width, height = render_badge(letters, colors)
    os.makedirs(directory, exist_ok=True)
    # Written via a temp file in the same directory and then moved, so a
    # concurrent reader never sees a half-written PNG -- two navigator panes
    # refreshing at once is the normal case, not an exotic one.
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".png")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(_encode_png(bytes(rgb), bytes(alpha), width, height))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


#: MATLAB-cased alias.
statusIcon = status_icon
