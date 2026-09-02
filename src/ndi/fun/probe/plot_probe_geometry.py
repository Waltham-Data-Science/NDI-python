"""ndi.fun.probe.plot_probe_geometry - draw a probe's electrode sites.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+probe/plotProbeGeometry.m``
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = ["plot_probe_geometry", "plotProbeGeometry"]


def plot_probe_geometry(
    pg: Any,
    ax: Any = None,
    marker_size: float = 60,
    contour_color: Any = (0.6, 0.6, 0.6),
    contour_linewidth: float = 1.5,
    show_labels: bool = True,
    labels: Sequence[Any] | None = None,
    label_font_size: float = 7,
    label_color: Any = (0, 0, 0),
) -> dict[str, Any]:
    """Plot the electrode sites of PG, and its body contour when it has one.

    PG is a probe_geometry dict or a probe_geometry document. Sites are coloured
    by ``shank_id``, and numbered 1..N unless LABELS says otherwise -- 1-based
    because a site number is a thing a user reads off a probe's datasheet, not
    an index into a Python list.

    Returns the handles, as MATLAB does: ``sites``, ``contour`` (None when the
    layout has none), ``labels``, ``ax``.
    """
    import matplotlib.pyplot as plt

    from .geometry import _column

    if hasattr(pg, "document_properties"):
        pg = pg.document_properties.get("probe_geometry", {})

    if ax is None:
        ax = plt.gca()

    x = _column(pg.get("site_locations_leftright"))
    y = _column(pg.get("site_locations_depth"))
    shank = _column(pg.get("shank_id"))
    if shank.size == 0:
        shank = [1.0] * len(x)

    handles: dict[str, Any] = {"sites": None, "contour": None, "labels": [], "ax": ax}

    contour_x = _column(pg.get("contour_x"))
    contour_y = _column(pg.get("contour_y"))
    if pg.get("has_planar_contour") and contour_x.size:
        (handles["contour"],) = ax.plot(
            contour_x, contour_y, "-", color=contour_color, linewidth=contour_linewidth
        )

    handles["sites"] = ax.scatter(x, y, s=marker_size, c=shank, edgecolors="k")

    if show_labels:
        site_labels = list(labels) if labels is not None else list(range(1, len(x) + 1))
        for index, (site_x, site_y) in enumerate(zip(x, y)):
            text = str(site_labels[index]) if index < len(site_labels) else ""
            handles["labels"].append(
                ax.text(
                    site_x,
                    site_y,
                    text,
                    horizontalalignment="center",
                    verticalalignment="center",
                    fontsize=label_font_size,
                    color=label_color,
                    clip_on=True,
                )
            )

    unit = pg.get("unit") or "um"
    ax.set_xlabel(f"Left/Right ({unit})")
    ax.set_ylabel(f"Depth ({unit})")

    title = str(pg.get("probe_model") or "") or "Probe Geometry"
    manufacturer = str(pg.get("manufacturer") or "")
    if manufacturer and pg.get("probe_model"):
        title = f"{manufacturer} {title}"
    ax.set_title(title)

    if len(set(map(float, shank))) > 1:
        colorbar = ax.figure.colorbar(handles["sites"], ax=ax)
        colorbar.set_label("Shank ID")

    ax.set_aspect("equal")
    return handles


#: MATLAB's spelling.
plotProbeGeometry = plot_probe_geometry
