"""gui_v2 — Enhanced NDI session GUI with Experiment and ndi_database views.

Mirrors MATLAB: ndi.gui.gui_v2

Opens a QMainWindow with two tab views:
- **Experiment View** (ndi_gui_Lab): shows subjects, probes, and DAQs as
  draggable icons with connection wires.
- **ndi_database View** (ndi_gui_Data): shows a searchable/filterable document
  table with dependency graph visualisation.
"""

from __future__ import annotations

from typing import Any

from ndi.gui._qt_helpers import get_or_create_app, require_qt


def gui_v2(ndi_session_obj: Any) -> None:
    """Open the enhanced NDI session GUI.

    Parameters
    ----------
    ndi_session_obj : ndi.session.ndi_session
        The session to display.
    """
    require_qt()
    app = get_or_create_app()
    win = _build_v2_window(ndi_session_obj)
    win.show()
    app.exec()


def _build_v2_window(session: Any) -> Any:
    """Construct the enhanced GUI window."""
    from PySide6 import QtWidgets

    class _NDIV2Window(QtWidgets.QMainWindow):
        """Enhanced GUI window with ndi_gui_Lab + ndi_gui_Data tabs."""

        def __init__(self, session: Any) -> None:
            super().__init__()
            self._session = session

            self.setWindowTitle("Neuroscience ndi_gui_Data Interface")
            screen = QtWidgets.QApplication.primaryScreen()
            geom = screen.availableGeometry()
            self.resize(geom.width() // 2, geom.height() // 2)

            # -- Tab widget -----------------------------------------------
            self._tabs = QtWidgets.QTabWidget()
            self.setCentralWidget(self._tabs)

            # Experiment View (ndi_gui_Lab)
            self._lab_widget = QtWidgets.QWidget()
            self._init_lab_tab()
            self._tabs.addTab(self._lab_widget, "Experiment View")

            # ndi_database View (ndi_gui_Data)
            self._data_widget = QtWidgets.QWidget()
            self._init_data_tab()
            self._tabs.addTab(self._data_widget, "ndi_database View")

            # Load data from session
            self._load_session()

        # -- Tab initialisation -------------------------------------------

        def _init_lab_tab(self) -> None:
            from ndi.gui.lab import ndi_gui_Lab

            layout = QtWidgets.QHBoxLayout(self._lab_widget)

            self._lab = ndi_gui_Lab(self._lab_widget)

            left = QtWidgets.QVBoxLayout()
            left.addWidget(self._lab._edit_btn)

            zoom_row = QtWidgets.QHBoxLayout()
            zoom_row.addWidget(self._lab._zoom_in_btn)
            zoom_row.addWidget(self._lab._zoom_out_btn)
            left.addLayout(zoom_row)

            left.addWidget(self._lab.window, stretch=1)
            layout.addLayout(left, stretch=3)
            layout.addWidget(self._lab.panel, stretch=1)

        def _init_data_tab(self) -> None:
            from ndi.gui.data import ndi_gui_Data

            layout = QtWidgets.QHBoxLayout(self._data_widget)

            self._data = ndi_gui_Data(self._data_widget)

            left = QtWidgets.QVBoxLayout()

            # Search controls row
            search_row = QtWidgets.QHBoxLayout()
            for w in self._data.search:
                search_row.addWidget(w)
            left.addLayout(search_row)

            left.addWidget(self._data.table, stretch=1)
            layout.addLayout(left, stretch=3)
            layout.addWidget(self._data.panel, stretch=1)

        # -- ndi_session loading ----------------------------------------------

        def _load_session(self) -> None:
            s = self._session

            try:
                elements = s.getelements() if hasattr(s, "getelements") else []
            except Exception:
                elements = []

            try:
                from ndi.query import ndi_query

                docs = s.database_search(ndi_query("base.id", "regex", "(.*)", ""))
            except Exception:
                docs = []
            if not isinstance(docs, list):
                docs = []

            try:
                daqs = s.daqsystem_load() if hasattr(s, "daqsystem_load") else []
            except Exception:
                daqs = []
            if not isinstance(daqs, list):
                daqs = []

            try:
                probes = s.getprobes() if hasattr(s, "getprobes") else []
            except Exception:
                probes = []
            if not isinstance(probes, list):
                probes = []

            # Gather unique subjects
            subject_ids: list[str] = []
            for p in probes:
                sid = getattr(p, "subject_id", None)
                if sid and sid not in subject_ids:
                    subject_ids.append(sid)
            for e in elements:
                sid = getattr(e, "subject_id", None)
                if sid and sid not in subject_ids:
                    subject_ids.append(sid)

            subjects: list[Any] = []
            for sid in subject_ids:
                try:
                    from ndi.query import ndi_query

                    result = s.database_search(ndi_query("base.id", "exact_string", sid, ""))
                    if result:
                        subjects.append(result)
                except Exception:
                    pass

            # Populate ndi_gui_Lab view
            if subjects:
                self._lab.addSubject(subjects)
            if probes:
                self._lab.addProbe(probes)
            if daqs:
                self._lab.addDAQ(daqs)

            # Populate ndi_gui_Data view
            if docs:
                self._data.addDoc(docs)

    return _NDIV2Window(session)
