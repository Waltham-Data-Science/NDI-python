"""
ndi.app.markgarbage - Mark valid/invalid time intervals.

Provides the MarkGarbage app for identifying and storing valid
time intervals within recording epochs.

MATLAB equivalent: src/ndi/+ndi/+app/markgarbage.m
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import App

if TYPE_CHECKING:
    from ..session.session_base import Session


class MarkGarbage(App):
    """
    App for marking valid/invalid time intervals in recordings.

    Allows users to identify and store which portions of a recording
    are valid (not "garbage") for analysis.

    Example:
        >>> app = MarkGarbage(session)
        >>> app.markvalidinterval(epochset, 0.5, timeref, 10.0, timeref)
        >>> intervals = app.loadvalidinterval(epochset)
    """

    def __init__(self, session: Session | None = None):
        super().__init__(session=session, name="ndi_app_markgarbage")

    def markvalidinterval(
        self,
        epochset_obj: Any,
        t0: float,
        timeref_t0: Any,
        t1: float,
        timeref_t1: Any,
    ) -> None:
        """
        Mark a valid time interval.

        Args:
            epochset_obj: EpochSet or Element to mark
            t0: Start time of valid interval
            timeref_t0: Time reference for t0
            t1: End time of valid interval
            timeref_t1: Time reference for t1
        """
        interval = {
            "t0": t0,
            "timeref_t0": str(timeref_t0),
            "t1": t1,
            "timeref_t1": str(timeref_t1),
        }
        self.savevalidinterval(epochset_obj, interval)

    def savevalidinterval(
        self,
        epochset_obj: Any,
        interval_struct: dict[str, Any],
    ) -> None:
        """
        Save a valid interval to the database.

        Args:
            epochset_obj: EpochSet or Element
            interval_struct: Dict with t0, timeref_t0, t1, timeref_t1
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ..document import Document

        doc = Document("apps/markgarbage/valid_interval", valid_interval=interval_struct)
        doc = doc.set_session_id(self._session.id())
        if hasattr(epochset_obj, "id"):
            doc = doc.set_dependency_value(
                "element_id",
                epochset_obj.id,
                error_if_not_found=False,
            )
        self._session.database_add(doc)

    def clearvalidinterval(self, epochset_obj: Any) -> None:
        """
        Clear all valid intervals for an epochset.

        Args:
            epochset_obj: EpochSet or Element
        """
        if self._session is None:
            return

        from ..query import Query

        q = Query("").isa("valid_interval")
        if hasattr(epochset_obj, "id"):
            q = q & Query("").depends_on("element_id", epochset_obj.id)

        docs = self._session.database_search(q)
        for doc in docs:
            self._session.database_remove(doc)

    def loadvalidinterval(self, epochset_obj: Any) -> list[dict[str, Any]]:
        """
        Load stored valid intervals.

        Args:
            epochset_obj: EpochSet or Element

        Returns:
            List of interval dicts
        """
        if self._session is None:
            return []

        from ..query import Query

        q = Query("").isa("valid_interval")
        if hasattr(epochset_obj, "id"):
            q = q & Query("").depends_on("element_id", epochset_obj.id)

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
        return intervals

    def __repr__(self) -> str:
        return f"MarkGarbage(session={self._session is not None})"
