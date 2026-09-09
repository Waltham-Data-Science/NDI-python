"""A secret's field name has to be the one NDI-matlab writes, character for character.

NDI-matlab runs every secret key through matlab.lang.makeValidName before
using it as a struct field -- it has to, because reading the secrets file
back through jsondecode requires each JSON key to be a valid MATLAB
identifier. Python has no such constraint, and had substituted underscores
for spaces, which is the reasonable guess and the wrong one: makeValidName
DELETES whitespace and capitalises the following letter.

So MATLAB wrote NDICloud<uid> and Python looked for NDI_Cloud_<uid>. Both
files parsed, both profiles listed, and the password was reported missing:

    KeyError: 'No secret stored for "NDI Cloud 41269713c8f30937_...".'

The two implementations could not read each other's secrets in either
direction, which is the whole point of the shared ~/.ndi store.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ndi.cloud import profile
from ndi.cloud.profile import _legacy_safe_field, _make_valid_name, _safe_field


class TestMakeValidNamePort(unittest.TestCase):
    """Cases checked against MATLAB's documented makeValidName behaviour."""

    def test_the_key_shape_ndi_actually_uses(self):
        # Verbatim from a ~/.ndi/NDI_Cloud_Secrets.json written by NDI-matlab.
        self.assertEqual(
            _safe_field("NDI Cloud 41269713c8f30937_40d3dfe383e33674"),
            "NDICloud41269713c8f30937_40d3dfe383e33674",
        )

    def test_whitespace_is_deleted_not_replaced(self):
        self.assertEqual(_make_valid_name("a b"), "aB")

    def test_the_character_after_whitespace_is_capitalised(self):
        self.assertEqual(_make_valid_name("hello world"), "helloWorld")

    def test_a_digit_after_whitespace_is_not_capitalisable_and_just_joins(self):
        self.assertEqual(_make_valid_name("NDI Cloud 4abc"), "NDICloud4abc")

    def test_a_uid_beginning_with_a_letter_is_capitalised_by_the_same_rule(self):
        # Not a wart -- MATLAB does this too, and half of NDI-python's uuid4
        # UIDs begin with a-f, so getting it "tidier" than MATLAB would break
        # exactly the interop this exists for.
        self.assertEqual(
            _safe_field("NDI Cloud f68d6370c3f34c9cb4935916fb42ae19"),
            "NDICloudF68d6370c3f34c9cb4935916fb42ae19",
        )

    def test_other_invalid_characters_each_become_one_underscore(self):
        self.assertEqual(_make_valid_name("a:b-c"), "a_b_c")

    def test_a_name_that_would_start_with_a_digit_gets_a_leading_x(self):
        self.assertEqual(_make_valid_name("9lives"), "x9lives")

    def test_a_name_that_would_start_with_an_underscore_gets_one_too(self):
        self.assertEqual(_make_valid_name("_leading"), "x_leading")

    def test_a_keyword_is_not_left_as_a_keyword(self):
        self.assertEqual(_make_valid_name("end"), "end_")

    def test_a_word_merely_containing_a_keyword_is_untouched(self):
        self.assertEqual(_make_valid_name("endpoint"), "endpoint")

    def test_an_empty_key_still_yields_a_usable_name(self):
        self.assertEqual(_make_valid_name(""), "x")

    def test_the_name_is_capped_at_namelengthmax(self):
        self.assertEqual(len(_make_valid_name("a" * 200)), 63)

    def test_non_ascii_letters_are_replaced_rather_than_kept(self):
        # MATLAB identifiers are ASCII; Python's str.isalnum() is not, so a
        # naive port would keep these and diverge.
        self.assertEqual(_make_valid_name("café"), "caf_")

    def test_the_legacy_name_is_the_one_we_used_to_write(self):
        self.assertEqual(
            _legacy_safe_field("NDI Cloud abc"),
            "NDI_Cloud_abc",
        )
        self.assertNotEqual(_legacy_safe_field("NDI Cloud abc"), _safe_field("NDI Cloud abc"))


def _matlab_field(uid: str) -> str:
    """The field name MATLAB writes for "NDI Cloud <uid>", spelled out here.

    Deliberately NOT _safe_field: an assertion that calls the function under
    test to compute what it expects proves nothing.
    """
    if uid[:1].isalpha():
        uid = uid[0].upper() + uid[1:]
    return "NDICloud" + uid


