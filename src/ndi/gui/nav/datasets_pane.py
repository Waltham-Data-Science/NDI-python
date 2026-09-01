"""ndi.gui.nav.datasets_pane - the navigator's Datasets pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/datasetsPane.m``

A scrollable tree of the datasets and sessions available to the user, with a
context menu on every node. The pane is collapsible AND resizable, which
makes it the navigator's ELASTIC pane: it absorbs the leftover window height
so the panes below it keep hugging the bottom edge. Appending it in
:meth:`ndi.gui.navigator.Navigator.build_panes` is what finally takes the
layout out of its no-elastic branch.

WHERE THE LOGIC LIVES, AND WHY NOT HERE
Almost none of the decisions are in this file. The tree's contents come from
:mod:`ndi.gui.nav.datasets_model`, the message and menu-enablement rules from
:mod:`ndi.gui.nav.datasets_text`, and the cloud commands from
:mod:`ndi.gui.nav.datasets_cloud` -- all Qt-free and separately tested. What
is left here is widget construction and the wiring between the two, which is
the part a display is genuinely needed to check.

ONE GAP LEFT, DELIBERATE AND VISIBLE

The per-session "Apps" menu is filled by :func:`session_apps`, which asks
:class:`ndi.gui.app.SessionApp` what apps exist rather than naming any --
so an app appears in the menu by existing, in either language. MATLAB's own
eleven apps are not ported yet, so what the menu offers today is whatever
apps the user's own packages supply (see the
``GUI.Navigator.SessionAppPackages`` preference). The menu is built either
way: an empty "Apps" menu says "no apps found" honestly, while omitting it
would say "sessions have no apps", which is false.

The "+" add-dataset flows (new blank dataset, open dataset, open a cloud
dataset, create/open a session) are the next slice. The button is therefore
not built yet: a "+" that does nothing is worse than no "+". Datasets and
sessions bound to variables in the user's workspace are still listed, which
is how the tree has anything in it today.
"""

from __future__ import annotations

from typing import Any

from ..app.session_app import SessionApp
from ..cloud_colors import cloud_colors, rgb_to_hex
from . import datasets_cloud, datasets_model
from .datasets_text import dataset_menu_enable
from .pane import NavPane
from .status_icon import status_icon

__all__ = ["DatasetsPane", "session_apps", "GRIP_HEIGHT", "REFRESH_WIDTH"]

#: Height of the thin divider strip at the bottom of the body, in pixels.
GRIP_HEIGHT = 6

#: Width of the header's right-hand control column, in pixels. MATLAB's
#: rightWidth: the "+" square plus the Refresh button.
REFRESH_WIDTH = 108

#: The label of the root node holding sessions that belong to no dataset.
UNAFFILIATED_TEXT = "Unaffiliated sessions"


def session_apps() -> list[dict[str, Any]]:
    """The apps offered for a session, discovered dynamically.

    Returns records with ``Label``, ``Launch`` and ``Category``, as MATLAB's
    ``sessionApps`` does: ``Launch`` takes the session and opens the app.

    Nothing is hardcoded here in either language. The list comes from
    :meth:`ndi.gui.app.SessionApp.list`, so any class adopting that
    interface -- NDI's own, or one in a package the user named in the
    ``GUI.Navigator.SessionAppPackages`` preference -- appears here without
    this file, or the menu that consumes it, being touched.

    A discovery failure yields no apps rather than an error, as MATLAB's
    try/catch does: the rest of the session menu is still worth opening.
    """
    try:
        found = SessionApp.list()
    except Exception:  # noqa: BLE001 - a broken scan costs apps, not the menu
        found = []
    return [
        {
            "Label": str(entry.get("Name", "")),
            "Launch": _launcher(str(entry.get("Class", ""))),
            "Category": str(entry.get("Category", "") or ""),
        }
        for entry in found
    ]


def _launcher(app_class: str):
    """The ``Launch`` callable for APP_CLASS.

    A function of its own rather than a lambda in the comprehension, so each
    record closes over its own class name instead of the loop variable.
    """
    return lambda session: SessionApp.launch(app_class, session)


