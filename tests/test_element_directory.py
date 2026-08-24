"""
Port of MATLAB ndi.unittest.fun.file.ElementDirectoryTest.

MATLAB source files:
  +ndi/+fun/+file/pathSafeName.m          -> ndi.fun.file.pathSafeName
  +ndi/+fun/+file/elementDirectoryName.m  -> ndi.fun.file.elementDirectoryName
  +ndi/+fun/+file/elementDirectory.m      -> ndi.fun.file.elementDirectory

``ndi.element.elementstring()`` separates an element's name from its reference
with ``' | '``.  ``'|'`` is not a legal filename character on Windows, so the
element string must not be turned directly into a folder name.  These tests pin
the MATLAB contract of the sanitizer, of the two folder names (current and
legacy), and of the legacy-folder fallback, plus the four Python call sites that
build per-element working directories.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ndi.fun.file import elementDirectory, elementDirectoryName, pathSafeName


class _FakeElement:
    """Minimal stand-in for an ndi.element / ndi.probe: answers elementstring()."""

    def __init__(self, elementstring: str):
        self._elementstring = elementstring

    def elementstring(self) -> str:
        return self._elementstring


# ===========================================================================
# pathSafeName - the sanitizer contract
# ===========================================================================


class TestPathSafeName:
    """MATLAB contract: map to [A-Za-z0-9._-]; whitespace/control -> '_';
    everything else -> '-'; strip trailing '.'; prefix '_' on Windows reserved
    device names; empty -> 'x'."""

    def test_portable_name_unchanged(self):
        assert pathSafeName("ctx_-_1") == "ctx_-_1"
        assert pathSafeName("abcXYZ019._-") == "abcXYZ019._-"

    def test_space_becomes_underscore(self):
        assert pathSafeName("probe 1") == "probe_1"

    def test_pipe_becomes_dash(self):
        # the live bug: 'probe | 1' must not keep its '|'
        assert pathSafeName("probe | 1") == "probe_-_1"
        assert "|" not in pathSafeName("probe | 1")

    def test_matlab_doc_example(self):
        # from the MATLAB help text of pathSafeName
        assert pathSafeName("ctx_|_1") == "ctx_-_1"

    def test_windows_forbidden_characters_become_dash(self):
        for ch in '<>:"/\\|?*':
            assert pathSafeName(f"a{ch}b") == "a-b", ch

    def test_control_characters_become_underscore(self):
        assert pathSafeName("a\tb") == "a_b"
        assert pathSafeName("a\nb") == "a_b"
        assert pathSafeName("a\rb") == "a_b"
        assert pathSafeName("a\x00b") == "a_b"
        assert pathSafeName("a\x7fb") == "a_b"

    def test_non_ascii_whitespace_is_not_whitespace_to_matlab(self):
        # MATLAB only treats char < 32, char 127 and ' ' as whitespace/control;
        # U+00A0 falls through to the non-portable branch.
        assert pathSafeName("a\u00a0b") == "a-b"

    def test_trailing_dots_stripped(self):
        assert pathSafeName("name.") == "name"
        assert pathSafeName("name...") == "name"
        assert pathSafeName("name.txt") == "name.txt"
        # interior dots survive
        assert pathSafeName("a.b.c") == "a.b.c"

    def test_only_dots_becomes_x(self):
        assert pathSafeName("...") == "x"

    def test_empty_becomes_x(self):
        assert pathSafeName("") == "x"

    def test_windows_reserved_names_prefixed(self):
        for name in (
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM5",
            "COM9",
            "LPT1",
            "LPT5",
            "LPT9",
        ):
            assert pathSafeName(name) == "_" + name, name

    def test_windows_reserved_names_case_insensitive(self):
        assert pathSafeName("con") == "_con"
        assert pathSafeName("Com1") == "_Com1"

    def test_windows_reserved_names_with_extension(self):
        assert pathSafeName("CON.txt") == "_CON.txt"
        assert pathSafeName("com1.tar.gz") == "_com1.tar.gz"

    def test_windows_reserved_check_uses_first_dot(self):
        # baseName is everything before the FIRST '.', so 'a.CON' is not reserved
        assert pathSafeName("a.CON") == "a.CON"
        # leading dot -> empty baseName -> not reserved
        assert pathSafeName(".CON") == ".CON"

    def test_near_reserved_names_untouched(self):
        for name in ("COM0", "COM10", "LPT0", "CONS", "CONSOLE", "AUXX"):
            assert pathSafeName(name) == name, name

    def test_reserved_name_with_trailing_dot(self):
        # trailing dots are stripped first, so 'CON.' is reserved
        assert pathSafeName("CON.") == "_CON"

    def test_unicode_becomes_dash_per_utf16_code_unit(self):
        # MATLAB char() works in UTF-16 code units. A BMP character is one
        # unit -> one '-'; an astral character is a surrogate pair -> two '-'.
        assert pathSafeName("café") == "caf-"
        assert pathSafeName("µV") == "-V"
        assert pathSafeName("神経") == "--"
        assert pathSafeName("a\U0001f389b") == "a--b"

    def test_result_is_always_in_the_portable_set(self):
        import re

        for probe_name in (
            "probe | 1",
            "ctx | 12",
            "a\tb",
            "神経 | 3",
            'weird<>:"/\\|?*name',
            "...",
            "",
            "CON",
        ):
            assert re.fullmatch(r"[A-Za-z0-9._-]+", pathSafeName(probe_name)), probe_name

    def test_rejects_non_text(self):
        # MATLAB: arguments name {mustBeTextScalar}
        with pytest.raises(TypeError):
            pathSafeName(1)
        with pytest.raises(TypeError):
            pathSafeName(["a", "b"])


# ===========================================================================
# elementDirectoryName - current name + legacy name
# ===========================================================================


class TestElementDirectoryName:
    def test_from_element_object(self):
        dir_name, legacy = elementDirectoryName(_FakeElement("ctx | 1"))
        assert dir_name == "ctx_-_1"
        assert legacy == "ctx_|_1"

    def test_from_string(self):
        dir_name, legacy = elementDirectoryName("ctx | 1")
        assert dir_name == "ctx_-_1"
        assert legacy == "ctx_|_1"

    def test_legacy_only_replaces_spaces(self):
        dir_name, legacy = elementDirectoryName("a b|c*d")
        assert legacy == "a_b|c*d"
        assert dir_name == "a_b-c-d"

    def test_already_safe_names_are_equal(self):
        dir_name, legacy = elementDirectoryName("probe 1")
        assert dir_name == legacy == "probe_1"

    def test_reserved_element_name(self):
        dir_name, legacy = elementDirectoryName("CON | 1")
        assert legacy == "CON_|_1"
        assert dir_name == "CON_-_1"  # baseName has no '.', 'CON_-_1' != 'CON'


# ===========================================================================
# elementDirectory - path resolution with the legacy fallback
# ===========================================================================


class TestElementDirectory:
    def test_new_name_when_nothing_exists(self, tmp_path):
        dir_path, dir_name, is_legacy = elementDirectory(tmp_path, _FakeElement("ctx | 1"))
        assert dir_name == "ctx_-_1"
        assert dir_path == tmp_path / "ctx_-_1"
        assert is_legacy is False
        assert not dir_path.exists()  # resolution must not create anything

    def test_new_name_preferred_when_it_exists(self, tmp_path):
        (tmp_path / "ctx_-_1").mkdir()
        dir_path, dir_name, is_legacy = elementDirectory(tmp_path, _FakeElement("ctx | 1"))
        assert dir_name == "ctx_-_1"
        assert dir_path == tmp_path / "ctx_-_1"
        assert is_legacy is False

    @pytest.mark.skipif(
        sys.platform.startswith("win"), reason="'|' folders cannot be created on Windows"
    )
    def test_legacy_folder_found_when_only_it_exists(self, tmp_path):
        (tmp_path / "ctx_|_1").mkdir()
        dir_path, dir_name, is_legacy = elementDirectory(tmp_path, _FakeElement("ctx | 1"))
        assert dir_name == "ctx_|_1"
        assert dir_path == tmp_path / "ctx_|_1"
        assert is_legacy is True

    @pytest.mark.skipif(
        sys.platform.startswith("win"), reason="'|' folders cannot be created on Windows"
    )
    def test_new_name_wins_when_both_exist(self, tmp_path):
        (tmp_path / "ctx_-_1").mkdir()
        (tmp_path / "ctx_|_1").mkdir()
        _dir_path, dir_name, is_legacy = elementDirectory(tmp_path, _FakeElement("ctx | 1"))
        assert dir_name == "ctx_-_1"
        assert is_legacy is False

    @pytest.mark.skipif(
        sys.platform.startswith("win"), reason="'|' folders cannot be created on Windows"
    )
    def test_legacy_file_is_not_a_folder(self, tmp_path):
        # a *file* by the legacy name must not trigger the fallback
        (tmp_path / "ctx_|_1").write_text("not a folder")
        _dir_path, dir_name, is_legacy = elementDirectory(tmp_path, _FakeElement("ctx | 1"))
        assert dir_name == "ctx_-_1"
        assert is_legacy is False

    def test_no_fallback_when_names_are_equal(self, tmp_path):
        # 'probe 1' sanitizes to the same name as the legacy scheme; nothing to fall back to
        dir_path, dir_name, is_legacy = elementDirectory(tmp_path, "probe 1")
        assert dir_name == "probe_1"
        assert dir_path == tmp_path / "probe_1"
        assert is_legacy is False

    def test_accepts_str_parent(self, tmp_path):
        dir_path, _dir_name, _is_legacy = elementDirectory(str(tmp_path), "ctx | 1")
        assert dir_path == tmp_path / "ctx_-_1"

    def test_accepts_element_string_directly(self, tmp_path):
        _dir_path, dir_name, _is_legacy = elementDirectory(tmp_path, "ctx | 1")
        assert dir_name == "ctx_-_1"


# ===========================================================================
# Call sites: the folders these helpers are supposed to be building
# ===========================================================================


class _ExportProbe(_FakeElement):
    """Probe with just enough surface for export_all_binary (no epochs)."""

    def epochtable(self, force_rebuild: bool = False):
        return [], []


class _ExportSession:
    def __init__(self, path: Path, probes: list):
        self.path = str(path)
        self.reference = "testsession"
        self._probes = probes

    def getprobes(self, **kwargs):
        return self._probes


class TestExportAllBinaryDirectory:
    """ndi.fun.probe.export_all_binary must not write a '|' folder."""

    def test_creates_pathsafe_directory(self, tmp_path):
        from ndi.fun.probe import export_all_binary

        probe = _ExportProbe("ctx | 1")
        sess = _ExportSession(tmp_path, [probe])
        export_all_binary(sess, verbose=False)

        assert (tmp_path / "kilosort" / "ctx_-_1").is_dir()
        assert not (tmp_path / "kilosort" / "ctx_|_1").exists()
        names = [p.name for p in (tmp_path / "kilosort").iterdir()]
        assert all("|" not in n for n in names), names

    @pytest.mark.skipif(
        sys.platform.startswith("win"), reason="'|' folders cannot be created on Windows"
    )
    def test_reuses_existing_legacy_directory(self, tmp_path):
        from ndi.fun.probe import export_all_binary

        legacy = tmp_path / "kilosort" / "ctx_|_1"
        legacy.mkdir(parents=True)

        probe = _ExportProbe("ctx | 1")
        sess = _ExportSession(tmp_path, [probe])
        export_all_binary(sess, verbose=False)

        assert (legacy / "kilosort.bin").is_file()
        assert not (tmp_path / "kilosort" / "ctx_-_1").exists()


class _InfoProbe(_FakeElement):
    """Probe with only elementstring(), which is all getInfo() needs."""


class _InfoSession:
    def __init__(self, path: Path):
        self.path = str(path)


def _write_min_kilosort_fixture(kdir: Path) -> None:
    import numpy as np

    kdir.mkdir(parents=True, exist_ok=True)
    np.save(kdir / "spike_times.npy", np.array([10, 20, 30], dtype=np.int64))
    np.save(kdir / "spike_clusters.npy", np.array([0, 0, 1], dtype=np.int64))
    (kdir / "cluster_group.tsv").write_text("cluster_id\tgroup\n0\tgood\n1\tmua\n")


class TestKilosortImportDirectory:
    """The importer must find the folder the exporter writes, and must still
    find folders written by older versions of NDI."""

    def test_getinfo_reads_pathsafe_directory(self, tmp_path):
        from ndi.fun.probe.import_ import kilosort

        kdir = tmp_path / "kilosort" / "ctx_-_1" / "kilosort_output"
        _write_min_kilosort_fixture(kdir)

        info, _summary = kilosort.getInfo(_InfoSession(tmp_path), _InfoProbe("ctx | 1"))
        assert Path(info["directory"]) == kdir
        assert info["num_clusters"] == 2

    @pytest.mark.skipif(
        sys.platform.startswith("win"), reason="'|' folders cannot be created on Windows"
    )
    def test_getinfo_falls_back_to_legacy_directory(self, tmp_path):
        from ndi.fun.probe.import_ import kilosort

        kdir = tmp_path / "kilosort" / "ctx_|_1" / "kilosort_output"
        _write_min_kilosort_fixture(kdir)

        info, _summary = kilosort.getInfo(_InfoSession(tmp_path), _InfoProbe("ctx | 1"))
        assert Path(info["directory"]) == kdir
        assert info["num_clusters"] == 2
