"""Pure layout arithmetic for ndi.gui.navigator.

MATLAB counterpart: the private layout methods of
``src/ndi/+ndi/+gui/navigator.m``

THE LAYOUT MODEL: content-driven height, elastic filler panes

    * The panes fill the window top to bottom with no dead space, so the
      bottom pane always hugs the bottom edge.
    * RESIZABLE panes are elastic: they share whatever height is left after
      the fixed panes, floored at their minimum. Dragging the window edge
      therefore grows and shrinks them, not the others.
    * STRUCTURAL actions resize the window: collapsing a pane shrinks the
      window by that pane's body height, expanding grows it.
    * CONTENT changes do not resize the window. The elastic panes shrink to
      make room and the content scrolls once they reach their minimum. This
      is the distinction ``NavPane.set_engaged_quietly`` exists for -- a
      background task starting must not move a window the user did not ask
      to move.

Everything here is arithmetic over pane geometry and a figure height: no Qt,
no window, no display. That is deliberate. The navigator's layout is the part
most likely to be got subtly wrong in a port -- an off-by-one in the padding,
a min that is not applied, a share computed before the fixed panes are
subtracted -- and none of those raise. They just leave a gap at the bottom of
someone's window, or a pane that cannot be dragged smaller than it should be.
So the rules live here where they can be tested exactly, and
``ndi.gui.navigator`` does nothing but apply the results to widgets.

A "pane" here is anything with ``current_height()``, ``min_height``,
``collapsible``, ``engaged`` and ``rendered_height`` -- duck-typed, so the
tests can use small fakes rather than building real widgets.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .pane import HEADER_HEIGHT

__all__ = [
    "PAD",
    "SPACING",
    "GRIP_PIXELS",
    "MIN_WIDTH",
    "MIN_HEIGHT",
    "is_elastic",
    "elastic_mask",
    "first_elastic_index",
    "content_height",
    "figure_height_for_content",
    "min_figure_height",
    "distribute",
    "pane_bottom_edge",
    "toggle_delta",
]

#: Root-grid padding, in pixels, on each of the four sides.
PAD = 6

#: Vertical space between pane rows, in pixels.
SPACING = 4

#: Hit-test tolerance around the resizable pane's lower edge, in pixels.
GRIP_PIXELS = 6

#: Minimum figure width, in pixels.
MIN_WIDTH = 250

#: Initial figure height floor. At run time the height follows the panes --
#: see :func:`min_figure_height` -- so this only constrains construction.
MIN_HEIGHT = 300


def is_elastic(pane: Any) -> bool:
    """True if PANE shares the leftover height.

    A pane is elastic only when it is resizable AND collapsible AND engaged.
    A collapsed pane has no body to stretch, and a pane that never declared
    itself resizable must keep the height it asks for.

    ``resizable`` is read with a default of False because the base pane does
    not define it -- only panes that opt in (the datasets pane) carry it, and
    MATLAB tests the same way with ``isprop``.
    """
    return bool(getattr(pane, "resizable", False) and pane.collapsible and pane.engaged)


def elastic_mask(panes: Sequence[Any]) -> list[bool]:
    """Which panes are elastic, in stack order."""
    return [is_elastic(p) for p in panes]


def first_elastic_index(panes: Sequence[Any]) -> int | None:
    """Index of the first elastic pane, or None. The grip sits on its edge."""
    for i, p in enumerate(panes):
        if is_elastic(p):
            return i
    return None


def content_height(figure_height: float, n_panes: int) -> float:
    """Pixels available to the pane rows inside a figure of that height."""
    return figure_height - 2 * PAD - max(n_panes - 1, 0) * SPACING


def figure_height_for_content(content_sum: float, n_panes: int, floor_height: float) -> float:
    """The figure height that exactly fits CONTENT_SUM pixels of rows."""
    h = content_sum + 2 * PAD + max(n_panes - 1, 0) * SPACING
    return max(h, floor_height)


def min_figure_height(panes: Sequence[Any]) -> float:
    """The smallest figure height that still fits the pane stack.

    A collapsed pane needs only its header; an elastic pane needs its
    minimum; anything else needs the height it currently asks for.

    Purely content-driven: when every collapsible pane is collapsed the
    window shrinks to the stack of headers rather than being held open at a
    fixed floor. That is why this is computed rather than being a constant.
    """
    total = 0.0
    for p in panes:
        if p.collapsible and not p.engaged:
            total += HEADER_HEIGHT
        elif getattr(p, "resizable", False):
            total += p.min_height
        else:
            total += p.current_height()
    return total + 2 * PAD + max(len(panes) - 1, 0) * SPACING


def distribute(panes: Sequence[Any], figure_height: float) -> tuple[list[float], float | None]:
    """Split the window height across the pane rows.

    Returns ``(heights, new_figure_height)``. ``new_figure_height`` is None
    when the window should be left alone, and a number when the window must
    be resized to fit the content exactly.

    Fixed panes take the height they request. Elastic panes share what is
    left, floored at their own minimum -- so an elastic pane never collapses
    below its minimum just because the window is small; the window grows
    instead.

    When NO pane is elastic there is nothing to absorb a mismatch, so the
    window is sized to the content. That is what shrinks the window when the
    last resizable pane is collapsed, and it is why the bottom pane keeps
    hugging the bottom edge.
    """
    n = len(panes)
    want = [float(p.current_height()) for p in panes]
    elastic = elastic_mask(panes)
    new_figure_height: float | None = None

    if any(elastic):
        available = content_height(figure_height, n)
        fixed_sum = sum(w for w, e in zip(want, elastic) if not e)
        leftover = available - fixed_sum
        share = leftover / sum(elastic)
        for i, e in enumerate(elastic):
            if e:
                want[i] = max(share, float(panes[i].min_height))
    else:
        needed = figure_height_for_content(sum(want), n, min_figure_height(panes))
        # The 1px tolerance is MATLAB's: it stops a rounding difference from
        # triggering an endless resize/layout loop.
        if abs(needed - figure_height) > 1:
            new_figure_height = needed

    return want, new_figure_height


def pane_bottom_edge(panes: Sequence[Any], index: int, figure_height: float) -> float:
    """Y of pane INDEX's lower edge, measured from the figure's BOTTOM.

    ``index`` is 0-based here (MATLAB's is 1-based). Uses each pane's
    rendered height where the navigator has recorded one, falling back to
    the height it currently asks for -- the fallback matters before the
    first layout, when nothing has been rendered yet.
    """
    from_top = float(PAD)
    for i in range(index + 1):
        h = panes[i].rendered_height
        if h is None or (isinstance(h, float) and math.isnan(h)):
            h = panes[i].current_height()
        from_top += float(h)
        if i < index:
            from_top += SPACING
    return figure_height - from_top


def toggle_delta(pane: Any) -> float:
    """How much the window height should change for a just-toggled pane.

    Positive when the pane was expanded (its body was added), negative when
    it was collapsed (its body was removed). The collapsed case uses the
    pane's LAST RENDERED height rather than its current one, because by the
    time this is called the pane already reports header-only -- the body it
    lost is only knowable from what was on screen.
    """
    if pane.engaged:
        return float(pane.current_height() - HEADER_HEIGHT)

    previous = pane.rendered_height
    if (
        previous is None
        or (isinstance(previous, float) and math.isnan(previous))
        or previous < HEADER_HEIGHT
    ):
        previous = HEADER_HEIGHT
    return float(HEADER_HEIGHT - previous)
