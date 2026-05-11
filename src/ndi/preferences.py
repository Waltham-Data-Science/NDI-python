"""
ndi.preferences - Singleton store of NDI-python user preferences.

This module mirrors the MATLAB ``ndi.preferences`` singleton (see
``src/ndi/+ndi/preferences.m`` in NDI-matlab). It manages a process-wide
collection of user-editable preferences that persist to disk as JSON.

Each preference is represented by a :class:`PreferenceItem` with fields
matching the MATLAB struct: ``category``, ``subcategory``, ``name``,
``value``, ``default_value``, ``description``, ``type``.

Persistence
-----------
Values are stored as JSON at::

    ~/.ndi/NDI_Preferences.json

The file is read once on first access and rewritten by
:func:`ndi_preferences.set` and :func:`ndi_preferences.reset`. A missing
or corrupt file is tolerated: defaults are used and a warning is issued.

MATLAB deviates here by using ``fullfile(prefdir, 'NDI_Preferences.json')``
(MATLAB's per-installation prefdir). Python has no equivalent of
``prefdir``, so we use ``~/.ndi/NDI_Preferences.json``. The directory
is created on first save.

Access
------
Most callers should use the module-level convenience functions::

    import ndi

    value = ndi.preferences.get('Cloud.Upload.Max_File_Batch_Size')
    ndi.preferences.set('Cloud.Upload.Max_File_Batch_Size', 1_000_000_000)
    ndi.preferences.reset('Cloud.Upload.Max_File_Batch_Size')
    ndi.preferences.reset()                # reset every preference
    items = ndi.preferences.list_items()   # list of PreferenceItem
    has   = ndi.preferences.has('Cloud.Upload.Foo')
    path  = ndi.preferences.filename()

The underlying singleton object can be obtained with
:func:`get_singleton` (mirrors MATLAB's ``ndi.preferences.getSingleton``).

Conventions
-----------
Preference paths are dotted strings of the form ``Category.Name`` or
``Category.Subcategory.Name``. Lookups are case-sensitive.

Adding a new preference
-----------------------
Edit :meth:`ndi_preferences._register_defaults` and add an
``self._add_item(category, subcategory, name, default, type_, description)``
call. The new preference becomes available on next interpreter start (or
after calling :func:`_reset_singleton` from tests).
"""

from __future__ import annotations

import json
import os
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "PreferenceItem",
    "ndi_preferences",
    "get_singleton",
    "preferences",
    "get",
    "set",
    "reset",
    "list_items",
    "has",
    "filename",
]


@dataclass
class PreferenceItem:
    """A single preference entry.

    Mirrors the MATLAB Items struct fields.

    Attributes:
        category: Top-level grouping (e.g. ``'Cloud'``).
        subcategory: Optional second-level grouping (e.g. ``'Upload'``).
            Empty string when unused.
        name: Leaf identifier (e.g. ``'Max_File_Batch_Size'``).
        value: Current value.
        default_value: Value used on first run and after reset.
        description: Human-readable explanation; used as tooltip by the
            preferences editor and shown by :func:`list_items`.
        type: Expected Python type name used to coerce values when
            reloading from JSON. One of ``'float'``, ``'int'``,
            ``'bool'``, ``'str'``, or ``'any'``.
    """

    category: str
    subcategory: str
    name: str
    value: Any
    default_value: Any
    description: str
    type: str = "any"

    def key(self) -> str:
        """Build the JSON field name for this item.

        Returns ``'Category__Name'`` when subcategory is empty,
        otherwise ``'Category__Subcategory__Name'``. Matches the
        MATLAB ``itemKey`` static helper so files written by either
        language round-trip cleanly.
        """
        if not self.subcategory:
            return f"{self.category}__{self.name}"
        return f"{self.category}__{self.subcategory}__{self.name}"

    def path(self) -> str:
        """Return the dotted public path for this preference."""
        if not self.subcategory:
            return f"{self.category}.{self.name}"
        return f"{self.category}.{self.subcategory}.{self.name}"


def _default_filename() -> Path:
    """Return the absolute path of the JSON file used for persistence.

    Deviates from MATLAB ``fullfile(prefdir, 'NDI_Preferences.json')``
    because Python has no equivalent of MATLAB's per-installation
    ``prefdir``. We use ``~/.ndi/NDI_Preferences.json`` and create the
    directory lazily on first save.
    """
    return Path.home() / ".ndi" / "NDI_Preferences.json"


