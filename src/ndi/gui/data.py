"""ndi_gui_Data — ndi_document data-table view with search/filter and graph visualisation.

Mirrors MATLAB: ndi.gui.ndi_gui_Data

Provides a table of NDI documents with search, filtering (contains,
begins with, ends with), a detail panel, and dependency-graph
visualisation using *networkx*.
"""

from __future__ import annotations

import json
from typing import Any

from ndi.gui._qt_helpers import require_qt

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    pass


class ndi_gui_Data:
    """ndi_database view widget showing a searchable document table.

    The widget is embedded inside :func:`ndi.gui.gui_v2` but can also
    be used standalone.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        require_qt()

        self.fullDocuments: list[Any] = []
        self.fullTable: list[list[str]] = []
        self.tempDocuments: list[Any] = []
        self.tempTable: list[list[str]] = []

        # -- Table --------------------------------------------------------
        self.table = QtWidgets.QTableWidget(0, 4, parent)
        self.table.setHorizontalHeaderLabels(["Name", "ID", "Type", "Date"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._on_cell_clicked)

        # -- Detail panel -------------------------------------------------
        self.panel = QtWidgets.QFrame(parent)
        self.panel.setStyleSheet("background-color: white;")
        panel_layout = QtWidgets.QVBoxLayout(self.panel)
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet("font-weight: bold;")
        panel_layout.addWidget(self._name_label)
        self._detail_list = QtWidgets.QTextEdit()
        self._detail_list.setReadOnly(True)
        panel_layout.addWidget(self._detail_list)

        # Graph / Subgraph buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self._graph_btn = QtWidgets.QPushButton("Graph")
        self._graph_btn.clicked.connect(self._on_graph)
        btn_layout.addWidget(self._graph_btn)
        self._subgraph_btn = QtWidgets.QPushButton("Subgraph")
        self._subgraph_btn.clicked.connect(self._on_subgraph)
        btn_layout.addWidget(self._subgraph_btn)
        panel_layout.addLayout(btn_layout)

        # -- Search controls ----------------------------------------------
        self._search_col = QtWidgets.QComboBox(parent)
        self._search_col.addItems(["Select", "Name", "ID", "Type", "Date"])

        self._search_op = QtWidgets.QComboBox(parent)
        self._search_op.addItems(["Filter options", "contains", "begins with", "ends with"])

        self._search_text = QtWidgets.QLineEdit(parent)

        self._search_btn = QtWidgets.QPushButton("Search", parent)
        self._search_btn.clicked.connect(self.filter)

        self._clear_btn = QtWidgets.QPushButton("Clear", parent)
        self._clear_btn.clicked.connect(self.clear)

        self.search = [
            self._search_col,
            self._search_op,
            self._search_text,
            self._search_btn,
            self._clear_btn,
        ]

        self._selected_row: int | None = None

    # -- Public API -------------------------------------------------------

    def addDoc(self, docs: list[Any]) -> None:
        """Populate the table from a list of NDI documents.

        Parameters
        ----------
        docs : list
            Each element is expected to have ``document_properties``
            with ``ndi_document.{name, id, type, datestamp}`` fields.
        """
        for doc in docs:
            self.fullDocuments.append(doc)
            dp = doc.document_properties
            nd = dp.get("ndi_document", dp)
            name = nd.get("name", "") if isinstance(nd, dict) else getattr(nd, "name", "")
            doc_id = nd.get("id", "") if isinstance(nd, dict) else getattr(nd, "id", "")
            doc_type = nd.get("type", "") if isinstance(nd, dict) else getattr(nd, "type", "")
            datestamp = (
                nd.get("datestamp", "") if isinstance(nd, dict) else getattr(nd, "datestamp", "")
            )
            json_details = json.dumps(
                dp if isinstance(dp, dict) else dp.__dict__,
                indent=2,
                default=str,
            )
            self.fullTable.append(
                [str(name), str(doc_id), str(doc_type), str(datestamp), json_details]
            )

        self.tempTable = list(self.fullTable)
        self.tempDocuments = list(self.fullDocuments)
        self._refresh_table()

    def filter(self) -> None:
        """Filter the table using current search controls."""
        col_idx = self._search_col.currentIndex() - 1  # 0 is "Select"
        op_idx = self._search_op.currentIndex()  # 1=contains, 2=begins, 3=ends
        needle = self._search_text.text().lower()

        if col_idx < 0 or op_idx < 1 or not needle:
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

    def clear(self) -> None:
        """Clear the table display."""
        self.table.setRowCount(0)

    def details(self, row_index: int) -> None:
        """Show document details for *row_index*."""
        if row_index < 0 or row_index >= len(self.tempTable):
            return
        row = self.tempTable[row_index]
        self._name_label.setText(f"Name: {row[0]}")
        info_lines = [
            f"Type: {row[2]}",
            f"Date: {row[3]}",
            f"ID: {row[1]}",
            "",
            "Content:",
            row[4] if len(row) > 4 else "",
        ]
        self._detail_list.setPlainText("\n".join(info_lines))
        self._selected_row = row_index

    def graph(self, ind: int) -> None:
        """Show the full dependency graph with node *ind* highlighted."""
        self._show_graph(ind, subgraph=False)

    def subgraph(self, ind: int) -> None:
        """Show the dependency subgraph centred on node *ind*."""
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
        """Build and display a dependency graph using networkx + matplotlib."""
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
        full_ind = None
        for i, fd in enumerate(self.fullDocuments):
            if fd is doc:
                full_ind = i
                break
        if full_ind is None:
            full_ind = ind

        # Build edges from depends_on
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
            # Keep only nodes connected to full_ind
            neighbors = set(G.predecessors(full_ind)) | set(G.successors(full_ind))
            neighbors.add(full_ind)
            G = G.subgraph(neighbors).copy()

        fig, ax = plt.subplots(figsize=(6, 6))
        if len(G.nodes) > 0:
            pos = nx.spring_layout(G)
            node_colors = ["red" if n == full_ind else "#4472C4" for n in G.nodes]
            nx.draw(
                G,
                pos,
                ax=ax,
                with_labels=True,
                node_color=node_colors,
                node_size=300,
                font_size=8,
                arrows=True,
            )
        ax.set_title("Subgraph" if subgraph else "Full Graph")
        plt.show()
