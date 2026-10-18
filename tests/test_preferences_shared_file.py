"""Tests for sharing ~/.ndi/NDI_Preferences.json with other NDI versions.

MATLAB counterpart: ndi.preferences (saveToDisk), tested in
tests/+ndi/+unittest/TestPreferences.m of NDI-matlab.

NDI-python and NDI-matlab read and write the same file, and each registers
preferences the other does not have. Saving from one side must not drop the
other side's entries, including ones written after this process first read
the file.
"""

from __future__ import annotations

import json

from ndi.preferences import ndi_preferences


def test_saving_keeps_entries_this_version_does_not_register(tmp_path):
    f = tmp_path / "NDI_Preferences.json"
    f.write_text(
        json.dumps(
            {
                "Tools__FFmpegPath": "/opt/ffmpeg/bin/ffmpeg",
                "GUI__LightsheetZarrManager__ViewerLauncher": "",
                "OtherNDI__Count": 7,
            }
        ),
        encoding="utf-8",
    )
    prefs = ndi_preferences(filename=f)

    prefs.set("Cloud.Download.Max_Document_Batch_Count", 42)

    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["Tools__FFmpegPath"] == "/opt/ffmpeg/bin/ffmpeg"
    assert saved["GUI__LightsheetZarrManager__ViewerLauncher"] == ""
    assert saved["OtherNDI__Count"] == 7
    assert saved["Cloud__Download__Max_Document_Batch_Count"] == 42


def test_entries_written_after_loading_survive_a_save(tmp_path):
    f = tmp_path / "NDI_Preferences.json"
    prefs = ndi_preferences(filename=f)
    # The other language saves while this process is running.
    on_disk = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    on_disk["Tools__RscriptPath"] = "C:/Program Files/R/R-4.4.1/bin/Rscript.exe"
    f.write_text(json.dumps(on_disk), encoding="utf-8")

    prefs.set("Cloud.Download.Max_Document_Batch_Count", 43)

    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["Tools__RscriptPath"] == "C:/Program Files/R/R-4.4.1/bin/Rscript.exe"
    assert saved["Cloud__Download__Max_Document_Batch_Count"] == 43


def test_this_version_still_wins_for_its_own_keys(tmp_path):
    f = tmp_path / "NDI_Preferences.json"
    prefs = ndi_preferences(filename=f)
    f.write_text(json.dumps({"Cloud__Download__Max_Document_Batch_Count": 5}), encoding="utf-8")

    prefs.set("Cloud.Download.Max_Document_Batch_Count", 44)

    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["Cloud__Download__Max_Document_Batch_Count"] == 44


def test_saving_over_a_corrupt_file_still_writes(tmp_path):
    f = tmp_path / "NDI_Preferences.json"
    prefs = ndi_preferences(filename=f)
    f.write_text("{ not json", encoding="utf-8")

    prefs.set("Cloud.Download.Max_Document_Batch_Count", 45)

    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["Cloud__Download__Max_Document_Batch_Count"] == 45
