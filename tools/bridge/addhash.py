"""Insert ``matlab_last_sync_hash`` into a bridge entry, in place.

    python tools/bridge/addhash.py <bridge yaml> <entry name> <matlab path> [hash]

The hash defaults to the commit that last touched that MATLAB file. Pass one
explicitly to record a LATER commit that did not touch the file -- section 7
of the bridge spec allows either form.

Textual on purpose. The bridge YAMLs are hand-maintained and carry comments
and blank-line grouping that a yaml.safe_load/yaml.dump round trip destroys.

Paths: the bridge YAML is relative to the repo root. The NDI-matlab checkout
comes from $NDI_MATLAB_PATH, the same variable the bridge tests use.

WHAT THIS DOES NOT DO: decide whether the hash is honest. Recording a commit
asserts someone read that MATLAB file against its Python counterpart. If you
changed no Python, tests/test_matlab_bridge_hashes.py's
TestAHashChangeIsJustified requires the entry's decision_log to change in the
same diff and to name the commit -- see tools/bridge/decision_log.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def matlab_repo() -> Path:
    path = os.environ.get("NDI_MATLAB_PATH")
    if not path:
        raise SystemExit("set NDI_MATLAB_PATH to your NDI-matlab checkout")
    return Path(path)


def last_touching(matlab_path: str) -> str:
    """The short hash of the last commit to touch ``src/ndi/<matlab_path>``."""
    out = subprocess.run(
        [
            "git",
            "-C",
            str(matlab_repo()),
            "log",
            "-1",
            "--format=%h",
            "--",
            f"src/ndi/{matlab_path}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not out:
        raise SystemExit(f"no commit touches src/ndi/{matlab_path}")
    return out


def add(rel: str, name: str, matlab_path: str, hash_: str | None = None) -> str:
    """Insert the hash line after the entry's matlab_path. Returns what it wrote."""
    hash_ = hash_ or last_touching(matlab_path)
    path = REPO / rel
    lines = path.read_text(encoding="utf-8").split("\n")

    # Match on name AND matlab_path: several entries legitimately share a
    # name (a method called 'read' exists on many classes), and several
    # share a path, so neither alone identifies one entry.
    target = None
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)- name: "?([^"\n]*?)"?\s*$', line)
        if not m or m.group(2) != name:
            continue
        for j in range(i + 1, min(i + 12, len(lines))):
            if re.match(r"^\s*- ", lines[j]):
                break
            mp = re.match(r'^(\s*)matlab_path:\s*"?(.*?)"?\s*$', lines[j])
            if mp and mp.group(2) == matlab_path:
                target = (j, mp.group(1))
                break
        if target:
            break

    if target is None:
        raise SystemExit(f"{rel}: entry {name!r} with matlab_path {matlab_path!r} not found")

    j, indent = target
    if j + 1 < len(lines) and "matlab_last_sync_hash" in lines[j + 1]:
        raise SystemExit(f"{rel}: {name} already has a hash")
    lines.insert(j + 1, f'{indent}matlab_last_sync_hash: "{hash_}"')
    path.write_text("\n".join(lines), encoding="utf-8")
    return hash_


def main(argv: list[str]) -> None:
    if not 4 <= len(argv) <= 5:
        raise SystemExit(__doc__)
    rel, name, matlab_path = argv[1], argv[2], argv[3]
    written = add(rel, name, matlab_path, argv[4] if len(argv) > 4 else None)
    print(f"{name}  {matlab_path}  ->  {written}")


if __name__ == "__main__":
    main(sys.argv)
