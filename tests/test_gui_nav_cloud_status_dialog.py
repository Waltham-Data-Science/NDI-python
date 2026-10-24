"""ndi.gui.nav.cloud_status_dialog against MATLAB's cloudStatusDialog.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudStatusDialog.m`` (tests:
``tests/+ndi/+unittest/+gui/+nav/cloudStatusDialog_test.m``)

What the window says is decided by static methods and tested everywhere;
the window itself is built under the offscreen platform and skips without
PySide6.
"""

from __future__ import annotations

import os

import pytest

from ndi.gui.nav import datasets_cloud as dc
from ndi.gui.nav.cloud_status_dialog import CloudStatusDialog

D = CloudStatusDialog


class TestWhatItSays:
    def test_copy_enabled_in_cloud(self):
        assert D.copy_enable(True, "abc123") is True
        assert D.id_text(True, "abc123") == "abc123"

    def test_copy_disabled_when_not_in_cloud(self):
        assert D.copy_enable(False, "") is False
        assert "not in NDI Cloud" in D.id_text(False, "")

    def test_copy_disabled_when_the_id_is_missing(self):
        # a linked dataset with no id has nothing to copy
        assert D.copy_enable(True, "") is False

    def test_status_message(self):
        assert "linked to NDI Cloud" in D.status_message(True)
        assert "not in NDI Cloud" in D.status_message(False)


class FakeDataset:
    def __init__(self, in_cloud, cloud_id=""):
        self._answer = (in_cloud, cloud_id)

    def is_in_cloud(self):
        return self._answer


class TestCheckCloudStatusCarriesTheId:
    def test_in_cloud(self):
        r = dc.check_cloud_status(FakeDataset(True, "668b0539f13096e04f1feccd"))
        assert r.state == "incloud"
        assert r.cloud_dataset_id == "668b0539f13096e04f1feccd"

    def test_not_in_cloud(self):
        r = dc.check_cloud_status(FakeDataset(False))
        assert r.state == "notincloud"
        assert r.cloud_dataset_id == ""


def _qt_or_skip():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        return get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")


class TestWindow:
    def test_in_cloud(self):
        _qt_or_skip()
        d = CloudStatusDialog(True, "abc123")
        assert d.id_field.text() == "abc123"
        assert d.id_field.isReadOnly()
        assert d.copy_button.isEnabled()

    def test_not_in_cloud(self):
        _qt_or_skip()
        d = CloudStatusDialog(False, "")
        assert not d.copy_button.isEnabled()
        assert "not in NDI Cloud" in d.id_field.text()

    def test_copy_puts_the_id_on_the_clipboard(self):
        app = _qt_or_skip()
        d = CloudStatusDialog(True, "abc123")
        assert d.copy_id() is True
        assert app.clipboard().text() == "abc123"
        assert d.copy_button.text() == "Copied"

    def test_copy_does_nothing_without_an_id(self):
        _qt_or_skip()
        assert CloudStatusDialog(False, "").copy_id() is False


if __name__ == "__main__":
    pytest.main([__file__])
