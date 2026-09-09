"""Genes opened as their own layers, and the sign-in behind a button.

TWO DIFFERENT REQUESTS live next to each other and are easy to confuse.
``--genes`` FILTERS the base image down to a subset, leaving one
picture. ``--gene-layers`` adds a layer per gene ON TOP of the base, so
"All genes" stays and the named genes are comparable against it. Most of
these tests exist to keep that distinction from eroding.
"""

import os

import pytest

from ndi.gui.app.genepyramid import controls
from ndi.gui.app.genepyramid.controls import parseGeneLayers

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# What NDI-matlab's GEFManager.ferretDemoGenes emits, spelled out here so
# a change on either side of the bridge shows up as a failing test rather
# than as a demo that opens the wrong colours.
_FERRET_DEMO = "HPCAL1:green,RORB:blue,FEZF2:bop orange,TSHZ2:yellow,NXPH4:red,SST:cyan"


class TestParsingTheSpec:
    def test_it_pairs_each_gene_with_its_colour(self):
        assert parseGeneLayers("A:red,B:cyan") == [("A", "red"), ("B", "cyan")]

    def test_a_gene_may_go_without_a_colour(self):
        """None means "take the next one from the cycle", so a caller can
        name the colours that matter and leave the rest."""
        assert parseGeneLayers("A,B:cyan") == [("A", None), ("B", "cyan")]

    def test_a_colour_may_contain_a_space(self):
        """napari ships 'bop orange', 'bop blue' and 'bop purple'. Only
        the ends of each field are trimmed, never the middle."""
        assert parseGeneLayers("FEZF2:bop orange") == [("FEZF2", "bop orange")]

    def test_spaces_around_the_entries_are_ignored(self):
        assert parseGeneLayers(" A : red , B ") == [("A", "red"), ("B", None)]

    def test_nothing_asked_for_is_an_empty_list(self):
        """A fact, not a missing answer."""
        for spec in ("", "   ", ",,", None):
            assert parseGeneLayers(spec) == []

    def test_a_gene_named_twice_is_kept_once(self):
        """Ticking the same box twice adds nothing the second time, and
        the layer names would collide."""
        assert parseGeneLayers("A:red,A:cyan,B") == [("A", "red"), ("B", None)]

    def test_an_empty_colour_reads_as_no_colour(self):
        assert parseGeneLayers("A:") == [("A", None)]

    def test_the_ferret_demo_spec_round_trips(self):
        """The exact string NDI-matlab builds for the demo."""
        assert parseGeneLayers(_FERRET_DEMO) == [
            ("HPCAL1", "green"),
            ("RORB", "blue"),
            ("FEZF2", "bop orange"),
            ("TSHZ2", "yellow"),
            ("NXPH4", "red"),
            ("SST", "cyan"),
        ]

    def test_the_demo_colours_are_all_distinct(self):
        colours = [c for _s, c in parseGeneLayers(_FERRET_DEMO)]
        assert len(set(colours)) == len(colours)

    def test_the_order_is_kept(self):
        """It is the order the layers are added, and so the order the
        colour cycle advances for any gene that named no colour."""
        assert [s for s, _c in parseGeneLayers("D,C,B,A")] == ["D", "C", "B", "A"]


class TestTheCliOption:
    def test_it_is_a_separate_option_from_genes(self):
        """The two answer different questions and must not be conflated:
        one filters the base layer, the other adds layers beside it."""
        from ndi.gui.app.genepyramid.cli import build_parser

        args = build_parser().parse_args(["/s", "--gene-layers", _FERRET_DEMO])
        assert args.gene_layers == _FERRET_DEMO
        assert args.genes == ""

    def test_it_defaults_to_nothing(self):
        from ndi.gui.app.genepyramid.cli import build_parser

        assert build_parser().parse_args(["/s"]).gene_layers == ""

    def test_the_resolver_hands_the_panel_pairs(self):
        from ndi.gui.app.genepyramid.cli import _resolve_gene_layers

        assert _resolve_gene_layers("A:red") == [("A", "red")]

    def test_the_resolver_gives_none_for_nothing(self):
        """None rather than [] so the panel can tell "not asked" from
        "asked for an empty set"."""
        from ndi.gui.app.genepyramid.cli import _resolve_gene_layers

        assert _resolve_gene_layers("") is None

    def test_both_options_can_be_given_together(self):
        """Filtering the base layer AND opening named genes beside it is
        a coherent request, not a contradiction."""
        from ndi.gui.app.genepyramid.cli import build_parser

        args = build_parser().parse_args(["/s", "--genes", "SST,VIP", "--gene-layers", "SST:cyan"])
        assert args.genes == "SST,VIP"
        assert args.gene_layers == "SST:cyan"


@pytest.fixture(scope="module")
def qt():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield widgets
    del app


