"""ndi.gui.preferences_editor - browse and edit ndi.preferences.

MATLAB counterpart: ``src/ndi/+ndi/+gui/preferencesEditor.m``

A window over the preferences singleton: a tree of categories (with
subcategories as children) on the left, one editor row per preference on the
right, and Revert / Apply / Save along the bottom.

EDITS ARE DEFERRED
A changed widget records a PENDING edit inside the editor and marks its row
with a trailing asterisk. Nothing reaches :mod:`ndi.preferences` -- and so
nothing rewrites the JSON file -- until Apply or Save is pressed. That is
MATLAB's contract and the one part of this a user would notice at once if it
broke: preferences that saved themselves on every keystroke would write a
half-typed number to disk.

WHAT IS QT AND WHAT IS NOT
Everything that decides what the window SHOWS -- the tree, which rows a
selection resolves to, each row's label, which widget a type gets, and what a
typed string coerces to -- is plain Python here and tested without a display.
:class:`PreferencesEditor` owns the widgets and does nothing else. This is the
split :mod:`ndi.gui.navigator` makes with :mod:`ndi.gui.nav.layout`, for the
same reason: a row labelled with the wrong preference, or a value coerced to
the wrong type, does not raise. It quietly writes something untrue into the
user's preferences file.

DEVIATIONS FROM MATLAB
* MATLAB's ``uieditfield('numeric')`` refuses a non-numeric entry at the
  widget, so a bad value can never be committed. Qt's line edit is validated
  but a validator cannot cover every partial state, so the coercion is done
  again in :func:`coerce_value` when Apply runs, and a value that will not
  convert is reported the way MATLAB reports a failing ``set``.
* :class:`PreferencesEditorState` accepts an ``ndi.preferences.ndi_preferences``
  instance. MATLAB always edits the singleton; taking the store as an argument
  is what lets the editor be tested against a temporary preferences file
  instead of the developer's own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .cloud_colors import cloud_colors, rgb_to_hex

__all__ = [
    "DEFAULT_POSITION",
    "WINDOW_TAG",
    "NUMERIC_TYPES",
    "BOOL_TYPES",
    "TreeNode",
    "PreferenceRow",
    "ApplyResult",
    "PreferencesEditorState",
    "PreferencesEditor",
    "preferences_editor",
    "preferencesEditor",
    "item_path",
    "build_tree",
    "matching_indices",
    "row_label",
    "widget_kind",
    "display_text",
    "coerce_value",
]

#: Default window geometry, ``(x, y, width, height)``, as MATLAB has it.
DEFAULT_POSITION = (100, 100, 820, 540)

#: Object name on the window, mirroring MATLAB's ``Tag``, so an open editor
#: can be found again.
WINDOW_TAG = "ndiPreferencesEditor"

#: Type names that get a numeric editor. MATLAB switches on ``'double'`` and
#: ``'single'``; the Python preferences store writes ``'float'`` and ``'int'``
#: for the same items, so both vocabularies are listed -- a preferences file
#: written by either language then renders the same widget.
NUMERIC_TYPES = frozenset({"double", "single", "float", "int", "int32", "int64", "numeric"})

#: Type names that get a checkbox.
BOOL_TYPES = frozenset({"logical", "bool"})

#: Marker appended to the label of a row with an unapplied edit.
PENDING_MARK = "*"

# Row geometry, in pixels. MATLAB's grid uses 30-pixel rows.
ROW_HEIGHT = 30
BUTTON_WIDTH = 90
HEADER_HEIGHT = 28


# ----------------------------------------------------------------------
# the model: what the window shows
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class TreeNode:
    """One node of the left-hand tree.

    A top-level node is a category and carries an empty ``subcategory``;
    its children are that category's subcategories. Selecting a node names
    the ``(category, subcategory)`` pair the right pane filters on, which is
    exactly what MATLAB stashes in each node's ``NodeData``.
    """

    text: str
    category: str
    subcategory: str = ""
    children: tuple[TreeNode, ...] = ()


@dataclass(frozen=True)
class PreferenceRow:
    """One editor row: a preference, as the right pane needs to draw it."""

    index: int
    path: str
    label: str
    value: Any
    kind: str
    type: str
    description: str
    pending: bool


@dataclass
class ApplyResult:
    """What one Apply did.

    ``applied`` lists the dotted paths written, in the order they were
    written. ``error`` is None on success, else the message for the first
    failing item -- and, as in MATLAB, the paths already in ``applied`` have
    been written even when it is set.
    """

    applied: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def item_path(item: Mapping[str, Any]) -> str:
    """Return the dotted path of a preference item.

    ``Category.Name`` when the subcategory is empty, otherwise
    ``Category.Subcategory.Name``. Mirrors MATLAB's ``itemPath`` local
    function, and the result is what :func:`ndi.preferences.set` takes.
    """
    category = str(item["category"])
    subcategory = str(item.get("subcategory") or "")
    name = str(item["name"])
    if not subcategory:
        return f"{category}.{name}"
    return f"{category}.{subcategory}.{name}"


def _unique_stable(values: Iterable[str]) -> list[str]:
    """MATLAB's ``unique(..., 'stable')``: first-seen order, no repeats."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def build_tree(items: Sequence[Mapping[str, Any]]) -> list[TreeNode]:
    """Build the category / subcategory tree from a snapshot of items.

    One top-level node per distinct category and one child per non-empty
    subcategory, both in first-seen order so the tree follows the order
    preferences were registered in rather than an alphabetical one the
    author did not choose. Mirrors MATLAB's ``populateTree``.
    """
    nodes: list[TreeNode] = []
    for category in _unique_stable(str(item["category"]) for item in items):
        subs = _unique_stable(
            str(item.get("subcategory") or "")
            for item in items
            if str(item["category"]) == category and item.get("subcategory")
        )
        nodes.append(
            TreeNode(
                text=category,
                category=category,
                subcategory="",
                children=tuple(
                    TreeNode(text=sub, category=category, subcategory=sub) for sub in subs
                ),
            )
        )
    return nodes


