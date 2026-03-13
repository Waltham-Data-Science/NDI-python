"""
ndi.app.stimulus.decoder - Stimulus presentation decoder.

Parses stimulus timing and parameters from stimulus elements
into structured stimulus_presentation documents.

MATLAB equivalent: src/ndi/+ndi/+app/+stimulus/decoder.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import App

if TYPE_CHECKING:
    from ...document import Document
    from ...session.session_base import Session


class StimulusDecoder(App):
    """
    App for decoding stimulus presentations.

    Reads raw stimulus data from stimulus probes/elements and
    converts it into structured stimulus_presentation documents
    with timing and parameter information.

    Example:
        >>> decoder = StimulusDecoder(session)
        >>> newdocs, existingdocs = decoder.parse_stimuli(stim_element)
    """

    def __init__(self, session: Session | None = None):
        super().__init__(session=session, name="ndi_app_stimulus_decoder")

    def parse_stimuli(
        self,
        ndi_element_stim: Any,
        reset: bool = False,
    ) -> tuple[list[Document], list[Document]]:
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
        stimulus_presentation_doc: Document,
    ) -> dict[str, Any] | None:
        """
        Load presentation timing from a stimulus_presentation document.

        MATLAB equivalent: ndi.app.stimulus.decoder/load_presentation_time

        Args:
            stimulus_presentation_doc: stimulus_presentation document

        Returns:
            Dict with 'stimon', 'stimoff' timing arrays, or None
        """
        if self._session is None:
            return None
        # Framework method
        return None

    def _clear_presentations(self, ndi_element_stim: Any) -> None:
        """Clear existing stimulus presentation documents."""
        if self._session is None:
            return
        from ...query import Query

        q = Query("").isa("stimulus_presentation")
        if hasattr(ndi_element_stim, "id"):
            q = q & Query("").depends_on("stimulus_element_id", ndi_element_stim.id)
        docs = self._session.database_search(q)
        for doc in docs:
            self._session.database_remove(doc)

    def __repr__(self) -> str:
        return f"StimulusDecoder(session={self._session is not None})"
