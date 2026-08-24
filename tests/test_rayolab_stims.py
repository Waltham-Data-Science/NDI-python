"""Tests for the RayoLab stimulus metadata reader and its DAQ-system config.

Python equivalent of MATLAB
``tests/+ndi/+unittest/+daq/+metadatareader/TestRayoLabStims.m`` (added in
NDI-matlab ``a05a0a80a``, PR #876), plus a config regression test for the
vendored ``ndi_common/daq_systems/rayolab/rayo_stim.json``.

Background (NDI-matlab a05a0a80a): ``rayo_stim.json`` stored the
file-navigator ``'#'`` wildcard in ``MetadataReaderFileParameters``. The
``'#'`` is resolved by ``ndi.file.navigator`` for ``FileParameters`` and
``EpochProbeMapFileParameters``, but the metadata reader uses its pattern
raw as a regular expression, where ``'#'`` is a literal character that
never appears in a recording filename. Ingest therefore aborted with
"No epochfiles match regular expression #_\\d{6}_\\d{6}._epochprobemap.txt".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ndi.common import ndi_common_PathConstants
from ndi.daq.metadatareader import ndi_daq_metadatareader_RayoLabStims
from ndi.util.matlab_regex import matlab_to_python_regex

# A real RayoLab epoch's file pair (from the ingest failure that motivated
# the MATLAB fix).
EPOCH_RHD = "/data/EST_VISUAL_PREDROGA_251121_201438.rhd"
EPOCH_PROBEMAP = "/data/EST_VISUAL_PREDROGA_251121_201438._epochprobemap.txt"

# The navigator-only wildcard. Valid in FileParameters /
# EpochProbeMapFileParameters, never valid in a raw regexp.
NAVIGATOR_WILDCARD = "#"


def _rayo_stim_config() -> dict:
    config_path = (
        Path(ndi_common_PathConstants.COMMON_FOLDER) / "daq_systems" / "rayolab" / "rayo_stim.json"
    )
    assert config_path.is_file(), f"vendored rayo_stim.json not found at {config_path}"
    return json.loads(config_path.read_text(encoding="utf-8"))


class TestRayoStimConfig:
    """Regression tests for ndi_common/daq_systems/rayolab/rayo_stim.json."""

    def test_metadata_reader_file_parameters_is_a_plain_regexp(self):
        """MetadataReaderFileParameters must not carry the navigator '#'.

        The metadata reader compiles this string directly; the '#' is only
        substituted by ndi.file.navigator, so a stored '#' makes the
        pattern match nothing.
        """
        pattern = _rayo_stim_config()["MetadataReaderFileParameters"]
        assert NAVIGATOR_WILDCARD not in pattern, (
            f"MetadataReaderFileParameters {pattern!r} still contains the "
            f"file-navigator '#' wildcard, which the metadata reader does not "
            f"resolve (NDI-matlab a05a0a80a)."
        )

    def test_metadata_reader_file_parameters_matches_a_real_epoch_file(self):
        """The stored pattern must actually match a RayoLab epochprobemap file."""
        pattern = _rayo_stim_config()["MetadataReaderFileParameters"]
        compiled = re.compile(matlab_to_python_regex(pattern), re.IGNORECASE)
        assert compiled.search(EPOCH_PROBEMAP) is not None, (
            f"MetadataReaderFileParameters {pattern!r} does not match " f"{EPOCH_PROBEMAP!r}."
        )
        assert compiled.search(EPOCH_RHD) is None, (
            f"MetadataReaderFileParameters {pattern!r} should not match the "
            f"recording file {EPOCH_RHD!r}."
        )

    def test_navigator_parameters_keep_the_wildcard(self):
        """FileParameters/EpochProbeMapFileParameters keep '#'.

        Guard against over-correcting the fix: the file navigator resolves
        '#' for these two fields and needs it (NDI-matlab a05a0a80a leaves
        them untouched).
        """
        config = _rayo_stim_config()
        for entry in config["FileParameters"]:
            assert entry.startswith(
                NAVIGATOR_WILDCARD
            ), f"FileParameters entry {entry!r} lost the navigator '#' wildcard."
        assert config["EpochProbeMapFileParameters"].startswith(NAVIGATOR_WILDCARD)


class TestRayoLabStims:
    """Mirror of MATLAB ndi.unittest.daq.metadatareader.TestRayoLabStims."""

    def test_readmetadata_returns_constant(self):
        """readmetadata ignores epochfiles and returns [{'stimid': 1}]."""
        reader = ndi_daq_metadatareader_RayoLabStims()
        params = reader.readmetadata(["anything.rhd"])
        assert params == [{"stimid": 1}]

    def test_readmetadata_does_not_require_a_matching_file(self):
        """A non-matching tsv pattern must not break readmetadata.

        Regression for the RayoLab ingest failure: sessions already built
        with the '#' pattern stored in their daqmetadatareader document must
        keep working without reconfiguration.
        """
        reader = ndi_daq_metadatareader_RayoLabStims(r"#_\d{6}_\d{6}\._epochprobemap\.txt\>")
        params = reader.readmetadata([EPOCH_RHD, EPOCH_PROBEMAP])
        assert params == [{"stimid": 1}]

    def test_readmetadatafromfile_ignores_the_file(self):
        """readmetadatafromfile ignores its argument and returns the constant."""
        reader = ndi_daq_metadatareader_RayoLabStims()
        assert reader.readmetadatafromfile(None) == [{"stimid": 1}]

    def test_base_class_still_requires_a_matching_file(self):
        """The override is on RayoLabStims, not the base class.

        Confirms the base ndi_daq_metadatareader behaviour that motivated the
        override is unchanged, so this test pins the reason the override
        exists rather than a coincidence.
        """
        from ndi.daq.metadatareader import ndi_daq_metadatareader

        base = ndi_daq_metadatareader(r"nomatch_.*\.tsv")
        with pytest.raises(ValueError, match="No files match pattern"):
            base.readmetadata([EPOCH_RHD, EPOCH_PROBEMAP])
