"""Shared statusIcon badge battery, defined identically in both languages.

MATLAB counterpart: tests/+ndi/+symmetry/+gui/statusIconCases.m

WHY THIS BATTERY COMPARES PIXELS AND NOT BYTES
Like the VHSB battery (``tests/symmetry/element/vhsb_cases.py``), what
crosses the language boundary here is a binary rather than a JSON transcript
of results -- ``ndi.gui.nav.status_icon`` turns a status into a PNG, and the
thing that has to hold is that both ports draw the same picture.

But unlike VHSB, the *bytes* are not the contract. MATLAB writes its badge
with ``imwrite(rgb, path, 'Alpha', alpha)``; this port encodes the PNG itself
with ``zlib``/``struct`` so the shipped module needs no imaging stack. Both
produce a valid 8-bit RGBA PNG of the same picture, and both are free to
differ in compression level, scanline filter choice, chunk layout and
ancillary chunks. A byte comparison would go red for a reason that has
nothing to do with whether the two badges look the same.

So both files are DECODED and compared as ``(width, height)`` plus every
pixel's ``(r, g, b, a)``.

WHY THE EXPECTATION IS RE-DERIVED HERE RATHER THAN IMPORTED
``expected_image`` renders each case from this module's own glyph table,
geometry and state->colour vocabulary rather than calling into
``ndi.gui.nav.status_icon``. That is deliberate, and it is what makes the
battery non-vacuous in the direction that matters: each language checks
*both* languages' artifacts against its own independent reference, so two
ports that agreed with each other on the WRONG picture still go red. The
MATLAB side has no choice in the matter anyway -- ``glyphMask``,
``glyphLetter`` and ``stateColor`` are local functions inside
``statusIcon.m`` and are not reachable from a test -- so re-deriving on this
side too keeps the two batteries the same shape.

The one thing taken from shipped code is the palette
(``ndi.gui.cloud_colors``), which is a shared, documented constant on both
sides.

WHY THERE IS A PNG DECODER HERE
``tests/test_gui_nav_status_icon.py`` has a minimal reader that assumes
filter type 0 on every scanline. That holds for this port's encoder, which
always writes filter 0, but MATLAB's ``imwrite`` picks filters adaptively, so
that reader throws on MATLAB's file. :func:`decode_png` implements all five
PNG filter types instead. Pillow would also have done the job, but it is not
a declared dependency of this package and the shipped module deliberately has
no imaging dependency (MATLAB's docstring promises the badge needs "no
toolboxes and no display"); a hand-written decoder keeps the test extra empty
and is proved against all five filter types by
``tests/symmetry/make_artifacts/gui/test_status_icon.py``.

BADGE_VERSION MUST STAY LEVEL ACROSS THE TWO PORTS
Both are at ``v2``. The cache key is ``navstatus_<version>_<key>.png``, so if
one side bumps and the other does not, the same filename means different
pictures in the two caches. If this battery is ever red on a case whose
picture obviously matches, check that first.
"""

from __future__ import annotations

import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

INDEX_FILE = "statusIconIndex.json"

#: The badge version both ports must agree on. Compared against the shipped
#: constant by the make test, so a one-sided bump is caught here rather than
#: as a mysterious pixel mismatch.
EXPECTED_BADGE_VERSION = "v2"

# ----------------------------------------------------------------------
# The battery's own reference rendering vocabulary.
#
# These mirror the constants inside ndi.gui.nav.status_icon (and the locals
# inside MATLAB's renderBadge/glyphMask, which are not reachable from a
# test). They are duplicated on purpose -- see the module docstring. A
# deliberate change to the badge means editing the renderer, both batteries,
# and BADGE_VERSION; an accidental one-sided change goes red here.
# ----------------------------------------------------------------------

SCALE = 2  # integer upscaling of the 5x7 bitmap cells
PAD_TB = 1  # transparent rows above and below the glyphs
PAD_LR = 1  # transparent columns at the far left and right
GAP = 2  # transparent columns between adjacent glyphs
CELL_W = 5
CELL_H = 7

#: Dimension name -> default (lowercase) glyph, in drawing order.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("ingestion", "i"),
    ("cloud", "c"),
)

#: state -> palette attribute on ndi.gui.cloud_colors.CloudColors.
#: A state that is not here draws nothing at all, which is the mechanism
#: behind the three no-badge cases below.
STATE_COLORS: dict[str, str] = {
    "ingested": "ok_green",
    "linked": "warn_amber",
    "none": "neutral_grey",
    "incloud": "light_blue",
}

