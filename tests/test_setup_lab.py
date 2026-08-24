"""Tests for :mod:`ndi.setup.lab` -- lab configuration parity with MATLAB.

Covers:

* ``MetadataReaderFileParameters`` -> ``daqmetadatareader.tab_separated_file_parameter``
  (MATLAB ``@DaqSystemConfiguration/DaqSystemConfiguration.m:createMetadataReader``,
  which does ``feval(MetadataReaderClass(i), char(MetadataReaderFileParameters(i)))``).
* ``force_update`` semantics ported from MATLAB
  ``ndi.setup.lab(..., 'forceUpdate', tf)`` /
  ``ndi.setup.daq.addDaqSystems(S, labName, force)``.
* Lab sync-rule installation (MATLAB ``ndi.setup.sync.addSyncRules``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ndi.setup
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir
from ndi.time.syncrule import ndi_time_syncrule_filematch


def _lab_config_dir(lab_name: str) -> Path:
    import ndi.ndi_common

    return Path(ndi.ndi_common.__path__[0]) / "daq_systems" / lab_name


def _expected_metadata_file_parameters(lab_name: str) -> dict[str, list[str]]:
    """Map DAQ system name -> expected tab_separated_file_parameter values.

    Mirrors MATLAB ``DaqSystemConfiguration/createMetadataReader``: one reader
    per ``MetadataReaderFileParameters`` entry, or a single reader with an
    empty file parameter when the field is absent/empty.
    """
    expected: dict[str, list[str]] = {}
    for json_file in sorted(_lab_config_dir(lab_name).glob("*.json")):
        with open(json_file, encoding="utf-8") as f:
            cfg = json.load(f)
        if not cfg.get("MetadataReaderClass"):
            continue
        fp = cfg.get("MetadataReaderFileParameters", "")
        if isinstance(fp, list):
            fps = [p for p in fp if p != ""] or [""]
        else:
            fps = [fp]
        expected[cfg["Name"]] = sorted(fps)
    return expected


def _metadatareader_docs(session) -> dict[str, list[str]]:
    """Map daqmetadatareader doc name -> its tab_separated_file_parameter values."""
    docs = session.database_search(ndi_query("").isa("daqmetadatareader"))
    out: dict[str, list[str]] = {}
    for doc in docs:
        props = doc.document_properties
        out.setdefault(props["base"]["name"], []).append(
            props["daqmetadatareader"]["tab_separated_file_parameter"]
        )
    return {k: sorted(v) for k, v in out.items()}


@pytest.fixture
def session(tmp_path):
    session_dir = tmp_path / "exp1"
    session_dir.mkdir()
    s = ndi_session_dir("exp1", session_dir)
    s.cache.clear()
    return s


@pytest.mark.parametrize(
    "lab_name",
    [
        "angeluccilab",
        "dabrowskalab",
        "dbkatzlab",
        "gluckmanlab",
        "kjnielsenlab",
        "marderlab",
        "rayolab",
        "sjbirrenlab",
        "vhlab",
        "yangyangwang",
    ],
)
def test_metadata_reader_file_parameter_is_written(tmp_path, lab_name):
    """Every configured metadata reader carries its lab JSON file parameter.

    Regression: ``ndi.setup.lab`` used to drop ``MetadataReaderFileParameters``
    entirely, so every Python-configured lab produced daqmetadatareader
    documents with ``tab_separated_file_parameter == ""`` -- meaning
    ``readmetadata()`` silently returned no stimulus metadata at all.
    """
    session_dir = tmp_path / lab_name
    session_dir.mkdir()
    s = ndi_session_dir(lab_name, session_dir)
    s.cache.clear()

    ndi.setup.lab(s, lab_name)

    expected = _expected_metadata_file_parameters(lab_name)
    got = _metadatareader_docs(s)
    assert got == expected, (
        f"{lab_name}: daqmetadatareader tab_separated_file_parameter mismatch.\n"
        f"  got:      {got}\n"
        f"  lab JSON: {expected}"
    )


def test_some_labs_actually_declare_metadata_readers():
    """Guard against the parity test above passing because nothing is configured."""
    with_readers = [
        lab_name
        for lab_name in ("kjnielsenlab", "rayolab", "vhlab", "dbkatzlab")
        if any(v != [""] for v in _expected_metadata_file_parameters(lab_name).values())
    ]
    assert sorted(with_readers) == ["dbkatzlab", "kjnielsenlab", "rayolab", "vhlab"]


def test_multi_parameter_lab_gets_one_reader_per_parameter(tmp_path):
    """dbkatzlab declares one reader class and three file parameters.

    MATLAB's ``arrayfun(@(fp) feval(MetadataReaderClass, char(fp)), ...)``
    builds three readers; the old Python code built exactly one, with an empty
    file parameter, silently losing two of the three stimulus metadata files.
    """
    session_dir = tmp_path / "dbkatzlab"
    session_dir.mkdir()
    s = ndi_session_dir("dbkatzlab", session_dir)
    s.cache.clear()

    ndi.setup.lab(s, "dbkatzlab")

    got = _metadatareader_docs(s)
    assert got["narendra_intan"] == [
        "stimulus_metadata_intraoral_canulae.tsv",
        "stimulus_metadata_optical_fiber1.tsv",
        "stimulus_metadata_optical_fiber2.tsv",
    ]

    # The daqsystem document must depend on all three of them.
    daq_docs = s.database_search(
        ndi_query("").isa("daqsystem") & (ndi_query("base.name") == "narendra_intan")
    )
    assert len(daq_docs) == 1
    dep_ids = daq_docs[0].dependency_value_n("daqmetadatareader_id", error_if_not_found=False)
    assert len(dep_ids) == 3


def test_metadata_reader_roundtrips_into_object(session):
    """A daqmetadatareader doc built by lab() reconstructs a working reader."""
    from ndi.daq.metadatareader import ndi_daq_metadatareader

    ndi.setup.lab(session, "kjnielsenlab")

    docs = session.database_search(
        ndi_query("").isa("daqmetadatareader") & (ndi_query("base.name") == "nielsen_vis")
    )
    assert len(docs) == 1
    reader = ndi_daq_metadatareader(session=session, document=docs[0])
    assert reader.tab_separated_file_parameter == "(.*)\\.analyzer\\>"


def test_multiple_metadata_readers_get_matching_parameters(session):
    """MATLAB pairs reader class i with file parameter i; Python must too."""
    from ndi.setup.lab import _add_daq_systems_from_configs

    configs = [
        {
            "Name": "twin",
            "DaqSystemClass": "ndi.daq.system.mfdaq",
            "DaqReaderClass": "ndi.daq.reader.mfdaq",
            "MetadataReaderClass": [
                "ndi.daq.metadatareader",
                "ndi.daq.metadatareader",
            ],
            "MetadataReaderFileParameters": ["a\\.tsv", "b\\.tsv"],
            "FileParameters": ["a.tsv", "b.tsv"],
            "EpochProbeMapFileParameters": "",
            "HasEpochDirectories": False,
        }
    ]
    _add_daq_systems_from_configs(session, configs, force_update=False)

    docs = session.database_search(ndi_query("").isa("daqmetadatareader"))
    params = sorted(
        d.document_properties["daqmetadatareader"]["tab_separated_file_parameter"] for d in docs
    )
    assert params == ["a\\.tsv", "b\\.tsv"]


# kjnielsenlab: plain daqreader docs. rayolab: NDR-family daqreader_ndr docs.
# dbkatzlab: a DAQ system with three daqmetadatareader dependencies.
# vhlab: the largest set, incl. systems with and without metadata readers.
_FORCE_UPDATE_LABS = ["dbkatzlab", "kjnielsenlab", "rayolab", "vhlab"]


@pytest.mark.parametrize("lab_name", _FORCE_UPDATE_LABS)
def test_lab_is_idempotent_without_force_update(tmp_path, lab_name):
    """Calling lab() twice must not duplicate DAQ systems (MATLAB addDaqSystems)."""
    session_dir = tmp_path / lab_name
    session_dir.mkdir()
    s = ndi_session_dir(lab_name, session_dir)
    s.cache.clear()

    ndi.setup.lab(s, lab_name)
    ids_first = sorted(d.id for d in s.database_search(ndi_query("").isa("daqsystem")))

    ndi.setup.lab(s, lab_name)
    ids_second = sorted(d.id for d in s.database_search(ndi_query("").isa("daqsystem")))

    assert ids_first == ids_second


@pytest.mark.parametrize("lab_name", _FORCE_UPDATE_LABS)
def test_force_update_recreates_daq_systems(tmp_path, lab_name):
    """force_update=True removes and re-creates the lab's DAQ systems."""
    session_dir = tmp_path / lab_name
    session_dir.mkdir()
    s = ndi_session_dir(lab_name, session_dir)
    s.cache.clear()

    ndi.setup.lab(s, lab_name)
    first = s.database_search(ndi_query("").isa("daqsystem"))
    ids_first = sorted(d.id for d in first)
    names_first = sorted(d.document_properties["base"]["name"] for d in first)

    ndi.setup.lab(s, lab_name, force_update=True)
    second = s.database_search(ndi_query("").isa("daqsystem"))
    ids_second = sorted(d.id for d in second)
    names_second = sorted(d.document_properties["base"]["name"] for d in second)

    assert names_first == names_second, "force_update must not change the set of DAQ systems"
    assert ids_first != ids_second, "force_update must re-create (new ids) the DAQ systems"
    assert len(second) == len(first), "force_update must not duplicate DAQ systems"


