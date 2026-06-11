"""PR9 §3.5/§3.6: security, packaging, and CI hardening.

Each test pins one hardening behavior so a regression (someone restoring
``eval``, dropping the chmod, un-pinning a dependency, re-committing the
artifact tarball, ...) fails loudly.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# §3.5-2  eval() on document-derived strings -> ast.literal_eval
# ===========================================================================


class TestNavigatorNoEval:
    def test_module_parser_rejects_call_expression(self):
        # Module-level helper (the file/epoch path). ``ndi.file`` re-exports the
        # class under the name ``navigator``, so import the function directly.
        from ndi.file.navigator import _parse_fileparameters

        # A call expression executes under eval(); literal_eval must refuse it
        # and the caller falls back to "no patterns" (None).
        assert _parse_fileparameters("__import__('os').getcwd()") is None

    def test_module_parser_still_handles_python_list(self):
        from ndi.file.navigator import _parse_fileparameters

        assert _parse_fileparameters("['#.rhd', '#.dat']") == ["#.rhd", "#.dat"]

    def test_module_parser_preserves_matlab_cell_order(self):
        from ndi.file.navigator import _parse_fileparameters

        assert _parse_fileparameters("{ '#.rhd', '#.epochprobemap.ndi' }") == [
            "#.rhd",
            "#.epochprobemap.ndi",
        ]

    def test_static_parser_returns_raw_on_non_literal(self):
        from ndi.file.navigator import ndi_file_navigator

        # Not a cell array, not a literal -> returned verbatim, never executed.
        assert ndi_file_navigator._parse_fileparameters("os.getcwd()") == "os.getcwd()"
        assert ndi_file_navigator._parse_fileparameters("['a', 'b']") == ["a", "b"]

    def test_parser_does_not_execute_code(self, tmp_path):
        """The headline RCE guard: a crafted fileparameters string must not
        run code. Under eval() the payload below would create a file."""
        import ndi.file.navigator as navigator

        sentinel = tmp_path / "pwned"
        payload = f"[open({str(sentinel)!r}, 'w').close()]"
        navigator._parse_fileparameters(payload)
        assert not sentinel.exists(), "fileparameters parsing executed code (eval leak)"


# ===========================================================================
# §3.5-1  Secrets at rest: chmod 0600
# ===========================================================================


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
class TestProfileFilePermissions:
    def test_profile_and_secret_files_are_owner_only(self, tmp_path, monkeypatch):
        import ndi.cloud.profile as profile

        monkeypatch.setenv("NDI_PREFDIR", str(tmp_path))
        profile.reset()
        profile.use_backend("aes")  # writes both the profiles JSON and secrets JSON
        try:
            profile.add("nick", "user@example.com", "hunter2")

            prof_file = profile.filename()
            sec_file = profile.secrets_filename()

            assert prof_file.exists()
            assert stat.S_IMODE(os.stat(prof_file).st_mode) == 0o600
            assert sec_file.exists()
            assert stat.S_IMODE(os.stat(sec_file).st_mode) == 0o600
        finally:
            profile.reset()


# ===========================================================================
# §3.5-6  XML parsing via defusedxml (no entity expansion)
# ===========================================================================


class TestDefusedXml:
    _ENTITY_PAYLOAD = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE root [ <!ENTITY a "EXPANDED"> ]>\n'
        "<TaxaSet><Taxon><ScientificName>&a;</ScientificName></Taxon></TaxaSet>"
    )

    def test_provider_parser_refuses_internal_entities(self, monkeypatch):
        """NCBITaxonProvider parses network XML; defusedxml must reject the
        internal entity that stdlib ElementTree would happily expand."""
        from defusedxml.common import EntitiesForbidden

        from ndi.ontology.providers import NCBITaxonProvider

        class FakeResp:
            text = self._ENTITY_PAYLOAD

        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResp())

        with pytest.raises(EntitiesForbidden):
            NCBITaxonProvider()._lookup_taxid("10090")

    def test_stdlib_would_have_expanded(self):
        """Contrast: the stdlib parser does NOT raise on the same payload —
        evidence the defusedxml switch is load-bearing."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(self._ENTITY_PAYLOAD)
        assert root.findtext(".//ScientificName") == "EXPANDED"


# ===========================================================================
# §3.5-7  Download path-traversal sanitization
# ===========================================================================


class TestDownloadPathTraversal:
    def test_malicious_filename_stays_within_target(self, tmp_path, monkeypatch):
        from ndi.cloud import download as dl

        target = tmp_path / "target"
        outside = tmp_path / "outside"
        outside.mkdir()

        class Doc:
            def __init__(self, props):
                self.document_properties = props

        malicious = Doc(
            {
                "base": {"id": "abc123"},
                "generic_file": {"filename": "../outside/PWNED.bin"},
                "files": {
                    "file_info": [{"name": "../outside/PWNED.bin", "locations": [{"uid": "u1"}]}]
                },
            }
        )

        class DS:
            def database_search(self, q):
                return [malicious]

        class FakeResp:
            status_code = 200

            def iter_content(self, chunk_size=65536):
                yield b"payload"

        monkeypatch.setattr(
            "ndi.cloud.internal.getCloudDatasetIdForLocalDataset",
            lambda *a, **k: ("cloud-ds-id", None),
        )
        monkeypatch.setattr(
            "ndi.cloud.api.files.getFileDetails",
            lambda *a, **k: {"downloadUrl": "http://example/file"},
        )
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResp())

        ok, msg, report = dl.downloadGenericFiles(
            DS(), ["abc123"], target, verbose=False, naming_strategy="original"
        )

        assert ok, msg
        # The traversal was neutralized to a basename inside target...
        assert (target / "PWNED.bin").exists()
        # ...and nothing escaped into the sibling directory.
        assert not (outside / "PWNED.bin").exists()