def matching_indices(
    items: Sequence[Mapping[str, Any]], category: str, subcategory: str = ""
) -> list[int]:
    """Indices of the items a tree selection shows.

    An empty *subcategory* means a category node was selected, and then
    EVERY item in that category is shown -- including those that do live in
    a subcategory. Narrowing to only the subcategory-less items would hide
    every preference in the store from the top-level node, which is the one
    node the editor opens on.
    """
    out: list[int] = []
    for index, item in enumerate(items):
        if str(item["category"]) != category:
            continue
        if subcategory and str(item.get("subcategory") or "") != subcategory:
            continue
        out.append(index)
    return out


def row_label(
    item: Mapping[str, Any], *, pending: bool = False, show_subcategory: bool = False
) -> str:
    """Build the text of one row's label.

    The pending asterisk goes on the NAME, then the subcategory prefix goes
    in front of the result (``'Upload / Max_File_Batch_Size*'``), which is
    the order MATLAB builds it in. *show_subcategory* is true exactly when a
    category node is selected, so the rows say which subcategory they came
    from; under a subcategory node the prefix would repeat what the
    selection already says.
    """
    label = str(item["name"])
    if pending:
        label += PENDING_MARK
    subcategory = str(item.get("subcategory") or "")
    if subcategory and show_subcategory:
        label = f"{subcategory} / {label}"
    return label


def widget_kind(type_name: str) -> str:
    """Return the editor widget a preference type gets.

    One of ``'numeric'``, ``'bool'``, or ``'text'``. Anything unrecognised
    -- including the store's ``'any'`` -- falls back to ``'text'``, as
    MATLAB's ``otherwise`` branch does: a preference whose type nobody
    taught this editor about is still editable as its printed form.
    """
    name = str(type_name or "").strip().lower()
    if name in NUMERIC_TYPES:
        return "numeric"
    if name in BOOL_TYPES:
        return "bool"
    return "text"


