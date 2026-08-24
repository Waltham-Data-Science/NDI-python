"""Tests for :mod:`ndi.setup.sync` -- declarative lab sync-rule installation.

Python port of MATLAB ``tests/+ndi/+unittest/+setup/+sync/addSyncRulesTest.m``
(NDI-matlab commit ``881919d39``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ndi.setup.sync
from ndi.session.dir import ndi_session_dir
from ndi.time.syncrule import (
    ndi_time_syncrule_commonTriggersOverlappingEpochs,
    ndi_time_syncrule_filefind,
)


def _sync_rules_dir(lab_name: str) -> Path:
    import ndi.ndi_common

    return Path(ndi.ndi_common.__path__[0]) / "sync_rules" / lab_name


def _rule_class_names(session) -> list[str]:
    return sorted(type(r).__name__ for r in session.syncgraph.rules)


@pytest.fixture
def session(tmp_path):
    session_dir = tmp_path / "exp1"
    session_dir.mkdir()
    s = ndi_session_dir("exp1", session_dir)
    s.cache.clear()
    return s


def test_vhlab_sync_rule_configs_are_vendored():
    """The vhlab sync-rule JSONs must exist in the vendored ndi_common tree."""
    d = _sync_rules_dir("vhlab")
    assert d.is_dir(), f"missing vendored sync_rules dir: {d}"
    names = sorted(p.name for p in d.glob("*.json"))
    assert names == ["vhintan_intan2spike2.json", "vhtaste_sync2bpod.json"]


def test_filefind_rule_from_config():
    """vhintan<->vhvis_spike2 loads with the correct type and parameters."""
    rule = ndi.setup.sync.sync_rule_from_config_file(
        _sync_rules_dir("vhlab") / "vhintan_intan2spike2.json"
    )
    assert isinstance(rule, ndi_time_syncrule_filefind)
    assert rule.parameters["syncfilename"] == "vhintan_intan2spike2time.txt"
    assert rule.parameters["daqsystem1"] == "vhintan"
    assert rule.parameters["daqsystem2"] == "vhvis_spike2"
    assert rule.parameters["number_fullpath_matches"] == 1


def test_common_triggers_rule_from_config():
    """vhtaste_sync<->vhtaste_bpod loads with the correct type and parameters."""
    rule = ndi.setup.sync.sync_rule_from_config_file(
        _sync_rules_dir("vhlab") / "vhtaste_sync2bpod.json"
    )
    assert isinstance(rule, ndi_time_syncrule_commonTriggersOverlappingEpochs)
    assert rule.parameters["daqsystem1_name"] == "vhtaste_sync"
    assert rule.parameters["daqsystem2_name"] == "vhtaste_bpod"
    assert rule.parameters["daqsystem_ch1"] == "dep1"
    assert rule.parameters["daqsystem_ch2"] == "mk1"
    assert rule.parameters["errorOnFailure"] is True


def test_config_missing_required_fields_raises(tmp_path):
    """A config without syncrule_class / parameters is an error, as in MATLAB."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"syncrule_class": "ndi.time.syncrule.filematch"}))
    with pytest.raises(ValueError, match="syncrule_class"):
        ndi.setup.sync.sync_rule_from_config_file(bad)


def test_add_sync_rules_installs_vhlab_rules(session):
    """addSyncRules puts both vhlab-specific rules into the syncgraph."""
    ndi.setup.sync.add_sync_rules(session, "vhlab")
    names = _rule_class_names(session)
    assert "ndi_time_syncrule_filefind" in names
    assert "ndi_time_syncrule_commonTriggersOverlappingEpochs" in names


def test_add_sync_rules_is_idempotent(session):
    """Calling addSyncRules twice must not duplicate rules."""
    ndi.setup.sync.add_sync_rules(session, "vhlab")
    n1 = len(session.syncgraph.rules)
    ndi.setup.sync.add_sync_rules(session, "vhlab")
    n2 = len(session.syncgraph.rules)
    assert n1 == n2
    assert n1 == 2


def test_unknown_lab_is_noop(session):
    """A lab with no sync_rules folder leaves the syncgraph unchanged."""
    n0 = len(session.syncgraph.rules) if session.syncgraph is not None else 0
    ndi.setup.sync.add_sync_rules(session, "a_lab_that_does_not_exist")
    n1 = len(session.syncgraph.rules) if session.syncgraph is not None else 0
    assert n1 == n0
