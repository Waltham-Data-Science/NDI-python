"""
Tests for Batch E: Minor remaining MATLAB gaps.

Tests find_epoch_node(), SessionTable, TuningFit.
"""

from pathlib import Path

import numpy as np
import pytest

from ndi.calc.tuning_fit import TuningFit

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from ndi.epoch.functions import find_epoch_node
from ndi.session.sessiontable import SessionTable


class TestImports:
    """Verify all Batch E items are importable."""

    def test_import_find_epoch_node_from_epoch(self):
        from ndi.epoch import find_epoch_node as fen

        assert fen is find_epoch_node

    def test_import_session_table_from_session(self):
        from ndi.session import SessionTable as ST

        assert ST is SessionTable

    def test_import_tuning_fit_from_calc(self):
        from ndi.calc import TuningFit as TF

        assert TF is TuningFit


# ===========================================================================
# find_epoch_node
# ===========================================================================


class TestFindEpochNode:
    """Tests for the epoch node search function."""

    @pytest.fixture
    def sample_nodes(self):
        """A small array of epoch nodes for testing."""
        return [
            {
                "objectname": "probe1",
                "objectclass": "Probe",
                "epoch_id": "e1",
                "epoch_session_id": "s1",
                "epoch_clock": "dev_local_time",
                "t0_t1": (0.0, 10.0),
            },
            {
                "objectname": "probe2",
                "objectclass": "Probe",
                "epoch_id": "e2",
                "epoch_session_id": "s1",
                "epoch_clock": "dev_local_time",
                "t0_t1": (10.0, 20.0),
            },
            {
                "objectname": "probe1",
                "objectclass": "Element",
                "epoch_id": "e3",
                "epoch_session_id": "s2",
                "epoch_clock": "utc",
                "t0_t1": (0.0, 100.0),
            },
        ]

    def test_empty_search_matches_all(self, sample_nodes):
        """Empty search node = wildcard, matches everything."""
        result = find_epoch_node({}, sample_nodes)
        assert result == [0, 1, 2]

    def test_search_by_epoch_id(self, sample_nodes):
        result = find_epoch_node({"epoch_id": "e2"}, sample_nodes)
        assert result == [1]

    def test_search_by_objectname(self, sample_nodes):
        result = find_epoch_node({"objectname": "probe1"}, sample_nodes)
        assert result == [0, 2]

    def test_search_by_objectclass(self, sample_nodes):
        result = find_epoch_node({"objectclass": "Probe"}, sample_nodes)
        assert result == [0, 1]

    def test_search_by_session_id(self, sample_nodes):
        result = find_epoch_node({"epoch_session_id": "s2"}, sample_nodes)
        assert result == [2]

    def test_search_by_multiple_fields(self, sample_nodes):
        result = find_epoch_node(
            {"objectname": "probe1", "objectclass": "Probe"},
            sample_nodes,
        )
        assert result == [0]

    def test_search_no_match(self, sample_nodes):
        result = find_epoch_node({"epoch_id": "e99"}, sample_nodes)
        assert result == []

    def test_search_by_epoch_clock(self, sample_nodes):
        result = find_epoch_node({"epoch_clock": "utc"}, sample_nodes)
        assert result == [2]

    def test_search_by_time_value_in_range(self, sample_nodes):
        result = find_epoch_node({"time_value": 5.0}, sample_nodes)
        # 5.0 is in [0, 10] (node 0) and [0, 100] (node 2)
        assert result == [0, 2]

    def test_search_by_time_value_boundary(self, sample_nodes):
        result = find_epoch_node({"time_value": 10.0}, sample_nodes)
        # 10.0 is at boundary of node 0 [0,10] and node 1 [10,20] and node 2 [0,100]
        assert 0 in result
        assert 1 in result
        assert 2 in result

    def test_search_by_time_value_out_of_range(self, sample_nodes):
        result = find_epoch_node({"time_value": 200.0}, sample_nodes)
        assert result == []

    def test_combined_string_and_time(self, sample_nodes):
        result = find_epoch_node(
            {"objectname": "probe1", "time_value": 5.0},
            sample_nodes,
        )
        # probe1 = [0, 2]; time 5.0 in [0,10] and [0,100]
        assert result == [0, 2]

    def test_empty_node_array(self):
        result = find_epoch_node({"epoch_id": "e1"}, [])
        assert result == []

    def test_none_field_treated_as_wildcard(self, sample_nodes):
        result = find_epoch_node({"epoch_id": None}, sample_nodes)
        assert result == [0, 1, 2]

    def test_empty_string_treated_as_wildcard(self, sample_nodes):
        result = find_epoch_node({"objectname": ""}, sample_nodes)
        assert result == [0, 1, 2]


# ===========================================================================
# SessionTable
# ===========================================================================


