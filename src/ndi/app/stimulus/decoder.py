"""
ndi.app.stimulus.decoder - Stimulus presentation decoder.

Parses stimulus timing and parameters from stimulus elements
into structured stimulus_presentation documents.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/decoder.m

WHAT A stimulus_presentation DOCUMENT IS FOR
It is the record of what was shown and when: the order stimuli were
presented in, the parameters of each distinct stimulus, and -- in an
attached binary -- the open/onset/offset/close times of every trial.
Everything downstream of a stimulus experiment reads it: the tuning-response
app, ``ndi.fun.export.blech_clust``, the Katz exporter, and the
"what varies / what is constant" panels of
:class:`ndi.gui.app.stimulusDecoder`. Until it exists, none of them can say
anything about the session.

WHY THE TIMES GO IN A FILE
The document's schema still carries a ``presentation_time`` field, and
MATLAB still reads it when an old document has one, but nothing writes it
any more: a run of ten thousand trials would put ten thousand nested structs
inside a JSON document. The times are written to ``presentation_time.bin``
instead, through ``ndi.database_fun.write_presentation_time_structure``, and
read back by :meth:`load_presentation_time`.
"""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, Any

import numpy as np

from ...fun.utils import identifier
from .. import ndi_app

if TYPE_CHECKING:
    from ...document import ndi_document
    from ...session.session_base import ndi_session


