"""Two mistakes that produced silently-wrong answers, pinned codebase-wide.

Three bugs across #128, #132 and this change came from the same two
mistakes. Both are cheap to detect statically, and neither is visible at
runtime -- each one returns an ordinary-looking answer.

MISTAKE 1: reaching the database through ``.session``
    Neither ndi_session nor ndi_dataset has a ``session`` attribute. Code
    that wrote ``dataset.session.database_search(...)`` raised AttributeError
    on every call, and a surrounding ``except Exception`` reported it as an
    empty document list or a dataset that had never been uploaded.

MISTAKE 2: searching with a bare ``ndi_query("")``
    An empty query matches NO documents -- it is not "match everything".
    ``dataset.database_search(ndi_query(""))`` therefore returns [] on a
    dataset holding thousands of documents. It reads like a wildcard, which
    is exactly why it survived review in three places.

Both mistakes uploaded empty datasets to the cloud while reporting success.
The runtime tests for each fix live beside the code they cover; these two
stop the same mistake reappearing anywhere else.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


def _source_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


class TestNeitherClassHasASessionAttribute:
    """The premise of the first guard. If either class ever grows a
    ``session`` attribute, that guard is measuring nothing and should be
    reconsidered rather than left to pass vacuously."""

    def test_ndi_dataset_has_no_session_attribute(self, tmp_path):
        from ndi.dataset import ndi_dataset_dir

        assert not hasattr(ndi_dataset_dir("myds", str(tmp_path)), "session")

    def test_ndi_session_has_no_session_attribute(self, tmp_path):
        import ndi.session

        assert not hasattr(ndi.session.dir("ref", str(tmp_path)), "session")


class TestNothingReachesTheDatabaseThroughSession:
    def test_no_source_file_calls_x_session_database(self) -> None:
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if not node.attr.startswith("database"):
                    continue
                inner = node.value
                if not (isinstance(inner, ast.Attribute) and inner.attr == "session"):
                    continue
                # `self.session` is excluded: several classes legitimately OWN
                # a session attribute -- ndi.daq.system exposes it as a
                # property, and the GUI apps assign `self.session = session`
                # in __init__. Reaching your own attribute is not this bug.
                #
                # The bug is reaching for `.session` on a session or dataset
                # PASSED IN, which is what every occurrence fixed in #128,
                # #132 and this change did. Those all name the object
                # (`dataset`, `session_or_dataset`, `ndi_session_obj`), so
                # skipping `self` costs no coverage of the real pattern --
                # and `self.dataset.session...` is still caught, because the
                # holder there is an Attribute rather than the bare name.
                if isinstance(inner.value, ast.Name) and inner.value.id == "self":
                    continue
                offenders.append(
                    f"{path.relative_to(SRC.parent)}:{node.lineno} {ast.unparse(node)}"
                )
        assert not offenders, "database reached through a nonexistent .session:\n" + "\n".join(
            offenders
        )

    @pytest.mark.parametrize(
        "snippet, caught",
        [
            ("dataset.session.database_search(q)", True),
            ("session_or_dataset.session.database_search(q)", True),
            ("self.holder.session.database_search(q)", True),
            # the exclusion, asserted rather than assumed
            ("self.session.database_search(q)", False),
        ],
    )
    def test_the_check_catches_the_original_and_spares_self(self, snippet, caught) -> None:
        """Without this, the test above passes whether or not it works, and
        the `self` exclusion could quietly widen to swallow real cases."""
        tree = ast.parse(snippet)
        found = []
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Attribute) and n.attr.startswith("database")):
                continue
            inner = n.value
            if not (isinstance(inner, ast.Attribute) and inner.attr == "session"):
                continue
            if isinstance(inner.value, ast.Name) and inner.value.id == "self":
                continue
            found.append(ast.unparse(n))
        assert bool(found) is caught


class TestNoSearchUsesABareEmptyQuery:
    def test_no_source_file_searches_with_an_unrefined_query(self) -> None:
        offenders = []
        for path in _source_files():
            tree = ast.parse(path.read_text(), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (
                    isinstance(func, ast.Attribute) and func.attr.startswith("database_search")
                ):
                    continue
                if not node.args:
                    continue
                arg = node.args[0]
                # ndi_query("") with nothing chained onto it: .isa(...),
                # .depends_on(...) and comparisons all wrap it in something
                # else, so only the naked call reaches here.
                if (
                    isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Name)
                    and arg.func.id == "ndi_query"
                    and len(arg.args) == 1
                    and isinstance(arg.args[0], ast.Constant)
                    and arg.args[0].value == ""
                ):
                    offenders.append(
                        f"{path.relative_to(SRC.parent)}:{node.lineno} {ast.unparse(node)}"
                    )
        assert not offenders, (
            "database_search called with a bare ndi_query(''), which matches "
            "no documents:\n" + "\n".join(offenders)
        )

    def test_a_bare_query_really_does_match_nothing(self, tmp_path) -> None:
        """The premise. If an empty query ever became a wildcard the guard
        above would be forbidding something harmless."""
        from ndi.dataset import ndi_dataset_dir
        from ndi.document import ndi_document
        from ndi.query import ndi_query

        ds = ndi_dataset_dir("myds", str(tmp_path))
        ds.database_add(ndi_document("base"))
        assert ds.database_search(ndi_query("").isa("base"))
        assert ds.database_search(ndi_query("")) == []

    def test_the_check_would_catch_the_original(self) -> None:
        tree = ast.parse('dataset.database_search(ndi_query(""))')
        call = tree.body[0].value
        arg = call.args[0]
        assert isinstance(arg, ast.Call) and arg.func.id == "ndi_query"
        assert arg.args[0].value == ""


def test_the_walk_finds_the_source_tree() -> None:
    """A guard on the guards: an empty file list passes everything above."""
    files = _source_files()
    assert len(files) > 100, f"only {len(files)} source files found; the walk is wrong"


if __name__ == "__main__":
    pytest.main([__file__])
