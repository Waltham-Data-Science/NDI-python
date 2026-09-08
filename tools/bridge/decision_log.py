"""Append a paragraph to a bridge entry's ``decision_log``, in place.

    python tools/bridge/decision_log.py <bridge yaml> <entry name> <matlab path> <note>

WHY THIS EXISTS. Recording or moving a ``matlab_last_sync_hash`` asserts that
someone read that MATLAB file against its Python counterpart. When the port
needed no change, the reading is the only evidence there is -- so
``TestAHashChangeIsJustified`` requires that a hash change touching none of
the entry's ``python_path`` files also change that entry's ``decision_log``,
and that the log name the commit. This writes that paragraph.

    ... NDI-matlab abc1234 renamed a local variable; no behavioural change,
    nothing to port.

Textual on purpose: the bridge YAMLs are hand-maintained and carry comments
and blank-line grouping that a yaml round trip destroys.

Handles both spellings in use -- a ``>`` folded block, and a single-line
quoted scalar, which is converted to a folded block so the note fits -- and
creates the field when the entry has none (the gui component entries carry
only per-property logs nested deeper).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WIDTH = 78


def _wrap(text: str, indent: str, width: int = WIDTH) -> list[str]:
    words, out, cur = text.split(), [], indent
    for word in words:
        if len(cur) + len(word) + 1 > width and cur.strip():
            out.append(cur.rstrip())
            cur = indent + word
        else:
            cur = (cur + " " + word) if cur.strip() else cur + word
    if cur.strip():
        out.append(cur.rstrip())
    return out


def _find_entry(lines: list[str], name: str, matlab_path: str) -> tuple[int, str]:
    """Locate the entry by name AND path.

    Neither alone identifies one entry: a method named 'read' exists on many
    classes, and several entries legitimately share a MATLAB path.
    """
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)- name: "?([^"\n]*?)"?\s*$', line)
        if not m or m.group(2) != name:
            continue
        for j in range(i + 1, min(i + 14, len(lines))):
            if re.match(r"^\s*- ", lines[j]):
                break
            mp = re.match(r'^\s*matlab_path:\s*"?(.*?)"?\s*$', lines[j])
            if mp and mp.group(1) == matlab_path:
                return i, m.group(1)
    raise SystemExit(f"entry {name!r} with matlab_path {matlab_path!r} not found")


def _entry_end(lines: list[str], start: int, entry_indent: str) -> int:
    """The entry ends at the next sibling list item -- one at the SAME indent.

    A deeper ``- `` belongs to a nested block (input_arguments), and stopping
    there would miss a decision_log that follows it.
    """
    for j in range(start + 1, len(lines)):
        if re.match(rf"^{entry_indent}- ", lines[j]) or lines[j].startswith("  # ====="):
            return j
    return len(lines)


def append(rel: str, name: str, matlab_path: str, note: str) -> None:
    path = REPO / rel
    lines = path.read_text(encoding="utf-8").split("\n")

    start, entry_indent = _find_entry(lines, name, matlab_path)
    end = _entry_end(lines, start, entry_indent)
    key_indent = entry_indent + "  "

    # Only this entry's OWN decision_log, not one belonging to a nested entry.
    dl = None
    for j in range(start + 1, end):
        if re.match(rf"^{key_indent}decision_log:", lines[j]):
            dl = j
            break

    if dl is None:
        # No log at all: open one right after the entry's last simple key.
        insert_at = start + 1
        for j in range(start + 1, end):
            if re.match(rf"^{key_indent}\S", lines[j]):
                insert_at = j + 1
        lines[insert_at:insert_at] = [f"{key_indent}decision_log: >"] + _wrap(
            note, key_indent + "  "
        )
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    indent = re.match(r"^(\s*)", lines[dl]).group(1)
    wrapped = _wrap(note, indent + "  ")

    if re.match(r"^\s*decision_log:\s*>\s*$", lines[dl]):
        # The folded scalar runs until a line indented no deeper than the
        # `decision_log:` key itself -- the entry's next key. Appending past
        # that would land the note under a sibling field.
        last = dl
        for j in range(dl + 1, end):
            if not lines[j].strip():
                continue
            if len(re.match(r"^(\s*)", lines[j]).group(1)) <= len(indent):
                break
            last = j
        lines[last + 1 : last + 1] = [""] + wrapped
    else:
        m = re.match(r'^\s*decision_log:\s*"(.*)"\s*$', lines[dl]) or re.match(
            r"^\s*decision_log:\s*(.+?)\s*$", lines[dl]
        )
        original = m.group(1).strip().strip('"')
        lines[dl : dl + 1] = (
            [f"{indent}decision_log: >"] + _wrap(original, indent + "  ") + [""] + wrapped
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str]) -> None:
    if len(argv) != 5:
        raise SystemExit(__doc__)
    append(argv[1], argv[2], argv[3], argv[4])
    print(f"appended to {argv[2]} in {argv[1]}")


if __name__ == "__main__":
    main(sys.argv)
