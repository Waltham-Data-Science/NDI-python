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
from pathlib import Path


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
        from ndi.common import ndi_common_PathConstants

        folder = ndi_common_PathConstants.COMMON_FOLDER
        if folder.is_dir():
            check("ndi_common data folder", True, str(folder))
        else:
            check("ndi_common data folder", False, f"not found at {folder}")
    except Exception as e:
        check("ndi_common data folder", False, str(e))

    # DID-python
    ok, detail = _try_import("did.document")
    check("DID-python (did.document)", ok, detail)

    ok, detail = _try_import("did.implementations.sqlitedb")
    check("DID-python (did.implementations)", ok, detail)

    ok, detail = _try_import("did.datastructures")
    check("DID-python (did.datastructures)", ok, detail)

    # DID $PATH globals.  Every NDI document names its definition and its
    # validation schema through an $NDI...PATH placeholder, and DID resolves
    # those through did.common.PathConstants.DEFINITIONS.  If ndi.common did
    # not register them, document validation -- which did.database.add_docs
    # runs on every add -- fails for every NDI document.
    try:
        from did.common import PathConstants as _DIDPathConstants

        from ndi.common import _DID_PLACEHOLDERS

        definitions = _DIDPathConstants.DEFINITIONS
        missing = [k for k in _DID_PLACEHOLDERS if k not in definitions]
        unresolved = [
            k
            for k in _DID_PLACEHOLDERS
            if k in definitions and not Path(str(definitions[k])).is_dir()
        ]
        if missing:
            check(
                "DID path globals ($NDI...PATH)",
                False,
                f"not registered: {', '.join(missing)}",
            )
        elif unresolved:
            check(
                "DID path globals ($NDI...PATH)",
                False,
                f"registered but no such directory: {', '.join(unresolved)}",
            )
        else:
            check(
                "DID path globals ($NDI...PATH)",
                True,
                f"{len(_DID_PLACEHOLDERS)} registered",
            )
    except Exception as e:
        check("DID path globals ($NDI...PATH)", False, str(e))

    # NDR and NDI-compress are real runtime dependencies that nothing else here
    # imports, so a missing or broken one used to go unreported until a read.
    ok, detail = _try_import("ndr")
    check("NDR-python (ndr)", ok, detail)

    ok, detail = _try_import("ndicompress")
    check("NDI-compress (ndicompress)", ok, detail)

    # ndi.ontology re-exports this package, and every caller inside NDI-python
    # imports it lazily inside a function body, so a missing or broken install
    # stays invisible until someone performs a lookup -- and lookup() answers an
    # unresolvable provider with an empty result rather than an error. Check it
    # here, including the data files, since a wheel built without them imports
    # perfectly well and then finds nothing.
    ok, detail = _try_import("ndi_ontology")
    if ok:
        try:
            from ndi_ontology.paths import NDIC_FILE, ONTOLOGY_LIST_FILE

            missing = [str(f) for f in (ONTOLOGY_LIST_FILE, NDIC_FILE) if not f.exists()]
            if missing:
                ok, detail = False, f"installed but data files missing: {', '.join(missing)}"
        except Exception as e:  # pragma: no cover - defensive
            ok, detail = False, str(e)
    check("ndi-ontology (ndi_ontology)", ok, detail)

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
        from ndi.document import ndi_document

        doc = ndi_document("base")
        if doc.id:
            check("Smoke test: ndi_document('base')", True, f"id={doc.id[:12]}...")
        else:
            check("Smoke test: ndi_document('base')", False, "created but has no ID")
    except Exception as e:
        check("Smoke test: ndi_document('base')", False, str(e))

    # Round-trip smoke test.  Constructing a document exercises none of the
    # schema resolution that storing one does; this adds, reads back and
    # removes a document in a throwaway session so a mis-wired install fails
    # here instead of in the middle of someone's experiment.
    try:
        import tempfile

        from ndi.query import ndi_query
        from ndi.session.dir import ndi_session_dir

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "ndi_check_session"
            session_dir.mkdir()
            session = ndi_session_dir("ndi_check", session_dir)
            doc = session.newdocument("base")
            session.database_add(doc)
            read_back = session.database_search(ndi_query("base.id") == doc.id)
            session.database_rm(doc)
            check(
                "Smoke test: session add/search/remove",
                any(d.id == doc.id for d in read_back),
                f"{len(read_back)} document(s) in a fresh session",
            )
    except Exception as e:
        check("Smoke test: session add/search/remove", False, f"{type(e).__name__}: {e}")

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
