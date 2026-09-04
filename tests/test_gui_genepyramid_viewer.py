"""Tests for the napari binding.

napari is an extra, so these assert the two things that hold whether or
not it is installed: that a missing napari says what to install rather
than raising ImportError from deep inside, and that importing the package
does not pull napari in.
"""

from __future__ import annotations

import builtins
import importlib

import pytest


def test_importing_the_package_does_not_need_napari():
    """ndi.gui.app must stay importable on a headless box."""
    import ndi.gui.app.genepyramid as gp

    assert callable(gp.layerSpec)


def test_missing_napari_names_the_extra(monkeypatch):
    from ndi.gui.app.genepyramid import viewer

    real_import = builtins.__import__

    def no_napari(name, *a, **k):
        if name == "napari":
            raise ImportError("No module named 'napari'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_napari)
    with pytest.raises(ImportError, match=r"pip install 'ndi\[napari\]'"):
        viewer.require_napari()


@pytest.mark.skipif(importlib.util.find_spec("napari") is None, reason="napari not installed")
def test_require_napari_returns_the_module():
    from ndi.gui.app.genepyramid import viewer

    assert viewer.require_napari().__name__ == "napari"