class TestSessionTable:
    """Tests for the session table registry."""

    @pytest.fixture
    def table_dir(self, tmp_path):
        """Create a temp directory for the session table file."""
        table_file = tmp_path / "test_sessiontable.txt"
        return table_file

    @pytest.fixture
    def table(self, table_dir):
        """Create a SessionTable instance using a temp file."""
        return SessionTable(table_path=table_dir)

    def test_init_default_path(self):
        table = SessionTable()
        expected = Path.home() / ".ndi" / "preferences" / "local_sessiontable.txt"
        assert table._table_path == expected

    def test_init_custom_path(self, table_dir):
        table = SessionTable(table_path=table_dir)
        assert table._table_path == table_dir

    def test_empty_table_on_new(self, table):
        result = table.get_session_table()
        assert result == []

    def test_add_entry(self, table):
        table.add_entry("sess1", "/data/experiment1")
        entries = table.get_session_table()
        assert len(entries) == 1
        assert entries[0]["session_id"] == "sess1"
        assert entries[0]["path"] == "/data/experiment1"

    def test_add_multiple_entries(self, table):
        table.add_entry("sess1", "/data/exp1")
        table.add_entry("sess2", "/data/exp2")
        entries = table.get_session_table()
        assert len(entries) == 2

    def test_add_replaces_existing(self, table):
        table.add_entry("sess1", "/old/path")
        table.add_entry("sess1", "/new/path")
        entries = table.get_session_table()
        assert len(entries) == 1
        assert entries[0]["path"] == "/new/path"

    def test_get_session_path_found(self, table):
        table.add_entry("sess1", "/data/exp1")
        assert table.get_session_path("sess1") == "/data/exp1"

    def test_get_session_path_not_found(self, table):
        assert table.get_session_path("nonexistent") is None

    def test_remove_entry(self, table):
        table.add_entry("sess1", "/data/exp1")
        table.add_entry("sess2", "/data/exp2")
        table.remove_entry("sess1")
        entries = table.get_session_table()
        assert len(entries) == 1
        assert entries[0]["session_id"] == "sess2"

    def test_remove_nonexistent_entry(self, table):
        table.add_entry("sess1", "/data/exp1")
        table.remove_entry("nonexistent")
        entries = table.get_session_table()
        assert len(entries) == 1

    def test_clear(self, table):
        table.add_entry("sess1", "/data/exp1")
        table.add_entry("sess2", "/data/exp2")
        table.clear()
        entries = table.get_session_table()
        assert len(entries) == 0

    def test_clear_with_backup(self, table):
        table.add_entry("sess1", "/data/exp1")
        table.clear(make_backup=True)
        entries = table.get_session_table()
        assert len(entries) == 0
        # Backup file should exist
        backups = table.backup_file_list()
        assert len(backups) == 1

    def test_backup(self, table):
        table.add_entry("sess1", "/data/exp1")
        backup_path = table.backup()
        assert backup_path is not None
        assert backup_path.exists()
        assert "_bkup001" in backup_path.name

    def test_backup_numbered(self, table):
        table.add_entry("sess1", "/data/exp1")
        table.backup()
        table.backup()
        backups = table.backup_file_list()
        assert len(backups) == 2
        assert "_bkup001" in backups[0].name
        assert "_bkup002" in backups[1].name

    def test_backup_no_file(self, table):
        result = table.backup()
        assert result is None

    def test_check_table_valid(self, table, tmp_path):
        # Use a real existing directory as the path
        table.add_entry("sess1", str(tmp_path))
        valid, results = table.check_table()
        assert valid is True
        assert len(results) == 1
        assert results[0]["exists"] is True

    def test_check_table_nonexistent_path(self, table):
        table.add_entry("sess1", "/nonexistent/path")
        valid, results = table.check_table()
        assert valid is True
        assert len(results) == 1
        assert results[0]["exists"] is False

    def test_is_valid_table(self, table):
        entries = [{"session_id": "a", "path": "/b"}]
        valid, msg = table.is_valid_table(entries)
        assert valid is True
        assert msg == ""

    def test_is_valid_table_missing_path(self, table):
        entries = [{"session_id": "a"}]
        valid, msg = table.is_valid_table(entries)
        assert valid is False
        assert "path" in msg

    def test_is_valid_table_missing_session_id(self, table):
        entries = [{"path": "/b"}]
        valid, msg = table.is_valid_table(entries)
        assert valid is False
        assert "session_id" in msg

    def test_add_empty_session_id_raises(self, table):
        with pytest.raises(ValueError, match="session_id"):
            table.add_entry("", "/data/exp1")

    def test_add_empty_path_raises(self, table):
        with pytest.raises(ValueError, match="path"):
            table.add_entry("sess1", "")

    def test_persistence_across_instances(self, table_dir):
        t1 = SessionTable(table_path=table_dir)
        t1.add_entry("sess1", "/data/exp1")

        t2 = SessionTable(table_path=table_dir)
        assert t2.get_session_path("sess1") == "/data/exp1"

    def test_repr(self, table):
        assert "SessionTable" in repr(table)

    def test_local_table_filename(self):
        path = SessionTable.local_table_filename()
        assert "local_sessiontable" in path.name
        assert path.suffix == ".txt"