class DatasetsPane(NavPane):
    """The navigator's Datasets pane: a tree of datasets and sessions."""

    #: Marks this pane as the elastic one. The layout module reads it with a
    #: default of False, mirroring MATLAB's isprop test.
    resizable = True

    def __init__(self, navigator: Any = None):
        super().__init__(
            navigator,
            title="Datasets",
            collapsible=True,
            engaged=True,
            min_height=100,
            height=220,
        )
        self.tree: Any = None
        self.grip: Any = None

        #: Datasets and sessions the user added by hand. Empty until the "+"
        #: flows land; the tree is still populated from the workspace.
        self.user_datasets: list[Any] = []
        self.user_sessions: list[Any] = []

        #: object id -> the user's variable names holding it. Rebuilt on each
        #: tree build, and used only to decorate node labels.
        self.ws_var_index: dict[str, list[str]] = {}

        #: The session apps opened from this pane, held so their windows are
        #: not garbage-collected out from under the user. See
        #: :meth:`launch_app`.
        self.launched_apps: list[Any] = []

    def has_body(self) -> bool:
        return True

    def right_width(self) -> float:
        return REFRESH_WIDTH

    def refresh(self) -> None:
        """Rebuild the tree from the model."""
        self.populate_tree()

    # ------------------------------------------------------------------
    # Qt construction
    # ------------------------------------------------------------------
    def build_body(self, container: Any) -> None:
        from PySide6 import QtWidgets

        layout = container.layout() or QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        from PySide6 import QtCore

        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_node_menu)
        layout.addWidget(self.tree, 1)

        c = cloud_colors()
        self.grip = QtWidgets.QFrame()
        self.grip.setFixedHeight(GRIP_HEIGHT)
        self.grip.setStyleSheet(f"background-color: {rgb_to_hex(c.light_blue)};")
        layout.addWidget(self.grip, 0)

        self.populate_tree()

    def build_header_right(self, layout: Any) -> None:
        """The header's right-hand controls.

        Only Refresh for now. MATLAB also has a "+" that opens the
        add-dataset menu; those flows are the next slice, and a "+" that did
        nothing would be worse than none. The column keeps MATLAB's width so
        the header does not shift when the button arrives.
        """
        from PySide6 import QtWidgets

        button = QtWidgets.QPushButton("Refresh")
        button.setToolTip("Rebuild the list of datasets and sessions")
        button.clicked.connect(self.refresh)
        self.accent_button(button)
        layout.addWidget(button)
        self.refresh_button = button

    # ------------------------------------------------------------------
    # the tree
    # ------------------------------------------------------------------
    def populate_tree(self) -> list[dict[str, Any]]:
        """Rebuild the tree, returning the rows it drew.

        The return value is what makes the tree's CONTENTS checkable without
        inspecting widgets: each row is the label and node payload that was
        rendered, in display order. A tree that lists a session twice or
        labels it with the wrong variable is a wrong row here, not a raised
        error.
        """
        rows = self.tree_rows()
        if self.tree is None:
            return rows

        from PySide6 import QtWidgets

        self.tree.clear()
        for row in rows:
            item = QtWidgets.QTreeWidgetItem([row["label"]])
            item.setData(0, _NODE_ROLE, row["node_data"])
            for child in row.get("children", ()):
                sub = QtWidgets.QTreeWidgetItem([child["label"]])
                sub.setData(0, _NODE_ROLE, child["node_data"])
                item.addChild(sub)
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)
        return rows

    def tree_rows(self) -> list[dict[str, Any]]:
        """The rows the tree should show, top to bottom. No Qt.

        MATLAB's order: the "Unaffiliated sessions" root with its sessions as
        children, then one node per dataset with its sessions as children.
        """
        session_cls, dataset_cls = _model_classes()
        self.ws_var_index = datasets_model.build_workspace_var_index((session_cls, dataset_cls))

        sessions = datasets_model.unaffiliated_sessions(self.user_sessions, session_cls)
        rows: list[dict[str, Any]] = [
            {
                "label": UNAFFILIATED_TEXT,
                "node_data": datasets_model.dataset_node_data(),
                "children": datasets_model.unaffiliated_rows(sessions, self.ws_var_index),
            }
        ]

        for row in datasets_model.dataset_rows(
            self.user_datasets, dataset_cls, None, self.ws_var_index
        ):
            rows.append(
                {
                    "label": row["label"],
                    "node_data": row["node_data"],
                    "children": row["sessions"],
                }
            )
        return rows

    def dataset_nodes(self) -> list[Any]:
        """The top-level tree items that carry a dataset.

        The "Unaffiliated sessions" root is a top-level node too but holds no
        dataset, so a bulk action must not treat it as one.
        """
        if self.tree is None:
            return []
        nodes = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            data = item.data(0, _NODE_ROLE) or {}
            if data.get("dataset") is not None:
                nodes.append(item)
        return nodes

    def check_all_cloud_status(self, on_progress: Any = None) -> dict[str, int]:
        """Check every dataset's NDI Cloud status and badge the nodes.

        The bulk action behind the NDI Cloud pane's "C" button. Returns the
        report, which :func:`ndi.gui.nav.datasets_text.cloud_summary_message`
        turns into the sentence shown to the user.
        """
        nodes = self.dataset_nodes()
        datasets = [n.data(0, _NODE_ROLE)["dataset"] for n in nodes]
        report, states = datasets_model.check_all_cloud_status(datasets, on_progress)
        for node, state in zip(nodes, states):
            if state != "unknown":
                self.set_dataset_cloud_state(node, state)
        return report

    # ------------------------------------------------------------------
    # node state and badges
    # ------------------------------------------------------------------
    def set_dataset_cloud_state(self, node: Any, state: str) -> None:
        """Cache STATE on NODE and draw its cloud badge.

        Stored on the node so the menu's enable/disable can read it WITHOUT a
        database query -- which is what keeps opening the menu instant, and
        why the status is computed only on demand rather than during a tree
        build.
        """
        data = dict(node.data(0, _NODE_ROLE) or {})
        data["cloud"] = str(state)
        node.setData(0, _NODE_ROLE, data)
        self._set_icon(node, {"cloud": str(state)})

    def apply_node_status(self, node: Any, status: dict[str, str]) -> None:
        """Store STATUS on NODE and draw its ingestion badge."""
        data = dict(node.data(0, _NODE_ROLE) or {})
        data["status"] = dict(status)
        node.setData(0, _NODE_ROLE, data)
        self._set_icon(node, status)

    def _set_icon(self, node: Any, status: dict[str, str]) -> None:
        path = status_icon(status)
        if not path or node is None:
            return
        from PySide6 import QtGui

        node.setIcon(0, QtGui.QIcon(path))

    # ------------------------------------------------------------------
    # context menus
    # ------------------------------------------------------------------
    def _show_node_menu(self, point: Any) -> None:
        item = self.tree.itemAt(point)
        if item is None:
            return
        menu = self.build_node_menu(item)
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(point))

    def build_node_menu(self, node: Any) -> Any:
        """The context menu for NODE, or None when it has none.

        Built fresh on each right-click rather than kept per node, which is
        why there is no equivalent of MATLAB's ``clearNodeMenus``: menus
        cannot outlive a tree rebuild if they are never stored.

        Each item captures the NODE it was built for. MATLAB does the same
        deliberately -- a right-click does not reliably commit a tree
        selection before the menu opens, so an action that read "the selected
        node" could act on the wrong one.
        """
        data = node.data(0, _NODE_ROLE) or {}
        kind = data.get("kind")
        if kind == "session":
            return self._session_menu(node)
        if data.get("dataset") is not None:
            return self._dataset_menu(node, data["dataset"])
        if node.text(0) == UNAFFILIATED_TEXT:
            return self._unaffiliated_menu(node)
        return None

    def _session_menu(self, node: Any) -> Any:
        from PySide6 import QtWidgets

        menu = QtWidgets.QMenu(self.tree)

        # "Apps" then "Session", alphabetical, as MATLAB creates them.
        apps_root = menu.addMenu("Apps")
        for entry in _order_app_menu(session_apps()):
            if entry["kind"] == "app":
                app = entry["apps"]
                apps_root.addAction(entry["label"], lambda a=app, n=node: self.launch_app(a, n))
            else:
                sub = apps_root.addMenu(entry["label"])
                for app in entry["apps"]:
                    sub.addAction(
                        str(app.get("Label", "")),
                        lambda a=app, n=node: self.launch_app(a, n),
                    )

        session_root = menu.addMenu("Session")
        session_root.addAction("Clear Cache", lambda: self.clear_session_cache(node))
        session_root.addAction("Info...", lambda: self.show_session_info(node))
        session_root.addAction("Ingest", lambda: self.ingest_session_node(node))
        session_root.addAction("Ingestion Status", lambda: self.update_session_status(node))
        return menu

    def _unaffiliated_menu(self, node: Any) -> Any:
        """The root node's menu.

        Its two items create or open a session, and both belong to the "+"
        slice. The menu is omitted entirely until then rather than shown with
        dead entries.
        """
        return None

    def _dataset_menu(self, node: Any, dataset: Any) -> Any:
        from PySide6 import QtWidgets

        menu = QtWidgets.QMenu(self.tree)
        cloud = menu.addMenu("Cloud")

        cloud.addAction(
            "Check Cloud status", lambda: self._run_cloud(node, "check_status", dataset)
        )
        upload_item = cloud.addAction(
            "Upload to Cloud", lambda: self._run_cloud(node, "upload", dataset)
        )
        upload_item.setSeparator(False)
        cloud.addSeparator()

        linked = [
            cloud.addAction(
                "Check Cloud for New",
                lambda: self._run_cloud(node, "check_new_remote", dataset),
            ),
            cloud.addAction(
                "Check Local for New",
                lambda: self._run_cloud(node, "check_new_local", dataset),
            ),
        ]
        cloud.addSeparator()
        for label, mode in (
            ("Download New from Cloud", "download_new"),
            ("Upload New to Cloud", "upload_new"),
            ("Two Way Sync", "two_way_sync"),
        ):
            linked.append(cloud.addAction(label, lambda m=mode: self._run_sync(node, dataset, m)))
        cloud.addSeparator()
        for label, direction in (
            ("Mirror from Cloud", "from_remote"),
            ("Mirror to Cloud", "to_remote"),
        ):
            linked.append(
                cloud.addAction(label, lambda d=direction: self._run_mirror(node, dataset, d))
            )

        # Grey out the inapplicable items from the state CACHED on the node.
        # No database query on menu open, so opening it stays instant.
        self.update_dataset_menu_enable(node, upload_item, linked)
        return menu

    def update_dataset_menu_enable(
        self, node: Any, upload_item: Any, linked_items: list[Any]
    ) -> tuple[bool, bool]:
        """Enable the applicable cloud actions from NODE's cached state.

        Until the status has been checked the state is ``"unknown"`` and
        EVERYTHING is enabled -- blocking an action because we have not
        looked yet would stop a user for no reason.
        """
        data = node.data(0, _NODE_ROLE) or {}
        upload_enable, linked_enable = dataset_menu_enable(data.get("cloud", "unknown"))
        if upload_item is not None:
            upload_item.setEnabled(upload_enable)
        for item in linked_items:
            item.setEnabled(linked_enable)
        return upload_enable, linked_enable

    # ------------------------------------------------------------------
    # cloud commands
    # ------------------------------------------------------------------
    def _run_cloud(self, node: Any, action: str, dataset: Any) -> Any:
        if action == "check_status":
            result = datasets_cloud.check_cloud_status(dataset)
        elif action == "upload":
            result = datasets_cloud.upload_dataset(dataset)
        elif action == "check_new_remote":
            result = datasets_cloud.check_for_new(dataset, "remote")
        else:
            result = datasets_cloud.check_for_new(dataset, "local")
        return self._report(node, result)

    def _run_sync(self, node: Any, dataset: Any, mode: str) -> Any:
        return self._report(node, datasets_cloud.sync_dataset(dataset, mode))

    def _run_mirror(self, node: Any, dataset: Any, direction: str) -> Any:
        """Confirm, then mirror. Both directions delete documents for good.

        The confirmation is obtained HERE rather than inside
        ``mirror_dataset``, so the destructive call cannot be reached without
        a user having seen the warning that names which side loses documents.
        """
        title, prompt = datasets_cloud.mirror_prompt(direction)
        if not self._confirm(title, prompt, accept="Continue"):
            return None
        return self._report(node, datasets_cloud.mirror_dataset(dataset, direction))

    def _report(self, node: Any, result: Any) -> Any:
        """Show a cloud action's outcome and record any state it established."""
        if result is None:
            return None
        if result.state is not None and node is not None:
            self.set_dataset_cloud_state(node, result.state)
        self._alert(result.message, result.title, success=result.ok)
        return result

    # ------------------------------------------------------------------
    # session node actions
    # ------------------------------------------------------------------
    def launch_app(self, app: dict[str, Any], node: Any) -> None:
        """Resolve NODE's session and start the chosen app.

        The app object is kept, where MATLAB may discard it: a MATLAB app
        stays alive because its figure holds it through guidata, while a
        Python app that nothing references can be collected -- taking its
        window with it -- as soon as this method returns.
        """
        title = str(app.get("Label", "App"))
        session = self._resolve_or_report(node, title)
        if session is None:
            return
        try:
            opened = app["Launch"](session)
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), title, success=False)
            return
        if opened is not None:
            self.launched_apps.append(opened)

    def clear_session_cache(self, node: Any) -> bool:
        """Clear the cache of NODE's session.

        Note that clearing a session cache also clears the global memoized
        function caches, so this frees session-scoped data such as epoch
        tables too.
        """
        title = "Clear Cache"
        session = self._resolve_or_report(node, title)
        if session is None:
            return False
        try:
            session.cache.clear()
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), title, success=False)
            return False
        self._alert("The session cache was cleared.", title, success=True)
        return True

    def show_session_info(self, node: Any) -> Any:
        """Open the vital-statistics window for NODE's session."""
        title = "Session Info"
        session = self._resolve_or_report(node, title)
        if session is None:
            return None
        from .session_info import SessionInfo

        try:
            return SessionInfo(session)
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), title, success=False)
            return None

    def ingest_session_node(self, node: Any) -> bool:
        """Ingest NODE's session's raw data, after confirming.

        Scope note, as in MATLAB: this is SESSION-level ingestion (raw data
        into the database). Converting a linked session to an ingested one
        inside a dataset is a different operation with its own confirmation
        and disk-space caveats, and is deliberately not reachable from here.
        """
        title = "Ingest session"
        session = self._resolve_or_report(node, "Ingest")
        if session is None:
            return False
        if not self._confirm(
            title,
            "Ingest this session's raw data into the database? " "This may take a while.",
            accept="Ingest",
        ):
            return False

        ok = True
        try:
            ok, message = session.ingest()
            if not ok:
                self._alert(f"Ingestion did not complete: {message}", title, success=False)
        except Exception as exc:  # noqa: BLE001
            ok = False
            self._alert(str(exc), title, success=False)

        # The badge is refreshed either way: a partial ingestion still
        # changes the state, and leaving a stale badge would be worse than
        # showing the new one alongside the error.
        self.update_session_status(node)
        return ok

    def update_session_status(self, node: Any) -> dict[str, str]:
        """Recompute NODE's ingestion badge, on demand.

        Status is only ever computed here, never during a tree build, so
        listing sessions stays cheap; a node shows a badge only once the user
        has asked for its status or ingested it.
        """
        title = "Ingestion Status"
        data = node.data(0, _NODE_ROLE) or {}
        session = self._resolve_or_report(node, title)
        if session is None:
            return dict(datasets_model.UNKNOWN_STATUS)

        status, error = datasets_model.compute_session_status(session, data)
        self.apply_node_status(node, status)
        if error is not None:
            self._alert(
                "Could not determine the ingestion status of this session: " f"{error}",
                title,
                success=False,
            )
        return status

    def _resolve_or_report(self, node: Any, title: str) -> Any:
        session = datasets_model.resolve_session(node.data(0, _NODE_ROLE) or {})
        if session is None:
            self._alert("Could not open the session for this node.", title, success=False)
        return session

    # ------------------------------------------------------------------
    # dialogs, routed through the navigator
    # ------------------------------------------------------------------
    def _alert(self, message: str, title: str, *, success: bool) -> None:
        if self.navigator is None:
            return
        alert = getattr(self.navigator, "alert", None)
        if callable(alert):
            alert(message, title, success=success)

    def _confirm(self, title: str, prompt: str, *, accept: str) -> bool:
        """Ask the user to confirm a destructive or long action.

        Defaults to CANCEL, as MATLAB does: the default button on a dialog
        that can delete documents or run for a long time must not be the one
        that proceeds.
        """
        if self.navigator is None or getattr(self.navigator, "figure", None) is None:
            return False
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.navigator.figure)
        box.setWindowTitle(title)
        box.setText(prompt)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        go = box.addButton(accept, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is go


def _order_app_menu(apps: Any) -> list[dict[str, Any]]:
    from .datasets_text import order_app_menu

    return order_app_menu(apps)


def _model_classes() -> tuple[type, type]:
    """The session and dataset classes the workspace scan looks for."""
    from ...dataset import _DatasetBase
    from ...session.session_base import ndi_session

    # The BASE classes on both sides: ndi.dataset.ndi_dataset is an alias for
    # the directory-backed subclass, so scanning for it would miss any other
    # dataset kind a user holds.
    return ndi_session, _DatasetBase


#: Qt item-data role holding a node's payload dict. 32 is Qt.UserRole; the
#: literal avoids importing Qt just to name a constant in a module that is
#: otherwise importable without a display.
_NODE_ROLE = 32
