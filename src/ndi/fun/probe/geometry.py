"""ndi.fun.probe.geometry - a probe's electrode geometry, and the channel maps built from it.

MATLAB counterpart: ``+ndi/+fun/+probe/+geometry/`` (``get.m``,
``toKilosortMap.m``, ``writeKilosortMap.m``, ``listLibrary.m``,
``readLibrary.m``, ``fromStruct.m``, ``fromLibrary.m``, ``plot.m``). MATLAB's
package becomes one module here, as ``+ndi/+fun/+export/`` did in
:mod:`ndi.fun.export`. ``fromKilosortMap``, ``fromProbeInterface`` and
``writeLibrary`` are not ported yet; no Python caller needs them.

THE LIBRARY, AND WHAT A LAYOUT IS
An electrode layout says where a probe's recording sites physically are. NDI
ships a library of them under ``ndi_common/probe/geometry/<group>/<model>.json``
-- :func:`list_library` and :func:`read_library` read it -- and
:func:`from_library` / :func:`from_struct` turn one into the
``probe_geometry`` document that records which layout a particular probe in a
particular session has. That is what the navigator's Electrode Map app
(:mod:`ndi.gui.app.electrode_map`) drives.

SITES ARE NOT CHANNELS, WHICH IS WHY THERE ARE TWO DOCUMENTS
A layout describes electrodes. Which recording channel each site is wired to
depends on the headstage and adapter, not on the electrode, so it lives in a
separate ``site2channelmap`` and is written only when it is known. Some
fixed-headstage layouts ship a default wiring in a ``map`` field, used when
the caller supplies none.

WHAT A CHANNEL MAP HAS TO GET RIGHT
NDI stores geometry per SITE -- where each electrode site sits on the probe
-- while an exported binary is ordered by CHANNEL. The ``site2channelmap``
document bridges them: ``map[i]`` is the recording channel of site ``i``.
:func:`toKilosortMap` inverts that, placing each site's coordinates at its
channel, so that a sorter reading the map alongside the binary sees each
channel at its real position. Get the inversion backwards and nothing
raises: the sort simply merges units that were never neighbours.

CHANNELS ARE 1-BASED HERE
``map``, ``chanMap`` and the ``num_channels`` bounds are 1-based, as in
MATLAB and as ``ndi_xlang_principles`` requires of a user-facing count; only
the array offsets used to place a site are 0-based. A map that looks 0-based
(a minimum of 0 within range) is shifted up by one, as MATLAB does, because
that is what a map imported from a Kilosort file looks like.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "ProbeGeometry",
    "get",
    "library_root",
    "listLibrary",
    "list_library",
    "readLibrary",
    "read_library",
    "fromStruct",
    "from_struct",
    "fromLibrary",
    "from_library",
    "plot",
    "toKilosortMap",
    "to_kilosort_map",
    "writeKilosortMap",
    "write_kilosort_map",
    "DEFAULT_SPACING",
    "HORIZONTAL_AXES",
    "GEOMETRY_DEFAULTS",
    "MATRIX_FIELDS",
    "EMPTY_COLUMN",
]

#: Microns between channels in the default single-column linear layout.
DEFAULT_SPACING = 20.0

#: Which probe axis may be used for the Kilosort x axis. y is always depth.
HORIZONTAL_AXES = ("leftright", "frontback")

#: Every ``probe_geometry`` field, with the default a layout that omits it
#: takes. MATLAB's fromStruct starts from the full set so a document is never
#: written with a field the schema expects missing.
GEOMETRY_DEFAULTS: dict[str, Any] = {
    "site_locations_leftright": [],
    "site_locations_frontback": [],
    "site_locations_depth": [],
    "shank_id": [],
    "contact_shape": "",
    "contact_shape_width": [],
    "contact_shape_height": [],
    "contact_shape_radius": [],
    "probe_model": "",
    "manufacturer": "",
    "ndim": 2,
    "unit": "um",
    "has_planar_contour": 0,
    "contour_x": [],
    "contour_y": [],
}

#: The ``probe_geometry`` fields the schema shapes as an N-element column.
MATRIX_FIELDS = (
    "site_locations_leftright",
    "site_locations_frontback",
    "site_locations_depth",
    "shank_id",
    "contact_shape_width",
    "contact_shape_height",
    "contact_shape_radius",
    "contour_x",
    "contour_y",
)

#: What an empty column looks like INSIDE a document, and nowhere else.
#:
#: The schema shapes these fields [N x 1], and the validator reads an empty
#: Python list as 0x0 and rejects it -- the failure MATLAB avoids by writing
#: zeros(0,1) rather than [] for an absent optional field (a square-contact
#: probe's contact_shape_radius, a layout with no contour). Python has no
#: 0x1; the shape the validator accepts is [[]], read as 1x0 under the same
#: rule that lets a row vector stand for a column. So [[]] goes in via
#: :func:`_document_column` and :func:`_column` reads it back as empty --
#: no caller sees the distinction.
EMPTY_COLUMN: list[list[float]] = [[]]


@dataclass
class ProbeGeometry:
    """What :func:`get` found -- MATLAB's ``G`` struct, field for field.

    A dataclass rather than a dict because the fields are fixed and MATLAB
    reads them by name (``G.found``, ``G.pg``): the same code reads the same
    way on both sides, and a typo is an ``AttributeError`` here rather than
    a silent ``None``.
    """

    #: True when a ``probe_geometry`` document was found.
    found: bool = False
    #: The ``probe_geometry`` property dict (``site_locations_*``,
    #: ``shank_id``, ...), or None.
    pg: dict[str, Any] | None = None
    #: The ``probe_geometry`` document, or None.
    pg_doc: Any = None
    #: The site->channel column of ``site2channelmap``: ``map[i]`` is the
    #: recording channel of site ``i``. None when there is no such document.
    map: np.ndarray | None = None
    #: The ``site2channelmap`` document, or None.
    s2c_doc: Any = None
    #: Every ``probe_geometry`` document found, first one used. Python only,
    #: so a caller can see the ambiguity MATLAB only warns about.
    all_pg_docs: list[Any] = field(default_factory=list)


def get(S: Any, probe: Any, *, verbose: int | bool = 0) -> ProbeGeometry:  # noqa: N803
    """Fetch the geometry documents describing *probe* in session *S*.

    Looks up the ``probe_geometry`` document that depends on the probe and,
    through it, the ``site2channelmap`` that says which channel records each
    site. Returns a :class:`ProbeGeometry`; ``found`` is False, and every
    other field empty, when the probe has no geometry on file.

    *verbose* 0/1 warns when several ``probe_geometry`` documents exist, the
    first of which is used.

    MATLAB equivalent: ``ndi.fun.probe.geometry.get``.
    """
    from ...query import ndi_query
    from ..utils import identifier

    result = ProbeGeometry()

    q_geom = ndi_query("").isa("probe_geometry") & ndi_query("").depends_on(
        "probe_id", identifier(probe)
    )
    geomdocs = S.database_search(q_geom)

    if not geomdocs:
        return result

    if len(geomdocs) > 1 and verbose:
        warnings.warn(
            f"Found {len(geomdocs)} probe_geometry documents for probe "
            f"{probe.elementstring()}; using the first.",
            stacklevel=2,
        )

    result.all_pg_docs = list(geomdocs)
    result.pg_doc = geomdocs[0]
    result.pg = _plain_columns(result.pg_doc.document_properties.get("probe_geometry"))
    result.found = True

    q_s2c = ndi_query("").isa("site2channelmap") & ndi_query("").depends_on(
        "probe_geometry_id", identifier(result.pg_doc)
    )
    s2cdocs = S.database_search(q_s2c)
    if s2cdocs:
        result.s2c_doc = s2cdocs[0]
        raw = result.s2c_doc.document_properties.get("site2channelmap", {}).get("map", [])
        result.map = np.asarray(raw, dtype=float).ravel()

    return result


def library_root() -> Path:
    """The directory the electrode-layout library lives in."""
    from ...common import ndi_common_PathConstants

    return Path(ndi_common_PathConstants.COMMON_FOLDER) / "probe" / "geometry"


def list_library(group: str | None = None) -> list[str]:
    """The electrode layouts NDI ships.

    With no argument, every layout as ``"group/model"``. With *group*, just
    the model names in that group. A group is a subfolder, normally a
    manufacturer: ``neuropixels``, ``neuronexus``, ``ucla``, ``generic``.

    DIVERGENCE: sorted, where MATLAB returns ``dir`` order. The Electrode Map
    app shows this list to a user, and would otherwise order it by whatever
    the filesystem happened to return.

    MATLAB equivalent: ``ndi.fun.probe.geometry.listLibrary``.
    """
    root = library_root()

    if group:
        directory = root / str(group)
        if not directory.is_dir():
            raise ValueError(f"No electrode-layout group '{group}' found in {root}.")
        return sorted(path.stem for path in directory.glob("*.json"))

    if not root.is_dir():
        return []
    names: list[str] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        if directory.name.startswith("."):
            continue
        names.extend(f"{directory.name}/{path.stem}" for path in sorted(directory.glob("*.json")))
    return names


def read_library(name: str) -> tuple[dict[str, Any], str]:
    """Read a named layout, returning ``(geometry, filepath)``.

    *name* is ``"group/model"`` -- an exact layout -- or a bare ``"model"``,
    searched across every group and raising if two groups have it. The
    returned dict's fields are ``probe_geometry`` fields, ready for
    :func:`from_struct`.

    Both outputs are always returned, where MATLAB's second is optional:
    Python has no nargout, and the path is what makes "which one did it
    read?" answerable.

    MATLAB equivalent: ``ndi.fun.probe.geometry.readLibrary``.
    """
    root = library_root()
    name = str(name)

    if "/" in name or "\\" in name:
        filepath = root.joinpath(*name.replace("\\", "/").split("/")).with_suffix(".json")
        if not filepath.is_file():
            raise ValueError(f"Electrode layout '{name}' not found (looked for {filepath}).")
    else:
        matches = sorted(
            directory / f"{name}.json"
            for directory in root.iterdir()
            if directory.is_dir()
            and not directory.name.startswith(".")
            and (directory / f"{name}.json").is_file()
        )
        if not matches:
            raise ValueError(f"Electrode layout '{name}' not found in any group under {root}.")
        if len(matches) > 1:
            raise ValueError(
                f"Electrode layout '{name}' is ambiguous (found in {len(matches)} groups). "
                f"Use 'group/{name}'."
            )
        filepath = matches[0]

    with open(filepath, encoding="utf-8") as handle:
        return json.load(handle), str(filepath)


def from_struct(
    S: Any,  # noqa: N803 (MATLAB mirror)
    probe: Any,
    geom: dict[str, Any],
    *,
    map: Any = None,  # noqa: A002 (MATLAB's option name)
    add: bool = True,
    replace: bool = False,
    check_channels: bool = True,
    verbose: int | bool = 1,
) -> tuple[Any, Any, dict[str, Any]]:
    """Build *probe*'s geometry documents from a ``probe_geometry`` dict.

    Returns ``(pg_doc, s2c_doc, info)``. *geom* must carry non-empty
    ``site_locations_leftright`` and ``site_locations_depth``; every other
    field takes its default from :data:`GEOMETRY_DEFAULTS`.

    *map* (site i -> recording channel) additionally creates the
    ``site2channelmap`` document. *replace* removes any geometry the probe
    already has before adding, so re-assigning replaces rather than stacking
    a second one. *add* writes to the database.

    INFO IS WHY THERE IS A THIRD RETURN VALUE. The site count is checked
    against the probe's epochprobemap channel count, which catches assigning
    a layout meant for a differently-sized probe. MATLAB warns AND returns
    the check, so a GUI can put it in a dialog rather than scraping
    ``lastwarn``. The assignment still succeeds either way: a probe can
    legitimately record a subset of a layout's sites.

    MATLAB equivalent: ``ndi.fun.probe.geometry.fromStruct``.
    """
    from ...document import ndi_document
    from ..utils import identifier

    pg = dict(GEOMETRY_DEFAULTS)
    for field_name in GEOMETRY_DEFAULTS:
        value = geom.get(field_name)
        if value is not None and not (isinstance(value, (list, tuple, str)) and len(value) == 0):
            pg[field_name] = value

    leftright = _column(pg["site_locations_leftright"])
    depth = _column(pg["site_locations_depth"])
    if leftright.size == 0 or depth.size == 0:
        raise ValueError(
            "geom must contain non-empty site_locations_leftright and site_locations_depth."
        )
    n_sites = int(leftright.size)
    if depth.size != n_sites:
        raise ValueError(
            "site_locations_leftright and site_locations_depth must have the same "
            "number of elements."
        )

    if _column(pg["site_locations_frontback"]).size == 0:
        pg["site_locations_frontback"] = [0.0] * n_sites
    if _column(pg["shank_id"]).size == 0:
        pg["shank_id"] = [1.0] * n_sites
    for field_name in MATRIX_FIELDS:
        pg[field_name] = _document_column(pg[field_name])

    info: dict[str, Any] = {
        "n_sites": n_sites,
        "n_channels": None,
        "channel_mismatch": False,
        "message": "",
    }
    if check_channels:
        from .channel_count import channelCount

        n_channels = channelCount(probe)
        info["n_channels"] = n_channels
        if n_channels is not None and n_channels != n_sites:
            info["channel_mismatch"] = True
            info["message"] = (
                f"Electrode geometry has {n_sites} site(s) but the epochprobemap for "
                f"probe {probe.elementstring()} has {n_channels} channel(s); they do "
                f"not match exactly."
            )
            warnings.warn(info["message"], stacklevel=2)

    if add and replace:
        _remove_existing(S, probe)

    pg_doc = ndi_document("probe_geometry", **{"probe_geometry": pg, "base.session_id": S.id()})
    pg_doc = pg_doc.set_dependency_value("probe_id", identifier(probe))

    s2c_doc = None
    site_map = _column(map)
    if site_map.size:
        if site_map.size != n_sites:
            raise ValueError(f"map must have one element per site ({n_sites}).")
        s2c_doc = ndi_document(
            "site2channelmap",
            **{"site2channelmap": {"map": site_map.tolist()}, "base.session_id": S.id()},
        )
        s2c_doc = s2c_doc.set_dependency_value("probe_id", identifier(probe))
        s2c_doc = s2c_doc.set_dependency_value("probe_geometry_id", identifier(pg_doc))

    if add:
        S.database_add(pg_doc)
        if s2c_doc is not None:
            S.database_add(s2c_doc)

    if verbose:
        model = pg["probe_model"] or "(unnamed)"
        action = "Added" if add else "Created"
        extra = " and site2channelmap" if s2c_doc is not None else ""
        print(
            f"{action} probe_geometry ({model}, {n_sites} sites){extra} for probe "
            f"{probe.elementstring()}."
        )

    return pg_doc, s2c_doc, info


def from_library(
    S: Any,  # noqa: N803 (MATLAB mirror)
    probe: Any,
    name: str,
    *,
    map: Any = None,  # noqa: A002 (MATLAB's option name)
    add: bool = True,
    replace: bool = False,
    verbose: int | bool = 1,
) -> tuple[Any, Any, dict[str, Any]]:
    """Attach the library layout *name* to *probe*. See :func:`from_struct`.

    A layout may ship a default site->channel wiring in its ``map`` field. A
    caller-supplied *map* wins; otherwise the shipped default is used.
    ``map`` is not a ``probe_geometry`` field, so it is taken out before the
    document is built.

    MATLAB equivalent: ``ndi.fun.probe.geometry.fromLibrary``.
    """
    geom, _ = read_library(name)
    geom = dict(geom)

    if "map" in geom:
        shipped = geom.pop("map")
        if _column(map).size == 0 and shipped is not None:
            map = shipped  # noqa: A001 (mirrors MATLAB's option)

    return from_struct(S, probe, geom, map=map, add=add, replace=replace, verbose=verbose)


def plot(source: Any, ax: Any = None, title: str = "") -> dict[str, Any]:
    """Plot an electrode layout.

    *source* is a library name, a ``probe_geometry`` dict, or a
    ``probe_geometry`` document. Draws the sites coloured by shank, with the
    body contour when the layout has one, and returns the handles from
    :func:`ndi.fun.probe.plot_probe_geometry.plot_probe_geometry`.

    With no *ax* a new figure is opened, as MATLAB does -- which is the
    Electrode Map app's "Plot geometry" button.

    MATLAB equivalent: ``ndi.fun.probe.geometry.plot``.
    """
    from .plot_probe_geometry import plot_probe_geometry

    label = title
    if isinstance(source, str):
        geom, _ = read_library(source)
        label = label or source
    elif isinstance(source, dict):
        geom = source
        label = label or str(source.get("probe_model", "") or "")
    elif hasattr(source, "document_properties"):
        geom = source.document_properties.get("probe_geometry", {})
        label = label or "probe geometry"
    else:
        raise ValueError(
            "source must be a library name, a probe_geometry dict, or an ndi.document."
        )

    if ax is None:
        import matplotlib.pyplot as plt

        figure = plt.figure()
        figure.canvas.manager.set_window_title(f"Electrode geometry: {label}")
        ax = figure.add_subplot(1, 1, 1)

    handles = plot_probe_geometry(geom, ax=ax)
    if label:
        ax.set_title(label)
    return handles


def _remove_existing(S: Any, probe: Any) -> None:  # noqa: N803 (MATLAB mirror)
    """Remove *probe*'s existing geometry, and any map hanging off it.

    The map goes first: a ``site2channelmap`` depends on the
    ``probe_geometry`` it maps, so removing the geometry first would strand a
    document depending on one that no longer exists.
    """
    from ...query import ndi_query
    from ..utils import identifier

    old_geom = S.database_search(
        ndi_query("").isa("probe_geometry")
        & ndi_query("").depends_on("probe_id", identifier(probe))
    )
    for doc in old_geom:
        old_s2c = S.database_search(
            ndi_query("").isa("site2channelmap")
            & ndi_query("").depends_on("probe_geometry_id", identifier(doc))
        )
        if old_s2c:
            S.database_rm(old_s2c)
    if old_geom:
        S.database_rm(old_geom)


#: MATLAB's spellings.
listLibrary = list_library  # noqa: N816
readLibrary = read_library  # noqa: N816
fromStruct = from_struct  # noqa: N816
fromLibrary = from_library  # noqa: N816


def toKilosortMap(  # noqa: N802 (MATLAB mirror)
    S: Any,  # noqa: N803 (MATLAB mirror)
    probe: Any,
    outputfile: str | Path,
    *,
    num_channels: int | None = None,
    horizontal_axis: str = "leftright",
    verbose: int | bool = 1,
) -> tuple[bool, str]:
    """Build a Kilosort/KIASORT channel map from *probe*'s stored geometry.

    Writes *outputfile* aligned to the channel order of the binary that
    :func:`ndi.fun.probe.export.binary` writes, and returns
    ``(True, outputfile)``.

    Returns ``(False, outputfile)`` AND WRITES NOTHING when the probe has no
    usable geometry -- no ``probe_geometry`` document, no site locations, a
    site count that cannot be aligned to the channels, or a map that places
    no site on any exported channel. Callers fall back to a default map on
    that answer, so "unusable" and "absent" have to be the same answer:
    half-placed geometry would be worse than none.

    *num_channels* defaults to the width of a single sample read from the
    probe. *horizontal_axis* chooses which probe axis becomes the Kilosort x
    axis; y is always depth, matching ``ndi.fun.probe.plotProbeGeometry``.

    MATLAB equivalent: ``ndi.fun.probe.geometry.toKilosortMap``.
    """
    if horizontal_axis not in HORIZONTAL_AXES:
        raise ValueError(
            f"horizontal_axis must be one of {HORIZONTAL_AXES}, got {horizontal_axis!r}"
        )

    outputfile = str(outputfile)

    # Step 1: the probe's geometry documents.
    geometry = get(S, probe, verbose=verbose)
    if not geometry.found or geometry.pg is None:
        if verbose:
            print(f"No probe_geometry document found for probe {probe.elementstring()}.")
        return False, outputfile
    pg = geometry.pg

    # Step 2: how many channels the exported binary has.
    if num_channels is None:
        num_channels = _num_channels_from_probe(probe)
    num_channels = int(num_channels)

    # Step 3: per-site coordinates.
    depth = _column(pg.get("site_locations_depth"))
    horiz = _column(pg.get("site_locations_frontback")) if horizontal_axis == "frontback" else None
    if horiz is None or horiz.size == 0:
        horiz = _column(pg.get("site_locations_leftright"))
    shank = _column(pg.get("shank_id"))

    n_sites = int(min(depth.size, horiz.size))
    if n_sites == 0:
        if verbose:
            print(f"probe_geometry for probe {probe.elementstring()} has no site locations.")
        return False, outputfile

    # Step 4: the site -> channel map.
    site_map = geometry.map
    if site_map is None or site_map.size == 0:
        # No explicit map. Site i -> channel i is the only reading available,
        # and it is only defensible when the counts agree.
        if n_sites != num_channels:
            if verbose:
                warnings.warn(
                    f"No site2channelmap for probe {probe.elementstring()} and site count "
                    f"({n_sites}) != num_channels ({num_channels}); cannot align geometry to "
                    "channels. Falling back to no geometry.",
                    stacklevel=2,
                )
            return False, outputfile
        if verbose:
            warnings.warn(
                f"No site2channelmap for probe {probe.elementstring()}; "
                "assuming site i -> channel i.",
                stacklevel=2,
            )
        site_map = np.arange(1, n_sites + 1, dtype=float)

    site_map = _to_one_based(site_map, num_channels)

    # Step 5: place each site's coordinates at its channel. Channels no site
    # reaches stay at the origin and are marked not connected, which is how a
    # sorter is told to ignore them.
    xcoords = np.zeros(num_channels)
    ycoords = np.zeros(num_channels)
    kcoords = np.ones(num_channels)
    connected = np.zeros(num_channels, dtype=bool)

    for i in range(int(min(n_sites, site_map.size))):
        channel = site_map[i]
        if not np.isfinite(channel) or channel < 1 or channel > num_channels:
            continue  # site not recorded on any exported channel
        index = int(round(float(channel))) - 1
        xcoords[index] = horiz[i]
        ycoords[index] = depth[i]
        if shank.size > i:
            kcoords[index] = shank[i]
        connected[index] = True

    if not connected.any():
        if verbose:
            warnings.warn(
                f"The site2channelmap for probe {probe.elementstring()} did not place any site "
                f"on channels 1..{num_channels}; falling back to no geometry.",
                stacklevel=2,
            )
        return False, outputfile

    # Step 6: write it. Real coordinates, so no default-geometry warning.
    writeKilosortMap(
        outputfile,
        num_channels=num_channels,
        chanMap=np.arange(1, num_channels + 1),
        connected=connected,
        xcoords=xcoords,
        ycoords=ycoords,
        kcoords=kcoords,
        verbose=verbose,
    )

    if verbose:
        print(
            f"Built channel map from probe_geometry for probe {probe.elementstring()} "
            f"({int(connected.sum())} of {num_channels} channels have sites)."
        )

    return True, outputfile


def writeKilosortMap(  # noqa: N802 (MATLAB mirror)
    outputfile: str | Path,
    *,
    num_channels: int | None = None,
    metadataFile: str | Path = "",  # noqa: N803 (MATLAB mirror)
    chanMap: Any = None,  # noqa: N803 (MATLAB mirror)
    connected: Any = None,
    xcoords: Any = None,
    ycoords: Any = None,
    kcoords: Any = None,
    spacing: float = DEFAULT_SPACING,
    verbose: int | bool = 1,
) -> None:
    """Write a channel map ``.mat`` in the Kilosort convention.

    The low-level writer behind :func:`toKilosortMap`; call it directly when
    the coordinate arrays are already in hand, or to write a placeholder map
    from a channel count alone. KIASORT's ``load_channel_map`` reads exactly
    this convention (``chanMap`` / ``chanMap0ind``, ``connected``,
    ``xcoords``, ``ycoords``, ``kcoords``).

    *num_channels* may be omitted if *metadataFile* names a ``.metadata``
    sidecar to read it from, or if one named ``kiasort.bin.metadata`` or
    ``kilosort.bin.metadata`` sits beside *outputfile*.

    With no coordinates supplied a DEFAULT SINGLE-COLUMN LINEAR geometry is
    written -- x all zero, y spaced by *spacing* microns -- and warned
    about. It lets a sorter run; it is not a real array's layout.

    MATLAB equivalent: ``ndi.fun.probe.geometry.writeKilosortMap``.
    """
    from scipy.io import savemat

    outputfile = Path(outputfile)

    if num_channels is None:
        num_channels = _num_channels_from_metadata(outputfile, metadataFile)

    num_channels = float(num_channels)
    if num_channels < 1 or num_channels % 1 != 0:
        raise ValueError("num_channels must be a positive integer.")
    num_channels = int(num_channels)

    # Assemble the fields, defaulting where not supplied.
    default_geometry = xcoords is None and ycoords is None

    chan_map = _column(chanMap) if chanMap is not None else np.arange(1, num_channels + 1)
    chan_map = chan_map.astype(float)
    chan_map_0ind = chan_map - 1

    connected_col = (
        _column(connected).astype(bool)
        if connected is not None
        else np.ones(num_channels, dtype=bool)
    )
    x = _column(xcoords).astype(float) if xcoords is not None else np.zeros(num_channels)
    y = (
        _column(ycoords).astype(float)
        if ycoords is not None
        else np.arange(num_channels, dtype=float) * spacing
    )
    k = _column(kcoords).astype(float) if kcoords is not None else np.ones(num_channels)

    for name, value in (
        ("chanMap", chan_map),
        ("connected", connected_col),
        ("xcoords", x),
        ("ycoords", y),
        ("kcoords", k),
    ):
        if value.size != num_channels:
            raise ValueError(
                "chanMap, connected, xcoords, ycoords, and kcoords must all have "
                f"num_channels ({num_channels}) elements; {name} has {value.size}."
            )

    if default_geometry and verbose:
        warnings.warn(
            "No probe geometry was provided; writing a default single-column linear geometry "
            f"({num_channels} channels, {spacing:g} um spacing). Pass xcoords/ycoords for the "
            "real geometry for best KIASORT results.",
            stacklevel=2,
        )

    outputfile.parent.mkdir(parents=True, exist_ok=True)

    # Column vectors, as MATLAB saves them, so a MATLAB load sees the same
    # shapes it wrote: Kilosort code indexes these as columns.
    savemat(
        str(outputfile),
        {
            "chanMap": chan_map.reshape(-1, 1),
            "chanMap0ind": chan_map_0ind.reshape(-1, 1),
            "connected": connected_col.reshape(-1, 1),
            "xcoords": x.reshape(-1, 1),
            "ycoords": y.reshape(-1, 1),
            "kcoords": k.reshape(-1, 1),
        },
        format="5",
    )

    if verbose:
        print(f"Wrote Kilosort-style channel map ({num_channels} channels) to {outputfile}.")


# ----------------------------------------------------------------------
# module helpers
# ----------------------------------------------------------------------
def _column(value: Any) -> np.ndarray:
    """VALUE as a flat float array; an empty array for None, ``[]`` or ``[[]]``.

    ``[[]]`` is what a document stores for an empty column (see
    :data:`EMPTY_COLUMN`), and ravel() flattens it to the same empty array a
    plain ``[]`` gives -- which is exactly why no caller has to know.
    """
    if value is None:
        return np.zeros(0)
    array = np.asarray(value, dtype=float).ravel()
    return array


def _document_column(value: Any) -> Any:
    """VALUE shaped for a document field: its values, or :data:`EMPTY_COLUMN`."""
    column = _column(value)
    return column.tolist() if column.size else EMPTY_COLUMN


def _plain_columns(pg: Any) -> Any:
    """A ``probe_geometry`` property dict with its matrix fields as lists."""
    if not isinstance(pg, dict):
        return pg
    plain = dict(pg)
    for field_name in MATRIX_FIELDS:
        if field_name in plain:
            plain[field_name] = _column(plain[field_name]).tolist()
    return plain


def _to_one_based(site_map: np.ndarray, num_channels: int) -> np.ndarray:
    """Shift a map that looks 0-based up by one, as MATLAB does.

    A map whose smallest channel is 0 and whose largest fits in
    ``0..num_channels-1`` was written 0-based (imported from a Kilosort
    file, say). Left alone it would place every site one channel low and
    drop the last one.
    """
    valid = site_map[np.isfinite(site_map)]
    if valid.size and valid.min() == 0 and valid.max() <= num_channels - 1:
        return site_map + 1
    return site_map


def _num_channels_from_probe(probe: Any) -> int:
    """The channel count of a single sample read from *probe*."""
    et, _ = probe.epochtable()
    if not et:
        raise ValueError(
            f"Probe {probe.elementstring()} has no epochs; cannot determine num_channels."
        )
    from .export import _epoch_t0_t1

    t0, _t1 = _epoch_t0_t1(et[0])
    data, _t, _ref = probe.readtimeseries(epoch=et[0].get("epoch_id", 1), t0=t0, t1=t0)
    array = np.asarray(data)
    return int(array.shape[1]) if array.ndim == 2 else 1


def _num_channels_from_metadata(outputfile: Path, metadata_file: str | Path) -> int:
    """Read ``num_channels`` from a ``.metadata`` sidecar.

    Named explicitly, or found beside *outputfile* under the names
    :func:`ndi.fun.probe.export.binary` writes.
    """
    from vlt.file import loadStructArray

    metafile = Path(metadata_file) if metadata_file else None
    if metafile is None:
        for candidate in ("kiasort.bin.metadata", "kilosort.bin.metadata"):
            path = outputfile.parent / candidate
            if path.is_file():
                metafile = path
                break

    if metafile is None or not metafile.is_file():
        raise ValueError(
            "num_channels was not provided and no .metadata sidecar was found. "
            "Provide num_channels or metadataFile."
        )

    try:
        meta = loadStructArray(str(metafile))
    except Exception as exc:  # noqa: BLE001 - report the file, not the parser
        raise ValueError(
            f"Could not read the metadata sidecar {metafile} ({exc}). "
            "Pass num_channels explicitly instead."
        ) from exc

    if not meta or "num_channels" not in meta[0]:
        raise ValueError(f"The metadata file {metafile} does not contain a num_channels field.")
    return int(float(meta[0]["num_channels"]))


#: snake_case spellings, the house style for new code.
to_kilosort_map = toKilosortMap
write_kilosort_map = writeKilosortMap
