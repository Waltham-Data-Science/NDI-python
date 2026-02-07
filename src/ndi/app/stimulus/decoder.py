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
        >>> docs = decoder.parse_stimuli(stim_element)
    """

    def __init__(self, session: Session | None = None):
        super().__init__(session=session, name="ndi_app_stimulus_decoder")

    def parse_stimuli(
        self,
        stimulus_element: Any,
        reset: bool = False,
    ) -> list[Document]:
        """
        Parse stimulus presentations from a stimulus element.

        Args:
            stimulus_element: Stimulus element or probe
            reset: If True, clear existing and re-parse

        Returns:
            List of stimulus_presentation documents
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        if reset:
            self._clear_presentations(stimulus_element)

        # Framework method - actual parsing depends on stimulus format
        return []

    def load_presentation_time(
        self,
        stim_doc: Document,
    ) -> dict[str, Any] | None:
        """
        Load presentation timing from a stimulus_presentation document.

        Args:
            stim_doc: stimulus_presentation document

        Returns:
            Dict with 'stimon', 'stimoff' timing arrays, or None
        """
        if self._session is None:
            return None
        # Framework method
        return None

    def _clear_presentations(self, stimulus_element: Any) -> None:
        """Clear existing stimulus presentation documents."""
        if self._session is None:
            return
        from ...query import Query

        q = Query("").isa("stimulus_presentation")
        if hasattr(stimulus_element, "id"):
            q = q & Query("").depends_on("stimulus_element_id", stimulus_element.id)
        docs = self._session.database_search(q)
        for doc in docs:
            self._session.database_remove(doc)

    def __repr__(self) -> str:
        return f"StimulusDecoder(session={self._session is not None})"
