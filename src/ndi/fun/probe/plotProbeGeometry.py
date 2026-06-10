"""
ndi.fun.probe.plotProbeGeometry - plot a probe geometry.

MATLAB equivalent: +ndi/+fun/+probe/plotProbeGeometry.m

matplotlib is imported lazily inside the function so this module imports cleanly
in environments without matplotlib; the import only fails (with a clear message)
when plotting is actually requested.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def plotProbeGeometry(
    pg: Any,
    *,
    axes: Any | None = None,
    marker_size: float = 60,
    contour_color: tuple[float, float, float] = (0.6, 0.6, 0.6),
    contour_linewidth: float = 1.5,
) -> dict[str, Any]:
    """Plot the electrode site positions and optional body contour of a probe geometry.

    MATLAB equivalent: ``ndi.fun.probe.plotProbeGeometry``

    Args:
        pg: Either a dict with ``probe_geometry`` fields
            (``site_locations_leftright``, ``site_locations_depth``, optional
            ``shank_id``, ``has_planar_contour``, ``contour_x``, ``contour_y``,
            ``unit``, ``probe_model``, ``manufacturer``), or an
            :class:`ndi.document` of class ``probe_geometry``.
        axes: matplotlib Axes to plot into (defaults to the current axes).
        marker_size: Size of the site markers.
        contour_color: RGB color of the body contour.
        contour_linewidth: Line width of the body contour.

    Returns:
        A dict ``h`` of graphics handles with keys ``sites`` (the scatter
        handle), ``contour`` (the contour line handle, or ``None``), and ``ax``
        (the axes handle).

    Raises:
        ImportError: If matplotlib is not installed.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - exercised only without matplotlib
        raise ImportError(
            "ndi.fun.probe.plotProbeGeometry requires matplotlib, which is not "
            "installed. Install matplotlib to plot probe geometry."
        ) from exc

    # extract probe_geometry struct from an ndi.document if needed
    if hasattr(pg, "document_properties"):
        pg = pg.document_properties["probe_geometry"]

    ax = axes if axes is not None else plt.gca()

    x = np.asarray(pg["site_locations_leftright"]).ravel()
    y = np.asarray(pg["site_locations_depth"]).ravel()

    # color by shank_id if available
    shank_id = pg.get("shank_id")
    if shank_id is not None and len(np.atleast_1d(shank_id)) > 0:
        c = np.asarray(shank_id).ravel()
    else:
        c = np.ones_like(x)

    h: dict[str, Any] = {"contour": None}

    # plot contour if available
    if (
        pg.get("has_planar_contour")
        and pg.get("contour_x") is not None
        and len(np.atleast_1d(pg.get("contour_x"))) > 0
    ):
        (h["contour"],) = ax.plot(
            np.asarray(pg["contour_x"]).ravel(),
            np.asarray(pg["contour_y"]).ravel(),
            "-",
            color=contour_color,
            linewidth=contour_linewidth,
        )

    # plot sites
    h["sites"] = ax.scatter(x, y, s=marker_size, c=c, edgecolors="k")

    # labels
    unit_str = pg.get("unit") or "um"
    ax.set_xlabel(f"Left/Right ({unit_str})")
    ax.set_ylabel(f"Depth ({unit_str})")

    title_str = "Probe Geometry"
    if pg.get("probe_model"):
        title_str = pg["probe_model"]
        if pg.get("manufacturer"):
            title_str = f"{pg['manufacturer']} {title_str}"
    ax.set_title(title_str)

    # add shank colorbar if multiple shanks
    if shank_id is not None and len(np.unique(np.asarray(shank_id).ravel())) > 1:
        cb = ax.figure.colorbar(h["sites"], ax=ax)
        cb.set_label("Shank ID")

    ax.set_aspect("equal")
    ax.set_box_aspect(None)
    for spine in ax.spines.values():
        spine.set_visible(True)

    h["ax"] = ax
    return h
