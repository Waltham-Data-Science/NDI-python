"""Every module under ``ndi.`` can be imported.

This is the cheapest test in the suite and it catches a failure class nothing
else does: a module that is broken on its face -- a wrong import path, a name
that does not exist -- stays green forever as long as no other test happens
to import it.

Two such modules were sitting on main when this was written, one of them an
entire package:

    ndi.gui.component     module path written as the CLASS name, so the whole
                          package and its three subpackages were unreachable
    ndi.cloud.admin       ``from xml.etree.ElementTree import ndi_element``,
                          the fallout of an automated Element -> ndi_element
                          rename that reached a stdlib import

Neither was exercised by any test, so CI was green while `import
ndi.gui.component` raised.

WHAT COUNTS AS A FAILURE HERE
An optional third-party dependency that is genuinely absent is not a broken
module, so a missing PySide6 (or any other optional extra) is skipped rather
than failed. Everything else -- a wrong path inside the package, a name that
does not exist, a syntax error -- is a failure, which is exactly the class
this exists to catch.
"""

from __future__ import annotations

import importlib
import os
import pkgutil

import pytest

import ndi

#: Third-party packages the library imports only where a feature needs them.
#: A module that fails solely because one of these is absent is skipped.
OPTIONAL_DEPENDENCIES = frozenset(
    {
        "PySide6",
        "shiboken6",
        "keyring",
        "cryptography",
        "matplotlib",
        "h5py",
        "scipy",
        "requests",
    }
)


def _module_names() -> list[str]:
    return sorted(m.name for m in pkgutil.walk_packages(ndi.__path__, "ndi."))


def _missing_optional(exc: BaseException) -> str:
    """The optional dependency this failure is about, or ``""``.

    Only a genuinely missing module counts. A dependency that is installed
    but broken is NOT excused -- that is a real problem for anyone with the
    same install, and ``ndi.cloud.profile`` had to be taught to survive
    exactly that case.
    """
    if not isinstance(exc, ModuleNotFoundError):
        return ""
    name = (getattr(exc, "name", "") or "").split(".")[0]
    return name if name in OPTIONAL_DEPENDENCIES else ""


@pytest.mark.parametrize("module_name", _module_names())
def test_module_imports(module_name: str) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        importlib.import_module(module_name)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 - a panic is a failure too
        optional = _missing_optional(exc)
        if optional:
            pytest.skip(f"optional dependency {optional!r} is not installed")
        raise AssertionError(f"{module_name} cannot be imported: {exc!r}") from exc


def test_the_walk_actually_found_the_package() -> None:
    """A guard on the guard: if walk_packages returned nothing, every test
    above would pass by vacuously not existing."""
    names = _module_names()
    assert len(names) > 100, f"only {len(names)} modules found; the walk is wrong"
    assert "ndi.gui.component" in names
    assert "ndi.cloud.admin" in names


if __name__ == "__main__":
    pytest.main([__file__])
