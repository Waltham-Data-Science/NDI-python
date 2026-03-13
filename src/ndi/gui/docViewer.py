"""docViewer — Standalone NDI document viewer window.

Mirrors MATLAB: ndi.gui.docViewer

A self-contained window with a document table, detail panel, search/filter
controls, and dependency-graph visualisation.
"""

from __future__ import annotations

import json
from typing import Any

from ndi.gui._qt_helpers import get_or_create_app, require_qt

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    pass


class docViewer:
    """Standalone document viewer window.

    Opens its own :class:`QMainWindow`.  Populate it with :meth:`addDoc`.
    """

    def __init__(self) -> None:
        require_qt()
        self._app = get_or_create_app()

        self.fullDocuments: list[Any] = []
        self.fullTable: list[list[str]] = []
        self.tempDocuments: list[Any] = []
        self.tempTable: list[list[str]] = []
        self.docs: list[Any] = []

        self.fig = QtWidgets.QMainWindow()
        self.fig.setWindowTitle("Document Viewer")
        self.fig.resize(900, 600)

        central = QtWidgets.QWidget()
        self.fig.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        # -- Search bar ---------------------------------------------------
        search_layout = QtWidgets.QHBoxLayout()
        self._search_col = QtWidgets.QComboBox()
        self._search_col.addItems(["Select", "Name", "ID", "Type", "Date", "Other"])
        search_layout.addWidget(self._search_col)

        self._search_op = QtWidgets.QComboBox()
        self._search_op.addItems(["Filter options", "contains", "begins with", "ends with"])
        search_layout.addWidget(self._search_op)

        self._search_text = QtWidgets.QLineEdit()
        search_layout.addWidget(self._search_text)

        btn_field = QtWidgets.QPushButton("Search field name")
        btn_field.clicked.connect(lambda: self.searchFieldName())
        search_layout.addWidget(btn_field)

        btn_filter = QtWidgets.QPushButton("Search by filter")
        btn_filter.clicked.connect(self.filter)
        search_layout.addWidget(btn_filter)

        btn_clear = QtWidgets.QPushButton("Clear table")
        btn_clear.clicked.connect(self.clearView)
        search_layout.addWidget(btn_clear)

        btn_restore = QtWidgets.QPushButton("Restore")
        btn_restore.clicked.connect(self.restore)
        search_layout.addWidget(btn_restore)

        main_layout.addLayout(search_layout)

        self.search = [
            self._search_col,
            self._search_op,
            self._search_text,
        ]

        # -- Body (table + panel) -----------------------------------------
        body = QtWidgets.QSplitter()

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "ID", "Type", "Date"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._on_cell_clicked)
        body.addWidget(self.table)

        self.panel = QtWidgets.QFrame()
        self.panel.setStyleSheet("background-color: white;")
        panel_layout = QtWidgets.QVBoxLayout(self.panel)
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet("font-weight: bold;")
        panel_layout.addWidget(self._name_label)
        self._detail_list = QtWidgets.QTextEdit()
        self._detail_list.setReadOnly(True)
        panel_layout.addWidget(self._detail_list)

        btn_row = QtWidgets.QHBoxLayout()
        self._graph_btn = QtWidgets.QPushButton("Graph")
        self._graph_btn.clicked.connect(self._on_graph)
        btn_row.addWidget(self._graph_btn)
        self._subgraph_btn = QtWidgets.QPushButton("Subgraph")
        self._subgraph_btn.clicked.connect(self._on_subgraph)
        btn_row.addWidget(self._subgraph_btn)
        panel_layout.addLayout(btn_row)

        body.addWidget(self.panel)
        body.setSizes([500, 350])
        main_layout.addWidget(body)

        self.info: list[Any] = []
        self._selected_row: int | None = None

        self.fig.show()

    # -- Public API -------------------------------------------------------

    def addDoc(self, docs: list[Any]) -> None:
        """Populate the viewer from a list of NDI documents."""
        self.docs = docs
        for doc in docs:
            dp = doc.document_properties
            dp_dict = dp if isinstance(dp, dict) else dp.__dict__
            nd = dp_dict.get("ndi_document", dp_dict)
            name = nd.get("name", "") if isinstance(nd, dict) else getattr(nd, "name", "")
            doc_id = nd.get("id", "") if isinstance(nd, dict) else getattr(nd, "id", "")
            doc_type = nd.get("type", "") if isinstance(nd, dict) else getattr(nd, "type", "")
            datestamp = (
                nd.get("datestamp", "") if isinstance(nd, dict) else getattr(nd, "datestamp", "")
            )
            self.fullTable.append([str(name), str(doc_id), str(doc_type), str(datestamp)])

        self.fullDocuments = list(docs)
        self.tempTable = list(self.fullTable)
        self.tempDocuments = list(self.fullDocuments)
        self._refresh_table()

    def details(self, row_index: int) -> None:
        """Show details for the selected row."""
        if row_index < 0 or row_index >= len(self.tempTable):
            return
        row = self.tempTable[row_index]
        doc = self.tempDocuments[row_index]
        dp = doc.document_properties
        json_details = json.dumps(
            dp if isinstance(dp, dict) else dp.__dict__,
            indent=2,
            default=str,
        )
        self._name_label.setText(f"Name: {row[0]}")
        info = [
            f"Type: {row[2]}",
            f"Date: {row[3]}",
            f"ID: {row[1]}",
            "",
            "Content:",
            json_details,
        ]
        self._detail_list.setPlainText("\n".join(info))
        self._selected_row = row_index

    def filter(self) -> None:
        """Filter the table based on current search controls."""
        col_idx = self._search_col.currentIndex() - 1
        op_idx = self._search_op.currentIndex()
        needle = self._search_text.text().lower()

        if col_idx < 0 or col_idx > 3 or op_idx < 1:
            return
        if not needle:
            return

        self.tempTable = []
        self.tempDocuments = []
        for i, row in enumerate(self.fullTable):
            val = row[col_idx].lower()
            match = False
            if op_idx == 1:
                match = needle in val
            elif op_idx == 2:
                match = val.startswith(needle)
            elif op_idx == 3:
                match = val.endswith(needle)
            if match:
                self.tempTable.append(row)
                self.tempDocuments.append(self.fullDocuments[i])

        self._refresh_table()

    def filterHelper(self, search1: int, search2: int, searchStr: str) -> None:
        """Programmatic filter interface.

        Parameters
        ----------
        search1 : int
            Column combo-box index.
        search2 : int
            Operation combo-box index.
        searchStr : str
            Search string.
        """
        self._search_col.setCurrentIndex(search1)
        self._search_op.setCurrentIndex(search2)
        self._search_text.setText(searchStr)
        self.filter()

    def searchID(self, list_ID: list[str]) -> None:
        """Filter to show only documents whose IDs contain entries in *list_ID*."""
        self.tempTable = []
        self.tempDocuments = []
        for doc_id in list_ID:
            for i, row in enumerate(self.fullTable):
                if doc_id.lower() in row[1].lower():
                    self.tempTable.append(row)
                    self.tempDocuments.append(self.fullDocuments[i])
        self._refresh_table()

    def contentSearch(self, fieldValue: str) -> None:
        """Search document content by field value.

        Prompts for a field name, then filters documents whose nested
        fields contain *fieldValue*.
        """
        fieldName, ok = QtWidgets.QInputDialog.getText(
            self.fig.centralWidget(),
            "Advanced search",
            "Field name:",
        )
        if not ok or not fieldName:
            return

        fieldName = fieldName.lower()
        fieldValue = fieldValue.lower()
        self.tempTable = []
        self.tempDocuments = []
        for i, doc in enumerate(self.docs):
            dp = doc.document_properties
            dp_dict = dp if isinstance(dp, dict) else dp.__dict__
            if self._field_contains(dp_dict, fieldName, fieldValue):
                self.tempTable.append(self.fullTable[i])
                self.tempDocuments.append(self.fullDocuments[i])
        self._refresh_table()

    def searchFieldName(self, fieldName: str | None = None) -> None:
        """Filter to documents that have a given field name.

        Parameters
        ----------
        fieldName : str | None
            If ``None``, prompts the user with an input dialog.
        """
        if fieldName is None:
            fieldName, ok = QtWidgets.QInputDialog.getText(
                self.fig.centralWidget(),
                "Search field name",
                "Field name:",
            )
            if not ok or not fieldName:
                return

        fieldName = fieldName.lower()
        self.tempTable = []
        self.tempDocuments = []
        for i, doc in enumerate(self.docs):
            dp = doc.document_properties
            dp_dict = dp if isinstance(dp, dict) else dp.__dict__
            if self._has_field(dp_dict, fieldName):
                self.tempTable.append(self.fullTable[i])
                self.tempDocuments.append(self.fullDocuments[i])
        self._refresh_table()

    def clearView(self) -> None:
        """Clear the table display."""
        self.table.setRowCount(0)

    def restore(self) -> None:
        """Restore the full unfiltered table."""
        self.tempTable = list(self.fullTable)
        self.tempDocuments = list(self.fullDocuments)
        self._refresh_table()

    def graph(self, ind: int) -> None:
        """Show the full dependency graph with *ind* highlighted."""
        self._show_graph(ind, subgraph=False)

    def subgraph(self, ind: int) -> None:
        """Show the subgraph centred on node *ind*."""
        self._show_graph(ind, subgraph=True)

    # -- Private ----------------------------------------------------------

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        self.details(row)

    def _on_graph(self) -> None:
        if self._selected_row is not None:
            self.graph(self._selected_row)

    def _on_subgraph(self) -> None:
        if self._selected_row is not None:
            self.subgraph(self._selected_row)

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self.tempTable))
        for r, row in enumerate(self.tempTable):
            for c in range(4):
                item = QtWidgets.QTableWidgetItem(row[c])
                item.setFlags(
                    QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled
                )
                self.table.setItem(r, c, item)

    def _show_graph(self, ind: int, *, subgraph: bool) -> None:
        try:
            import matplotlib.pyplot as plt
            import networkx as nx
        except ImportError:
            QtWidgets.QMessageBox.warning(
                None,
                "Missing dependency",
                "networkx and matplotlib are required for graph display.\n"
                "Install them with: pip install networkx matplotlib",
            )
            return

        # Map temp index → full index
        doc = self.tempDocuments[ind]
        full_ind = next(
            (i for i, fd in enumerate(self.fullDocuments) if fd is doc),
            ind,
        )

        edges: list[tuple[int, int]] = []
        for i, fd in enumerate(self.fullDocuments):
            dp = fd.document_properties
            dp_dict = dp if isinstance(dp, dict) else dp.__dict__
            depends = dp_dict.get("depends_on", [])
            if isinstance(depends, list):
                for dep in depends:
                    dep_val = (
                        dep.get("value", "") if isinstance(dep, dict) else getattr(dep, "value", "")
                    )
                    for k, fd2 in enumerate(self.fullDocuments):
                        dp2 = fd2.document_properties
                        nd2 = (
                            dp2.get("ndi_document", dp2)
                            if isinstance(dp2, dict)
                            else getattr(dp2, "ndi_document", dp2)
                        )
                        base_id = (
                            nd2.get("id", "") if isinstance(nd2, dict) else getattr(nd2, "id", "")
                        )
                        if base_id == dep_val:
                            edges.append((i, k))

        G = nx.DiGraph(edges)
        if subgraph:
            neighbors = set(G.predecessors(full_ind)) | set(G.successors(full_ind))
            neighbors.add(full_ind)
            G = G.subgraph(neighbors).copy()

        fig, ax = plt.subplots(figsize=(6, 6))
        if len(G.nodes) > 0:
            pos = nx.spring_layout(G)
            colors = ["red" if n == full_ind else "#4472C4" for n in G.nodes]
            nx.draw(
                G,
                pos,
                ax=ax,
                with_labels=True,
                node_color=colors,
                node_size=300,
                font_size=8,
                arrows=True,
            )
        ax.set_title("Subgraph" if subgraph else "Full Graph")
        plt.show()

    @staticmethod
    def _field_contains(d: dict, field_name: str, value: str) -> bool:
        """Recursively check if *d* has a field containing *value*."""
        for k, v in d.items():
            if k.lower() == field_name:
                if isinstance(v, str) and value in v.lower():
                    return True
            if isinstance(v, dict):
                if docViewer._field_contains(v, field_name, value):
                    return True
        return False

    @staticmethod
    def _has_field(d: dict, field_name: str) -> bool:
        """Recursively check if *d* has a field named *field_name*."""
        for k, v in d.items():
            if k.lower() == field_name:
                return True
            if isinstance(v, dict):
                if docViewer._has_field(v, field_name):
                    return True
        return False
