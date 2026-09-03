"""ndi_install.py must exit non-zero when the install did not work.

It did not. `main()` returned 0 on every path that reached step 4, so a failed
`pip install -e .` and a failed validation both reported success to the shell:

    pip install fails, --no-validate -> 0
    validation 12/15 fails           -> 0

The first of those is the case CI runs. Three workflows invoke
`python ndi_install.py --dev --no-validate --verbose`, so a broken install was
carried into the test steps rather than stopping the job, and surfaced later as
some less obvious import error.

`python -m ndi check` runs the very same checks as the installer's validation
step and has always exited 1 when any fail (ndi/check.py). These tests pin the
installer to that same convention.

The exit code is the whole contract here, so each case asserts the returned
code and nothing about the printed output beyond the heading, which used to say
"Installation Complete" directly above a list of failures.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "ndi_install.py"


def _load_installer():
    """Import ndi_install.py by path; it is a root script, not a package module."""
    spec = importlib.util.spec_from_file_location("ndi_install_under_test", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installer():
    return _load_installer()


def _run(module, argv: list[str], **overrides) -> tuple[int, str]:
    """Run main() with argv and the named module functions replaced.

    Everything up to step 4 is stubbed to succeed, so each test isolates one
    failure and the exit code can only reflect that.
    """
    defaults = {
        "check_prerequisites": lambda: [],
        "clone_or_update": lambda *a, **k: True,
        "get_site_packages": lambda: Path("/tmp"),
        "write_pth_file": lambda *a, **k: Path("/tmp/ndi-test.pth"),
        "find_ndi_root": lambda: REPO_ROOT,
        "install_ndi_common_docs": lambda *a, **k: None,
    }
    defaults.update(overrides)

    patches = [patch.object(module, name, value) for name, value in defaults.items()]

    # main() step 5 purges every ndi/did/vlt entry from sys.modules so that
    # validation imports a fresh tree. In a pytest session that is destructive:
    # the rest of the suite keeps references to the module objects imported at
    # collection, and re-importing gives different ones, so class registries
    # populated at import time no longer match what later tests look up. Calling
    # main() without this restore turned a clean run into 63 failures across
    # test_vhprairieview.py and friends.
    saved_modules = dict(sys.modules)

    with patch.object(sys, "argv", ["ndi_install.py"] + argv):
        for p in patches:
            p.start()
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = module.main()
            return code, out.getvalue()
        finally:
            for p in patches:
                p.stop()
            # Re-bind the original module objects. Anything imported during the
            # call is left alone; only the deletions are undone.
            sys.modules.update(saved_modules)


class TestInstallerExitCodes:
    def test_failed_package_install_exits_nonzero(self, installer):
        """install_ndi_and_deps() returning False means NDI is not installed."""
        code, _ = _run(installer, [], install_ndi_and_deps=lambda *a, **k: False)
        assert code == 1

    def test_failed_package_install_exits_nonzero_with_no_validate(self, installer):
        """The exact flags CI uses -- the case that was silently exiting 0."""
        code, _ = _run(
            installer,
            ["--dev", "--no-validate", "--verbose"],
            install_ndi_and_deps=lambda *a, **k: False,
        )
        assert code == 1

    def test_failed_validation_exits_nonzero(self, installer):
        """Matches `python -m ndi check`, which exits 1 on the same checks."""
        code, out = _run(
            installer,
            [],
            install_ndi_and_deps=lambda *a, **k: True,
            validate=lambda: (12, 15),
        )
        assert code == 1
        assert "Installation Incomplete" in out
        assert "Installation Complete" not in out

    def test_successful_install_exits_zero(self, installer):
        code, out = _run(
            installer,
            [],
            install_ndi_and_deps=lambda *a, **k: True,
            validate=lambda: (15, 15),
        )
        assert code == 0
        assert "Installation Complete" in out

    def test_successful_install_with_no_validate_exits_zero(self, installer):
        code, _ = _run(
            installer,
            ["--no-validate"],
            install_ndi_and_deps=lambda *a, **k: True,
        )
        assert code == 0

    def test_failed_prerequisites_still_exits_nonzero(self, installer):
        """The paths that were already correct stay correct."""
        code, _ = _run(installer, [], check_prerequisites=lambda: ["no git"])
        assert code == 1

    def test_failed_clone_still_exits_nonzero(self, installer):
        code, _ = _run(installer, [], clone_or_update=lambda *a, **k: False)
        assert code == 1