@pytest.mark.parametrize("lab_name", _FORCE_UPDATE_LABS)
def test_force_update_removes_stale_child_documents(tmp_path, lab_name):
    """Re-created DAQ systems must not leave orphaned navigator/reader docs."""
    session_dir = tmp_path / lab_name
    session_dir.mkdir()
    s = ndi_session_dir(lab_name, session_dir)
    s.cache.clear()

    def counts():
        return {
            t: len(s.database_search(ndi_query("").isa(t)))
            for t in ("filenavigator", "daqreader", "daqmetadatareader")
        }

    ndi.setup.lab(s, lab_name)
    before = counts()
    assert before["filenavigator"] > 0

    ndi.setup.lab(s, lab_name, force_update=True)

    assert counts() == before


# ---------------------------------------------------------------------------
# Sync-rule installation performed by lab() (MATLAB ndi.setup.lab, 881919d39)
# ---------------------------------------------------------------------------


def _rule_class_names(session) -> list[str]:
    return sorted(type(r).__name__ for r in session.syncgraph.rules)


def test_lab_installs_default_filematch_rule(session):
    """MATLAB ndi.setup.lab always adds filematch(number_fullpath_matches=2)."""
    ndi.setup.lab(session, "marderlab")
    rules = session.syncgraph.rules
    filematch = [r for r in rules if isinstance(r, ndi_time_syncrule_filematch)]
    assert len(filematch) == 1
    assert filematch[0].parameters["number_fullpath_matches"] == 2


