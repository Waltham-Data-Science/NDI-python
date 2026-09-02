"""ndi.element.ensemble - a spiking-neuron ensemble as a timeseries element.

MATLAB counterpart: ``src/ndi/+ndi/+element/ensemble.m``

An ``ndi_element_ensemble`` is an ``ndi_element_timeseries`` (type
``'ensemble'``) built on a probe (its underlying element), representing the
joint spiking activity of the neurons recorded on that probe. Each epoch
stores a marked point process: every spike of every neuron, sorted by time,
with a "mark" saying which neuron fired it.

``readtimeseries`` therefore returns, for a requested window,

    data, times, timeref = obj.readtimeseries(timeref_or_epoch, t0, t1)

where ``times[k]`` is the time of the k-th spike in the window and
``data[k]`` is the 1-BASED column index of the neuron that fired it. The
1-based mark is not a Python slip: it is the stored value, written by MATLAB
and read by both languages, so the on-disk contract stays identical. Convert
at the point of use, not in storage.

Because the data are stored with the standard element-timeseries binary
(VHSB), reads are windowed and times come back in the element's clock
(inherited from the underlying probe).

The mapping from a column index to the actual neuron is stored PER EPOCH --
the set of recorded neurons may change between epochs. Each epoch has an
``ensemble`` document depending on that epoch's ``element_epoch`` document,
listing the neuron element ids (in column order) and their names. Recover the
mapping with ``neuron_ids`` / ``neuron_names`` / ``neurons``; do not read the
document directly.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import numpy as np

from ..element_timeseries import ndi_element_timeseries

#: The file, on the per-epoch ``ensemble`` document, holding the neuron names
#: in column order -- one name per line. Named by the document definition, so
#: it is fixed in both languages.
NEURON_NAMES_FILE = "neuron_names.txt"

#: Default for the map document's ``value_type``, matching MATLAB's default.
DEFAULT_VALUE_TYPE = "spiketimes"


class ndi_element_ensemble(ndi_element_timeseries):
    """A spiking-neuron ensemble stored as a marked point process.

    Construction mirrors MATLAB's two forms:

        obj = ndi_element_ensemble(session, name, reference, underlying)
        obj = ndi_element_ensemble(session=..., document=...)

    In the build form the subject comes from the underlying element, so no
    ``subject_id`` is passed -- MATLAB's constructor warns that it is ignoring
    one, and passing it here would be the same mistake in a language that
    would not warn.
    """

    def __init__(self, *args, **kwargs):
        if len(args) >= 4:
            session, name, reference, underlying = args[:4]
            super().__init__(
                session=session,
                name=name,
                reference=reference,
                type="ensemble",
                underlying_element=underlying,
                direct=False,
                **kwargs,
            )
        elif len(args) == 2:
            # Load form, MATLAB's ndi.element.ensemble(S, DOC_OR_ID). The base
            # takes keywords only, so a positional pass-through would raise
            # TypeError rather than load anything.
            session, document = args
            super().__init__(session=session, document=document, **kwargs)
        elif args:
            raise TypeError(
                "ndi_element_ensemble takes either (session, name, reference, "
                f"underlying) or (session, document); got {len(args)} positional "
                "arguments."
            )
        else:
            super().__init__(**kwargs)

    def ndi_element_class(self) -> str:
        """The MATLAB class name stored in ``element.ndi_element_class``.

        Must be overridden or an ensemble would be written to the database as
        a plain ``ndi.element`` and would load back as one, losing every
        method below. (``ndi_element_timeseries`` and ``ndi_neuron`` had the
        same gap until issue #133; both now override it too.)
        """
        return "ndi.element.ensemble"

    # ------------------------------------------------------------------
    # writing
    # ------------------------------------------------------------------
    def add_ensemble_epoch(
        self,
        epoch_id: str,
        epoch_clock: Any,
        t0_t1: Any,
        neuron_ids: list[str],
        neuron_names: list[str],
        spike_rows: list[Any],
        *,
        value_type: str = DEFAULT_VALUE_TYPE,
        value_description: str = "",
        ensemble_name: str = "",
        add_to_database: bool = True,
    ) -> tuple[Any, Any]:
        """Add one epoch of ensemble activity.

        ``spike_rows[k]`` is the vector of spike times for the neuron whose
        element id is ``neuron_ids[k]`` and whose name is ``neuron_names[k]``.
        The trains are flattened into a single time-sorted marked point
        process and stored with the standard element-timeseries binary; a
        per-epoch ``ensemble`` map document records the ids and names for this
        epoch's columns.

        Returns ``(epoch_document, map_document)``. Both are added to the
        database unless ``add_to_database`` is False, in which case they are
        returned unadded -- built, with their files attached, and with the map
        already depending on the epoch document's id.

        The two documents must land together: the map depends on the epoch
        document, so adding the epoch alone would leave a resolvable epoch
        with no neuron mapping, and adding the map alone would leave a
        dangling dependency.
        """
        if len(neuron_ids) != len(spike_rows) or len(neuron_names) != len(neuron_ids):
            raise ValueError(
                "neuron_ids, neuron_names, and spike_rows must all have the same "
                f"number of elements; got {len(neuron_ids)}, {len(neuron_names)}, "
                f"and {len(spike_rows)}."
            )

        times, colindex = self._flatten_spike_rows(spike_rows)

        # The epoch document is built and its binary attached, but it is NOT
        # added yet: the map document depends on its id, and both are added
        # below so a failure cannot leave one without the other. MATLAB gets
        # the same deferral from asking for a second output.
        _, epoch_doc = self.addepoch(
            epoch_id,
            epoch_clock,
            t0_t1,
            times.reshape(-1, 1),
            colindex.reshape(-1, 1),
            add_to_database=False,
        )

        map_doc = self._build_map_doc(
            epoch_id,
            epoch_clock,
            epoch_doc,
            neuron_ids,
            neuron_names,
            value_type=value_type,
            value_description=value_description,
            ensemble_name=ensemble_name,
        )

        if add_to_database:
            self._session.database_add(epoch_doc)
            self._session.database_add(map_doc)
            # A new epoch was added. Clear the cached epoch table and the
            # cached syncgraph so both rebuild from the database on the next
            # epochtable/readtimeseries; otherwise a read in this same session
            # cannot find the epoch just added.
            self.resetepochtable()
            syncgraph = getattr(self._session, "syncgraph", None)
            if syncgraph is not None and hasattr(syncgraph, "remove_cached_graphinfo"):
                syncgraph.remove_cached_graphinfo()

        return epoch_doc, map_doc

    @staticmethod
    def _flatten_spike_rows(spike_rows: list[Any]) -> tuple[np.ndarray, np.ndarray]:
        """Flatten per-neuron spike trains into a time-sorted marked process.

        Returns ``(times, colindex)`` with ``colindex`` 1-BASED, matching what
        MATLAB writes into the same binary. An empty ensemble, or one whose
        neurons all have no spikes, gives two empty float arrays rather than
        raising -- an epoch with no spikes is a real thing to record.

        The sort is stable, so two neurons spiking at the identical timestamp
        keep their column order in both languages. MATLAB's ``sort`` is stable
        for the same reason, so the stored order matches.
        """
        times_parts: list[np.ndarray] = []
        index_parts: list[np.ndarray] = []
        for k, row in enumerate(spike_rows):
            v = np.asarray(row, dtype=np.float64).ravel()
            times_parts.append(v)
            # 1-based to match the stored MATLAB convention.
            index_parts.append(np.full(v.shape, k + 1, dtype=np.float64))

        if not times_parts:
            return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)

        times = np.concatenate(times_parts)
        colindex = np.concatenate(index_parts)
        order = np.argsort(times, kind="stable")
        return times[order], colindex[order]

    def _build_map_doc(
        self,
        epoch_id: str,
        epoch_clock: Any,
        epoch_doc: Any,
        neuron_ids: list[str],
        neuron_names: list[str],
        *,
        value_type: str,
        value_description: str,
        ensemble_name: str,
    ) -> Any:
        """Build (but do not add) the per-epoch ``ensemble`` map document."""
        from ..document import ndi_document

        # epoch_clock is a LIST of clocktypes (the shape addepoch takes), but
        # the document stores ONE clocktype string. Unwrapping matters: taking
        # str() of the list stored "[<ndi_time_clocktype.DEV_LOCAL_TIME: ...>]"
        # into a queryable field, which no query would ever match.
        clocks = list(epoch_clock) if isinstance(epoch_clock, (list, tuple)) else [epoch_clock]
        if len(clocks) != 1:
            raise ValueError(f"An ensemble epoch stores a single clocktype; got {len(clocks)}.")
        clockname = getattr(clocks[0], "type", None) or str(clocks[0])

        tmpdir = tempfile.mkdtemp(prefix="ndi-ensemble-")
        names_path = os.path.join(tmpdir, NEURON_NAMES_FILE)
        # One name per line, with a trailing newline after the last -- the
        # shape MATLAB writes with fprintf('%s\n', ...) in a loop, and the
        # shape _read_names below expects back.
        with open(names_path, "w", encoding="utf-8") as fh:
            for name in neuron_names:
                fh.write(f"{name}\n")

        doc = ndi_document(
            "ensemble",
            **{
                "ensemble.ensemble_name": ensemble_name,
                "ensemble.value_type": value_type,
                "ensemble.value_description": value_description,
                "ensemble.num_neurons": len(neuron_ids),
                "ensemble.clocktype": clockname,
                "epochid.epochid": epoch_id,
                "app.name": "ndi.element.ensemble",
            },
        )
        doc.set_session_id(self._session.id())
        # These dependencies are declared in the 'ensemble' definition, so a
        # missing one signals a genuine problem -- a wrong definition or a
        # stale definition cache -- rather than something to paper over.
        doc.set_dependency_value("element_id", self.id)
        doc.set_dependency_value("element_epoch_id", epoch_doc.id)
        for nid in neuron_ids:
            doc = doc.add_dependency_value_n("neuron_id", nid)
        return doc.add_file(NEURON_NAMES_FILE, names_path)

    # ------------------------------------------------------------------
    # reading the per-epoch map
    # ------------------------------------------------------------------
    def epoch_ensemble_doc(self, epoch: Any) -> Any:
        """The ``ensemble`` map document for one epoch.

        Raises if none, or more than one, is found: both are real corruption
        of the one-map-per-epoch invariant, and returning the first of several
        would hide it.
        """
        from ..query import ndi_query

        epoch_id = self._resolve_epoch_id(epoch)
        if epoch_id is None:
            raise ValueError(f"Could not resolve {epoch!r} to an epoch of this element.")

        q = (
            ndi_query("").isa("ensemble")
            & ndi_query("").depends_on("element_id", self.id)
            & ndi_query("epochid.epochid", "exact_string", epoch_id, "")
        )
        docs = self._session.database_search(q)
        if not docs:
            raise ValueError(f"No ensemble map document was found for epoch '{epoch_id}'.")
        if len(docs) > 1:
            raise ValueError(
                f"More than one ensemble map document was found for epoch '{epoch_id}'."
            )
        return docs[0]

    def neuron_ids(self, epoch: Any) -> list[str]:
        """The neuron element ids for an epoch, in column order.

        Column index ``i`` of ``readtimeseries`` (1-based, as stored)
        corresponds to ``neuron_ids(epoch)[i - 1]``.
        """
        doc = self.epoch_ensemble_doc(epoch)
        ids = doc.dependency_value_n("neuron_id", error_if_not_found=False)
        return list(ids) if ids else []

    def neuron_names(self, epoch: Any) -> list[str]:
        """The neuron names for an epoch, in column order."""
        from ..database_fun import copydocfile2temp

        doc = self.epoch_ensemble_doc(epoch)
        # Returns (path, path_without_extension); only the first is the file.
        tempfile_path, _ = copydocfile2temp(doc, self._session, NEURON_NAMES_FILE, ".txt")
        try:
            return self._read_names(tempfile_path)
        finally:
            if os.path.exists(tempfile_path):
                os.remove(tempfile_path)

    @staticmethod
    def _read_names(path: str) -> list[str]:
        """Read one name per line, dropping only the final empty line.

        Splits on \\r\\n, \\r or \\n so a file written on either platform reads
        back the same, and drops a single trailing empty entry -- the artifact
        of the trailing newline, not a nameless neuron. An interior blank line
        IS kept: it would mean a neuron whose name is empty, which is a data
        problem to surface rather than silently repair.
        """
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        if not text:
            return []
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines

    def neurons(self, epoch: Any) -> list[Any]:
        """The neuron element objects for an epoch, in column order."""
        from ..database_fun import ndi_document2ndi_object

        return [ndi_document2ndi_object(nid, self._session) for nid in self.neuron_ids(epoch)]

    # ------------------------------------------------------------------
    # export form
    # ------------------------------------------------------------------
    def spike_matrix(self, epoch: Any) -> tuple[Any, list[str]]:
        """Reconstruct the neuron-by-spike sparse matrix for an epoch.

        Returns ``(M, ids)`` where ``M`` is an N-neurons-by-Smax sparse matrix
        with ``M[i, n]`` the time of the n-th spike of neuron ``i``, and
        ``ids`` the neuron element ids for the rows.

        A spike at time exactly 0.0 is invisible in this representation -- a
        sparse matrix cannot distinguish a stored zero from an absent one.
        That limitation is MATLAB's too, and is inherent to the export format
        rather than to this port, so it is preserved rather than papered over;
        use ``readtimeseries`` when exact spike counts matter.
        """
        from scipy.sparse import lil_matrix

        epoch_id = self._resolve_epoch_id(epoch)
        ids = self.neuron_ids(epoch_id)
        n = len(ids)

        data, times, _ = self.readtimeseries(epoch_id, -np.inf, np.inf)
        colindex = np.round(np.asarray(data, dtype=np.float64).ravel()).astype(int)
        times = np.asarray(times, dtype=np.float64).ravel()

        counts = [int(np.sum(colindex == (c + 1))) for c in range(n)]
        smax = max(counts) if counts else 0

        m = lil_matrix((n, max(smax, 1)), dtype=np.float64)
        for c in range(n):
            sc = times[colindex == (c + 1)]
            if sc.size:
                m[c, : sc.size] = sc
        return m.tocsr(), ids

    def __repr__(self) -> str:
        return f"ndi_element_ensemble(name={self.name!r}, reference={self.reference!r})"
