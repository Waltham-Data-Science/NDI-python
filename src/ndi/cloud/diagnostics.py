"""Reports that describe a set of downloaded documents.

Written because three separate readings of a CI failure -- from truncated
logs, hundreds of lines of per-document errors, and a completeness check that
compared two different id spaces -- each produced a different and wrong story
about why a downloaded dataset would not store. The pipeline gives counts at
the end and errors at the far end, and nothing in between describes the set
itself.

``document_set_report`` answers the question those readings kept guessing at:
is the downloaded set internally complete? It needs no database, no add
attempt and no cloud access -- only the JSON that came back.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _doc_id(doc: Any) -> str:
    if not isinstance(doc, dict):
        return ""
    base = doc.get("base")
    if not isinstance(base, dict):
        return ""
    return str(base.get("id", "") or "")


def _class_name(doc: Any) -> str:
    if not isinstance(doc, dict):
        return "<not a dict>"
    document_class = doc.get("document_class")
    if not isinstance(document_class, dict):
        return "<no document_class>"
    return str(document_class.get("class_name", "") or "<unnamed>")


def _dependencies(doc: Any):
    """Yield ``(name, value)`` for every dependency entry of a document."""
    if not isinstance(doc, dict):
        return
    depends = doc.get("depends_on")
    if isinstance(depends, dict):  # MATLAB unwraps a 1-element cell
        depends = [depends]
    if not isinstance(depends, list):
        return
    for entry in depends:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if isinstance(value, str) and value:
            yield str(entry.get("name", "") or "<unnamed>"), value


def document_set_report(doc_jsons: list, *, max_lines: int = 15) -> str:
    """Describe a set of documents: what is in it, and what it refers to.

    The dangling section is the point of the whole thing. A dependency whose
    target is absent from the set cannot be satisfied by any ordering, so it
    separates "this set is incomplete" from "we stored it wrongly" without
    running an add at all.
    """
    total = len(doc_jsons)
    ids = [_doc_id(d) for d in doc_jsons]
    present = {i.lower() for i in ids if i}
    missing_id = sum(1 for i in ids if not i)
    duplicates = total - len(present) - missing_id

    classes = Counter(_class_name(d) for d in doc_jsons)

    edges = 0
    dangling: Counter = Counter()
    dangling_by_target: dict[str, set] = {}
    for doc in doc_jsons:
        source = _class_name(doc)
        for name, value in _dependencies(doc):
            edges += 1
            if value.lower() not in present:
                dangling[(source, name)] += 1
                dangling_by_target.setdefault(value, set()).add(f"{source}.{name}")

    lines = [
        "=== downloaded document set ===",
        f"  documents:            {total}",
        f"  distinct base.id:     {len(present)}",
    ]
    if missing_id:
        lines.append(f"  WITHOUT a base.id:    {missing_id}")
    if duplicates:
        lines.append(f"  duplicate base.id:    {duplicates}")

    lines.append(f"  classes:              {len(classes)}")
    for name, count in classes.most_common(max_lines):
        lines.append(f"      {count:6d}  {name}")
    if len(classes) > max_lines:
        lines.append(f"      ... and {len(classes) - max_lines} more classes")

    lines.append(f"  dependency edges:     {edges}")
    lines.append(f"  ... pointing outside the set: {sum(dangling.values())}")
    lines.append(f"  ... distinct absent targets:  {len(dangling_by_target)}")

    if dangling:
        lines.append("  referenced but absent, by referring class and slot:")
        for (source, name), count in dangling.most_common(max_lines):
            lines.append(f"      {count:6d}  {source}.{name}")
        if len(dangling) > max_lines:
            lines.append(f"      ... and {len(dangling) - max_lines} more")
        lines.append("  absent target ids:")
        for target, refs in list(dangling_by_target.items())[:max_lines]:
            lines.append(f"      {target}  <- {', '.join(sorted(refs))}")
        if len(dangling_by_target) > max_lines:
            lines.append(f"      ... and {len(dangling_by_target) - max_lines} more")
    else:
        lines.append("  every dependency resolves within the set.")

    return "\n".join(lines)
