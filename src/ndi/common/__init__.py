"""
ndi.common - common utilities for NDI.

MATLAB equivalent: +ndi/+common

Provides path constants, cache, logger, and other shared utilities.

MATLAB functions:
    ndi.common.PathConstants
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


class PathConstants:
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


# Keep old name for backwards compatibility
get_logger = getLogger


# ---------------------------------------------------------------------------
# Singleton cache — mirrors MATLAB ndi.common.getCache
# ---------------------------------------------------------------------------

_cache_singleton: Any = None


def getCache() -> Any:
    """Return the global NDI cache singleton.

    MATLAB equivalent: ndi.common.getCache

    Returns a shared :class:`ndi.cache.Cache` instance, creating it on first
    call. Subsequent calls return the same object.

    Returns:
        The global :class:`~ndi.cache.Cache` instance.
    """
    global _cache_singleton  # noqa: PLW0603
    if _cache_singleton is None:
        from ..cache import Cache

        _cache_singleton = Cache()
    return _cache_singleton


# ---------------------------------------------------------------------------
# Database hierarchy — mirrors MATLAB ndi.common.getDatabaseHierarchy
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
    doc_path = PathConstants.DOCUMENT_PATH
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
    """Assert that the DID (Document Interface Database) package is installed.

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
    "PathConstants",
    "timestamp",
    "getLogger",
    "get_logger",
    "getCache",
    "getDatabaseHierarchy",
    "assertDIDInstalled",
]
