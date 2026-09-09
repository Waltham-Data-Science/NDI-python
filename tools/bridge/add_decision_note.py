#!/usr/bin/env python3
"""Append to (or create) one bridge entry's ``decision_log``, textually.

    tools/bridge/add_decision_note.py <name> <matlab_path> <<'TEXT'
    2026-09-08: examined against abc1234. Renames a local variable; no
    behavioural change, nothing to port.
    TEXT

The note is read from stdin. ``matlab_path`` is as the entry records it,
with or without the ``src/ndi/`` prefix.

WHY TEXTUAL: see tools/bridge/bump_sync_hash.py. Round-tripping these files
through a YAML library rewrites block scalars and drops the comments that
carry the reasoning.

THE TRAP THIS ENCODES. An entry whose decision_log is an INLINE scalar --

    decision_log: "Exact match."

-- cannot take appended prose: the appended lines land outside the quotes
and the file stops parsing. Two bridge YAMLs were broken this way before
the conversion below existed. So an inline scalar is first rewritten as a
block scalar, and the note is appended inside it:

    decision_log: >
      Exact match.
      2026-09-08: examined against abc1234. ...

WHEN A NOTE IS REQUIRED. Not for a regular port -- NDI-python#211 decision
4 settled that the bumped hash is itself the record of "examined as of this
commit", and demanding prose on every routine bump would bury the ~100 logs
that carry real reasoning. It IS required when a hash moves and none of the
entry's python_path files change in the same diff, which
tests/test_matlab_bridge_hashes.py::TestAHashChangeIsJustified enforces:
the log must change too, and must name the new commit. That check exists
because merely reporting "the hash does not match" tempts a reader into
bumping the hash rather than fixing what moved (VH-Lab/NDR-python#23).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from bump_sync_hash import bridge_files, entry_block, normalize


def add_note(name: str, matlab_path: str, text: str) -> Path | None:
    for path in bridge_files():
        lines = path.read_text().split("\n")
        out: list[str] | None = None
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
            body = [f"{field}  {ln}" for ln in text.split("\n")]
            logs = [k for k in block if re.match(rf"^{field}decision_log:", lines[k])]

            if logs:
                k = logs[0]
                # An inline scalar cannot take appended prose; make it a block.
                inline = re.match(rf'^{field}decision_log:\s*"(.*)"\s*$', lines[k])
                if inline:
                    lines[k : k + 1] = [
                        f"{field}decision_log: >",
                        f"{field}  {inline.group(1)}",
                    ]
                    block = list(range(block[0], block[-1] + 2))
                    k += 1
                end = k + 1
                while end < len(lines) and lines[end].startswith(field + "  "):
                    end += 1
                out = lines[:end] + body + lines[end:]
            else:
                # Insert after the hash line when there is one, else at the top
                # of the entry -- the log reads as a note on the examination.
                anchor = [
                    k for k in block if re.match(rf"^{field}matlab_last_sync_hash:", lines[k])
                ]
                k = anchor[0] if anchor else block[0]
                out = lines[: k + 1] + [f"{field}decision_log: >"] + body + lines[k + 1 :]
            break

        if out is not None:
            path.write_text("\n".join(out))
            return path
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit(__doc__.strip().split("\n\n")[1].strip())
    name, matlab_path = argv[1], normalize(argv[2])
    text = sys.stdin.read().strip()
    if not text:
        raise SystemExit("the note is read from stdin, and was empty")

    edited = add_note(name, matlab_path, text)
    if edited is None:
        raise SystemExit(f"no entry matched name={name!r} path={matlab_path!r}")
    print(f"  noted {name} in {edited}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
