"""
ndi.common - common utilities for NDI.

MATLAB equivalent: +ndi/+common

Provides path constants, cache, logger, and other shared utilities.

MATLAB functions:
    ndi.common.ndi_common_PathConstants
    ndi.common.assertDIDInstalled
    ndi.common.getCache
    ndi.common.getDatabaseHierarchy
    ndi.common.getLogger
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any


class ndi_common_PathConstants:
    """NDI path constants for document definitions and schemas.

    This class provides paths to NDI document definitions, schemas,
    and other common resources.

    Class Attributes:
        NDI_ROOT: Root directory of NDI installation.
        COMMON_FOLDER: Path to ndi_common folder with shared resources.
        DOCUMENT_PATH: Path to document JSON definitions.
        SCHEMA_PATH: Path to JSON schema files.
    """

    # These can be overridden by environment variables or set programmatically
    _ndi_root: Path | None = None
    _common_folder: Path | None = None
    _document_path: Path | None = None
    _schema_path: Path | None = None

    @classmethod
    def _find_ndi_root(cls) -> Path:
        """Find the NDI root directory.

        Looks for environment variable NDI_ROOT, or tries to find it
        relative to this package. The ndi_common directory lives inside
        the ndi package (src/ndi/ndi_common), so the root is the ndi
        package directory itself.
        """
        if os.environ.get("NDI_ROOT"):
            return Path(os.environ["NDI_ROOT"])

        # ndi_common is inside the ndi package directory.
        # src/ndi/common/__init__.py -> common -> ndi (package root)
        package_dir = Path(__file__).parent.parent

        if (package_dir / "ndi_common" / "database_documents").exists():
            return package_dir

        raise ValueError(
            "Cannot find NDI root directory. "
            "Set NDI_ROOT environment variable or install NDI properly."
        )

    @classmethod
    @property
    def NDI_ROOT(cls) -> Path:
        """Root directory of NDI installation."""
        if cls._ndi_root is None:
            cls._ndi_root = cls._find_ndi_root()
        return cls._ndi_root

    @classmethod
    @property
    def COMMON_FOLDER(cls) -> Path:
        """Path to ndi_common folder with shared resources."""
        if cls._common_folder is None:
            cls._common_folder = cls.NDI_ROOT / "ndi_common"
        return cls._common_folder

    @classmethod
    @property
    def DOCUMENT_PATH(cls) -> Path:
        """Path to document JSON definitions."""
        if cls._document_path is None:
            cls._document_path = cls.COMMON_FOLDER / "database_documents"
        return cls._document_path

    @classmethod
    @property
    def SCHEMA_PATH(cls) -> Path:
        """Path to JSON schema files."""
        if cls._schema_path is None:
            cls._schema_path = cls.COMMON_FOLDER / "schema_documents"
        return cls._schema_path

    @classmethod
    def set_paths(
        cls,
        ndi_root: Path | None = None,
        common_folder: Path | None = None,
        document_path: Path | None = None,
        schema_path: Path | None = None,
    ) -> None:
        """Set custom paths for NDI resources.

        Args:
            ndi_root: Custom NDI root directory.
            common_folder: Custom path to common folder.
            document_path: Custom path to document definitions.
            schema_path: Custom path to schema files.
        """
        if ndi_root is not None:
            cls._ndi_root = Path(ndi_root)
        if common_folder is not None:
            cls._common_folder = Path(common_folder)
        if document_path is not None:
            cls._document_path = Path(document_path)
        if schema_path is not None:
            cls._schema_path = Path(schema_path)
        # Paths moved: re-register them with DID so its resolver follows.
        updateDIDConstants(force=True)


# ---------------------------------------------------------------------------
# DID globals — mirrors MATLAB ndi.common.PathConstants.updateDIDConstants
# ---------------------------------------------------------------------------

#: NDI's ``$PATH`` placeholders, in the order MATLAB registers them.
#:
#: MATLAB keeps calculator definitions in separate toolboxes and so registers
#: ``$NDICALC*PATH`` as a *list* of directories.  Python has no separate
#: calculator packages: ``ndi_install.py`` copies every dependency's
#: ``ndi_common/{database,schema}_documents`` tree into NDI-python's own
#: ``ndi_common`` folder, so the calculator placeholders resolve to the same
#: two directories as the non-calculator ones.  Recorded rather than papered
#: over: if Python ever grows out-of-tree calculator packages this mapping is
#: where the extra directories belong.
_DID_PLACEHOLDERS = (
    "$NDISCHEMAPATH",
    "$NDIDOCUMENTPATH",
    "$NDICALCSCHEMAPATH",
    "$NDICALCDOCUMENTPATH",
)


def _did_placeholder_values() -> dict[str, str]:
    """Current filesystem target for each NDI ``$PATH`` placeholder."""
    document_path = str(ndi_common_PathConstants.DOCUMENT_PATH)
    schema_path = str(ndi_common_PathConstants.SCHEMA_PATH)
    return {
        "$NDISCHEMAPATH": schema_path,
        "$NDIDOCUMENTPATH": document_path,
        "$NDICALCSCHEMAPATH": schema_path,
        "$NDICALCDOCUMENTPATH": document_path,
    }


def updateDIDConstants(force: bool = False) -> dict[str, str]:
    """Register NDI's ``$PATH`` placeholders with DID's ``PathConstants``.

    MATLAB equivalent: ``ndi.common.PathConstants.updateDIDConstants`` (and the
    ``mustUpdateDidGlobals`` validator that runs when the constant properties
    are first touched).

    DID resolves every ``definition`` and ``validation`` location through
    ``did.common.PathConstants.DEFINITIONS``.  Since DID-python grew a real
    document-vs-schema validator (``did.validate``), which ``add_docs`` runs by
    default, an unregistered placeholder is no longer a silent miss: adding any
    NDI document raises ``Validation file "$NDISCHEMAPATH/....json" not found``.
    MATLAB has always registered these four keys; Python never did.

    Args:
        force: Overwrite entries that are already registered.  The default
            (``False``) mirrors MATLAB, which only fills in keys that are
            absent, so an embedding application can pre-point a placeholder
            somewhere else and keep it.

    Returns:
        The mapping that is now in effect for NDI's placeholders.

    Raises:
        ValueError: if ``$NDIDOCUMENTPATH`` cannot be resolved.  MATLAB raises
            ``'Could not update DID globals'`` for that one key alone; without
            it no NDI document can name its own definition.
    """
    from did.common import PathConstants as _DIDPathConstants

    definitions = _DIDPathConstants.DEFINITIONS
    values = _did_placeholder_values()

    if not values.get("$NDIDOCUMENTPATH"):
        raise ValueError("Could not update DID globals")

    for key in _DID_PLACEHOLDERS:
        value = values.get(key)
        if not value:
            continue
        if force or key not in definitions:
            definitions[key] = value

    return {key: definitions[key] for key in _DID_PLACEHOLDERS if key in definitions}


def timestamp() -> str:
    """Generate an ISO 8601 timestamp in UTC.

    Returns:
        String timestamp in format '2024-01-15T10:30:45.123Z'

    Example:
        >>> ts = timestamp()
        >>> print(ts)
        '2024-01-15T10:30:45.123456Z'
    """
    now = datetime.now(timezone.utc)
    # Format with microseconds and Z suffix
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def getLogger(name: str = "ndi"):
    """Get a logger for NDI components.

    MATLAB equivalent: ndi.common.getLogger

    Args:
        name: Logger name (default: 'ndi').

    Returns:
        logging.Logger instance.
    """
    import logging

    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Singleton cache — mirrors MATLAB ndi.common.getCache
# ---------------------------------------------------------------------------

_cache_singleton: Any = None


def getCache() -> Any:
    """Return the global NDI cache singleton.

    MATLAB equivalent: ndi.common.getCache

    Returns a shared :class:`ndi.cache.ndi_cache` instance, creating it on first
    call. Subsequent calls return the same object.

    Returns:
        The global :class:`~ndi.cache.ndi_cache` instance.
    """
    global _cache_singleton  # noqa: PLW0603
    if _cache_singleton is None:
        from ..cache import ndi_cache

        _cache_singleton = ndi_cache()
    return _cache_singleton


# ---------------------------------------------------------------------------
# ndi_database hierarchy — mirrors MATLAB ndi.common.getDatabaseHierarchy
# ---------------------------------------------------------------------------

_database_hierarchy_singleton: Any = None


def getDatabaseHierarchy() -> dict[str, Any]:
    """Return the database document type hierarchy.

    MATLAB equivalent: ndi.common.getDatabaseHierarchy

    Reads the document definitions from ``ndi_common/database_documents``
    and builds a mapping of document types to their superclasses and fields.
    The result is cached after the first call.

    Returns:
        Dict mapping document type names to their definition metadata.
    """
    global _database_hierarchy_singleton  # noqa: PLW0603
    if _database_hierarchy_singleton is not None:
        return _database_hierarchy_singleton

    import json

    hierarchy: dict[str, Any] = {}
    doc_path = ndi_common_PathConstants.DOCUMENT_PATH
    if doc_path.is_dir():
        for json_file in sorted(doc_path.rglob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                # Each definition has a "document_class" with "definition"
                # containing the type name and superclasses.
                doc_class = data.get("document_class", {})
                def_info = doc_class.get("definition", "")
                if def_info:
                    # Use the definition URL/path stem as the type name
                    type_name = Path(def_info).stem
                    hierarchy[type_name] = {
                        "definition": def_info,
                        "class_version": doc_class.get("class_version", 1),
                        "superclasses": doc_class.get("superclasses", []),
                        "file": str(json_file),
                    }
            except (json.JSONDecodeError, KeyError):
                continue

    _database_hierarchy_singleton = hierarchy
    return _database_hierarchy_singleton


# ---------------------------------------------------------------------------
# DID install check — mirrors MATLAB ndi.common.assertDIDInstalled
# ---------------------------------------------------------------------------


def assertDIDInstalled() -> None:
    """Assert that the DID (ndi_document Interface ndi_database) package is installed.

    MATLAB equivalent: ndi.common.assertDIDInstalled

    Raises:
        ImportError: If the ``did`` package is not installed.
    """
    try:
        import did  # noqa: F401
    except ImportError:
        raise ImportError(
            "The 'did' package is required but not installed. " "Install it with: pip install did"
        ) from None


__all__ = [
    "ndi_common_PathConstants",
    "timestamp",
    "getLogger",
    "getCache",
    "getDatabaseHierarchy",
    "assertDIDInstalled",
]


# Register NDI's $PATH placeholders with DID as soon as ``ndi.common`` is
# imported — DID's validator runs on every ``add_docs``, so registration has to
# happen before any NDI document reaches the database.  MATLAB gets this for
# free from constant-property validators; Python needs an explicit call.
#
# A failure here is reported rather than raised: ``import ndi`` has never been
# able to fail on a partially-installed tree, and ``python -m ndi check`` is
# where a broken install is meant to surface.  It is not silent — the warning
# names the exception, and the first document added will fail loudly anyway.
try:
    updateDIDConstants()
except Exception as exc:  # pragma: no cover - only on a broken installation
    import warnings

    warnings.warn(
        "ndi.common could not register NDI's $PATH placeholders with DID "
        f"({exc!r}); document validation and superclass resolution will fail. "
        "Run 'python -m ndi check'.",
        RuntimeWarning,
        stacklevel=2,
    )