class _Window:
    def __init__(self):
        self.docked = []

    def add_dock_widget(self, widget, name=None, area=None):
        self.docked.append((widget, name, area))
        return widget


class _Viewer:
    def __init__(self):
        self.window = _Window()


class TestTheCloudPanelIsOneRow:
    def test_it_is_a_button_and_a_clock(self, qt):
        """Three permanently docked fields say a reader signs in often.
        They do it once a day at most, so the credentials live behind the
        button."""
        viewer = _Viewer()
        panel = controls.addCloudPanel(viewer)
        assert len(panel.findChildren(qt.QPushButton)) == 1
        assert not panel.findChildren(qt.QLineEdit)
        # The viewer owns the dock; a collected one deletes the widget.
        assert viewer.window.docked

    def test_the_clock_still_warns_before_it_bites(self, qt, monkeypatch):
        import base64
        import json
        import time

        def seg(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

        monkeypatch.setenv(
            "NDI_CLOUD_TOKEN",
            f"{seg({'alg': 'none'})}.{seg({'exp': int(time.time()) + 600})}.sig",
        )
        viewer = _Viewer()
        panel = controls.addCloudPanel(viewer)
        said = " ".join(lbl.text() for lbl in panel.findChildren(qt.QLabel))
        assert "renew before it runs out" in said
        assert viewer.window.docked


class _Entry:
    def __init__(self, uid, email, nickname="", stage="prod"):
        self.UID = uid
        self.Email = email
        self.Nickname = nickname
        self.Stage = stage


class TestTheProfileChoices:
    def test_a_nickname_is_shown_with_the_email(self, monkeypatch):
        """Two profiles for the same person on different stages have to
        be tellable apart."""
        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles",
            lambda: [_Entry("u1", "me@example.com", "work")],
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", lambda _u: "pw")
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "aes")
        rows = controls.cloudProfileChoices()
        assert rows == [("work (me@example.com)", "me@example.com", "u1", True, "password saved")]

    def test_a_dev_profile_is_marked(self, monkeypatch):
        """A dev profile signing in against prod is the failure that
        reads as a permissions error, so the stage is on the label."""
        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles",
            lambda: [_Entry("u1", "me@example.com", stage="dev")],
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", lambda _u: "")
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "keyring")
        label, _email, _uid, stored, note = controls.cloudProfileChoices()[0]
        assert "[dev]" in label
        assert not stored
        assert "keyring" in note

    def test_a_backend_that_will_not_open_costs_no_dialog(self, monkeypatch):
        """Typing the credentials by hand is exactly the fallback this
        dialog exists to offer, so it must still appear."""

        def boom():
            raise RuntimeError("no keyring")

        monkeypatch.setattr("ndi.cloud.profile.list_profiles", boom)
        assert controls.cloudProfileChoices() == []

    def test_an_unreadable_secret_only_costs_its_flag(self, monkeypatch):
        def boom(_uid):
            raise RuntimeError("locked")

        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles", lambda: [_Entry("u1", "me@example.com")]
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", boom)
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "keyring")
        rows = controls.cloudProfileChoices()
        assert len(rows) == 1 and rows[0][3] is False


@pytest.fixture
def dialogOf(qt, monkeypatch):
    held = []

    def build(profiles=()):
        monkeypatch.setattr("ndi.cloud.profile.list_profiles", lambda: list(profiles))
        monkeypatch.setattr(
            "ndi.cloud.profile.get_password", lambda uid: "saved-pw" if uid == "u1" else ""
        )
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "keyring")
        dialog, outcome = controls.buildCloudSignInDialog()
        held.append(dialog)
        return dialog, outcome

    return build


