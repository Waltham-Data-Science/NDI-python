"""ndi.gui.cloud_colors - the NDI Cloud colour palette.

MATLAB counterpart: ``src/ndi/+ndi/+gui/cloudColors.m``

One palette so NDI GUIs stop hardcoding RGB triplets per widget. The values
are the same numbers MATLAB uses, kept as 0..1 float triplets on this side
too rather than converted to 0..255, so a divergence between the two ports
would be a changed number and not a changed unit.

The three status colours are the shared palette for navigator node badges
(see ``ndi.gui.nav.status_icon``): the badge letter names the check and the
colour names the state, so any future badge draws from these.
"""

from __future__ import annotations

from typing import NamedTuple

__all__ = ["CloudColors", "cloud_colors", "cloudColors", "rgb_to_hex"]


class CloudColors(NamedTuple):
    """The palette. Each field is an ``(r, g, b)`` triplet in 0..1."""

    #: NDI Cloud navy. Header bars, and text on light backgrounds.
    #:
    #: MATLAB documents this as #082051 but stores (0.0314, 0.1216, 0.3176),
    #: and 0.1216 * 255 = 31.008, i.e. 0x1F -- so what MATLAB actually paints
    #: is #081F51, one step off its own comment. (0x20 would be 0.1255.) The
    #: stored triplet is mirrored here rather than the comment, because the
    #: triplet is what renders: matching the hex would make the two ports
    #: paint visibly different navies. Reported rather than corrected here --
    #: see VH-Lab/NDI-matlab, ndi.gui.cloudColors.
    dark_blue: tuple[float, float, float] = (0.0314, 0.1216, 0.3176)
    #: #4EA5F8 NDI Cloud accent. Buttons and accents.
    light_blue: tuple[float, float, float] = (0.3059, 0.6471, 0.9725)
    #: Panel bodies, and text on navy.
    white: tuple[float, float, float] = (1.0, 1.0, 1.0)
    #: The figure-background tint used by the cloud apps.
    off_white: tuple[float, float, float] = (0.9922, 0.9686, 0.9804)
    #: #2E9E47 status: good / complete (e.g. an ingested session).
    ok_green: tuple[float, float, float] = (0.1804, 0.6196, 0.2784)
    #: #E69F21 status: partial / attention (e.g. linked but not ingested).
    warn_amber: tuple[float, float, float] = (0.9020, 0.6235, 0.1294)
    #: #8C949E status: not yet / absent (e.g. an un-ingested on-disk session).
    neutral_grey: tuple[float, float, float] = (0.5490, 0.5804, 0.6196)

    # MATLAB-cased aliases, so code written against either convention reads
    # naturally -- the same dual-naming used across this port.
    @property
    def darkBlue(self) -> tuple[float, float, float]:  # noqa: N802
        return self.dark_blue

    @property
    def lightBlue(self) -> tuple[float, float, float]:  # noqa: N802
        return self.light_blue

    @property
    def offWhite(self) -> tuple[float, float, float]:  # noqa: N802
        return self.off_white

    @property
    def okGreen(self) -> tuple[float, float, float]:  # noqa: N802
        return self.ok_green

    @property
    def warnAmber(self) -> tuple[float, float, float]:  # noqa: N802
        return self.warn_amber

    @property
    def neutralGrey(self) -> tuple[float, float, float]:  # noqa: N802
        return self.neutral_grey


_PALETTE = CloudColors()


def cloud_colors() -> CloudColors:
    """Return the NDI Cloud palette.

    A function rather than a bare constant because that is MATLAB's shape
    (``c = ndi.gui.cloudColors()``), and a caller porting code across should
    not have to remember which side needs the parentheses.
    """
    return _PALETTE


#: MATLAB-cased alias.
cloudColors = cloud_colors


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    """Convert a 0..1 triplet to a ``#rrggbb`` string for Qt stylesheets.

    Qt wants hex or 0..255; the palette is stored in MATLAB's 0..1 units.
    Rounding is round-half-away-from-zero on the scaled value, so
    ``0.0314 -> 8`` (0x08) reproduces the documented ``#082051`` exactly
    rather than landing a bit off it.
    """
    vals = []
    for v in rgb:
        scaled = float(v) * 255.0
        vals.append(int(scaled + 0.5) if scaled >= 0 else int(scaled - 0.5))
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, v)) for v in vals))
