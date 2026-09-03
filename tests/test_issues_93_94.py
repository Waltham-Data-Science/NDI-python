"""Regression tests for ndi-python issues #93 and #94.

Each of the following was reproducible on ``main`` prior to this fix:

  - Issue #93.1: ``~(A & B)`` evaluated as ``(~A) & (~B)`` (broken De Morgan).
  - Issue #93.2: ``readngrid``/``writengrid`` ignored MATLAB's column-major
    layout, so multi-dimensional files were byte-incompatible.
  - Issue #93.3: ``validate()`` failed open when a document's schema was
    declared but unparseable.
  - Issue #93.4: Two bundled schemas (``simple_calc_schema.json``,
    ``valid_interval_schema.json``) did not parse.
  - Issue #94:  ``setup.lab()`` dropped every metadata reader's file
    parameter, collapsed multi-entry readers to one, installed no default
    syncrule, and never called ``ndi.setup.sync`` (which did not exist).
    Also, unknown syncrule class names silently fell back to the abstract
    base instead of erroring.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

import ndi.ndi_common
from ndi.query import ndi_query
from ndi.time.syncrule import (
    ndi_time_syncrule_filematch,
    resolve_syncrule_class,
)


# ---------------------------------------------------------------------------
# Issue 93.4 — every bundled schema parses
# ---------------------------------------------------------------------------


def _schema_dir() -> Path:
    return Path(ndi.ndi_common.__path__[0]) / "schema_documents"


def test_all_bundled_schemas_parse():
    """Tripwire so a third unparseable schema cannot appear silently."""
    failures: list[tuple[Path, str]] = []
    for path in sorted(_schema_dir().rglob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, OSError) as exc:  # pragma: no cover
            failures.append((path, str(exc)))
    assert not failures, (
        "the following bundled schemas failed to parse:\n"
        + "\n".join(f"  {p}: {msg}" for p, msg in failures)
    )


def test_calc_and_valid_interval_schemas_specifically_parse():
    """Named check for the two schemas the issue called out."""
    root = _schema_dir()
    with open(root / "apps" / "calculations" / "simple_calc_schema.json") as f:
        assert json.load(f)["classname"] == "simple_calc"
    with open(root / "apps" / "markgarbage" / "valid_interval_schema.json") as f:
        assert json.load(f)["classname"] == "valid_interval"


# ---------------------------------------------------------------------------
# Issue 93.3 — validate() fails closed on unparseable schemas
# ---------------------------------------------------------------------------


def _use_fake_schema_root(monkeypatch, fake_root: Path) -> None:
    """Point ``ndi_common_PathConstants.SCHEMA_PATH`` at ``fake_root``."""
    from ndi.common import ndi_common_PathConstants

    monkeypatch.setattr(ndi_common_PathConstants, "_schema_path", fake_root)


def test_load_schema_raises_on_parse_error(tmp_path, monkeypatch):
    """``_load_schema`` distinguishes 'not found' from 'unloadable'."""
    from ndi import validate as validate_mod

    validate_mod._schema_cache.clear()

    fake_root = tmp_path / "schemas"
    fake_root.mkdir()
    (fake_root / "broken_schema.json").write_text("{ not json ")

    _use_fake_schema_root(monkeypatch, fake_root)

    # Missing file → None (no schema declared)
    assert validate_mod._load_schema("does_not_exist") is None

    # Present but broken → SchemaLoadError (fail closed)
    with pytest.raises(validate_mod.SchemaLoadError):
        validate_mod._load_schema("broken")

    validate_mod._schema_cache.clear()


def test_validate_fails_closed_when_schema_unparseable(tmp_path, monkeypatch):
    """A document whose declared schema fails to parse must NOT be valid."""
    from ndi import validate as validate_mod

    validate_mod._schema_cache.clear()

    fake_root = tmp_path / "schemas"
    fake_root.mkdir()
    (fake_root / "widget_schema.json").write_text("{ still not json ")

    _use_fake_schema_root(monkeypatch, fake_root)

    doc = MagicMock()
    doc.document_properties = {
        "document_class": {
            "definition": "$NDIDOCUMENTPATH/widget.json",
            "class_name": "widget",
        },
        "widget": {"name": "w1"},
    }

    result = validate_mod.validate(doc)
    assert result.is_valid is False
    assert result.errors_this  # error message about schema load
    assert "schema failed to load" in result.errors_this[0]

    validate_mod._schema_cache.clear()


# ---------------------------------------------------------------------------
# Issue 93.1 — De Morgan on the AND composite
# ---------------------------------------------------------------------------


class TestDeMorganAndComposite:
    def test_invert_and_composite_produces_or(self):
        """``~(A & B)`` must be an OR composite, not AND."""
        a = ndi_query("element.type") == "probe"
        b = ndi_query("element.name") == "e1"
        combined = a & b

        negated = ~combined

        assert negated._composite is True
        assert negated._composite_op == "or"

    def test_invert_and_composite_serialises_as_or(self):
        """The serialised search_structure is an ``or`` of negated leaves."""
        a = ndi_query("element.type") == "probe"
        b = ndi_query("element.name") == "e1"
        negated = ~(a & b)

        ss = negated.search_structure
        assert len(ss) == 1
        top = ss[0]
        assert top["operation"] == "or"

        # Each side is a negated leaf.
        left = top["param1"]
        right = top["param2"]
        assert left[0]["operation"] == "~exact_string"
        assert left[0]["field"] == "element.type"
        assert left[0]["param1"] == "probe"
        assert right[0]["operation"] == "~exact_string"
        assert right[0]["field"] == "element.name"
        assert right[0]["param1"] == "e1"

    def test_invert_and_preserves_other_matches(self):
        """The user story from the issue: ``NOT (probe named e1)`` must
        keep OTHER probes (``type=probe`` and ``name=e2``).

        Simulates DID's AND-evaluation semantics (``all(...)`` over
        negated leaves) to catch a regression that would drop them.
        """
        a = ndi_query("element.type") == "probe"
        b = ndi_query("element.name") == "e1"
        negated = ~(a & b)

        # A record for "probe named e2": neither is-not-probe nor
        # is-not-named-e1 alone is true; only the OR of the two matches.
        doc = {"element.type": "probe", "element.name": "e2"}

        top = negated.search_structure[0]
        assert top["operation"] == "or"

        def leaf_matches(leaf: dict) -> bool:
            field = leaf["field"]
            op = leaf["operation"]
            expected = leaf["param1"]
            actual = doc.get(field)
            if op == "exact_string":
                return actual == expected
            if op == "~exact_string":
                return actual != expected
            raise AssertionError(f"unexpected op {op}")

        left_all = all(leaf_matches(leaf) for leaf in top["param1"])
        right_all = all(leaf_matches(leaf) for leaf in top["param2"])
        assert (left_all or right_all), (
            "regression: an OR of negated conjuncts should keep other "
            "probes; got left=%s right=%s" % (left_all, right_all)
        )


# ---------------------------------------------------------------------------
# Issue 93.2 — ngrid column-major order
# ---------------------------------------------------------------------------


class TestNgridColumnMajor:
    def test_writengrid_serialises_column_major(self, tmp_path):
        from ndi.fun.data import writengrid

        arr = np.array([[1, 2, 3], [4, 5, 6]], dtype="float64")
        out = tmp_path / "grid.bin"
        writengrid(arr, str(out), "double")

        raw = np.fromfile(str(out), dtype="<f8")
        # MATLAB column-major: 1, 4, 2, 5, 3, 6
        assert raw.tolist() == [1.0, 4.0, 2.0, 5.0, 3.0, 6.0]

    def test_readngrid_deserialises_column_major(self, tmp_path):
        from ndi.fun.data import readngrid

        # Write bytes in MATLAB column-major layout for a 2x3 matrix.
        column_major = np.array([1, 4, 2, 5, 3, 6], dtype="<f8")
        path = tmp_path / "grid.bin"
        column_major.tofile(str(path))

        out = readngrid(str(path), (2, 3), "double")
        assert out.shape == (2, 3)
        assert np.array_equal(out, np.array([[1, 2, 3], [4, 5, 6]]))

    def test_write_then_read_round_trip(self, tmp_path):
        from ndi.fun.data import readngrid, writengrid

        arr = np.arange(24, dtype="float64").reshape(2, 3, 4)
        out = tmp_path / "grid.bin"
        writengrid(arr, str(out), "double")
        back = readngrid(str(out), arr.shape, "double")
        assert np.array_equal(back, arr)


# ---------------------------------------------------------------------------
# Issue 94 — syncrule class resolution never silently falls back
# ---------------------------------------------------------------------------


class TestSyncruleClassResolution:
    def test_resolve_matlab_dotted_name(self):
        cls = resolve_syncrule_class("ndi.time.syncrule.filematch")
        assert cls is ndi_time_syncrule_filematch

    def test_resolve_python_underscore_name(self):
        cls = resolve_syncrule_class("ndi_time_syncrule_filematch")
        assert cls is ndi_time_syncrule_filematch

    def test_unknown_class_raises_not_falls_back_to_abstract(self):
        with pytest.raises(ValueError) as exc:
            resolve_syncrule_class("ndi.time.syncrule.doesnotexist")
        # The abstract base class must not be silently returned.
        assert "Unknown" in str(exc.value)

    def test_from_document_rejects_unknown_class(self):
        """``from_document`` used to silently fall back to the abstract base."""
        from ndi.time.syncrule_base import ndi_time_syncrule

        doc = MagicMock()
        doc.document_properties = {
            "syncrule": {
                "ndi_syncrule_class": "ndi.time.syncrule.bogus",
                "parameters": {"number_fullpath_matches": 2},
            },
            "base": {"id": "did:mock:1"},
        }
        with pytest.raises(ValueError):
            ndi_time_syncrule.from_document(session=None, doc=doc)


# ---------------------------------------------------------------------------
# Issue 94 — sync_rules directory is vendored and parses
# ---------------------------------------------------------------------------


def test_sync_rules_directory_exists_and_parses():
    from ndi.setup.sync import syncrule_from_config_file

    sr_dir = Path(ndi.ndi_common.__path__[0]) / "sync_rules" / "vhlab"
    assert sr_dir.is_dir(), "sync_rules/vhlab must be vendored"

    configs = sorted(sr_dir.glob("*.json"))
    assert configs, "sync_rules/vhlab must contain lab-specific configs"

    for config in configs:
        rule = syncrule_from_config_file(config)
        # Each config resolves to a concrete syncrule class.
        assert rule is not None


def test_syncrule_from_config_file_missing_fields(tmp_path):
    from ndi.setup.sync import syncrule_from_config_file

    bad = tmp_path / "bad.json"
    bad.write_text('{"syncrule_class": "ndi.time.syncrule.filematch"}')
    with pytest.raises(ValueError):
        syncrule_from_config_file(bad)


def test_add_sync_rules_unknown_lab_is_noop():
    """A lab without a sync_rules directory returns the session unchanged."""
    from ndi.setup.sync import add_sync_rules

    session = MagicMock()
    result = add_sync_rules(session, "lab_with_no_sync_rules_defined")
    assert result is session
    session.syncgraph_addrule.assert_not_called()


def test_add_sync_rules_installs_vendored_vhlab_rules():
    """Every vendored ``vhlab/*.json`` must reach ``syncgraph_addrule``."""
    from ndi.setup.sync import add_sync_rules

    sr_dir = Path(ndi.ndi_common.__path__[0]) / "sync_rules" / "vhlab"
    expected = len(sorted(sr_dir.glob("*.json")))

    session = MagicMock()
    add_sync_rules(session, "vhlab")
    assert session.syncgraph_addrule.call_count == expected


# ---------------------------------------------------------------------------
# Issue 94 — setup.lab() carries metadata reader file parameters and
# installs a default filematch(2) syncrule
# ---------------------------------------------------------------------------


class _FakeDoc:
    """Minimal stand-in for ndi_document good enough for setup.lab()."""

    _next_id = 0

    def __init__(self, doc_type: str, props: dict):
        type(self)._next_id += 1
        self.id = f"doc:{type(self)._next_id}"
        self.doc_type = doc_type
        self.props = dict(props)
        self.dependencies: list[tuple[str, str]] = []

    def set_dependency_value(self, name, value, error_if_not_found=False):
        self.dependencies.append((name, value))
        return self

    def add_dependency_value_n(self, name, value):
        self.dependencies.append((name, value))
        return self


class _FakeSession:
    def __init__(self):
        self.docs: list[_FakeDoc] = []
        self.sync_rules: list = []

    def newdocument(self, doc_type, **kwargs):
        return _FakeDoc(doc_type, kwargs)

    def database_add(self, doc):
        self.docs.append(doc)

    def syncgraph_addrule(self, rule):
        self.sync_rules.append(rule)


def _metadata_reader_docs(session: _FakeSession) -> list[_FakeDoc]:
    return [d for d in session.docs if d.doc_type == "daq/daqmetadatareader"]


def test_setup_lab_populates_metadata_reader_file_parameter():
    """One reader per file-parameter entry, each with its file param stored."""
    from ndi.setup.lab import lab

    # narendra_intan has 1 class + 3 tsv file parameters → 3 readers.
    session = _FakeSession()
    lab(session, "dbkatzlab")

    tsv_files = [
        "stimulus_metadata_intraoral_canulae.tsv",
        "stimulus_metadata_optical_fiber1.tsv",
        "stimulus_metadata_optical_fiber2.tsv",
    ]
    narendra_readers = [
        d for d in _metadata_reader_docs(session) if d.props["base.name"] == "narendra_intan"
    ]
    assert len(narendra_readers) == len(tsv_files), (
        f"expected 3 metadata readers for narendra_intan, got {len(narendra_readers)}"
    )

    file_params_seen = sorted(
        r.props["daqmetadatareader.tab_separated_file_parameter"] for r in narendra_readers
    )
    assert file_params_seen == sorted(tsv_files)


def test_setup_lab_single_metadata_reader_carries_its_file_parameter():
    """``rayolab/rayo_stim.json`` declares a single-string file parameter."""
    from ndi.setup.lab import lab

    session = _FakeSession()
    lab(session, "rayolab")

    rayo_readers = [
        d for d in _metadata_reader_docs(session) if d.props["base.name"] == "rayo_stim"
    ]
    assert len(rayo_readers) == 1
    fp = rayo_readers[0].props["daqmetadatareader.tab_separated_file_parameter"]
    assert fp == r"#_\d{6}_\d{6}\._epochprobemap\.txt\>"


def test_setup_lab_installs_default_filematch_syncrule():
    """MATLAB installs ``filematch(number_fullpath_matches=2)`` — Python must too."""
    from ndi.setup.lab import lab

    session = _FakeSession()
    lab(session, "vhlab")

    # First rule is the default filematch(2).
    assert session.sync_rules, "setup.lab() must install at least one syncrule"
    first = session.sync_rules[0]
    assert isinstance(first, ndi_time_syncrule_filematch)
    assert first.parameters.get("number_fullpath_matches") == 2


def test_setup_lab_installs_vhlab_sync_rules():
    """After the default rule, every vhlab sync-rule JSON is installed."""
    from ndi.setup.lab import lab

    session = _FakeSession()
    lab(session, "vhlab")

    sr_dir = Path(ndi.ndi_common.__path__[0]) / "sync_rules" / "vhlab"
    expected_extra = len(sorted(sr_dir.glob("*.json")))

    # 1 default filematch(2) + N vhlab-specific rules.
    assert len(session.sync_rules) == 1 + expected_extra