class _AesStoreCase(unittest.TestCase):
    """A real AES-backed store in a scratch prefdir."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        patcher = mock.patch.dict(os.environ, {"NDI_PREFDIR": self.dir})
        patcher.start()
        self.addCleanup(patcher.stop)
        profile.reset()
        self.addCleanup(profile.reset)
        try:
            profile.use_backend("aes")
        except Exception as exc:  # pragma: no cover - cryptography is a dependency
            self.skipTest(f"aes backend unavailable: {exc}")

    @property
    def secrets(self) -> Path:
        return Path(self.dir) / "NDI_Cloud_Secrets.json"

    def read_secrets(self) -> dict:
        return json.loads(self.secrets.read_text())


class TestSecretsAreWrittenWhereMatlabLooks(_AesStoreCase):
    def test_a_saved_password_lands_under_the_matlab_field_name(self):
        uid = profile.add("work", "a@example.com", "hunter2")
        stored = self.read_secrets()
        self.assertIn(_matlab_field(uid), stored)
        self.assertNotIn(_legacy_safe_field("NDI Cloud " + uid), stored)

    def test_a_saved_password_reads_back(self):
        uid = profile.add("work", "a@example.com", "hunter2")
        self.assertEqual(profile.get_password(uid), "hunter2")

    def test_a_password_written_by_matlab_is_found(self):
        # The file MATLAB leaves, built from the outside: a MATLAB-shaped UID
        # (<16hex>_<16hex>, unlike Python's uuid4), a MATLAB-shaped field
        # name, and a ciphertext under the shared key derivation.
        from ndi.cloud.profile import _aes_encrypt

        uid = "41269713c8f30937_40d3dfe383e33674"
        profiles = {
            "Profiles": {
                "UID": uid,
                "Nickname": "work",
                "Email": "a@example.com",
                "Stage": "prod",
                "PasswordSecret": "NDI Cloud " + uid,
            },
            "DefaultUID": uid,
        }
        (Path(self.dir) / "NDI_Cloud_Profiles.json").write_text(json.dumps(profiles))
        self.secrets.write_text(
            json.dumps({"NDICloud41269713c8f30937_40d3dfe383e33674": _aes_encrypt("frommatlab")})
        )
        profile.reload()
        self.assertEqual(profile.get_password(uid), "frommatlab")


class TestOlderPythonSecretsStillOpen(_AesStoreCase):
    def _demote_to_legacy(self, uid: str) -> None:
        stored = self.read_secrets()
        stored[_legacy_safe_field("NDI Cloud " + uid)] = stored.pop(_matlab_field(uid))
        self.secrets.write_text(json.dumps(stored))

    def test_a_password_saved_by_an_older_ndi_python_is_still_readable(self):
        uid = profile.add("work", "a@example.com", "olddog")
        self._demote_to_legacy(uid)
        self.assertEqual(profile.get_password(uid), "olddog")

    def test_rewriting_it_moves_it_to_the_matlab_name_and_leaves_no_copy(self):
        uid = profile.add("work", "a@example.com", "olddog")
        self._demote_to_legacy(uid)
        profile.set_password(uid, "newtrick")
        stored = self.read_secrets()
        self.assertIn(_matlab_field(uid), stored)
        self.assertNotIn(_legacy_safe_field("NDI Cloud " + uid), stored)
        self.assertEqual(profile.get_password(uid), "newtrick")

    def test_removing_a_profile_takes_the_legacy_copy_with_it(self):
        uid = profile.add("work", "a@example.com", "olddog")
        self._demote_to_legacy(uid)
        profile.remove(uid)
        stored = self.read_secrets()
        self.assertNotIn(_matlab_field(uid), stored)
        self.assertNotIn(_legacy_safe_field("NDI Cloud " + uid), stored)

    def test_a_genuinely_absent_secret_still_reports_absence(self):
        uid = profile.add("work", "a@example.com", "olddog")
        stored = self.read_secrets()
        stored.clear()
        self.secrets.write_text(json.dumps(stored))
        with self.assertRaises(KeyError):
            profile.get_password(uid)


if __name__ == "__main__":
    unittest.main()