#: The states that are double-coded by SHAPE as well as colour, as
#: (dimension, state) -> capital glyph. This is an accessibility property:
#: ingested-vs-not and in-cloud-vs-not stay distinguishable without colour.
SHAPE_DOUBLE_CODED: dict[tuple[str, str], str] = {
    ("ingestion", "ingested"): "I",
    ("cloud", "incloud"): "C",
}

#: The bitmap font, "#" for a lit pixel. Only the glyphs this battery draws.
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
    "I": (
        "#####",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "..#..",
        "#####",
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
}

# ----------------------------------------------------------------------
# The cases
# ----------------------------------------------------------------------

#: name -> (status, note). Eight cases draw a badge; three deliberately draw
#: none, and that distinction is the whole point of statusIcon returning "".
CASES: dict[str, tuple[dict[str, str], str]] = {
    "ingestionIngested": (
        {"ingestion": "ingested"},
        "The completed state: capital 'I' in ok_green. 12x16.",
    ),
    "ingestionLinked": (
        {"ingestion": "linked"},
        "Linked but not ingested: lowercase 'i' in warn_amber, so the "
        "partial state differs from the complete one in shape as well as "
        "colour. 12x16.",
    ),
    "ingestionNone": (
        {"ingestion": "none"},
        "On disk, not ingested: lowercase 'i' in neutral_grey. 12x16.",
    ),
    "cloudIncloud": (
        {"cloud": "incloud"},
        "The only drawn cloud state: capital 'C' in light_blue. 12x16.",
    ),
    "bothDrawn": (
        {"ingestion": "ingested", "cloud": "incloud"},
        "Both dimensions active: 24x16, green 'I' then blue 'C', left to "
        "right in DIMENSIONS order. Pins the composite width (two glyphs "
        "plus one gap) and the drawing order.",
    ),
    "bothMixed": (
        {"ingestion": "linked", "cloud": "incloud"},
        "Two dimensions in different states: amber 'i' then blue 'C'. Pins "
        "that each glyph carries its own dimension's colour.",
    ),
    "ingestedUnknownCloud": (
        {"ingestion": "ingested", "cloud": "unknown"},
        "An unknown dimension contributes nothing but must not suppress the "
        "other: 12x16, not 24x16 with a blank slot and not an empty badge.",
    ),
    "extraField": (
        {"ingestion": "ingested", "bookkeeping": "whatever"},
        "Unrecognised keys are ignored, so callers may pass extra "
        "bookkeeping fields. Renders identically to ingestionIngested.",
    ),
    "cloudNotInCloud": (
        {"cloud": "notincloud"},
        "NO BADGE. A local-only dataset carries no cloud glyph -- 'notincloud' "
        "is a known state that is deliberately not drawn, rather than an "
        "unknown one.",
    ),
    "allUnknown": (
        {"ingestion": "unknown", "cloud": "unknown"},
        "NO BADGE. Every dimension unknown, so a freshly-listed node carries "
        "no icon until a status command computes one.",
    ),
    "emptyStatus": (
        {},
        "NO BADGE. No dimensions at all: the empty status must not raise and "
        "must not draw an empty image.",
    ),
}


def case_names() -> list[str]:
    """Case names in a stable order."""
    return sorted(CASES)


def status_for(name: str) -> dict[str, str]:
    """The status struct a case is built from."""
    return dict(CASES[name][0])


def expected_glyphs(name: str) -> list[tuple[str, tuple[float, float, float]]]:
    """The (letter, colour) pairs this case should draw, left to right.

    Derived from this module's own vocabulary tables, not from the renderer.
    """
    from ndi.gui.cloud_colors import cloud_colors

    palette = cloud_colors()
    status = CASES[name][0]
    out: list[tuple[str, tuple[float, float, float]]] = []
    for field, default_letter in DIMENSIONS:
        if field not in status:
            continue
        state = str(status[field]).lower()
        attr = STATE_COLORS.get(state)
        if attr is None:
            continue  # unknown / unrecognised / notincloud -> nothing drawn
        letter = SHAPE_DOUBLE_CODED.get((field, state), default_letter)
        out.append((letter, getattr(palette, attr)))
    return out


def draws_badge(name: str) -> bool:
    """Whether this case should produce a file at all."""
    return bool(expected_glyphs(name))


def _color_bytes(color: tuple[float, float, float]) -> tuple[int, int, int]:
    """0..1 floats to 0..255, rounding half away from zero.

    Matches MATLAB's ``uint8(round(color * 255))``. No palette entry lands on
    a .5 tie, so the two roundings cannot disagree on the shipped colours.
    """
    return tuple(min(255, max(0, int(v * 255 + 0.5))) for v in color)  # type: ignore[return-value]