class ndi_app_stimulus_decoder(ndi_app):
    """
    ndi_app for decoding stimulus presentations.

    Reads raw stimulus data from stimulus probes/elements and
    converts it into structured stimulus_presentation documents
    with timing and parameter information.

    Example:
        >>> decoder = ndi_app_stimulus_decoder(session)
        >>> newdocs, existingdocs = decoder.parse_stimuli(stim_element)
    """

    def __init__(self, session: ndi_session | None = None):
        super().__init__(session=session, name="ndi_app_stimulus_decoder")

    def parse_stimuli(
        self,
        ndi_element_stim: Any,
        reset: bool = False,
        epochids: str | list[str] | None = None,
    ) -> tuple[list[ndi_document], list[ndi_document]]:
        """
        Write stimulus_presentation documents for a stimulus element's epochs.

        MATLAB equivalent: ndi.app.stimulus.decoder/parse_stimuli

        For each epoch of *ndi_element_stim* that does not already have one,
        reads the epoch's stimulus record and writes a
        ``stimulus_presentation`` document -- with the presentation times in
        an attached ``presentation_time.bin`` -- INTO THE DATABASE. An epoch
        that already has one is left alone and reported in *existingdocs*,
        which is what makes the call safe to repeat over a session that is
        half decoded.

        Args:
            ndi_element_stim: Stimulus element or probe.
            reset: Remove and rebuild the documents of the epochs this call
                operates on. Only those epochs' documents are removed, so
                re-decoding one epoch never costs the others.
            epochids: An epoch id, or a list of them, to restrict the call
                to. None (the default) means every epoch of the element.

        Returns:
            Tuple of (newdocs, existingdocs): the documents written by this
            call, and the ones that already existed and were kept.

        DEVIATION, deliberate: MATLAB's ``intersect``/``setdiff`` sort the
        epoch ids alphabetically, so its documents are written in that
        order; here the element's own epoch-table order is kept. The
        documents are identical either way -- each is keyed by its epoch id
        -- and epoch-table order is the order the caller sees in the GUI.
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ...query import ndi_query

        session = self._session
        element_id = identifier(ndi_element_stim)

        requested = _as_epoch_id_list(epochids)

        existing_docs = session.database_search(
            ndi_query("").isa("stimulus_presentation")
            & ndi_query("").depends_on("stimulus_element_id", element_id)
            & session.searchquery()
        )
        existing_epoch_ids = [_doc_epoch_id(doc) for doc in existing_docs]

        target_epochs = _element_epoch_ids(ndi_element_stim)
        if requested:
            target_epochs = [e for e in target_epochs if e in requested]

        if reset:
            # Only the target epochs' documents go. Removing the element's
            # whole set would silently destroy epochs the caller did not ask
            # about -- and each takes minutes to rebuild.
            doomed = [
                doc
                for doc, epoch in zip(existing_docs, existing_epoch_ids)
                if epoch in target_epochs
            ]
            if doomed:
                session.database_rm(doomed)
            kept = [
                (doc, epoch)
                for doc, epoch in zip(existing_docs, existing_epoch_ids)
                if epoch not in target_epochs
            ]
            existing_docs = [doc for doc, _ in kept]
            existing_epoch_ids = [epoch for _, epoch in kept]

        finished = set(existing_epoch_ids)
        remaining = [epoch for epoch in target_epochs if epoch not in finished]

        newdocs: list[ndi_document] = []
        temp_files: list[str] = []
        try:
            for epoch_id in remaining:
                doc, temp_path = self._presentation_document(ndi_element_stim, epoch_id, element_id)
                newdocs.append(doc)
                temp_files.append(temp_path)

            # The temp files must OUTLIVE the add: add_file only records
            # where the bytes are, and the database copies them in here.
            # Deleting them before this point ingests nothing and leaves a
            # document whose presentation_time.bin cannot be opened -- which
            # nothing notices until something tries to read the times back.
            if newdocs:
                session.database_add(newdocs)
        finally:
            for temp_path in temp_files:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        return newdocs, list(existing_docs)

    def _presentation_document(
        self,
        ndi_element_stim: Any,
        epoch_id: str,
        element_id: str,
    ) -> tuple[ndi_document, str]:
        """Build one epoch's document; returns it and its pending temp file.

        The document is NOT added here, and the temp file holding its
        presentation times is NOT removed here: both are the caller's, which
        is what keeps the file alive until the database has copied it in.
        """
        session = self._session
        data, t, timeref = ndi_element_stim.readtimeseriesepoch(
            epoch_id, float("-inf"), float("inf")
        )
        data = data or {}
        t = t or {}

        stimuli = [{"parameters": p} for p in data.get("parameters", [])]
        presentation_time = _presentation_time(t, timeref)

        from ...database_fun import write_presentation_time_structure

        handle, temp_path = tempfile.mkstemp(suffix=".bin", prefix="presentation_time_")
        os.close(handle)
        write_presentation_time_structure(temp_path, presentation_time)

        doc = session.newdocument(
            "stimulus_presentation",
            **{
                "stimulus_presentation": {
                    "presentation_order": _presentation_order(data),
                    "stimuli": stimuli,
                },
                "epochid.epochid": epoch_id,
            },
        )
        doc = doc + self.newdocument()
        doc = doc.set_dependency_value("stimulus_element_id", element_id)
        doc = doc.add_file("presentation_time.bin", temp_path)
        return doc, temp_path

    def load_presentation_time(
        self,
        stimulus_presentation_doc: ndi_document,
    ) -> list[dict[str, Any]]:
        """
        Load presentation timing from a stimulus_presentation document.

        MATLAB equivalent: ndi.app.stimulus.decoder/load_presentation_time

        Returns a list with one entry per trial, each carrying at least
        ``onset``, ``offset`` and ``clocktype``. This was previously a stub
        that returned None and documented a ``{'stimon', 'stimoff'}`` dict
        that nothing produced; the real shape is the per-trial list MATLAB
        returns, and the binary reader for it already existed in
        ``ndi.database_fun.read_presentation_time_structure``.

        Args:
            stimulus_presentation_doc: stimulus_presentation document

        Returns:
            A list of per-trial timing dicts (empty if there is no session).
        """
        import warnings

        from ...database_fun import read_presentation_time_structure

        if self._session is None:
            return []

        props = getattr(stimulus_presentation_doc, "document_properties", {}) or {}
        sp = props.get("stimulus_presentation", {}) or {}
        if "presentation_time" in sp:
            # The deprecated in-document form. Still read, still warned about,
            # exactly as MATLAB does -- old documents remain loadable.
            warnings.warn(
                "stimulus presentation document uses deprecated form of "
                "presentation_time storage.",
                stacklevel=2,
            )
            return list(sp["presentation_time"])

        fobj = self._session.database_openbinarydoc(
            stimulus_presentation_doc, "presentation_time.bin"
        )
        try:
            _, presentation_time = read_presentation_time_structure(
                getattr(fobj, "fullpathfilename", fobj)
            )
        finally:
            self._session.database_closebinarydoc(fobj)
        return presentation_time

    def _clear_presentations(self, ndi_element_stim: Any) -> None:
        """Remove every stimulus_presentation document of an element.

        The whole-element form. :meth:`parse_stimuli` does NOT use it -- a
        reset there removes only the epochs it was asked about -- so this
        stays for a caller that genuinely wants the element wiped.

        Two things were wrong here and are fixed: ``id`` was read as an
        attribute rather than called, so the query filtered on a bound
        method and matched nothing, and removal called ``database_remove``,
        which no session has. Between them the method removed nothing at all
        while appearing to succeed.
        """
        if self._session is None:
            return
        from ...query import ndi_query

        q = ndi_query("").isa("stimulus_presentation")
        element_id = identifier(ndi_element_stim)
        if element_id is not None:
            q = q & ndi_query("").depends_on("stimulus_element_id", element_id)
        docs = self._session.database_search(q)
        if docs:
            self._session.database_rm(docs)

    def __repr__(self) -> str:
        return f"ndi_app_stimulus_decoder(session={self._session is not None})"


# ----------------------------------------------------------------------
# module helpers
# ----------------------------------------------------------------------


def _as_epoch_id_list(epochids: Any) -> list[str]:
    """Normalise the epochids argument to a list. None or "" means "all"."""
    if epochids is None:
        return []
    if isinstance(epochids, str):
        return [epochids] if epochids else []
    return [str(e) for e in epochids]


def _element_epoch_ids(element: Any) -> list[str]:
    """The element's epoch ids, in epoch-table order."""
    result = element.epochtable()
    et = result[0] if isinstance(result, tuple) else result
    ids = []
    for entry in et or []:
        epoch_id = entry.get("epoch_id") if isinstance(entry, dict) else entry.epoch_id
        if epoch_id is not None:
            ids.append(epoch_id)
    return ids


