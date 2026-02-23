"""
NDI installation validator.

Usage:
    python -m ndi check
    python -m ndi.check

Checks that all NDI dependencies are properly installed and configured.
"""

from __future__ import annotations

import importlib
import os
import sys


def _try_import(module: str) -> tuple[bool, str]:
    """Try importing a module. Returns (success, detail)."""
    try:
        mod = importlib.import_module(module)
        ver = getattr(mod, "__version__", "")
        return True, ver
    except ImportError as e:
        return False, str(e)


def run_checks() -> tuple[list[tuple[str, bool, str]], int, int]:
    """Run all installation checks.

    Returns:
        (results, passed, total) where results is a list of
        (name, passed, detail) tuples.
    """
    results: list[tuple[str, bool, str]] = []
    passed = 0
    total = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
        results.append((name, ok, detail))

    # Core NDI package
    ok, detail = _try_import("ndi")
    check("ndi core package", ok, detail)

    # ndi_common data folder
    try:
        from ndi.common import PathConstants

        folder = PathConstants.COMMON_FOLDER
        if folder.is_dir():
            check("ndi_common data folder", True, str(folder))
        else:
            check("ndi_common data folder", False, f"not found at {folder}")
    except Exception as e:
        check("ndi_common data folder", False, str(e))

    # DID-python (the packaging bug check)
    ok, detail = _try_import("did.document")
    check("DID-python (did.document)", ok, detail)

    ok, detail = _try_import("did.implementations.sqlitedb")
    check("DID-python (did.implementations)", ok, detail)

    ok, detail = _try_import("did.datastructures")
    check("DID-python (did.datastructures)", ok, detail)

    # vhlab-toolbox-python
    ok, detail = _try_import("vlt")
    check("vhlab-toolbox-python (vlt)", ok, detail)

    # Core pip dependencies
    for mod in ["numpy", "networkx", "jsonschema", "requests"]:
        ok, ver = _try_import(mod)
        check(mod, ok, ver if ok else str(ver))

    # Optional/tutorial dependencies
    for mod in ["pandas", "matplotlib", "scipy"]:
        ok, ver = _try_import(mod)
        check(mod, ok, ver if ok else str(ver))

    # Cloud credentials (informational)
    username = os.environ.get("NDI_CLOUD_USERNAME", "")
    if username:
        results.append(("NDI Cloud credentials", True, f"configured ({username})"))
    else:
        results.append(("NDI Cloud credentials", False, "not set (needed for tutorials)"))
    # Don't count credentials in pass/fail total

    # Smoke test
    try:
        from ndi.document import Document

        doc = Document("base")
        if doc.id:
            check("Smoke test: Document('base')", True, f"id={doc.id[:12]}...")
        else:
            check("Smoke test: Document('base')", False, "created but has no ID")
    except Exception as e:
        check("Smoke test: Document('base')", False, str(e))

    return results, passed, total


def print_report(results: list[tuple[str, bool, str]], passed: int, total: int) -> None:
    """Print formatted check results."""
    print()
    print("NDI-python Installation Check")
    print("=" * 40)

    for name, ok, detail in results:
        if name == "NDI Cloud credentials":
            # Informational, not pass/fail
            status = "[INFO]" if not ok else "[INFO]"
            print(f"  {status} {name}: {detail}")
        elif ok:
            ver_str = f" ({detail})" if detail else ""
            print(f"  [PASS] {name}{ver_str}")
        else:
            print(f"  [FAIL] {name}: {detail}")

    print()
    if passed == total:
        print(f"  Result: All {total} checks passed. NDI-python is ready to use.")
    else:
        print(f"  Result: {passed}/{total} checks passed.")
    print()


def main() -> int:
    """Entry point for python -m ndi.check."""
    results, passed, total = run_checks()
    print_report(results, passed, total)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
