"""
ndi.app.stimulus.decoder - Stimulus presentation decoder.

Parses stimulus timing and parameters from stimulus elements
into structured stimulus_presentation documents.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/decoder.m
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
