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


def _timeref_struct(timeref: Any) -> dict[str, Any]:
    """A time reference as the struct the valid_interval schema stores.

    The fields are MATLAB's ``ndi_timereference_struct``, so a marking
    written here is readable there. A reference that cannot describe itself
    yields the empty struct rather than raising: the marking is still worth
    storing, and :meth:`ndi_app_markgarbage.identifyvalidintervals` treats an
    unresolvable one as "says nothing about this epoch".
    """
    empty = {
        "referent_epochsetname": "",
        "referent_classname": "",
        "clocktypestring": "",
        "epoch": "",
        "session_id": "",
        "time": 0,
    }
    if timeref is None:
        return empty
    try:
        struct = timeref.to_struct()
    except Exception:  # noqa: BLE001 - not a time reference, or one that cannot say
        return empty
    return {
        "referent_epochsetname": str(getattr(struct, "referent_epochsetname", "") or ""),
        "referent_classname": str(getattr(struct, "referent_classname", "") or ""),
        "clocktypestring": str(getattr(struct, "clocktypestring", "") or ""),
        "epoch": str(getattr(struct, "epoch", "") or ""),
        "session_id": str(getattr(struct, "session_id", "") or ""),
        "time": getattr(struct, "time", 0),
    }


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

        The two time references are stored as the STRUCTS the
        ``valid_interval`` document schema defines --
        ``timeref_structt0`` and ``timeref_structt1``, each naming the
        referent, its class, the clock, the epoch and the time. That is
        what :meth:`identifyvalidintervals` rebuilds a live time reference
        from, and what NDI-matlab reads.

        Before this they were stored as ``timeref_t0``/``timeref_t1``
        holding ``str(timeref)`` -- fields the schema does not define,
        holding text nothing can project a time through. A marking written
        that way was unreadable by both languages, so no interval it named
        was ever honoured.

        Returns:
            True if interval was saved successfully
        """
        interval = {
            "timeref_structt0": _timeref_struct(timeref_t0),
            "t0": t0,
            "timeref_structt1": _timeref_struct(timeref_t1),
            "t1": t1,
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

    def loadvalidinterval(
        self, epochset_obj: Any
    ) -> tuple[list[dict[str, Any]], list[ndi_document]]:
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

        Every stored region is projected into TIMEREF's referent and clock
        through the session's syncgraph, and the projections are unioned with
        ``vlt.math.interval_add``, as MATLAB does.

        A region that cannot be projected, or that lands in a different epoch,
        adds NO restriction -- it is not evidence that the data here is bad,
        only that this marking says nothing about here. So the fall-through
        for "nothing projected" is the whole baseline ``[(t0, t1)]``, not the
        empty list: an element with no valid-interval markings at all is
        entirely valid, which is the common case and the one every caller
        depends on.

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element
            timeref: ndi_time_timereference the query interval is expressed in
            t0: Start time of query interval
            t1: End time of query interval

        Returns:
            List of (start, end) tuples, in TIMEREF's time.
        """
        import numpy as np
        from vlt.math.interval_add import interval_add

        baseline = [(float(t0), float(t1))]
        if self._session is None:
            return baseline

        intervals, _ = self.loadvalidinterval(epochset_obj)
        if not intervals:
            return baseline

        explicitly_good = np.zeros((0, 2))
        for region in intervals:
            timeref_0 = self._timeref_from_struct(region.get("timeref_structt0"))
            timeref_1 = self._timeref_from_struct(region.get("timeref_structt1"))
            if timeref_0 is None or timeref_1 is None:
                continue
            try:
                out_0, ref_0, _ = self._session.syncgraph.time_convert(
                    timeref_0, region["t0"], timeref.referent, timeref.clocktype
                )
                out_1, ref_1, _ = self._session.syncgraph.time_convert(
                    timeref_1, region["t1"], timeref.referent, timeref.clocktype
                )
            except Exception:  # noqa: BLE001 - an unprojectable region restricts nothing
                continue
            if out_0 is None or out_1 is None:
                continue
            if getattr(ref_0, "epoch", None) != timeref.epoch:
                continue
            if getattr(ref_1, "epoch", None) != timeref.epoch:
                continue
            explicitly_good = interval_add(explicitly_good, [float(out_0), float(out_1)])

        if len(explicitly_good) == 0:
            return baseline
        return [(float(a), float(b)) for a, b in explicitly_good]

    def _timeref_from_struct(self, struct: Any) -> Any:
        """Rebuild a live time reference from a stored struct, or None.

        MATLAB's ``ndi.time.timereference(session, struct)`` overload, which
        Python spells as :meth:`ndi_time_timereference.from_struct`. None is
        returned for a struct that cannot name its referent or its clock, so
        the caller takes MATLAB's "cannot project" branch rather than raising:
        a marking NDI can no longer resolve must not stop an analysis.
        """
        if not isinstance(struct, dict):
            return None
        if not struct.get("referent_classname") or not struct.get("clocktypestring"):
            return None
        try:
            from ..time.timereference import (
                ndi_time_timereference,
                ndi_time_timereference__struct,
            )

            return ndi_time_timereference.from_struct(
                self._session,
                ndi_time_timereference__struct(
                    referent_epochsetname=struct.get("referent_epochsetname", ""),
                    referent_classname=struct.get("referent_classname", ""),
                    clocktypestring=struct.get("clocktypestring", ""),
                    epoch=struct.get("epoch", ""),
                    session_id=struct.get("session_id", ""),
                    time=struct.get("time", 0),
                ),
            )
        except Exception:  # noqa: BLE001 - a struct nothing can be rebuilt from
            return None

    def __repr__(self) -> str:
        return f"ndi_app_markgarbage(session={self._session is not None})"