def _doc_epoch_id(doc: Any) -> str | None:
    """The epoch a stimulus_presentation document belongs to, or None.

    A document with no readable epochid cannot be matched to an epoch, so it
    is neither counted as finished nor removed on a reset -- MATLAB's
    ``try``/``continue`` around the same read.
    """
    try:
        return doc.document_properties["epochid"]["epochid"]
    except Exception:  # noqa: BLE001 - an unreadable epochid matches nothing
        return None


def _presentation_order(data: dict[str, Any]) -> list[int]:
    """The stimulus id shown on each trial, as a plain list of ints."""
    stimid = data.get("stimid", [])
    return [int(v) for v in np.asarray(stimid).ravel().tolist()]


def _presentation_time(t: dict[str, Any], timeref: Any) -> list[dict[str, Any]]:
    """One timing entry per trial, in presentation order.

    Each entry carries the clock the times are in, the four times that
    bracket the trial (stimulus opened, came on, went off, closed), and any
    stimulus events that fall inside that bracket.
    """
    clocktype = _clocktype_string(timeref)
    stimon = np.asarray(t.get("stimon", []), dtype=float).ravel()
    stimoff = np.asarray(t.get("stimoff", []), dtype=float).ravel()
    openclose = np.asarray(t.get("stimopenclose", []), dtype=float)
    if openclose.size and openclose.ndim == 1:
        openclose = openclose.reshape(-1, 2)

    entries: list[dict[str, Any]] = []
    for index in range(stimon.size):
        onset = float(stimon[index])
        offset = float(stimoff[index]) if index < stimoff.size else float("nan")
        stimopen = float(openclose[index, 0]) if index < len(openclose) else float("nan")
        stimclose = float(openclose[index, 1]) if index < len(openclose) else float("nan")
        entries.append(
            {
                "clocktype": clocktype,
                "stimopen": stimopen,
                "onset": onset,
                "offset": offset,
                "stimclose": stimclose,
                "stimevents": _stimevents_in_window(
                    t.get("stimevents"), onset, offset, stimopen, stimclose
                ),
            }
        )
    return entries


def _stimevents_in_window(
    stimevents: Any,
    onset: float,
    offset: float,
    stimopen: float,
    stimclose: float,
) -> np.ndarray:
    """The events falling inside one trial, as an Nx2 ``[time, channel]`` array.

    The window is the WIDEST bracket the trial offers -- ``nanmin`` of onset
    and stimopen to ``nanmax`` of offset and stimclose -- because a stimulus
    computer's open/close marks and its on/off marks do not always nest the
    way you would expect, and an event dropped here is a spike time lost
    from the record. Rows come back sorted by time across channels, as
    MATLAB sorts them.
    """
    if not stimevents:
        return np.empty((0, 2), dtype=float)

    opens = [v for v in (onset, stimopen) if np.isfinite(v)]
    closes = [v for v in (offset, stimclose) if np.isfinite(v)]
    if not opens or not closes:
        # A trial with no usable bracket keeps nothing. Reaching for
        # nanmin of all-NaN would only warn its way to the same answer.
        return np.empty((0, 2), dtype=float)
    start, stop = min(opens), max(closes)

    rows: list[np.ndarray] = []
    for channel_index, times in enumerate(stimevents):
        values = np.asarray(times, dtype=float).ravel()
        if values.size == 0:
            continue
        inside = values[(values >= start) & (values <= stop)]
        if inside.size == 0:
            continue
        # Channels are 1-based, as MATLAB numbers them and as the reader of
        # this file expects.
        channel = np.full(inside.size, channel_index + 1, dtype=float)
        rows.append(np.column_stack((inside, channel)))

    if not rows:
        return np.empty((0, 2), dtype=float)
    events = np.vstack(rows)
    return events[np.argsort(events[:, 0], kind="stable")]


def _clocktype_string(timeref: Any) -> str:
    """The clock the trial times are kept in, as the file records it.

    MATLAB's ``timeref.clocktype.ndi_clocktype2char()``; here the enum's own
    string. A time reference that cannot name its clock yields "", which the
    reader treats as unknown rather than misreporting a clock.
    """
    clocktype = getattr(timeref, "clocktype", None)
    if clocktype is None:
        return ""
    return str(clocktype)
