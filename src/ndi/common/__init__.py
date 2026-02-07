"""
ndi.common - common utilities for NDI

Provides path constants, timestamps, and other shared utilities.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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
    _ndi_root: Optional[Path] = None
    _common_folder: Optional[Path] = None
    _document_path: Optional[Path] = None
    _schema_path: Optional[Path] = None

    @classmethod
    def _find_ndi_root(cls) -> Path:
        """Find the NDI root directory.

        Looks for environment variable NDI_ROOT, or tries to find it
        relative to this package. Searches multiple possible locations.
        """
        if os.environ.get('NDI_ROOT'):
            return Path(os.environ['NDI_ROOT'])

        # Try to find it relative to this file
        # src/ndi/common/__init__.py -> src/ndi/common -> src/ndi -> src -> repo_root
        package_dir = Path(__file__).parent.parent.parent.parent

        # Check multiple possible locations for ndi_common
        possible_paths = [
            package_dir / 'ndi_common',              # repo_root/ndi_common
            package_dir / 'src' / 'ndi' / 'ndi_common',  # repo_root/src/ndi/ndi_common
        ]

        for path in possible_paths:
            if path.exists() and (path / 'database_documents').exists():
                # Return the parent that contains ndi_common
                return path.parent

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
            cls._common_folder = cls.NDI_ROOT / 'ndi_common'
        return cls._common_folder

    @classmethod
    @property
    def DOCUMENT_PATH(cls) -> Path:
        """Path to document JSON definitions."""
        if cls._document_path is None:
            cls._document_path = cls.COMMON_FOLDER / 'database_documents'
        return cls._document_path

    @classmethod
    @property
    def SCHEMA_PATH(cls) -> Path:
        """Path to JSON schema files."""
        if cls._schema_path is None:
            cls._schema_path = cls.COMMON_FOLDER / 'schema_documents'
        return cls._schema_path

    @classmethod
    def set_paths(
        cls,
        ndi_root: Optional[Path] = None,
        common_folder: Optional[Path] = None,
        document_path: Optional[Path] = None,
        schema_path: Optional[Path] = None
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
    return now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def get_logger(name: str = 'ndi'):
    """Get a logger for NDI components.

    Args:
        name: Logger name (default: 'ndi').

    Returns:
        logging.Logger instance.
    """
    import logging
    return logging.getLogger(name)


__all__ = ['PathConstants', 'timestamp', 'get_logger']
