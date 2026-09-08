#!/usr/bin/env python3
"""Bump one bridge entry's ``matlab_last_sync_hash``, textually.

    tools/bridge/bump_sync_hash.py <name> <matlab_path> [<commit>]

``matlab_path`` is as the entry records it, with or without the ``src/ndi/``
prefix. With no ``<commit>``, the file's own last-touching commit in
NDI-matlab is used; set ``NDI_MATLAB_PATH`` (or ``MAT``) to that checkout.

    NDI_MATLAB_PATH=../NDI-matlab \\
        tools/bridge/bump_sync_hash.py uploadNew "+ndi/+cloud/+sync/uploadNew.m"

WHY TEXTUAL RATHER THAN THROUGH A YAML LIBRARY

Round-tripping these files through PyYAML reformats them: it reorders
nothing but rewrites block scalars, drops comments, and re-wraps long
strings. The bridge YAMLs are read by people at least as often as by
tests, and their comments carry the reasoning. So this edits the one line
it means to edit and leaves every other byte alone.

TWO TRAPS THIS ENCODES, both of which cost a debugging session to find:

1. A CLASS ENTRY'S METHODS CARRY THEIR OWN HASHES. Matching
   ``matlab_last_sync_hash`` anywhere inside the entry's block finds
   several. The entry's own hash is the one at its own field indent
   (``- name:`` indent + 2); a nested method's sits deeper. This asserts it
   found exactly one at that level rather than guessing.

2. THE RECORDED PATH MAY CARRY A ``src/ndi/`` PREFIX. Some entries write
   ``src/ndi/+ndi/+app/...`` where most write ``+ndi/+app/...``. Both are
   the same file. Normalising here matches ``normalize_matlab_path`` in
   tests/test_matlab_bridge_hashes.py -- the alternative, editing the YAML
   to suit the tool, would be changing the data to fit the script.

BUMPING A HASH IS A CLAIM. It asserts somebody examined the entry against
that commit. If nothing on the Python side had to follow, say so in the
entry's decision_log (tools/bridge/add_decision_note.py) naming the commit
-- tests/test_matlab_bridge_hashes.py::TestAHashChangeIsJustified enforces
exactly that when a hash moves with no matching change to python_path.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def bridge_files() -> list[Path]:
    """Every bridge YAML, in a stable order."""
    return sorted(
        set(Path("src").glob("**/ndi_matlab_python_bridge.yaml"))
        | set(Path("src/ndi").glob("ndi_matlab_python_bridge_*.yaml"))
    )


def normalize(value: str) -> str:
    """A recorded matlab_path, with any ``src/ndi/`` prefix removed."""
    value = value.replace("\\", "/").strip().lstrip("/")
    return value[len("src/ndi/") :] if value.startswith("src/ndi/") else value


def entry_block(lines: list[str], start: int, indent: int) -> list[int]:
    """Line numbers belonging to the entry that opens at *start*."""
    block: list[int] = []
    j = start + 1
    while j < len(lines):
        nxt = lines[j]
        if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
            break
        block.append(j)
        j += 1
    return block


def last_touching_commit(matlab_root: str, matlab_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", matlab_root, "log", "-1", "--format=%h", "--", f"src/ndi/{matlab_path}"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()
    if not commit:
        raise SystemExit(f"no commit in {matlab_root} touches src/ndi/{matlab_path}")
    return commit


def bump(name: str, matlab_path: str, new_hash: str) -> list[tuple[Path, str, str]]:
    edited: list[tuple[Path, str, str]] = []
    for path in bridge_files():
        lines = path.read_text().split("\n")
        out = list(lines)
        for i, line in enumerate(lines):
            if not re.match(rf"^(\s*)- name: {re.escape(name)}\s*$", line):
                continue
            indent = len(line) - len(line.lstrip())
            block = entry_block(lines, i, indent)

            matches_path = False
            for k in block:
                hit = re.search(r'matlab_path:\s*"([^"]+)"', lines[k])
                if hit and normalize(hit.group(1)) == matlab_path:
                    matches_path = True
                    break
            if not matches_path:
                continue

            field = " " * (indent + 2)
            hashes = [k for k in block if lines[k].startswith(field + "matlab_last_sync_hash:")]
            if len(hashes) != 1:
                raise SystemExit(
                    f"{path}: {name} has {len(hashes)} matlab_last_sync_hash lines at its "
                    "own indent; expected exactly 1 (a class entry's methods carry their own)"
                )
            k = hashes[0]
            old = re.search(r'matlab_last_sync_hash:\s*"([0-9a-f]+)"', lines[k]).group(1)
            out[k] = re.sub(
                r'(matlab_last_sync_hash:\s*)"[0-9a-f]+"', rf'\1"{new_hash}"', lines[k]
            )
            edited.append((path, old, new_hash))
        if out != lines:
            path.write_text("\n".join(out))
    return edited


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit(__doc__.strip().split("\n\n")[1].strip())
    name, matlab_path = argv[1], normalize(argv[2])

    if len(argv) > 3:
        new_hash = argv[3]
    else:
        matlab_root = os.environ.get("NDI_MATLAB_PATH") or os.environ.get("MAT")
        if not matlab_root:
            raise SystemExit(
                "set NDI_MATLAB_PATH to an NDI-matlab checkout, or pass the commit explicitly"
            )
        new_hash = last_touching_commit(matlab_root, matlab_path)

    edited = bump(name, matlab_path, new_hash)
    if not edited:
        raise SystemExit(f"no entry matched name={name!r} path={matlab_path!r}")
    for path, old, new in edited:
        print(f"  {path}: {name} {old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
