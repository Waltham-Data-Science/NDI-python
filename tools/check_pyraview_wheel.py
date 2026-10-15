#!/usr/bin/env python3
"""Prove the installed pyraview came from one of the release wheels.

    python tools/check_pyraview_wheel.py [--expect-machine x86_64]
                                         [--expect-tag macosx_ --expect-tag x86_64]

Run with the interpreter of the environment to check. It fails unless:

* ``import pyraview`` works and loads the library bundled INSIDE the package
  (not one named by ``PYRAVIEW_LIB``);
* the installed ``.dist-info/WHEEL`` is a platform wheel (Root-Is-Purelib:
  false) whose tag set is exactly that of a wheel listed in
  install/pyraview-wheels.html. A wheel built locally from the sdist would
  carry a tag no release wheel has (``linux_x86_64`` rather than
  ``manylinux_*``, a different macOS deployment target) or a different
  generator, so this is what tells "downloaded" from "compiled here".

It prints the matching release wheel's filename and sha256, which is the line
to read in a CI log.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "install" / "pyraview-wheels.html"
_LINK = re.compile(r'<a href="[^"#]+#sha256=([0-9a-f]{64})">([^<]+\.whl)</a>')


def expand_tags(filename: str) -> set[str]:
    """The tag set a wheel filename stands for (PEP 425 compressed tag sets)."""
    stem = filename[: -len(".whl")]
    parts = stem.split("-")
    py, abi, plat = parts[-3], parts[-2], parts[-1]
    return {f"{p}-{a}-{q}" for p in py.split(".") for a in abi.split(".") for q in plat.split(".")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--expect-machine", help="required platform.machine()")
    parser.add_argument(
        "--expect-tag", action="append", default=[], help="substring every WHEEL tag must contain"
    )
    args = parser.parse_args()
    problems = []

    print(f"python: {sys.version.split()[0]} on {platform.system()} {platform.machine()}")
    if args.expect_machine and platform.machine() != args.expect_machine:
        problems.append(
            f"platform.machine() is {platform.machine()!r}, not {args.expect_machine!r}"
        )

    if os.environ.get("PYRAVIEW_LIB"):
        problems.append("PYRAVIEW_LIB is set; the bundled library would not be what loads")

    import pyraview

    package_dir = Path(pyraview.__file__).resolve().parent
    lib = Path(pyraview._lib_path).resolve()
    print(f"pyraview: {pyraview.__file__}")
    print(f"library:  {lib}")
    if lib.parent != package_dir or not lib.is_file():
        problems.append(f"library {lib} is not bundled in {package_dir}")

    dist = importlib.metadata.distribution("pyraview")
    wheel_text = dist.read_text("WHEEL") or ""
    tags = set(re.findall(r"^Tag:\s*(\S+)", wheel_text, re.M))
    print(f"version:  {dist.version}")
    print(f"installer: {(dist.read_text('INSTALLER') or '?').strip()}")
    print("WHEEL:\n  " + "\n  ".join(wheel_text.strip().splitlines()))
    if not re.search(r"^Root-Is-Purelib:\s*false", wheel_text, re.M | re.I):
        problems.append("WHEEL does not say Root-Is-Purelib: false -- not a platform wheel")
    if not tags or any(t.endswith("-any") for t in tags):
        problems.append(f"WHEEL tags {sorted(tags)} are not platform tags")
    for needle in args.expect_tag:
        if not all(needle in t for t in tags):
            problems.append(f"WHEEL tags {sorted(tags)} do not all contain {needle!r}")

    listed = {name: sha for sha, name in _LINK.findall(INDEX.read_text(encoding="utf-8"))}
    matches = [
        name
        for name in listed
        if name.startswith(f"pyraview-{dist.version}-") and expand_tags(name) == tags
    ]
    if len(matches) == 1:
        print(f"INSTALLED RELEASE WHEEL: {matches[0]}")
        print(f"  sha256 (from install/pyraview-wheels.html): {listed[matches[0]]}")
    else:
        problems.append(
            f"WHEEL tags {sorted(tags)} match {len(matches)} release wheels in {INDEX.name}; "
            "this pyraview was not installed from a release wheel"
        )

    for p in problems:
        print(f"FAIL: {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
