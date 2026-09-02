"""ndi.app.stimulus.decoder - what was shown, and when.

MATLAB counterpart: ``src/ndi/+ndi/+app/+stimulus/decoder.m``

The first step of the stimulus pipeline. A stimulator probe records, epoch by
epoch, which stimulus was shown and when it went up and came down;
:meth:`parse_stimuli` reads that and writes it as one
``stimulus_presentation`` document per epoch. Everything after it --
``ndi.app.stimulus.tuning_response``, then ``ndi.calc.stimulus.tuningcurve``
-- reads those documents and nothing else, so until this runs there is
nothing in the database to compute a response against.

WHY THE TIMING GOES IN A BINARY FILE
A presentation document holds one entry per stimulus PRESENTATION, and an
experiment can have tens of thousands. Kept inline they would make the
document's JSON enormous and slow to search; kept in ``presentation_time.bin``
the document stays small and the times are read only when a response is
computed. MATLAB moved to this form and left the inline reader in place for
documents written before it, which :meth:`load_presentation_time` still
honours -- with the same warning MATLAB gives.

ONE DOCUMENT PER EPOCH, AND EPOCHS ARE NOT REDONE
An epoch that already has a presentation document is skipped, not rewritten:
parsing is idempotent, so it can be run again after new epochs arrive without
disturbing what is already there or orphaning the responses computed from it.
``reset=True`` is the deliberate opposite, and removes only the documents of
the epochs it is about to redo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
        """Write a ``stimulus_presentation`` document for each stimulus epoch.

        MATLAB equivalent: ``ndi.app.stimulus.decoder/parse_stimuli``.

        For every epoch of NDI_ELEMENT_STIM that does not already have one,
        this reads the epoch's stimulus record and stores what was shown
        (each stimulus's parameters, and the order they were presented in)
        as the document, with the per-presentation timing in an attached
        ``presentation_time.bin``.

        Args:
            ndi_element_stim: the stimulator element or probe.
            reset: remove and rebuild the documents of the epochs this call
                covers. Only those epochs: a reset of one epoch must not
                delete another epoch's work.
            epochids: an epoch id, or a list of them, to limit the call to.
                None means every epoch of the element.

        Returns:
            ``(newdocs, existingdocs)`` -- the documents written now, and
            the ones that were already there. MATLAB's two outputs, in
            MATLAB's order.

        Raises:
            RuntimeError: when the app has no session to write to.
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ...query import ndi_query

        session = self._session
        existing = session.database_search(
            ndi_query("").isa("stimulus_presentation")
            & session.searchquery()
            & ndi_query("").depends_on("stimulus_element_id", ndi_element_stim.id())
        )
        existing_epochs = [self._document_epochid(doc) for doc in existing]

        target_epochs = self._target_epochs(ndi_element_stim, epochids)

        if reset:
            stale = [
                doc
                for doc, epoch in zip(existing, existing_epochs, strict=True)
                if epoch in target_epochs
            ]
            if stale:
                session.database_rm(stale)
            keep = [
                (doc, epoch)
                for doc, epoch in zip(existing, existing_epochs, strict=True)
                if epoch not in target_epochs
            ]
            existing = [doc for doc, _ in keep]
            existing_epochs = [epoch for _, epoch in keep]

        finished = set(existing_epochs)
        remaining = [epoch for epoch in target_epochs if epoch not in finished]

        newdocs: list[ndi_document] = []
        written: list[str] = []
        for epoch in remaining:
            doc, path = self._presentation_document(ndi_element_stim, epoch)
            if doc is not None:
                newdocs.append(doc)
                written.append(path)

        try:
            if newdocs:
                session.database_add(newdocs)
        finally:
            # The database ingests each timing file; whether it removes the
            # original is its business, not this app's. Cleaning up here
            # leaves nothing behind either way -- including when the add
            # raised, which is when a stranded temp file would otherwise be
            # the only trace of the attempt.
            _remove_files(written)
        return newdocs, existing

    def _target_epochs(self, ndi_element_stim: Any, epochids: Any) -> list[str]:
        """The epochs this call covers, in the element's own order.

        An id that names no epoch of this element is dropped rather than
        raising: asking to parse an epoch that is not there has already been
        answered, and the epochs that ARE there should still be parsed.
        """
        try:
            table = ndi_element_stim.epochtable()
        except Exception:  # noqa: BLE001 - an element that cannot list its epochs
            return []
        epochs = [str(entry.get("epoch_id", "")) for entry in _as_list(table)]
        epochs = [epoch for epoch in epochs if epoch]
        if epochids is None:
            return epochs
        wanted = {str(epochids)} if isinstance(epochids, str) else {str(e) for e in epochids}
        return [epoch for epoch in epochs if epoch in wanted]

    def _presentation_document(
        self, ndi_element_stim: Any, epoch: str
    ) -> tuple[ndi_document | None, str]:
        """The ``stimulus_presentation`` document for one epoch, and its file.

        Returns ``(None, "")`` when the epoch holds no stimuli at all -- an
        epoch the stimulator was running through but did not present in.
        Writing an empty document for it would make every later search return
        something with nothing in it.
        """
        import os
        import tempfile

        from ...database_fun import write_presentation_time_structure

        data, t, timeref = ndi_element_stim.readtimeseriesepoch(epoch, float("-inf"), float("inf"))
        if data is None or t is None:
            return None, ""
        stimids = _as_list(data.get("stimid"))
        onsets = _as_list(t.get("stimon"))
        if not stimids or not onsets:
            return None, ""

        stimuli = [{"parameters": parameters} for parameters in _as_list(data.get("parameters"))]
        presentation_time = self._presentation_time(t, timeref)

        handle, path = tempfile.mkstemp(suffix=".bin", prefix="ndi_presentation_time_")
        os.close(handle)
        write_presentation_time_structure(path, presentation_time)

        doc = self._session.newdocument(
            "stimulus_presentation",
            **{
                "stimulus_presentation": {
                    "presentation_order": [int(s) for s in stimids],
                    "stimuli": stimuli,
                },
                "epochid.epochid": str(epoch),
            },
        )
        doc = doc + self.newdocument()
        doc = doc.set_dependency_value(
            "stimulus_element_id", ndi_element_stim.id(), error_if_not_found=False
        )
        doc = doc.add_file("presentation_time.bin", path)
        return doc, path

    @staticmethod
    def _presentation_time(t: dict[str, Any], timeref: Any) -> list[dict[str, Any]]:
        """One timing entry per presentation, in the schema's field order.

        ``stimopen``/``stimclose`` bracket the whole trial and
        ``onset``/``offset`` the stimulus itself; they differ when the
        display was opened before the stimulus began. Both are kept, as
        MATLAB keeps them, because a prestimulus baseline is measured
        against the first and a response against the second.
        """
        import numpy as np

        clocktype = ""
        try:
            clocktype = str(timeref.clocktype)
        except Exception:  # noqa: BLE001 - a reference that will not name its clock
            clocktype = ""

        onsets = np.asarray(_as_list(t.get("stimon")), dtype=float).ravel()
        offsets = np.asarray(_as_list(t.get("stimoff")), dtype=float).ravel()
        openclose = np.atleast_2d(np.asarray(_as_list(t.get("stimopenclose")), dtype=float))
        events = _as_list(t.get("stimevents"))

        entries: list[dict[str, Any]] = []
        for z in range(onsets.size):
            onset = float(onsets[z])
            offset = float(offsets[z]) if z < offsets.size else float("nan")
            if openclose.shape[0] > z and openclose.shape[1] >= 2:
                stimopen, stimclose = float(openclose[z, 0]), float(openclose[z, 1])
            else:
                stimopen, stimclose = onset, offset
            entries.append(
                {
                    "clocktype": clocktype,
                    "stimopen": stimopen,
                    "onset": onset,
                    "offset": offset,
                    "stimclose": stimclose,
                    "stimevents": _events_in_window(events, onset, offset, stimopen, stimclose),
                }
            )
        return entries

    @staticmethod
    def _document_epochid(doc: ndi_document) -> str:
        return str((doc.document_properties.get("epochid", {}) or {}).get("epochid", ""))

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
        """Clear existing stimulus presentation documents."""
        if self._session is None:
            return
        from ...query import ndi_query

        q = ndi_query("").isa("stimulus_presentation")
        if hasattr(ndi_element_stim, "id"):
            q = q & ndi_query("").depends_on("stimulus_element_id", ndi_element_stim.id)
        docs = self._session.database_search(q)
        for doc in docs:
            self._session.database_remove(doc)

    def __repr__(self) -> str:
        return f"ndi_app_stimulus_decoder(session={self._session is not None})"


def _events_in_window(
    events: Any, onset: float, offset: float, stimopen: float, stimclose: float
) -> Any:
    """The events of this trial as an ``(N, 2)`` array of [time, channel].

    Channel numbers are 1-based, as MATLAB stores them: they identify a
    marker channel to a person reading the document, not a Python index.
    The window is the WIDEST of the trial's bounds -- an event can arrive
    before the stimulus is drawn or after it is taken down, and dropping it
    would lose the record of something the rig actually did.
    """
    import numpy as np

    if not events:
        return np.zeros((0, 2))

    start = np.nanmin([onset, stimopen])
    end = np.nanmax([offset, stimclose])
    rows = []
    for channel, times in enumerate(events, start=1):
        times = np.asarray(times, dtype=float).ravel()
        if times.size == 0:
            continue
        inside = times[(times >= start) & (times <= end)]
        if inside.size:
            rows.append(np.column_stack([inside, np.full(inside.size, float(channel))]))
    if not rows:
        return np.zeros((0, 2))
    stacked = np.vstack(rows)
    return stacked[np.argsort(stacked[:, 0])]


def _remove_files(paths: list[str]) -> None:
    """Delete PATHS if they are still there. Missing is the expected case."""
    import os

    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


def _as_list(value: Any) -> list:
    """VALUE as a list, without asking whether it is "truthy".

    Everything a stimulator reports arrives as a NumPy array, and
    ``value or []`` on an array of more than one element raises
    "truth value of an array is ambiguous" -- which is why this exists
    rather than the shorter idiom.
    """
    if value is None:
        return []
    return list(value)