def expected_image(name: str) -> tuple[int, int, list[tuple[int, int, int, int]]] | None:
    """Render the case locally as (width, height, RGBA pixels), or None.

    ``None`` means the case must produce no badge at all. Pixels are
    row-major, each an ``(r, g, b, a)`` tuple; everything outside a lit glyph
    pixel is fully transparent black, which is what both renderers leave
    behind when they paint only the lit cells onto a zeroed canvas.
    """
    glyphs = expected_glyphs(name)
    if not glyphs:
        return None

    gw = CELL_W * SCALE
    gh = CELL_H * SCALE
    height = gh + 2 * PAD_TB
    width = 2 * PAD_LR + len(glyphs) * gw + (len(glyphs) - 1) * GAP

    pixels: list[tuple[int, int, int, int]] = [(0, 0, 0, 0)] * (width * height)
    x = PAD_LR
    for letter, color in glyphs:
        art = GLYPH_ART[letter]
        rgb = _color_bytes(color)
        for r in range(gh):
            src = art[r // SCALE]
            for c in range(gw):
                if src[c // SCALE] == "#":
                    pixels[(PAD_TB + r) * width + x + c] = (*rgb, 255)
        x += gw + GAP
    return width, height, pixels


# ----------------------------------------------------------------------
# PNG decoding
# ----------------------------------------------------------------------

_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    """Reverse the per-scanline PNG filters. All five types, per RFC 2083.

    This is the part MATLAB's output needs and the minimal reader in
    tests/test_gui_nav_status_icon.py does not have: ``imwrite`` chooses a
    filter per scanline, so a decoder that only understands type 0 throws on
    a perfectly good MATLAB badge.
    """
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        else:
            raise ValueError(f"Unknown PNG filter type {ftype} on scanline {y}.")
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return out


def _samples(line: bytes, count: int, depth: int) -> list[int]:
    """Unpack COUNT samples of DEPTH bits from one unfiltered scanline."""
    if depth == 8:
        return list(line[:count])
    if depth == 16:
        return [(line[2 * i] << 8) | line[2 * i + 1] for i in range(count)]
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    out = []
    for i in range(count):
        byte = line[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        out.append((byte >> shift) & mask)
    return out


def decode_png(path: Path | str) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """Decode a PNG to (width, height, RGBA pixels), row-major.

    Handles every non-interlaced PNG this battery can meet: all five scanline
    filters, colour types 0/2/3/4/6, and bit depths 1/2/4/8/16. 16-bit
    samples are reduced to their high byte, which is exact for anything
    written from 8-bit data.
    """
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG.")

    width = height = depth = ctype = None
    interlace = 0
    idat = bytearray()
    palette = b""
    trns: bytes | None = None

    pos = 8
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        if crc != zlib.crc32(tag + payload) & 0xFFFFFFFF:
            raise ValueError(f"Bad CRC on {tag!r} chunk of {path}.")
        if tag == b"IHDR":
            width, height, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", payload)
            if comp != 0 or filt != 0:
                raise ValueError(f"{path}: unsupported compression/filter method.")
        elif tag == b"PLTE":
            palette = payload
        elif tag == b"tRNS":
            trns = payload
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
        pos += 12 + length

    if width is None:
        raise ValueError(f"{path} has no IHDR chunk.")
    if interlace:
        raise ValueError(f"{path} is interlaced, which neither port writes.")
    if ctype not in _CHANNELS:
        raise ValueError(f"{path}: unsupported colour type {ctype}.")

    channels = _CHANNELS[ctype]
    bits = channels * depth
    stride = (width * bits + 7) // 8
    bpp = max(1, bits // 8)
    raw = _unfilter(zlib.decompress(bytes(idat)), height, stride, bpp)

    maxval = (1 << depth) - 1
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(height):
        line = raw[y * stride : (y + 1) * stride]
        vals = _samples(line, width * channels, depth)
        for x in range(width):
            s = vals[x * channels : (x + 1) * channels]
            if ctype == 0:
                g = s[0] >> 8 if depth == 16 else s[0] * 255 // maxval
                px = (g, g, g, 255)
            elif ctype == 2:
                r, g, b = (v >> 8 for v in s) if depth == 16 else s
                px = (r, g, b, 255)
            elif ctype == 3:
                i = s[0]
                r, g, b = palette[3 * i : 3 * i + 3]
                a = trns[i] if trns is not None and i < len(trns) else 255
                px = (r, g, b, a)
            elif ctype == 4:
                g, a = (v >> 8 for v in s) if depth == 16 else s
                px = (g, g, g, a)
            else:  # ctype == 6
                r, g, b, a = (v >> 8 for v in s) if depth == 16 else s
                px = (r, g, b, a)
            pixels.append(px)
    return width, height, pixels


# ----------------------------------------------------------------------
# Writing and comparing
# ----------------------------------------------------------------------


def badge_version_from_path(path: str) -> str:
    """The BADGE_VERSION a rendered badge's cache filename carries.

    Read out of the filename rather than out of the module constant because
    the filename is the thing that can collide: the cache key is
    ``navstatus_<version>_<key>.png``, so if one port bumps and the other
    does not, the same name means different pictures in the shared cache.
    MATLAB keeps its BADGEVERSION as a local inside ``statusIcon.m``, where a
    test cannot reach it, so parsing the path is also the only mechanism
    available on that side -- doing it the same way here keeps the two
    batteries observing the same thing.
    """
    name = Path(path).name
    parts = name.split("_")
    if len(parts) < 3 or parts[0] != "navstatus":
        raise ValueError(f"Unexpected badge cache filename {name!r}.")
    return parts[1]


def clear_badge_cache() -> None:
    """Empty the shared on-disk badge cache before rendering.

    Both ports render into ``<tempdir>/ndi_navstatus``, and on a CI runner
    they share one tempdir. Without this, whichever language runs second
    finds the first one's PNG already sitting at the cache key, returns it
    unrendered, and publishes the OTHER language's bytes as its own artifact
    -- a comparison that can only pass. Clearing also drops a stale badge
    left by an earlier run of this same language.
    """
    from ndi.gui.nav.status_icon import cache_dir

    shutil.rmtree(cache_dir(), ignore_errors=True)


def write_cases(dest: Path) -> dict[str, bool]:
    """Render every case into DEST as ``<name>.png``, plus the index.

    Returns the name -> produced-a-badge map that goes into the index.
    ``status_icon`` writes into its own temp cache and takes no destination,
    so the returned path is copied here rather than widening shipped code
    with a ``dest`` argument.
    """
    from ndi.gui.nav.status_icon import status_icon

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    clear_badge_cache()

    badges: dict[str, bool] = {}
    observed_version = ""
    for name in case_names():
        path = status_icon(status_for(name))
        badges[name] = bool(path)
        if path:
            observed_version = badge_version_from_path(path)
            shutil.copyfile(path, dest / f"{name}.png")

    (dest / INDEX_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "language": "python",
                # Observed from the cache filename, not asserted: the reader
                # compares the two languages' values, so a one-sided bump
                # shows up as a named failure instead of eleven pixel
                # mismatches.
                "badgeVersion": observed_version,
                "cases": case_names(),
                # Which cases produced a badge. A silently-missing file and a
                # deliberately-absent badge look identical on disk, and that
                # distinction is exactly what statusIcon returning "" means.
                "badges": badges,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return badges


def compare_to_expectation(name: str, path: Path) -> list[str]:
    """Check one rendered badge against this battery's local reference.

    Returns a list of human-readable problems; empty means it matched.
    """
    want = expected_image(name)
    if want is None:
        return [f"expected no badge, but {path.name} exists"]
    want_w, want_h, want_px = want

    got_w, got_h, got_px = decode_png(path)
    if (got_w, got_h) != (want_w, want_h):
        return [f"size {got_w}x{got_h} != {want_w}x{want_h}"]

    problems = []
    for i, (got, wanted) in enumerate(zip(got_px, want_px)):
        if got != wanted:
            problems.append(f"pixel ({i % got_w},{i // got_w}) is {got}, expected {wanted}")
            if len(problems) >= 8:
                problems.append("... further pixel differences not listed")
                break
    return problems


def compare_files(path_a: Path, path_b: Path) -> list[str]:
    """Compare two languages' badges pixel for pixel.

    Deliberately NOT a byte comparison: the two encoders differ in
    compression level, scanline filters and chunk layout, none of which
    changes the picture. See the module docstring.
    """
    a_w, a_h, a_px = decode_png(path_a)
    b_w, b_h, b_px = decode_png(path_b)
    if (a_w, a_h) != (b_w, b_h):
        return [f"size {a_w}x{a_h} != {b_w}x{b_h}"]

    problems = []
    for i, (a, b) in enumerate(zip(a_px, b_px)):
        if a != b:
            problems.append(f"pixel ({i % a_w},{i // a_w}): {a} != {b}")
            if len(problems) >= 8:
                problems.append("... further pixel differences not listed")
                break
    return problems


def load_index(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