def test_lab_installs_lab_specific_rules(session):
    """ndi.setup.lab(session, 'vhlab') installs the vhlab sync rules too."""
    ndi.setup.lab(session, "vhlab")
    names = _rule_class_names(session)
    assert names == [
        "ndi_time_syncrule_commonTriggersOverlappingEpochs",
        "ndi_time_syncrule_filefind",
        "ndi_time_syncrule_filematch",
    ]


def test_lab_sync_rules_persist_to_database(session):
    """Rules added by lab() survive a re-open of the session directory."""
    ndi.setup.lab(session, "vhlab")
    reopened = ndi_session_dir("exp1", session.path)
    names = _rule_class_names(reopened)
    assert names == [
        "ndi_time_syncrule_commonTriggersOverlappingEpochs",
        "ndi_time_syncrule_filefind",
        "ndi_time_syncrule_filematch",
    ]


def test_multiple_classes_with_single_file_parameter_errors():
    """MATLAB's fallback branch fevals a non-scalar class list, which errors.

    Mirror that as a ValueError instead of silently dropping classes[1:].
    """
    from ndi.setup.lab import _metadata_reader_pairs

    config = {
        "Name": "bad_lab_config",
        "MetadataReaderClass": ["ndi.daq.metadatareader.A", "ndi.daq.metadatareader.B"],
        "MetadataReaderFileParameters": ["one.txt"],
    }
    with pytest.raises(ValueError, match="bad_lab_config"):
        _metadata_reader_pairs(config)
