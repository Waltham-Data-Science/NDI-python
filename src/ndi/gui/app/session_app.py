"""ndi.gui.app.session_app - the interface a session GUI app adopts.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/sessionApp.m``

A class marks itself as a session GUI app -- one the navigator offers in a
session's "Apps" context menu -- by subclassing :class:`SessionApp` and
giving it a ``Name``. Opening one is then uniform in both languages:
construct it with the session as its first argument.

    class MyViewer(SessionApp):
        Name = "My Viewer"

        def __init__(self, session):
            ...  # build the window

DISCOVERED, NOT REGISTERED
:meth:`SessionApp.list` walks a set of packages and reports every concrete
subclass it finds. Nothing keeps a list of apps, in either language, which is
the point: a lab adds its own app by putting a subclass in one of its own
packages and naming that package in the ``GUI.Navigator.SessionAppPackages``
preference. No edit to NDI, and no import of the app anywhere in NDI.

WHAT "CONCRETE" MEANS HERE
MATLAB declares ``Name`` an abstract constant, so a subclass that does not
supply one is abstract and ``meta.class`` says so. Python has no such
declaration to read, so ``Name`` is an annotation with no value: a subclass
that never assigns it does not have the attribute at all, and that absence is
what :meth:`SessionApp.is_abstract` tests. An ``abc``-abstract class is
skipped too, so the usual Python way of marking a base class also works.

WHY EVERY IMPORT FAILURE IS SWALLOWED
Discovery imports each module it scans, and one broken app module -- a lab's
half-finished app, an optional dependency that is not installed -- must not
take the Apps menu down with it. So an import error skips that module and
scanning continues, mirroring MATLAB's tolerance of packages that are not on
the path. The cost is that a broken app is silently absent rather than
announced; the menu staying usable is worth more.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from collections.abc import Sequence
from types import ModuleType
from typing import Any, ClassVar

__all__ = ["SessionApp", "sessionApp", "BUILTIN_PACKAGES", "PACKAGES_PREFERENCE"]

#: The packages always scanned for session apps, in scan order. MATLAB's
#: defaultPackages: NDI's own GUI apps, then the analysis apps in ndi.app.
BUILTIN_PACKAGES: tuple[str, ...] = ("ndi.gui.app", "ndi.app")

#: The preference holding the user's extra packages, semicolon- or
#: comma-separated. Registered in :mod:`ndi.preferences` with the same path
#: MATLAB uses, so a user's setting means the same thing in both languages.
PACKAGES_PREFERENCE = "GUI.Navigator.SessionAppPackages"

#: Package-list separators, as MATLAB's parsePackageList splits on.
_SEPARATORS = re.compile(r"[;,]")


class SessionApp:
    """Interface for GUI apps that operate on an :class:`ndi.session`.

    Contract, matching MATLAB's:

    * the constructor takes the session as its first argument, so launching
      is uniform: ``MyApp(session)``, or
      :meth:`SessionApp.launch` given the class name;
    * ``Name`` supplies the menu label and is required -- a subclass without
      one is treated as abstract and never listed;
    * ``Category`` is optional and groups the app into a submenu of that name
      in the Apps menu. Apps that declare none stay at the top level.

    See also :mod:`ndi.gui.nav.datasets_pane` (the menu that consumes this)
    and :func:`ndi.gui.nav.datasets_text.order_app_menu` (its layout).
    """

    #: The label shown in the session "Apps" menu. Abstract: annotated
    #: rather than assigned, so a subclass that does not set it genuinely
    #: lacks the attribute and is skipped by :meth:`list`.
    Name: ClassVar[str]

    #: Optional submenu grouping, "" for none. Concrete here, so an app
    #: opts into a submenu rather than opting out of one.
    Category: ClassVar[str] = ""

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    @staticmethod
    def list(packages: Sequence[str] | None = None) -> list[dict[str, str]]:
        """Discover the concrete session GUI apps in PACKAGES.

        Returns one record per app, in discovery order, with:

            ``Name``     -- the display label;
            ``Class``    -- the fully qualified class name, which
                            :meth:`launch` can resolve;
            ``Category`` -- the grouping label, "" when the app declares
                            none.

        PACKAGES defaults to :meth:`default_packages`. The menu sorts these
        itself (see ``order_app_menu``), so discovery order is only ever
        the tie-break between two labels differing in case.
        """
        if packages is None:
            packages = SessionApp.default_packages()

        apps: list[dict[str, str]] = []
        for cls in SessionApp.classes_in_packages(packages):
            if not SessionApp.is_session_app(cls):
                continue
            if SessionApp.is_abstract(cls):
                continue
            apps.append(
                {
                    "Name": SessionApp.read_name(cls),
                    "Class": class_name(cls),
                    "Category": SessionApp.read_category(cls),
                }
            )
        return apps

    @staticmethod
    def default_packages() -> list[str]:
        """The packages scanned for session apps by default.

        :data:`BUILTIN_PACKAGES` plus whatever the user registered in the
        ``GUI.Navigator.SessionAppPackages`` preference, duplicates dropped
        and order kept. An unreadable preference leaves the built-ins, since
        a missing user setting must not cost the user NDI's own apps.
        """
        extra: Any = ""
        try:
            from ... import preferences as ndi_preferences

            extra = ndi_preferences.get(PACKAGES_PREFERENCE)
        except Exception:  # noqa: BLE001 - preference absent or unreadable
            extra = ""
        return unique_stable(list(BUILTIN_PACKAGES) + SessionApp.parse_package_list(extra))

    @staticmethod
    def launch(app_class: str | type, session: Any) -> Any:
        """Construct APP_CLASS with SESSION, and return the app.

        APP_CLASS is either the class itself or the fully qualified name
        :meth:`list` reported for it. MATLAB's ``feval(className, session)``.

        RETURNING THE APP MATTERS HERE, where MATLAB can discard it: a
        MATLAB app survives because its figure holds it through guidata,
        while a Python app whose window nothing references can be collected
        the moment this returns. The caller keeps the object alive -- see
        ``DatasetsPane.launch_app``.
        """
        cls = app_class if isinstance(app_class, type) else resolve_class(str(app_class))
        return cls(session)

    # ------------------------------------------------------------------
    # The pieces of discovery, each separately checkable
    # ------------------------------------------------------------------
    @staticmethod
    def parse_package_list(value: Any) -> list[str]:
        """Split a user package-list preference into package names.

        VALUE is the preference's value: a string holding several names
        separated by semicolons or commas, as MATLAB stores it. A list or
        tuple is accepted too -- Python's preference store keeps values
        verbatim, so a user who set a list gets what they meant rather than
        the repr of one.
        """
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            parts: list[str] = []
            for item in value:
                parts.extend(SessionApp.parse_package_list(item))
            return parts
        return [part.strip() for part in _SEPARATORS.split(str(value)) if part.strip()]

    @staticmethod
    def classes_in_packages(packages: Sequence[str]) -> list[type]:
        """The classes defined in PACKAGES and their subpackages.

        MATLAB's classesInPackages, which reads ``meta.package`` without
        loading anything; Python has no such catalogue, so the modules are
        imported. Only classes whose ``__module__`` is the module being
        scanned are reported, so a class merely re-exported by a package's
        ``__init__`` is attributed to the package that defines it and is
        never counted twice.
        """
        found: list[type] = []
        seen: set[str] = set()
        for package in packages:
            for module in walk_modules(str(package)):
                for obj in list(vars(module).values()):
                    if not isinstance(obj, type) or obj.__module__ != module.__name__:
                        continue
                    key = class_name(obj)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(obj)
        return found

    @staticmethod
    def is_session_app(cls: Any) -> bool:
        """True when CLS adopts this interface (the interface itself does not)."""
        return isinstance(cls, type) and issubclass(cls, SessionApp) and cls is not SessionApp

    @staticmethod
    def is_abstract(cls: type) -> bool:
        """True when CLS is not launchable as it stands.

        Either it is ``abc``-abstract, or it never supplied a ``Name`` --
        the Python reading of MATLAB's abstract constant property.
        """
        return inspect.isabstract(cls) or "Name" not in dir(cls)

    @staticmethod
    def read_name(cls: type) -> str:
        """CLS's menu label, falling back to the class's own name."""
        try:
            name = str(cls.Name)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a Name that will not stringify
            name = ""
        return name or cls.__name__

    @staticmethod
    def read_category(cls: type) -> str:
        """CLS's submenu grouping, "" when it declares none."""
        try:
            category = str(cls.Category)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a Category that will not stringify
            return ""
        return category


