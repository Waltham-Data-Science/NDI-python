"""gui — Display the contents of an NDI session in a GUI window.

Mirrors MATLAB: ndi.gui.gui

Opens a QMainWindow showing probes/things, DAQ readers, cache, database
documents, and document-property details for a given
:class:`ndi.session.ndi_session`.
"""

from __future__ import annotations

import json
from typing import Any

from ndi.gui._qt_helpers import get_or_create_app, require_qt


def gui(ndi_session_obj: Any) -> None:
    """Open the NDI session GUI.

    Parameters
    ----------
    ndi_session_obj : ndi.session.ndi_session
        The session to display.

    Notes
    -----
    Mirrors MATLAB ``ndi.gui.gui(NDI_SESSION_OBJ)``.
    """
    require_qt()
    app = get_or_create_app()

    win = _build_window(ndi_session_obj)
    win.show()
    app.exec()


def _build_window(session: Any) -> Any:
    """Construct the NDI GUI QMainWindow."""
    from PySide6 import QtCore, QtWidgets

    class _NDIGuiWindow(QtWidgets.QMainWindow):
        """Main NDI GUI window (v1)."""

        def __init__(self, session: Any) -> None:
            super().__init__()
            self._session = session

            ref = getattr(session, "reference", "")
            self.setWindowTitle(f"NDI: {ref}")
            self.resize(1000, 500)

            central = QtWidgets.QWidget()
            self.setCentralWidget(central)
            main_layout = QtWidgets.QVBoxLayout(central)

            # -- Header ---------------------------------------------------
            header = QtWidgets.QLabel("<b style='font-size:18px;'>NDI GUI</b>")
            main_layout.addWidget(header)

            info_layout = QtWidgets.QHBoxLayout()
            path = ""
            if hasattr(session, "getpath"):
                path = session.getpath()
            elif hasattr(session, "path"):
                path = str(session.path)
            info_layout.addWidget(QtWidgets.QLabel(f"Path: {path}"))
            info_layout.addWidget(QtWidgets.QLabel(f"Reference: {ref}"))
            sid = (
                session.id()
                if callable(getattr(session, "id", None))
                else getattr(session, "id", "")
            )
            info_layout.addWidget(QtWidgets.QLabel(f"ID: {sid}"))
            main_layout.addLayout(info_layout)

            # -- Update button --------------------------------------------
            update_btn = QtWidgets.QPushButton("Update")
            update_btn.clicked.connect(self._update_all)
            main_layout.addWidget(update_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

            # -- Body -----------------------------------------------------
            body = QtWidgets.QHBoxLayout()

            # Left column: Probes / Things
            left = QtWidgets.QVBoxLayout()
            left.addWidget(QtWidgets.QLabel("<b>Probes/Things</b>"))
            self._probes_list = QtWidgets.QListWidget()
            left.addWidget(self._probes_list)
            self._things_list = QtWidgets.QListWidget()
            left.addWidget(self._things_list)
            body.addLayout(left, 1)

            # Middle column: DAQ Readers + ndi_cache
            mid = QtWidgets.QVBoxLayout()
            mid.addWidget(QtWidgets.QLabel("<b>DAQ-Readers</b>"))
            self._daq_list = QtWidgets.QListWidget()
            mid.addWidget(self._daq_list)

            mid.addWidget(QtWidgets.QLabel("<b>ndi_cache</b>"))
            self._cache_list = QtWidgets.QListWidget()
            mid.addWidget(self._cache_list)
            body.addLayout(mid, 1)

            # Right column: ndi_database + Doc Properties
            right_layout = QtWidgets.QVBoxLayout()
            right_layout.addWidget(QtWidgets.QLabel("<b>ndi_database</b>"))
            self._db_list = QtWidgets.QListWidget()
            self._db_list.currentRowChanged.connect(self._on_db_select)
            right_layout.addWidget(self._db_list)
            body.addLayout(right_layout, 2)

            props = QtWidgets.QVBoxLayout()
            props.addWidget(QtWidgets.QLabel("<b>ndi_document Properties</b>"))
            self._doc_props = QtWidgets.QTextEdit()
            self._doc_props.setReadOnly(True)
            props.addWidget(self._doc_props)
            body.addLayout(props, 3)

            main_layout.addLayout(body)

            # Internal state
            self._doc_ids: list[str] = []
            self._doc_cache: list[Any] = []

            # Initial population
            self._update_all()

        # -- Slots --------------------------------------------------------

        def _update_all(self) -> None:
            self._update_db_list()
            self._update_daq_list()

        def _update_db_list(self) -> None:
            self._db_list.clear()
            self._doc_ids.clear()
            self._doc_cache.clear()
            try:
                from ndi.query import ndi_query

                doc_list = self._session.database_search(ndi_query.all())
            except Exception:
                doc_list = []

            if not isinstance(doc_list, list):
                doc_list = []

            for doc in doc_list:
                dp = doc.document_properties
                dp_dict = dp if isinstance(dp, dict) else dp.__dict__
                dc = dp_dict.get("document_class", {})
                base = dp_dict.get("base", {})
                class_name = (
                    dc.get("class_name", "")
                    if isinstance(dc, dict)
                    else getattr(dc, "class_name", "")
                )
                name = base.get("name", "") if isinstance(base, dict) else getattr(base, "name", "")
                doc_id = base.get("id", "") if isinstance(base, dict) else getattr(base, "id", "")
                self._db_list.addItem(f"{class_name} | {name}")
                self._doc_ids.append(str(doc_id))
                self._doc_cache.append(doc)

        def _update_daq_list(self) -> None:
            self._daq_list.clear()
            try:
                daq_list = self._session.daqsystem_load()
            except Exception:
                daq_list = []
            if not isinstance(daq_list, list):
                daq_list = []
            for daq in daq_list:
                name = getattr(daq, "name", str(daq))
                self._daq_list.addItem(name)

        def _on_db_select(self, row: int) -> None:
            if row < 0 or row >= len(self._doc_cache):
                return
            doc = self._doc_cache[row]
            dp = doc.document_properties
            try:
                pretty = json.dumps(
                    dp if isinstance(dp, dict) else dp.__dict__,
                    indent=2,
                    default=str,
                )
            except Exception:
                pretty = str(dp)
            self._doc_props.setPlainText(pretty)

    return _NDIGuiWindow(session)
