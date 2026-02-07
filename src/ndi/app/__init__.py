"""
ndi.app - Base class for NDI applications.

An App operates on a Session and can create/find/store documents
that record the app's name, version, and execution environment.

MATLAB equivalent: src/ndi/+ndi/app.m
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Tuple

from ..documentservice import DocumentService

if TYPE_CHECKING:
    from ..document import Document
    from ..query import Query
    from ..session.session_base import Session


class App(DocumentService):
    """
    Base class for NDI applications.

    An App is attached to a Session and can create documents that
    record metadata about the app (name, version, URL, OS info).

    Attributes:
        session: The ndi.Session this app operates on
        name: The name of the application

    Example:
        >>> app = App(session, 'my_analysis')
        >>> doc = app.newdocument()
    """

    def __init__(
        self,
        session: Session | None = None,
        name: str = "generic",
    ):
        self._session = session
        self._name = name

    @property
    def session(self) -> Session | None:
        """Get the session."""
        return self._session

    @property
    def name(self) -> str:
        """Get the app name."""
        return self._name

    def varappname(self) -> str:
        """
        Return name sanitized as a valid Python identifier.

        Replaces invalid characters with underscores and ensures
        the name starts with a letter or underscore.

        Returns:
            Sanitized name string
        """
        an = re.sub(r"[^0-9a-zA-Z_]", "_", self._name)
        if an and an[0].isdigit():
            an = "_" + an
        if not an:
            an = "_app"
        return an

    def version_url(self) -> tuple[str, str]:
        """
        Return (version, url) for this app.

        Tries to read from git; falls back to defaults.
        Subclasses can override for different version control.

        Returns:
            Tuple of (version_string, repository_url)
        """
        try:
            module_file = Path(sys.modules[self.__class__.__module__].__file__)
            parent_dir = str(module_file.parent)
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=parent_dir,
                timeout=5,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
            else:
                version = "$Format:%H$"

            result_url = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                cwd=parent_dir,
                timeout=5,
            )
            if result_url.returncode == 0:
                url = result_url.stdout.strip()
            else:
                url = "https://github.com/Waltham-Data-Science/NDI-python"
        except Exception:
            version = "$Format:%H$"
            url = "https://github.com/Waltham-Data-Science/NDI-python"

        return version, url

    def newdocument(self) -> Document:
        """
        Create a new 'app' document with environment metadata.

        Returns:
            Document of type 'app'
        """
        from ..document import Document

        version, url = self.version_url()

        doc = Document(
            "app",
            **{
                "app.name": self._name,
                "app.version": version,
                "app.url": url,
                "app.os": platform.system(),
                "app.os_version": platform.version(),
                "app.interpreter": "Python",
                "app.interpreter_version": sys.version.split()[0],
            },
        )

        if self._session is not None:
            doc.set_session_id(self._session.id())

        return doc

    def searchquery(self) -> Query:
        """
        Return a query to find this app's documents.

        Matches on app.name == varappname().

        Returns:
            Compound Query object
        """
        from ..query import Query

        q = Query("").isa("app") & (Query("app.name") == self.varappname())
        return q

    def __repr__(self) -> str:
        return f"App('{self._name}')"