class ndi_preferences:
    """Singleton store of NDI-python user preferences.

    The class follows the singleton pattern: the first reference (via
    :func:`get_singleton`) creates the instance and loads any persisted
    values; every subsequent reference returns the same in-memory
    object.

    Direct construction is allowed but is intended only for tests; most
    code should call the module-level :func:`get`, :func:`set`, etc.
    """

    # Set of recognised type-coercion strings.
    _COERCERS = {"float", "int", "bool", "str", "any"}

    def __init__(self, filename: str | os.PathLike | None = None) -> None:
        """Initialise the preferences store.

        Args:
            filename: Optional path of the JSON file to use. Defaults to
                ``~/.ndi/NDI_Preferences.json``. Tests may pass a
                temporary path here.
        """
        self._filename: Path = Path(filename) if filename else _default_filename()
        self._items: list[PreferenceItem] = []
        self._register_defaults()
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Default registration
    # ------------------------------------------------------------------
    def _register_defaults(self) -> None:
        """Populate :attr:`_items` with the built-in NDI preferences.

        This is the canonical place to add new preferences. Each call to
        :meth:`_add_item` registers one item with its category,
        subcategory, name, default value, expected type, and a short
        description used by :func:`list_items` and any future
        preferences editor.
        """
        self._add_item(
            "Cloud", "Download", "Max_Document_Batch_Count",
            10000, "int",
            "Maximum number of documents downloaded per batch.",
        )
        self._add_item(
            "Cloud", "Upload", "Max_Document_Batch_Count",
            100000, "int",
            "Maximum number of documents uploaded per batch.",
        )
        self._add_item(
            "Cloud", "Upload", "Max_File_Batch_Size",
            500_000_000, "float",
            "Maximum size of file batch upload in bytes (default 500 MB).",
        )

    def _add_item(
        self,
        category: str,
        subcategory: str,
        name: str,
        default_value: Any,
        type_: str,
        description: str,
    ) -> None:
        """Append one preference item to :attr:`_items`.

        Both ``value`` and ``default_value`` are initialised to
        ``default_value``.
        """
        self._items.append(
            PreferenceItem(
                category=str(category),
                subcategory=str(subcategory),
                name=str(name),
                value=default_value,
                default_value=default_value,
                description=str(description),
                type=str(type_),
            )
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_from_disk(self) -> None:
        """Overlay persisted values onto registered defaults.

        Called once during construction. Reads the JSON file at
        :attr:`_filename`, decodes it, and copies each matching value
        back into the items list (after type coercion). Items not
        present in the file keep their default value.

        A missing file is silently ignored (first-run case). Any other
        error is reported via :func:`warnings.warn` and defaults remain
        in effect.
        """
        if not self._filename.is_file():
            return
        try:
            text = self._filename.read_text(encoding="utf-8")
            if not text.strip():
                return
            data = json.loads(text)
            if not isinstance(data, dict):
                return
            for item in self._items:
                key = item.key()
                if key in data:
                    item.value = self._coerce_type(data[key], item.type)
        except Exception as exc:  # noqa: BLE001 - mirror MATLAB behaviour
            warnings.warn(
                f"NDI:preferences:loadFailed: could not load preferences "
                f"from {self._filename}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    def _save_to_disk(self) -> None:
        """Write the current values to the JSON file.

        Builds a flat dict keyed by :meth:`PreferenceItem.key` and writes
        it pretty-printed. Failures are reported via
        :func:`warnings.warn`; the in-memory state is unaffected.
        """
        payload = {item.key(): item.value for item in self._items}
        try:
            self._filename.parent.mkdir(parents=True, exist_ok=True)
            self._filename.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - mirror MATLAB behaviour
            warnings.warn(
                f"NDI:preferences:saveFailed: could not save preferences "
                f"to {self._filename}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    def _find_item(self, category: str, subcategory: str, name: str) -> int:
        """Locate a preference by category / subcategory / name.

        Returns:
            Index into :attr:`_items` of the matching item.

        Raises:
            KeyError: If no item matches. The message shows the dotted
                path that was requested. Mirrors the MATLAB
                ``NDI:preferences:unknownPreference`` error.
        """
        for idx, item in enumerate(self._items):
            if (
                item.category == category
                and item.subcategory == subcategory
                and item.name == name
            ):
                return idx
        if not subcategory:
            path_str = f"{category}.{name}"
        else:
            path_str = f"{category}.{subcategory}.{name}"
        raise KeyError(f'Unknown preference "{path_str}".')

    @staticmethod
    def _parse_path(path_str: str) -> tuple[str, str, str]:
        """Split a dotted preference path into its components.

        Returns:
            Tuple ``(category, subcategory, name)``. ``subcategory`` is
            the empty string for two-part paths.

        Raises:
            ValueError: If the path is not two- or three-part. Mirrors
                the MATLAB ``NDI:preferences:invalidPath`` error.
        """
        parts = str(path_str).split(".")
        if len(parts) == 2:
            return parts[0], "", parts[1]
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        raise ValueError(
            f'Preference path must be Category.Name or '
            f'Category.Subcategory.Name (got "{path_str}").'
        )

    @classmethod
    def _coerce_type(cls, raw_value: Any, type_name: str) -> Any:
        """Convert a JSON-decoded value back to its declared type.

        Any conversion failure returns ``raw_value`` unchanged so a
        corrupt JSON payload does not break the session.
        """
        if not type_name or type_name == "any":
            return raw_value
        try:
            if type_name == "bool":
                return bool(raw_value)
            if type_name == "int":
                return int(raw_value)
            if type_name == "float":
                return float(raw_value)
            if type_name == "str":
                return str(raw_value)
        except (TypeError, ValueError):
            return raw_value
        return raw_value

    # ------------------------------------------------------------------
    # Public API (instance)
    # ------------------------------------------------------------------
    @property
    def filename(self) -> str:
        """Absolute path of the on-disk preferences file."""
        return str(self._filename)

    @property
    def items(self) -> list[PreferenceItem]:
        """Snapshot of all registered preference items.

        Returns a shallow copy of the internal list, so callers may not
        mutate the live store through this property.
        """
        return list(self._items)

    def get(self, path_str: str) -> Any:
        """Return the current value of the preference at *path_str*."""
        category, subcategory, name = self._parse_path(path_str)
        idx = self._find_item(category, subcategory, name)
        return self._items[idx].value

    def set(self, path_str: str, value: Any) -> None:
        """Update a preference and persist the change.

        No type validation is performed: the value is stored verbatim.
        The ``type`` field on the item is metadata used only when
        reloading the file.
        """
        category, subcategory, name = self._parse_path(path_str)
        idx = self._find_item(category, subcategory, name)
        self._items[idx].value = value
        self._save_to_disk()

    def reset(self, path_str: str | None = None) -> None:
        """Restore preference defaults and persist.

        With no argument, restores every preference to its registered
        ``default_value``. With *path_str*, restores only that one.
        """
        if path_str is None:
            for item in self._items:
                item.value = item.default_value
        else:
            category, subcategory, name = self._parse_path(path_str)
            idx = self._find_item(category, subcategory, name)
            self._items[idx].value = self._items[idx].default_value
        self._save_to_disk()

    def has(self, path_str: str) -> bool:
        """Return ``True`` if *path_str* identifies a registered item.

        Unlike :meth:`get`, never raises: malformed paths simply return
        ``False``.
        """
        try:
            category, subcategory, name = self._parse_path(path_str)
        except ValueError:
            return False
        for item in self._items:
            if (
                item.category == category
                and item.subcategory == subcategory
                and item.name == name
            ):
                return True
        return False

    def list_items(self) -> list[dict[str, Any]]:
        """Return a list of dicts describing every registered item.

        Each dict has keys ``category``, ``subcategory``, ``name``,
        ``value``, ``default_value``, ``description``, ``type``. Modifying
        the returned list does not affect the singleton.
        """
        return [asdict(item) for item in self._items]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        groups: dict[str, dict[str, Any]] = {}
        for item in self._items:
            label = (
                f"{item.subcategory}_{item.name}" if item.subcategory else item.name
            )
            groups.setdefault(item.category, {})[label] = item.value
        lines = [f"ndi_preferences(filename={self._filename!s})"]
        for cat, entries in groups.items():
            lines.append(f"  [{cat}]")
            for label, value in entries.items():
                lines.append(f"    {label} = {value!r}")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Module-level singleton accessor (mirrors MATLAB static methods)
# ----------------------------------------------------------------------
_singleton: ndi_preferences | None = None


def get_singleton() -> ndi_preferences:
    """Return the shared :class:`ndi_preferences` instance.

    The first call constructs the object (which loads the JSON file
    from disk); later calls reuse it. Mirrors MATLAB's
    ``ndi.preferences.getSingleton``.
    """
    global _singleton
    if _singleton is None:
        _singleton = ndi_preferences()
    return _singleton


def preferences() -> ndi_preferences:
    """Alias for :func:`get_singleton`. Pythonic accessor."""
    return get_singleton()


def _reset_singleton() -> None:
    """Discard the cached singleton (test helper, not public API)."""
    global _singleton
    _singleton = None


# ----------------------------------------------------------------------
# Module-level convenience functions (mirror MATLAB static methods)
# ----------------------------------------------------------------------
def get(path_str: str) -> Any:  # noqa: A001 - mirror MATLAB API
    """Return the value of the preference at *path_str*.

    Equivalent to ``ndi.preferences.get(path_str)`` in MATLAB.
    """
    return get_singleton().get(path_str)


def set(path_str: str, value: Any) -> None:  # noqa: A001 - mirror MATLAB API
    """Set the preference at *path_str* to *value* and persist.

    Equivalent to ``ndi.preferences.set(path_str, value)`` in MATLAB.
    """
    get_singleton().set(path_str, value)


def reset(path_str: str | None = None) -> None:
    """Reset one preference to its default, or all if *path_str* is None.

    Equivalent to ``ndi.preferences.reset`` in MATLAB.
    """
    get_singleton().reset(path_str)


def list_items() -> list[dict[str, Any]]:
    """Return a list of dicts describing every registered preference.

    Equivalent to ``ndi.preferences.list()`` in MATLAB. Renamed from
    ``list`` to avoid shadowing the Python built-in.
    """
    return get_singleton().list_items()


def has(path_str: str) -> bool:
    """Return ``True`` if *path_str* identifies a registered preference.

    Equivalent to ``ndi.preferences.has(path_str)`` in MATLAB. Never
    raises: malformed paths return ``False``.
    """
    return get_singleton().has(path_str)


def filename() -> str:
    """Return the absolute path of the on-disk preferences file.

    Equivalent to ``ndi.preferences.filename()`` in MATLAB.
    """
    return get_singleton().filename
