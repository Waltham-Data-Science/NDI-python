"""Report the environment a launched process actually sees, and whether the
binary-linked imports napari needs still work in it.

Run identically from a plain shell and from MATLAB's system(). The
difference between the two runs is the whole question: MATLAB prepends its
bundled libraries to LD_LIBRARY_PATH on Linux and children inherit it, so
Qt and numpy can load MATLAB's libstdc++ instead of the OS copies.

Printing the variables is not enough -- a variable can be set and harmless,
or unset and something else still broken -- so this actually imports the
two libraries that break in practice.
"""

import os
import sys

VARS = (
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "MW_ORIG_LD_LIBRARY_PATH",
    "MW_ORIG_DYLD_LIBRARY_PATH",
    "PYTHONHOME",
    "PYTHONPATH",
)


def main() -> int:
    print(f"  interpreter : {sys.executable}")
    print(f"  sys.prefix  : {sys.prefix}")
    print(f"  venv active : {sys.prefix != sys.base_prefix}")
    print()
    for v in VARS:
        # <unset> and '' are different states and the difference decides
        # whether a launcher can detect MATLAB by presence.
        print(f"  {v:26s} = {os.environ[v]!r}" if v in os.environ
              else f"  {v:26s} = <unset>")
    mw = {k: val for k, val in os.environ.items() if k.startswith("MW_")}
    print(f"  all MW_* : {mw or '<none>'}")
    print()

    bad = 0
    try:
        import numpy

        print(f"  numpy : OK {numpy.__version__}")
    except Exception as e:  # noqa: BLE001
        print(f"  numpy : FAIL {type(e).__name__}: {e}")
        bad += 1
    try:
        from PyQt5 import QtCore

        print(f"  Qt    : OK {QtCore.QT_VERSION_STR}")
    except Exception as e:  # noqa: BLE001
        print(f"  Qt    : FAIL {type(e).__name__}: {e}")
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