class TestTheSignInDialog:
    def test_it_signs_in_with_what_was_typed(self, qt, dialogOf, monkeypatch):
        seen = {}
        monkeypatch.setattr("ndi.cloud.auth.login", lambda w, s: seen.update(who=w, secret=s))
        dialog, outcome = dialogOf()
        dialog._ndi_fields["email"].setText(" me@example.com ")
        dialog._ndi_fields["password"].setText("pw")
        dialog._ndi_accept()
        assert seen == {"who": "me@example.com", "secret": "pw"}
        assert outcome["ok"]

    def test_the_password_is_never_shown_or_kept(self, qt, dialogOf, monkeypatch):
        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: None)
        dialog, _outcome = dialogOf()
        password = dialog._ndi_fields["password"]
        assert password.echoMode() == qt.QLineEdit.Password
        dialog._ndi_fields["email"].setText("me@example.com")
        password.setText("pw")
        dialog._ndi_accept()
        assert password.text() == ""

    def test_a_failed_attempt_clears_it_too(self, qt, dialogOf, monkeypatch):
        def boom(*_a):
            raise RuntimeError("HTTP 401")

        monkeypatch.setattr("ndi.cloud.auth.login", boom)
        dialog, outcome = dialogOf()
        dialog._ndi_fields["email"].setText("me@example.com")
        dialog._ndi_fields["password"].setText("wrong")
        dialog._ndi_accept()
        assert dialog._ndi_fields["password"].text() == ""
        assert not outcome["ok"]
        assert "401" in dialog._ndi_said.text()

    def test_picking_a_profile_fills_the_email_in(self, qt, dialogOf):
        dialog, _outcome = dialogOf([_Entry("u1", "me@example.com", "work")])
        dialog._ndi_fields["profile"].setCurrentIndex(1)
        assert dialog._ndi_fields["email"].text() == "me@example.com"

    def test_a_saved_password_needs_nothing_typed(self, qt, dialogOf, monkeypatch):
        """Someone whose profile works should not be retyping a password
        to get past an expired token."""
        seen = {}
        monkeypatch.setattr("ndi.cloud.auth.login", lambda w, s: seen.update(who=w, secret=s))
        dialog, outcome = dialogOf([_Entry("u1", "me@example.com", "work")])
        dialog._ndi_fields["profile"].setCurrentIndex(1)
        dialog._ndi_accept()
        assert seen == {"who": "me@example.com", "secret": "saved-pw"}
        assert outcome["ok"]

    def test_a_typed_password_beats_the_saved_one(self, qt, dialogOf, monkeypatch):
        """Which is the whole point of arriving here: what is saved is
        wrong and is being corrected."""
        seen = {}
        monkeypatch.setattr("ndi.cloud.auth.login", lambda w, s: seen.update(who=w, secret=s))
        dialog, _outcome = dialogOf([_Entry("u1", "me@example.com", "work")])
        dialog._ndi_fields["profile"].setCurrentIndex(1)
        dialog._ndi_fields["password"].setText("typed")
        dialog._ndi_accept()
        assert seen["secret"] == "typed"

    def test_the_first_entry_is_type_them_yourself(self, qt, dialogOf):
        """A dialog that opened on a profile would sign in as whoever the
        list happened to start with."""
        dialog, _outcome = dialogOf([_Entry("u1", "me@example.com")])
        chooser = dialog._ndi_fields["profile"]
        assert chooser.currentIndex() == 0
        assert chooser.itemData(0) is None

    def test_an_empty_field_asks_rather_than_calling(self, qt, dialogOf, monkeypatch):
        called = []
        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: called.append(a))
        dialog, _outcome = dialogOf()
        dialog._ndi_accept()
        assert called == []
        assert "needed" in dialog._ndi_said.text()

    def test_the_profile_is_only_written_when_asked(self, qt, dialogOf, monkeypatch):
        saved = []
        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: None)
        monkeypatch.setattr(controls, "saveCloudProfile", lambda *a: saved.append(a))
        dialog, _outcome = dialogOf()
        dialog._ndi_fields["email"].setText("me@example.com")
        dialog._ndi_fields["password"].setText("pw")
        dialog._ndi_accept()
        assert saved == []

        dialog2, _o2 = dialogOf()
        dialog2._ndi_fields["email"].setText("me@example.com")
        dialog2._ndi_fields["password"].setText("pw")
        dialog2._ndi_fields["save"].setChecked(True)
        dialog2._ndi_accept()
        assert saved == [("me@example.com", "pw")]

    def test_a_profile_that_will_not_save_does_not_undo_the_sign_in(
        self, qt, dialogOf, monkeypatch
    ):
        def boom(*_a):
            raise RuntimeError("no keyring")

        monkeypatch.setattr("ndi.cloud.auth.login", lambda *a: None)
        monkeypatch.setattr(controls, "saveCloudProfile", boom)
        dialog, outcome = dialogOf()
        dialog._ndi_fields["email"].setText("me@example.com")
        dialog._ndi_fields["password"].setText("pw")
        dialog._ndi_fields["save"].setChecked(True)
        dialog._ndi_accept()
        assert outcome["ok"]
        assert "Signed in" in outcome["note"] and "keyring" in outcome["note"]