def display_text(value: Any) -> str:
    """Render a value for a text field, never raising.

    Mirrors MATLAB's ``char(string(...))`` with its try/catch fallback to
    the empty string: a value that will not print must not stop the rest of
    the pane from drawing.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - mirror MATLAB's catch-all
        return ""


_TRUE_WORDS = {"true", "1", "yes", "on"}
_FALSE_WORDS = {"false", "0", "no", "off"}


def coerce_value(raw: Any, type_name: str) -> Any:
    """Convert a widget's value to the type its preference declares.

    Widgets hand back strings and booleans; the store keeps ints, floats,
    strings and booleans. Coercing here rather than at :func:`ndi.preferences.set`
    -- which stores whatever it is given, verbatim -- is what keeps
    ``Max_Document_Batch_Count`` an int after a trip through a text field.

    Raises:
        ValueError: If the text cannot be read as the declared type. Apply
            reports that per item, the way MATLAB reports a failing ``set``.
    """
    name = str(type_name or "").strip().lower()
    if name in BOOL_TYPES:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
        raise ValueError(f'"{raw}" is not a boolean')
    if name in NUMERIC_TYPES:
        text = raw if not isinstance(raw, str) else raw.strip()
        try:
            number = float(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'"{raw}" is not a number') from exc
        if name in {"int", "int32", "int64"}:
            if number != int(number):
                raise ValueError(f'"{raw}" is not a whole number')
            return int(number)
        return number
    if name == "str":
        return display_text(raw)
    return raw


class PreferencesEditorState:
    """The editor's state: the item snapshot, the pending edits, the selection.

    Holds no widgets, so every rule the window follows can be checked without
    a display. The snapshot is taken once at construction and refreshed after
    a successful Apply, which is what makes an edit "pending": the row shows
    the pending value while the snapshot still shows what is on disk.

    Args:
        prefs: The preferences store to edit. Defaults to the process
            singleton, which is what MATLAB always edits; tests pass an
            ``ndi_preferences`` pointed at a temporary file.
    """

    def __init__(self, prefs: Any = None):
        self._prefs = prefs if prefs is not None else _default_prefs()
        self.items: list[dict[str, Any]] = list(self._prefs.list_items())
        self.pending: dict[int, Any] = {}
        self.selection: tuple[str, str] | None = None
        nodes = self.tree()
        if nodes:
            self.select(nodes[0].category, nodes[0].subcategory)

    # -- reads ---------------------------------------------------------
    @property
    def prefs(self) -> Any:
        """The preferences store being edited."""
        return self._prefs

    def tree(self) -> list[TreeNode]:
        """The category / subcategory tree for the current snapshot."""
        return build_tree(self.items)

    def select(self, category: str, subcategory: str = "") -> None:
        """Point the right pane at one category or subcategory."""
        self.selection = (str(category), str(subcategory or ""))

    def value_for(self, index: int) -> Any:
        """The value a row shows: the pending edit if there is one, else saved."""
        if index in self.pending:
            return self.pending[index]
        return self.items[index]["value"]

    def rows(self) -> list[PreferenceRow]:
        """The rows the right pane draws for the current selection.

        Empty when nothing is selected -- an editor with no preferences
        registered has no first node to open on.
        """
        if self.selection is None:
            return []
        category, subcategory = self.selection
        show_subcategory = not subcategory
        rows: list[PreferenceRow] = []
        for index in matching_indices(self.items, category, subcategory):
            item = self.items[index]
            is_pending = index in self.pending
            rows.append(
                PreferenceRow(
                    index=index,
                    path=item_path(item),
                    label=row_label(item, pending=is_pending, show_subcategory=show_subcategory),
                    value=self.value_for(index),
                    kind=widget_kind(item.get("type", "")),
                    type=str(item.get("type", "")),
                    description=str(item.get("description", "")),
                    pending=is_pending,
                )
            )
        return rows

    # -- writes --------------------------------------------------------
    def set_pending(self, index: int, value: Any) -> None:
        """Record an unapplied edit for the item at *index*."""
        if not 0 <= index < len(self.items):
            raise IndexError(f"no preference item at index {index}")
        self.pending[int(index)] = value

    def revert(self) -> None:
        """Drop every pending edit. Does not touch the store or the file."""
        self.pending.clear()

    def apply(self) -> ApplyResult:
        """Write the pending edits through the preferences store.

        Each edit is coerced to its declared type and passed to
        ``prefs.set``, which persists the file. On the first failure the
        write stops and the message is returned: edits already written stay
        written and the pending map is left ALONE, so the user can fix the
        offending value and press Apply again without retyping the rest.
        MATLAB behaves the same way.
        """
        result = ApplyResult()
        for index in sorted(self.pending):
            item = self.items[index]
            path = item_path(item)
            try:
                value = coerce_value(self.pending[index], item.get("type", ""))
                self._prefs.set(path, value)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                result.error = f"Could not set {path}: {exc}"
                return result
            result.applied.append(path)
        self.pending.clear()
        self.refresh()
        return result

    def refresh(self) -> None:
        """Re-read the item snapshot from the store."""
        self.items = list(self._prefs.list_items())

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"PreferencesEditorState(items={len(self.items)}, "
            f"pending={len(self.pending)}, selection={self.selection!r})"
        )


def _default_prefs() -> Any:
    """The process-wide preferences singleton.

    Imported lazily so this module can be imported (and its model tested)
    without constructing the singleton, which reads the user's JSON file.
    """
    from ..preferences import get_singleton

    return get_singleton()


# ----------------------------------------------------------------------
# the window
# ----------------------------------------------------------------------
class PreferencesEditor:
    """The NDI preferences window.

    Args:
        position: ``(x, y, width, height)`` in pixels.
        prefs: Preferences store to edit; the singleton by default.
        build: Build the widgets now. False builds the state only, which is
            how the model is exercised without a display.
    """

    def __init__(
        self,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        prefs: Any = None,
        build: bool = True,
    ):
        self.state = PreferencesEditorState(prefs)
        self.position = tuple(position)
        self.figure: Any = None
        self.tree_widget: Any = None
        self.rows_area: Any = None
        self.rows_host: Any = None
        #: index -> QLabel / editor widget for the rows currently drawn.
        self.row_labels: dict[int, Any] = {}
        self.row_widgets: dict[int, Any] = {}
        if build:
            self.build()

    # -- construction --------------------------------------------------
    def build(self) -> Any:
        """Create the window: header bar, tree, row pane, button row."""
        from ._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        x, y, w, h = self.position

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle("NDI Preferences")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {rgb_to_hex(c.off_white)};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_header())

        splitter = QtWidgets.QHBoxLayout()
        splitter.setSpacing(8)
        self.tree_widget = self._build_tree_widget()
        splitter.addWidget(self.tree_widget, 3)
        splitter.addWidget(self._build_rows_area(), 7)
        root.addLayout(splitter, 1)

        root.addLayout(self._build_button_row())

        self.rebuild_rows()
        return self.figure

    def _build_header(self) -> Any:
        """The navy title bar, white bold text -- the NDI Cloud header."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        header = QtWidgets.QLabel("NDI Preferences")
        header.setFixedHeight(HEADER_HEIGHT)
        header.setStyleSheet(
            f"background-color: {rgb_to_hex(c.dark_blue)}; "
            f"color: {rgb_to_hex(c.white)}; font-weight: bold; "
            f"font-size: 14px; padding-left: 8px;"
        )
        return header

    def _build_tree_widget(self) -> Any:
        """The left tree, one top-level row per category."""
        from PySide6 import QtCore, QtWidgets

        tree = QtWidgets.QTreeWidget()
        tree.setObjectName("ndiPrefTree")
        tree.setHeaderHidden(True)
        role = QtCore.Qt.ItemDataRole.UserRole

        first: Any = None
        for node in self.state.tree():
            top = QtWidgets.QTreeWidgetItem([node.text])
            top.setData(0, role, (node.category, node.subcategory))
            tree.addTopLevelItem(top)
            for child in node.children:
                leaf = QtWidgets.QTreeWidgetItem([child.text])
                leaf.setData(0, role, (child.category, child.subcategory))
                top.addChild(leaf)
            top.setExpanded(True)
            if first is None:
                first = top

        if first is not None:
            tree.setCurrentItem(first)
        # Connected after the initial selection so building the tree does not
        # fire a rebuild before the rows pane exists.
        tree.currentItemChanged.connect(self._on_tree_select)
        return tree

    def _build_rows_area(self) -> Any:
        """The scrollable right pane the rows are drawn into."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        self.rows_area = QtWidgets.QScrollArea()
        self.rows_area.setObjectName("ndiPrefRightPanel")
        self.rows_area.setWidgetResizable(True)
        self.rows_area.setStyleSheet(f"background-color: {rgb_to_hex(c.white)};")
        self.rows_host = QtWidgets.QWidget()
        self.rows_area.setWidget(self.rows_host)
        return self.rows_area

    def _build_button_row(self) -> Any:
        """Revert | Apply | Save, right-aligned."""
        from PySide6 import QtWidgets

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        for text, slot in (
            ("Revert", self.on_revert),
            ("Apply", self.on_apply),
            ("Save", self.on_save),
        ):
            button = QtWidgets.QPushButton(text)
            button.setObjectName(f"ndiPref{text}Button")
            button.setFixedWidth(BUTTON_WIDTH)
            button.clicked.connect(slot)
            self._accent_button(button)
            row.addWidget(button)
        return row

    @staticmethod
    def _accent_button(button: Any) -> None:
        """Light-blue fill, bold navy text -- as the navigator's buttons."""
        c = cloud_colors()
        button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; "
            f"color: {rgb_to_hex(c.dark_blue)}; font-weight: bold;"
        )

    # -- the right pane ------------------------------------------------
    def rebuild_rows(self) -> list[PreferenceRow]:
        """Draw one row per preference in the current selection.

        Returns the rows drawn, which is what makes the pane checkable
        without reading widgets back out.
        """
        rows = self.state.rows()
        if self.rows_area is None:
            return rows

        from PySide6 import QtWidgets

        self.row_labels.clear()
        self.row_widgets.clear()

        host = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(host)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        heading_left = QtWidgets.QLabel("Preference")
        heading_right = QtWidgets.QLabel("Value")
        for heading in (heading_left, heading_right):
            heading.setStyleSheet("font-weight: bold;")
        grid.addWidget(heading_left, 0, 0)
        grid.addWidget(heading_right, 0, 1)

        for offset, row in enumerate(rows):
            label = QtWidgets.QLabel(row.label)
            label.setToolTip(row.description)
            label.setFixedHeight(ROW_HEIGHT)
            grid.addWidget(label, offset + 1, 0)

            widget = self._make_editor_widget(row)
            grid.addWidget(widget, offset + 1, 1)

            self.row_labels[row.index] = label
            self.row_widgets[row.index] = widget

        grid.setRowStretch(len(rows) + 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Replacing the scroll area's widget deletes the previous one and
        # every row in it, which is how the old widget set is discarded.
        self.rows_area.setWidget(host)
        self.rows_host = host
        return rows

    def _make_editor_widget(self, row: PreferenceRow) -> Any:
        """Build the editor widget for one row, chosen by its kind."""
        from PySide6 import QtGui, QtWidgets

        index = row.index
        if row.kind == "bool":
            widget = QtWidgets.QCheckBox()
            widget.setChecked(bool(row.value))
            widget.toggled.connect(lambda checked, i=index: self._on_value_changed(i, checked))
        else:
            widget = QtWidgets.QLineEdit(display_text(row.value))
            if row.kind == "numeric":
                # A validator keeps obvious nonsense out of the field; the
                # value is coerced again on Apply, because a validator cannot
                # reject every partial entry ('-', '1e').
                widget.setValidator(QtGui.QDoubleValidator(widget))
            widget.editingFinished.connect(
                lambda i=index, w=widget: self._on_value_changed(i, w.text())
            )
        widget.setToolTip(row.description)
        widget.setFixedHeight(ROW_HEIGHT)
        return widget

    # -- callbacks -----------------------------------------------------
    def _on_tree_select(self, current: Any = None, previous: Any = None) -> None:
        """Tree selection changed: point the state at it and redraw."""
        if current is None:
            return
        from PySide6 import QtCore

        data = current.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not data:
            return
        category, subcategory = data
        self.state.select(category, subcategory)
        self.rebuild_rows()

    def _on_value_changed(self, index: int, value: Any) -> None:
        """A widget was edited: record it as pending and mark the row.

        A line edit reports ``editingFinished`` when it merely loses focus,
        so a value equal to the saved one is dropped rather than recorded --
        otherwise tabbing across the pane would asterisk every row and hand
        Apply a pile of writes the user never made. MATLAB's
        ``ValueChangedFcn`` fires only on a real change, and this is what
        makes Qt behave the same way. A row that is ALREADY pending keeps its
        edit: retyping the saved value there is a change to the pending one.

        The label is marked in place rather than by redrawing the pane: a
        rebuild would take focus off the field the user is still working in.
        """
        if index not in self.state.pending and display_text(value) == display_text(
            self.state.items[index]["value"]
        ):
            return
        self.state.set_pending(index, value)
        label = self.row_labels.get(index)
        if label is not None and not label.text().endswith(PENDING_MARK):
            label.setText(label.text() + PENDING_MARK)

    def on_revert(self) -> None:
        """Revert: drop pending edits and show the saved values again."""
        self.state.revert()
        self.rebuild_rows()

    def on_apply(self) -> ApplyResult:
        """Apply: write the pending edits, then redraw without asterisks.

        Returns the :class:`ApplyResult` so a caller (or a test) can see what
        was written; a failure is also shown on the window.
        """
        result = self.state.apply()
        if result.error is not None:
            self._alert(result.error, "Apply failed", success=False)
        self.rebuild_rows()
        return result

    def on_save(self) -> ApplyResult:
        """Save: Apply, then close the window if everything was written.

        A failed Apply leaves the window OPEN with the offending edit still
        pending, so the value the user has to fix is still in front of them.
        """
        result = self.on_apply()
        if result.ok:
            self.close()
        return result

    # -- window --------------------------------------------------------
    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def is_open(self) -> bool:
        """Whether the window exists and has not been closed."""
        if self.figure is None:
            return False
        try:
            return bool(self.figure.isVisible())
        except RuntimeError:
            # The underlying C++ widget is gone.
            return False

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    def _alert(self, message: str, title: str, *, success: bool = True) -> None:
        """Show a message on the editor window, if there is one."""
        if self.figure is None:
            return
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(
            QtWidgets.QMessageBox.Icon.Information
            if success
            else QtWidgets.QMessageBox.Icon.Warning
        )
        box.exec()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"PreferencesEditor(state={self.state!r})"


def preferences_editor(
    *,
    position: tuple[float, float, float, float] = DEFAULT_POSITION,
    prefs: Any = None,
    visible: bool = True,
) -> PreferencesEditor:
    """Open the NDI preferences editor and return it.

    Mirrors the MATLAB entry point ``ndi.gui.preferencesEditor``. The
    returned object must be KEPT: a Qt window with no Python reference is
    garbage collected and disappears, where MATLAB's figure would stay up on
    its own.
    """
    editor = PreferencesEditor(position=position, prefs=prefs)
    if visible:
        editor.show()
    return editor


#: MATLAB-cased alias, as elsewhere in this package.
preferencesEditor = preferences_editor  # noqa: N816
