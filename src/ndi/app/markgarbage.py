"""
ndi.app.markgarbage - Mark valid/invalid time intervals.

Provides the ndi_app_markgarbage app for identifying and storing valid
time intervals within recording epochs.

MATLAB equivalent: src/ndi/+ndi/+app/markgarbage.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import ndi_app

if TYPE_CHECKING:
    from ..document import ndi_document
    from ..session.session_base import ndi_session


class ndi_app_markgarbage(ndi_app):
    """
    ndi_app for marking valid/invalid time intervals in recordings.

    Allows users to identify and store which portions of a recording
    are valid (not "garbage") for analysis.

    Example:
        >>> app = ndi_app_markgarbage(session)
        >>> app.markvalidinterval(epochset, 0.5, timeref, 10.0, timeref)
        >>> intervals, docs = app.loadvalidinterval(epochset)
    """

    def __init__(self, session: ndi_session | None = None):
        super().__init__(session=session, name="ndi_app_markgarbage")

    def markvalidinterval(
        self,
        epochset_obj: Any,
        t0: float,
        timeref_t0: Any,
        t1: float,
        timeref_t1: Any,
    ) -> bool:
        """
        Mark a valid time interval.

        MATLAB equivalent: ndi.app.markgarbage/markvalidinterval

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element to mark
            t0: Start time of valid interval
            timeref_t0: Time reference for t0
            t1: End time of valid interval
            timeref_t1: Time reference for t1

        Returns:
            True if interval was saved successfully
        """
        interval = {
            "t0": t0,
            "timeref_t0": str(timeref_t0),
            "t1": t1,
            "timeref_t1": str(timeref_t1),
        }
        return self.savevalidinterval(epochset_obj, interval)

    def savevalidinterval(
        self,
        epochset_obj: Any,
        interval_struct: dict[str, Any],
    ) -> bool:
        """
        Save a valid interval to the database.

        MATLAB equivalent: ndi.app.markgarbage/savevalidinterval

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element
            interval_struct: Dict with t0, timeref_t0, t1, timeref_t1

        Returns:
            True if interval was saved successfully
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ..document import ndi_document

        doc = ndi_document("apps/markgarbage/valid_interval", valid_interval=interval_struct)
        doc = doc.set_session_id(self._session.id())
        if hasattr(epochset_obj, "id"):
            doc = doc.set_dependency_value(
                "element_id",
                epochset_obj.id,
                error_if_not_found=False,
            )
        self._session.database_add(doc)
        return True

    def clearvalidinterval(self, epochset_obj: Any) -> None:
        """
        Clear all valid intervals for an epochset.

        MATLAB equivalent: ndi.app.markgarbage/clearvalidinterval

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element
        """
        if self._session is None:
            return

        from ..query import ndi_query

        q = ndi_query("").isa("valid_interval")
        if hasattr(epochset_obj, "id"):
            q = q & ndi_query("").depends_on("element_id", epochset_obj.id)

        docs = self._session.database_search(q)
        for doc in docs:
            self._session.database_remove(doc)

    def loadvalidinterval(self, epochset_obj: Any) -> tuple[list[dict[str, Any]], list[ndi_document]]:
        """
        Load stored valid intervals.

        MATLAB equivalent: ndi.app.markgarbage/loadvalidinterval

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element

        Returns:
            Tuple of (intervals, docs) where intervals is a list of
            interval dicts and docs is the list of matching Documents.
        """
        if self._session is None:
            return [], []

        from ..query import ndi_query

        q = ndi_query("").isa("valid_interval")
        if hasattr(epochset_obj, "id"):
            q = q & ndi_query("").depends_on("element_id", epochset_obj.id)

        docs = self._session.database_search(q)
        intervals = []
        for doc in docs:
            props = doc.document_properties
            if isinstance(props, dict):
                vi = props.get("valid_interval")
            else:
                vi = getattr(props, "valid_interval", None)
            if vi:
                intervals.append(vi if isinstance(vi, dict) else vars(vi))
        return intervals, docs

    def identifyvalidintervals(
        self,
        epochset_obj: Any,
        timeref: Any,
        t0: float,
        t1: float,
    ) -> list[tuple[float, float]]:
        """
        Identify valid regions within an interval.

        MATLAB equivalent: ndi.app.markgarbage/identifyvalidintervals

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element
            timeref: Time reference for the query interval
            t0: Start time of query interval
            t1: End time of query interval

        Returns:
            List of (start, end) tuples representing valid sub-intervals
        """
        raise NotImplementedError(
            "identifyvalidintervals requires time reference conversion infrastructure."
        )

    def __repr__(self) -> str:
        return f"ndi_app_markgarbage(session={self._session is not None})"