# ===========================================================================
# §3.6  Test ergonomics: MATLAB BYOL guard skips (not errors) when unset
# ===========================================================================


class TestLicenseGuardSkips:
    def test_skips_module_when_env_unset(self, monkeypatch):
        from tests._matlab_license_guard import ENV_VAR, fatal_check_license_env

        monkeypatch.delenv(ENV_VAR, raising=False)
        with pytest.raises(pytest.skip.Exception):
            fatal_check_license_env()

    def test_passes_when_env_set(self, monkeypatch):
        from tests._matlab_license_guard import ENV_VAR, fatal_check_license_env

        monkeypatch.setenv(ENV_VAR, "false")
        fatal_check_license_env()  # must not raise


# ===========================================================================
# §3.5-3 / §3.5-5  Packaging & supply-chain hygiene
# ===========================================================================


class TestPackagingHygiene:
    def test_git_deps_are_pinned_not_floating(self):
        text = (ROOT / "pyproject.toml").read_text()
        assert "@main" not in text, "git dependencies must be pinned to a tag/SHA, not @main"

    def test_defusedxml_is_a_dependency(self):
        text = (ROOT / "pyproject.toml").read_text()
        assert "defusedxml" in text

    def test_no_proprietary_license_classifier(self):
        text = (ROOT / "pyproject.toml").read_text()
        assert '"License :: Other/Proprietary License"' not in text

    def test_matlab_mapping_not_referenced_in_packaging(self):
        # The file does not exist; sdist/MANIFEST must not reference it.
        assert "MATLAB_MAPPING.md" not in (ROOT / "MANIFEST.in").read_text()
        assert "MATLAB_MAPPING.md" not in (ROOT / "pyproject.toml").read_text()

    def test_artifact_tarball_removed_and_ignored(self):
        assert not (ROOT / "pythonArtifacts.tar.gz").exists()
        assert "*.tar.gz" in (ROOT / ".gitignore").read_text()

    def test_installer_pins_dependencies(self):
        text = (ROOT / "ndi_install.py").read_text()
        # No floating-branch clone of the VH-Lab toolbox.
        assert '"branch": "main"' not in text
        assert '"ref"' in text


# ===========================================================================
# §3.5-2 (twin)  fitcurve fit_equation: restricted evaluator, no eval() RCE
# ===========================================================================


class TestFitcurveSafeEval:
    def test_helper_evaluates_real_equation(self):
        import numpy as np

        from ndi.fun.data import _safe_arithmetic_eval

        ns = {"a": 2.0, "tau": 0.5, "x": np.array([0.0, 1.0]), "exp": np.exp}
        out = _safe_arithmetic_eval("a*exp(-x/tau)", ns)
        assert np.allclose(out, 2.0 * np.exp(-np.array([0.0, 1.0]) / 0.5))

    def test_helper_handles_power_and_unary(self):
        from ndi.fun.data import _safe_arithmetic_eval

        assert _safe_arithmetic_eval("-a + b**2", {"a": 3, "b": 4}) == 13

    @pytest.mark.parametrize(
        "payload",
        [
            "abs.__class__",  # attribute access
            "().__class__.__mro__[1].__subclasses__()",  # the classic escape
            "__import__('os').system('echo pwned')",  # unknown name
            "[c for c in range(3)]",  # comprehension
            "(lambda: 1)()",  # lambda
        ],
    )
    def test_helper_rejects_code_execution(self, payload):
        from ndi.fun.data import _safe_arithmetic_eval

        with pytest.raises((ValueError, SyntaxError)):
            _safe_arithmetic_eval(payload, {"abs": abs})

    def test_evaluate_fitcurve_rejects_malicious_equation(self):
        import numpy as np

        from ndi.fun.data import evaluate_fitcurve

        doc = {
            "fitcurve": {
                "fit_equation": "x.__class__.__mro__[1].__subclasses__()",
                "fit_parameter_names": [],
                "fit_parameter_values": [],
                "fit_variable_names": ["x", "y"],
            }
        }
        with pytest.raises(ValueError):
            evaluate_fitcurve(doc, np.array([1.0]))


# ===========================================================================
# §3.5-7 (twin)  downloadFilesForDocument path-traversal sanitization
# ===========================================================================


class TestDownloadFilesForDocumentTraversal:
    def test_file_uid_traversal_stays_within_target(self, tmp_path, monkeypatch):
        from ndi.cloud import download as dl

        target = tmp_path / "target"
        target.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        class FakeResp:
            status_code = 200

            def iter_content(self, chunk_size=8192):
                yield b"payload"

        monkeypatch.setattr(
            "ndi.cloud.api.files.getFileDetails",
            lambda *a, **k: {"downloadUrl": "http://example/file"},
        )
        monkeypatch.setattr("requests.get", lambda *a, **k: FakeResp())

        document = {"file_uid": "../outside/PWNED.bin"}
        out = dl.downloadFilesForDocument("ds-id", document, target)

        # Neutralized to a basename inside target; nothing escaped.
        assert (target / "PWNED.bin").exists()
        assert not (outside / "PWNED.bin").exists()
        assert all(str(p).startswith(str(target.resolve())) for p in out)
