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
        Mark a valid time interval (all else in the epoch is garbage).

        MATLAB equivalent: ndi.app.markgarbage/markvalidinterval

        Saves a record marking a valid interval from ``t0`` to ``t1`` with
        respect to ``ndi_time_timereference`` objects ``timeref_t0`` (for ``t0``)
        and ``timeref_t1`` (for ``t1``). The time references are serialized into
        reconstructable structs (``timeref_structt0`` / ``timeref_structt1``,
        matching the ``valid_interval`` document schema) so that
        :meth:`identifyvalidintervals` can later rebuild them and project the
        interval into another time reference.

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element to mark
            t0: Start time of valid interval
            timeref_t0: Time reference (ndi_time_timereference) for t0
            t1: End time of valid interval
            timeref_t1: Time reference (ndi_time_timereference) for t1

        Returns:
            True if interval was saved successfully
        """
        # Mirrors MATLAB: validinterval.timeref_structt0 =
        #   timeref_t0.ndi_timereference_struct(); etc.
        validinterval: dict[str, Any] = {
            "timeref_structt0": self._timeref_to_struct(timeref_t0),
            "t0": t0,
            "timeref_structt1": self._timeref_to_struct(timeref_t1),
            "t1": t1,
        }
        return self.savevalidinterval(epochset_obj, validinterval)

    @staticmethod
    def _timeref_to_struct(timeref: Any) -> dict[str, Any]:
        """
        Serialize a time reference into a reconstructable struct dict.

        Mirrors MATLAB ``ndi.time.timereference/ndi_timereference_struct``. The
        result matches the ``valid_interval`` schema's ``timeref_structt0``
        shape (``referent_epochsetname``, ``referent_classname``,
        ``clocktypestring``, ``epoch``, ``time``) plus ``session_id`` for
        reconstruction.

        Accepts a live ``ndi_time_timereference`` (preferred) or an existing
        struct dict (passed through). Anything else (e.g. a plain string tag or
        a unittest mock) is wrapped in a struct whose reconstruction fields are
        empty, so it keeps the schema's structure shape but is treated as
        non-projectable by :meth:`identifyvalidintervals`.
        """
        if isinstance(timeref, dict):
            return dict(timeref)
        try:
            from ..time.timereference import ndi_time_timereference

            if isinstance(timeref, ndi_time_timereference):
                return dict(timeref.to_dict())
        except Exception:
            pass
        return {
            "referent_epochsetname": str(timeref),
            "referent_classname": "",
            "clocktypestring": "",
            "epoch": "",
            "session_id": "",
            "time": 0,
        }

    def _struct_to_timeref(self, struct: Any) -> Any:
        """
        Rebuild a live ``ndi_time_timereference`` from a stored struct dict.

        Returns ``None`` when the struct is not reconstructable (an opaque tag
        with empty referent/clock fields), so the caller can follow MATLAB's
        empty-projection branch and impose no restriction.
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

            s = ndi_time_timereference__struct(
                referent_epochsetname=struct.get("referent_epochsetname", ""),
                referent_classname=struct.get("referent_classname", ""),
                clocktypestring=struct.get("clocktypestring", ""),
                epoch=struct.get("epoch", ""),
                session_id=struct.get("session_id", ""),
                time=struct.get("time", 0),
            )
            return ndi_time_timereference.from_struct(self._session, s)
        except Exception:
            return None

    def savevalidinterval(
        self,
        epochset_obj: Any,
        interval_struct: dict[str, Any],
    ) -> bool:
        """
        Save a valid-interval struct to the database.

        MATLAB equivalent: ndi.app.markgarbage/savevalidinterval

        Mirrors MATLAB exactly: load the existing array of valid intervals, skip
        (return True) if an identical entry already exists, otherwise append the
        new struct, clear the old document, and store the whole array as the
        single ``valid_interval`` document field. The ``valid_interval`` schema
        field is an ARRAY of structs.

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element
            interval_struct: Dict with ``timeref_structt0``, ``t0``,
                ``timeref_structt1``, ``t1``

        Returns:
            True if interval was saved (or was already present)
        """
        if self._session is None:
            raise RuntimeError("No session configured")

        from ..document import ndi_document

        vi, _ = self.loadvalidinterval(epochset_obj)

        # if we find an exact duplicate, do not save (b is still True)
        for existing in vi:
            if existing == interval_struct:
                return True

        # no match found: append to the array
        vi = list(vi)
        vi.append(interval_struct)

        # save the new array, clearing the old document first (order matters)
        self.clearvalidinterval(epochset_obj)

        doc = ndi_document("apps/markgarbage/valid_interval", valid_interval=vi)
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

        Each ``valid_interval`` document stores an ARRAY of interval structs
        (keys ``timeref_structt0``, ``t0``, ``timeref_structt1``, ``t1``); the
        arrays from all matching documents are concatenated. If nothing is found
        and ``epochset_obj`` is an ``ndi_element`` with an underlying element,
        the underlying element's intervals are returned (MATLAB fallback).

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element

        Returns:
            Tuple of (intervals, docs).
        """
        if self._session is None:
            return [], []

        from ..query import ndi_query

        q = ndi_query("").isa("valid_interval")
        if hasattr(epochset_obj, "id"):
            q = q & ndi_query("").depends_on("element_id", epochset_obj.id)

        docs = self._session.database_search(q)
        intervals: list[dict[str, Any]] = []
        for doc in docs:
            props = doc.document_properties
            if isinstance(props, dict):
                vi = props.get("valid_interval")
            else:
                vi = getattr(props, "valid_interval", None)
            if not vi:
                continue
            # The schema stores an array; a legacy scalar struct is normalized.
            if isinstance(vi, dict):
                intervals.append(vi)
            else:
                for entry in vi:
                    intervals.append(entry if isinstance(entry, dict) else vars(entry))

        # MATLAB underlying_element fallback. MATLAB guards it with
        # isprop(obj,'underlying_element') (a class-level property check); the
        # Python equivalent must be isinstance(ndi_element), NOT a bare getattr,
        # since a duck-typed object (e.g. a unittest MagicMock) auto-creates a
        # fresh truthy 'underlying_element' on every access and would recurse
        # forever.
        if not intervals:
            from ..element import ndi_element

            underlying = getattr(epochset_obj, "underlying_element", None)
            if (
                isinstance(epochset_obj, ndi_element)
                and underlying is not None
                and underlying is not epochset_obj
            ):
                vi_try, docs_try = self.loadvalidinterval(underlying)
                if vi_try:
                    intervals = vi_try
                    docs = docs_try

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

        Examines stored ``valid_interval`` records for ``epochset_obj`` and
        returns the valid sub-intervals within ``[t0, t1]`` expressed with
        respect to ``timeref``. Each stored region is projected into
        ``timeref``'s referent + clock via the session syncgraph; regions that
        cannot be projected, or that land in a different epoch, impose no
        restriction (MATLAB's empty-projection branch). If no region projects,
        the whole baseline ``[(t0, t1)]`` is returned.

        Args:
            epochset_obj: ndi_epoch_epochset or ndi_element
            timeref: ndi_time_timereference for the query interval
            t0: Start time of query interval
            t1: End time of query interval

        Returns:
            List of ``(start, end)`` tuples (times w.r.t. ``timeref``).
        """
        import numpy as np

        baseline_interval: list[tuple[float, float]] = [(t0, t1)]

        vi, _ = self.loadvalidinterval(epochset_obj)
        if not vi:
            return baseline_interval

        explicitly_good = np.empty((0, 2))

        for interval in vi:
            tr0 = self._struct_to_timeref(interval.get("timeref_structt0"))
            tr1 = self._struct_to_timeref(interval.get("timeref_structt1"))
            if tr0 is None or tr1 is None:
                # Non-reconstructable region: add no restriction.
                continue
            try:
                out0, tref0, _ = self._session.syncgraph.time_convert(
                    tr0, interval["t0"], timeref.referent, timeref.clocktype
                )
                out1, tref1, _ = self._session.syncgraph.time_convert(
                    tr1, interval["t1"], timeref.referent, timeref.clocktype
                )
            except Exception:
                continue
            if out0 is None or out1 is None:
                # The region does not project here; add no restriction.
                continue
            if getattr(tref0, "epoch", None) != timeref.epoch or (
                getattr(tref1, "epoch", None) != timeref.epoch
            ):
                # We can find a match but not in the right epoch.
                continue
            explicitly_good = self._interval_add(explicitly_good, [float(out0), float(out1)])

        if explicitly_good.shape[0] == 0:
            return baseline_interval
        return [(float(a), float(b)) for a, b in explicitly_good]

    @staticmethod
    def _interval_add(intervals: Any, new: Any) -> Any:
        """
        Union ``new`` into a sorted, non-overlapping interval set.

        Mirrors the net result of ``vlt.math.interval_add`` (implemented inline
        so the core app does not depend on vlt): the accumulated set stays
        sorted and merged, which is exactly what repeated interval_add produces.
        """
        import numpy as np

        new_arr = np.asarray(new, dtype=float).reshape(1, 2)
        arr = np.vstack([intervals, new_arr]) if intervals.shape[0] else new_arr
        arr = arr[np.argsort(arr[:, 0], kind="stable")]
        merged: list[list[float]] = [list(arr[0])]
        for a, b in arr[1:]:
            if a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([float(a), float(b)])
        return np.asarray(merged, dtype=float)

    def __repr__(self) -> str:
        return f"ndi_app_markgarbage(session={self._session is not None})"
