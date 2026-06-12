"""
ndi.app.stimulus.decoder - Stimulus presentation decoder.

Parses stimulus timing and parameters from stimulus elements
into structured stimulus_presentation documents.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/decoder.m
"""

from __future__ import annotations

import warnings
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
    ) -> tuple[list[ndi_document], list[ndi_document]]:
        """
        Parse stimulus presentations from a stimulus element.

        MATLAB equivalent: ndi.app.stimulus.decoder/parse_stimuli

        Args:
            ndi_element_stim: Stimulus element or probe
            reset: If True, clear existing and re-parse

        Returns:
            Tuple of (newdocs, existingdocs) where newdocs are newly
            created documents and existingdocs are pre-existing ones.
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        if reset:
            self._clear_presentations(ndi_element_stim)

        # Framework method - actual parsing depends on stimulus format
        return [], []

    def load_presentation_time(
        self,
        stimulus_presentation_doc: ndi_document,
    ) -> list[dict[str, Any]] | None:
        """
        Load presentation timing from a stimulus_presentation document.

        MATLAB equivalent: ndi.app.stimulus.decoder/load_presentation_time

        MATLAB has two storage forms. The deprecated/inline form keeps the
        ``presentation_time`` list directly on the document
        (``stimulus_presentation.presentation_time``); this is supported here.
        The current form stores it in the binary portion
        (``presentation_time.bin``), read via
        ``database_openbinarydoc`` + ``ndi.database.fun.read_presentation_time_structure``
        (mirrors MATLAB). For an ndic:// (cloud) dataset the file is fetched on
        demand. ``None`` is returned only when neither form is available.

        Args:
            stimulus_presentation_doc: stimulus_presentation document

        Returns:
            List of per-stimulus timing dicts (each with ``onset``, ``offset``,
            ``clocktype``, ``stimevents``), or ``None`` if no timing is
            available (no inline form and no readable ``presentation_time.bin``).
        """
        props = getattr(stimulus_presentation_doc, "document_properties", None)
        if isinstance(props, dict):
            sp = props.get("stimulus_presentation", {})
        else:
            sp = getattr(props, "stimulus_presentation", {})
        if isinstance(sp, dict):
            pt = sp.get("presentation_time")
        else:
            pt = getattr(sp, "presentation_time", None)
        if pt:
            # Deprecated/inline form (MATLAB load_presentation_time first branch).
            return [dict(p) if isinstance(p, dict) else p for p in pt]
        # Current form: timing lives in the binary file presentation_time.bin.
        # Mirrors MATLAB load_presentation_time's else branch:
        #   fobj = session.database_openbinarydoc(doc, 'presentation_time.bin');
        #   [~, presentation_time] = ndi.database.fun.read_presentation_time_structure(...)
        # database_openbinarydoc fetches the file on demand for ndic:// (cloud)
        # datasets and returns an open handle whose .name is the local path.
        if self._session is None:
            return None
        try:
            fobj = self._session.database_openbinarydoc(
                stimulus_presentation_doc, "presentation_time.bin"
            )
        except Exception:  # noqa: BLE001 - no binary available -> blocker (None), as before
            return None
        try:
            from ...database_fun import read_presentation_time_structure

            path = getattr(fobj, "name", None)
            if not isinstance(path, (str, bytes)) and not hasattr(path, "__fspath__"):
                return None
            _header, presentation_time = read_presentation_time_structure(path)
            return presentation_time
        except Exception as exc:  # noqa: BLE001 - unreadable/corrupt binary -> blocker (None)
            warnings.warn(
                f"Could not read presentation_time.bin: {exc}",
                stacklevel=2,
            )
            return None
        finally:
            try:
                self._session.database_closebinarydoc(fobj)
            except Exception:  # noqa: BLE001
                try:
                    fobj.close()
                except Exception:  # noqa: BLE001
                    pass

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