class TestWhyThereIsNoPassword:
    """A backend mismatch used to look exactly like an empty store.

    profile._detect_backend picks keyring whenever keyring merely
    imports, while MATLAB writes its secret to the AES file -- so a
    machine with both looks in the wrong one and finds nothing. Told as
    "no password saved", that sends the reader off to re-save a password
    that is already saved, in a store nothing is reading.
    """

    def test_an_empty_store_names_the_backend(self, monkeypatch):
        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles", lambda: [_Entry("u1", "me@example.com")]
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", lambda _u: "")
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "keyring")
        note = controls.cloudProfileChoices()[0][4]
        assert "keyring" in note and "no password" in note

    def test_an_unreadable_secret_carries_its_reason(self, monkeypatch):
        def boom(_uid):
            raise RuntimeError("cryptography failed to load")

        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles", lambda: [_Entry("u1", "me@example.com")]
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", boom)
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "aes")
        note = controls.cloudProfileChoices()[0][4]
        assert "unreadable" in note
        assert "cryptography failed to load" in note
        assert "aes" in note

    def test_a_saved_password_says_so(self, monkeypatch):
        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles", lambda: [_Entry("u1", "me@example.com")]
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", lambda _u: "pw")
        monkeypatch.setattr("ndi.cloud.profile.backend", lambda: "aes")
        assert controls.cloudProfileChoices()[0][4] == "password saved"

    def test_a_backend_that_will_not_name_itself_is_not_an_error(self, monkeypatch):
        def boom():
            raise RuntimeError("no")

        monkeypatch.setattr(
            "ndi.cloud.profile.list_profiles", lambda: [_Entry("u1", "me@example.com")]
        )
        monkeypatch.setattr("ndi.cloud.profile.get_password", lambda _u: "")
        monkeypatch.setattr("ndi.cloud.profile.backend", boom)
        assert "unknown" in controls.cloudProfileChoices()[0][4]

    def test_the_chooser_shows_the_reason(self, qt, dialogOf):
        dialog, _outcome = dialogOf([_Entry("u2", "them@example.com", "other")])
        chooser = dialog._ndi_fields["profile"]
        assert "no password in the keyring store" in chooser.itemText(1)

    def test_picking_one_puts_the_reason_on_screen(self, qt, dialogOf):
        """ "This profile's password is not readable from here" is a
        different problem from "you never saved one", and only one of
        them is solved by typing it again."""
        dialog, _outcome = dialogOf([_Entry("u2", "them@example.com", "other")])
        dialog._ndi_fields["profile"].setCurrentIndex(1)
        assert "keyring" in dialog._ndi_said.text()

    def test_picking_a_working_one_says_nothing(self, qt, dialogOf):
        dialog, _outcome = dialogOf([_Entry("u1", "me@example.com", "work")])
        dialog._ndi_fields["profile"].setCurrentIndex(1)
        assert dialog._ndi_said.isHidden()


@pytest.fixture
def heldLogo(qt):
    """A logo label that OUTLIVES the assertion.

    cloudLogoLabel returns a parentless QLabel; a temporary is collected
    the moment the expression ends, Qt deletes the C++ object underneath
    it, and reading .pixmap() off the dangling wrapper SEGFAULTS PyQt5
    rather than raising. Holding it is the whole fix.
    """
    label = controls.cloudLogoLabel()
    assert label is not None, "the bundled logo did not load"
    yield label
    del label


class TestTheCloudLogo:
    """The wordmark, bundled and drawn so it is actually visible.

    Copied from NDI-matlab rather than referenced: the viewer runs from
    a Python install that need not have NDI-matlab on disk at all, which
    is the normal case for someone opening a downloaded dataset.
    """

    def test_it_ships_with_the_package(self):
        path = controls.cloudLogoPath()
        assert path is not None, "the bundled logo is missing"
        assert path.is_file()
        assert path.suffix == ".png"

    def test_it_is_the_file_ndi_matlab_serves(self):
        """Byte-for-byte, so the two repos cannot drift into showing
        different marks for the same product."""
        import hashlib

        digest = hashlib.md5(controls.cloudLogoPath().read_bytes()).hexdigest()
        assert digest == "3e8439f1b1b8686b38ad71f314fff157"

    def test_it_is_drawn_on_a_white_card(self, qt, heldLogo):
        """The wordmark is dark navy on transparency and napari's docks
        follow the viewer's theme -- on the dark one the lettering simply
        is not there."""
        assert "#ffffff" in heldLogo.styleSheet()

    def test_it_is_sized_for_a_dock_and_stays_crisp(self, qt, heldLogo):
        """Twice the display width at a device pixel ratio of 2, for the
        retina screen a demo is usually given from."""
        pixmap = heldLogo.pixmap()
        assert pixmap.devicePixelRatio() == 2.0
        assert 120 <= pixmap.width() / pixmap.devicePixelRatio() <= 200

    def test_a_missing_asset_costs_no_panel(self, qt, monkeypatch):
        """A missing file must cost the picture nothing -- the panel
        falls back to its own dock name in text."""
        monkeypatch.setattr(controls, "cloudLogoPath", lambda: None)
        assert controls.cloudLogoLabel() is None
        viewer = _Viewer()
        panel = controls.addCloudPanel(viewer)
        assert panel is not None
        assert viewer.window.docked

    def test_the_panel_shows_it(self, qt):
        viewer = _Viewer()
        panel = controls.addCloudPanel(viewer)
        assert any(
            lbl.pixmap() and not lbl.pixmap().isNull() for lbl in panel.findChildren(qt.QLabel)
        )
        assert viewer.window.docked