# ===========================================================================
# TuningFit
# ===========================================================================


class ConcreteTuningFit(TuningFit):
    """Concrete subclass for testing the abstract TuningFit."""

    def calculate(self, parameters):
        from ndi.document import Document

        doc = Document("base")
        return [doc]

    def default_search_for_input_parameters(self):
        from ndi.query import Query

        return {
            "input_parameters": {
                "independent_variable": ["angle"],
            },
            "depends_on": [],
            "query": [
                {"name": "document_id", "query": Query("").isa("stimulus_response_scalar")},
            ],
        }

    def generate_mock_parameters(self, scope, index):
        x = np.linspace(0, 360, 8, endpoint=False)
        r = np.cos(np.radians(x - 90))
        return (
            {"stimulus_type": "grating"},
            ["angle"],
            x,
            r,
        )


class TestTuningFit:
    """Tests for the TuningFit abstract base class."""

    def test_is_subclass_of_calculator(self):
        from ndi.calculator import Calculator

        assert issubclass(TuningFit, Calculator)

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            TuningFit()

    def test_concrete_subclass_instantiates(self):
        fit = ConcreteTuningFit()
        assert isinstance(fit, TuningFit)

    def test_scope_presets(self):
        assert "highSNR" in TuningFit.SCOPE_PRESETS
        assert "lowSNR" in TuningFit.SCOPE_PRESETS
        assert TuningFit.SCOPE_PRESETS["highSNR"]["reps"] == 5
        assert TuningFit.SCOPE_PRESETS["highSNR"]["noise"] == 0.001
        assert TuningFit.SCOPE_PRESETS["lowSNR"]["reps"] == 10
        assert TuningFit.SCOPE_PRESETS["lowSNR"]["noise"] == 1.0

    def test_generate_mock_parameters(self):
        fit = ConcreteTuningFit()
        param_struct, indep_var, x, r = fit.generate_mock_parameters("highSNR", 1)
        assert isinstance(param_struct, dict)
        assert isinstance(indep_var, list)
        assert len(x) == 8
        assert len(r) == 8

    def test_generate_mock_docs_high_snr(self):
        fit = ConcreteTuningFit()
        docs, output, expected = fit.generate_mock_docs("highSNR", 2)
        assert len(docs) == 2
        assert len(output) == 2
        assert len(expected) == 2
        # First test should have data
        assert docs[0] is not None
        assert docs[0]["reps"] == 5
        assert docs[0]["noise"] == 0.001

    def test_generate_mock_docs_low_snr(self):
        fit = ConcreteTuningFit()
        docs, output, expected = fit.generate_mock_docs("lowSNR", 1)
        assert docs[0]["reps"] == 10
        assert docs[0]["noise"] == 1.0

    def test_generate_mock_docs_invalid_scope(self):
        fit = ConcreteTuningFit()
        with pytest.raises(ValueError, match="scope"):
            fit.generate_mock_docs("invalid", 1)

    def test_generate_mock_docs_specific_indices(self):
        fit = ConcreteTuningFit()
        docs, output, expected = fit.generate_mock_docs(
            "highSNR",
            3,
            specific_test_inds=[2],
        )
        assert len(docs) == 3
        assert docs[0] is None  # skipped
        assert docs[1] is not None  # index 2 (1-based) → slot 1 (0-based)
        assert docs[2] is None  # skipped

    def test_generate_mock_docs_stim_responses(self):
        fit = ConcreteTuningFit()
        docs, _, _ = fit.generate_mock_docs("highSNR", 1)
        stim_resp = docs[0]["stim_responses"]
        # 8 stimuli * 5 reps = 40 responses
        assert len(stim_resp) == 40
        assert "stimid" in stim_resp[0]
        assert "response" in stim_resp[0]
        assert "parameters" in stim_resp[0]
        assert "angle" in stim_resp[0]["parameters"]

    def test_generate_mock_docs_expected_output(self):
        fit = ConcreteTuningFit()
        _, _, expected = fit.generate_mock_docs("highSNR", 1)
        exp = expected[0]
        assert "independent_variable" in exp
        assert "response_mean" in exp
        assert "response_stderr" in exp
        assert len(exp["response_mean"]) == 8

    def test_repr(self):
        fit = ConcreteTuningFit()
        assert "TuningFit" in repr(fit)