#: MATLAB's spelling of the class, as ``statusIcon`` is kept beside
#: ``status_icon`` in ndi.gui.nav.
sessionApp = SessionApp


# ----------------------------------------------------------------------
# Module helpers: the import machinery discovery runs on
# ----------------------------------------------------------------------
def class_name(cls: type) -> str:
    """The fully qualified name of CLS, as :meth:`SessionApp.list` reports it."""
    return f"{cls.__module__}.{cls.__qualname__}"


def import_module(name: str) -> ModuleType | None:
    """Import NAME, or return None if it cannot be imported.

    See the module docstring: a module that will not import is skipped, not
    raised, so one broken app cannot empty the Apps menu.
    """
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 - any failure means "not scannable"
        return None


def walk_modules(name: str) -> list[ModuleType]:
    """NAME's module and, if it is a package, every module beneath it."""
    module = import_module(name)
    if module is None:
        return []
    modules = [module]
    path = getattr(module, "__path__", None)
    if path is None:
        return modules
    for info in pkgutil.walk_packages(path, prefix=f"{module.__name__}.", onerror=lambda _n: None):
        submodule = import_module(info.name)
        if submodule is not None:
            modules.append(submodule)
    return modules


def resolve_class(name: str) -> type:
    """The class NAME refers to, importing whatever module holds it.

    Splits at each dot from the right, so a class nested in another class
    resolves as readily as one at module level.
    """
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module = import_module(".".join(parts[:cut]))
        if module is None:
            continue
        obj: Any = module
        try:
            for attribute in parts[cut:]:
                obj = getattr(obj, attribute)
        except AttributeError:
            continue
        if isinstance(obj, type):
            return obj
    raise ValueError(f"Could not resolve the session app class {name!r}.")


def unique_stable(values: Sequence[str]) -> list[str]:
    """VALUES with duplicates dropped and first-seen order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
