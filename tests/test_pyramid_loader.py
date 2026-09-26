"""The pyramid loader is the one class a caller talks to.

These tests pin the loader's plumbing -- lazy build, delegation to the
existing multiscale helpers, refresh-hint slot handling, stats
snapshot, close idempotency -- without a working NDI session and
without importing napari. The real end-to-end behaviour (fetching
across the network, upsample fallback on the wire, RefreshHint into
qtpy) is left to the cloud-integration test (a follow-up commit).

Together the unit tests here and the tests in
``test_pyramid_upsample_fallback.py`` cover everything the loader
does before it hands over to napari or matplotlib, and the seams to
those callers are exactly the two public hooks
``registerRefreshHint`` and ``stats``.
"""

from __future__ import annotations

import unittest
from unittest import mock

from ndi.pyramid import loader as loader_mod
from ndi.pyramid.loader import ImagePyramidLoader


class _FakeSession:
    """Enough of a session to construct a loader.

    The loader never touches the session until :meth:`build` runs,
    so an empty object is enough for lazy-construction tests. Tests
    that do build monkey-patch ``layerSpec`` and ``levelDocs`` on
    the multiscale module, and never actually reach the session's
    database.
    """


class _FakeDoc:
    def __init__(self, id="pyramid_id"):
        self.id = id
        self.document_properties: dict = {}


class _FakeFetcher:
    """Records lifecycle calls for tests that care about them."""

    def __init__(self):
        self.warmed = False
        self.closed = False
        self._fallback_context = None
        self._stats = "cache=42, cloud=10"

    def warm(self) -> None:
        self.warmed = True

    def close(self) -> None:
        self.closed = True

    def stats_summary(self) -> str:
        return self._stats


class TestLazyConstruction(unittest.TestCase):
    def test_it_touches_nothing_before_build(self):
        # The loader must be cheap to construct -- callers pass it
        # around and only pay for the dask graphs on first read.
        with mock.patch.object(loader_mod, "__name__", "loader") as _:  # noqa: F841
            with (
                mock.patch("ndi.pyramid.multiscale.layerSpec") as fake_layer_spec,
                mock.patch("ndi.pyramid.multiscale.levelDocs") as fake_level_docs,
            ):
                ImagePyramidLoader(_FakeSession(), _FakeDoc())
                fake_layer_spec.assert_not_called()
                fake_level_docs.assert_not_called()

    def test_construction_captures_all_the_args(self):
        loader = ImagePyramidLoader(
            _FakeSession(),
            _FakeDoc("doc1"),
            reduction="mean",
            workers=8,
            name="my pyramid",
            channel=2,
        )
        self.assertEqual(loader.reduction, "mean")
        self.assertEqual(loader.workers, 8)
        self.assertEqual(loader.name, "my pyramid")
        self.assertEqual(loader.channel, 2)
        self.assertEqual(loader.pyramid_doc.id, "doc1")


class TestBuild(unittest.TestCase):
    def test_it_delegates_to_layerSpec(self):
        specs = [{"name": "one"}, {"name": "two"}]
        fetcher = _FakeFetcher()
        with mock.patch(
            "ndi.pyramid.multiscale.layerSpec", return_value=(specs, fetcher)
        ) as fake_layer_spec:
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc(), reduction="mean", workers=8)
            loader.build()
            fake_layer_spec.assert_called_once()
            _, kwargs = fake_layer_spec.call_args
            self.assertEqual(kwargs["reduction"], "mean")
            self.assertEqual(kwargs["workers"], 8)
            self.assertEqual(loader.specs, specs)
            self.assertIs(loader.fetcher, fetcher)

    def test_build_is_idempotent(self):
        # First access to specs builds; second access reuses. Two
        # openings of the same viewer would otherwise pay the level
        # enumeration cost twice.
        fetcher = _FakeFetcher()
        with mock.patch(
            "ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)
        ) as fake_layer_spec:
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            _ = loader.specs
            _ = loader.specs
            _ = loader.fetcher
            self.assertEqual(fake_layer_spec.call_count, 1)


class TestDocs(unittest.TestCase):
    def test_it_delegates_to_levelDocs_and_caches(self):
        docs_ret = [object(), object(), object()]
        with mock.patch(
            "ndi.pyramid.multiscale.levelDocs", return_value=docs_ret
        ) as fake_level_docs:
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc(), reduction="max")
            _ = loader.docs
            _ = loader.docs
            fake_level_docs.assert_called_once()
            _, kwargs = fake_level_docs.call_args
            self.assertEqual(kwargs["reduction"], "max")
            self.assertEqual(loader.numLevels, 3)


class TestStartPrefetch(unittest.TestCase):
    def test_default_targets_the_coarsest(self):
        # docs and fetcher land through the mocks; the loader must
        # ask for the coarsest and pass the same session +
        # pyramid_doc + fetcher through.
        docs_ret = [object(), object(), object()]
        fetcher = _FakeFetcher()
        thread_sentinel = object()
        with (
            mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)),
            mock.patch("ndi.pyramid.multiscale.levelDocs", return_value=docs_ret),
            mock.patch(
                "ndi.pyramid.multiscale.prefetchCoarsestLevel", return_value=thread_sentinel
            ) as fake_prefetch,
        ):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc("p1"), reduction="mean")
            got = loader.startPrefetch()
            fake_prefetch.assert_called_once()
            args, kwargs = fake_prefetch.call_args
            self.assertIs(args[2], fetcher)
            self.assertEqual(kwargs["reduction"], "mean")
            self.assertIs(got, thread_sentinel)

    def test_prefetch_for_a_non_coarsest_level_is_noop_in_v1(self):
        # The knob accepts a level index for a future arbitrary-
        # level prefetch, but only the coarsest is supported now.
        # Anything else returns None so callers get a signal rather
        # than a silent wrong-level fetch.
        fetcher = _FakeFetcher()
        with (
            mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)),
            mock.patch("ndi.pyramid.multiscale.levelDocs", return_value=[object(), object()]),
            mock.patch("ndi.pyramid.multiscale.prefetchCoarsestLevel") as fake_prefetch,
        ):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            self.assertIsNone(loader.startPrefetch(level=0))
            fake_prefetch.assert_not_called()


class TestRegisterRefreshHint(unittest.TestCase):
    def test_a_hint_lands_in_the_fallback_context_slot(self):
        # The fallback reader reads slot[0] every delayed task and
        # fires the hint on async-fetch completion. Installing the
        # hint after build must reach the same slot.
        fetcher = _FakeFetcher()
        fetcher._fallback_context = {"refresh_hint_slot": [None]}
        with mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            hint = object()
            loader.registerRefreshHint(hint)
            self.assertIs(fetcher._fallback_context["refresh_hint_slot"][0], hint)

    def test_registering_without_a_fallback_context_is_a_noop(self):
        # Single-level pyramids and env-off sessions have no
        # fallback context. Installing a hint must not raise.
        fetcher = _FakeFetcher()
        fetcher._fallback_context = None
        with mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            loader.registerRefreshHint(object())  # must not raise


class TestStats(unittest.TestCase):
    def test_before_build_the_snapshot_is_empty(self):
        loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
        self.assertEqual(loader.stats(), {})

    def test_after_build_the_fetcher_line_is_present(self):
        fetcher = _FakeFetcher()
        with mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            loader.build()
            snap = loader.stats()
            self.assertEqual(snap.get("fetcher"), "cache=42, cloud=10")

    def test_fallback_line_only_appears_when_the_env_is_on(self):
        import os

        fetcher = _FakeFetcher()
        with mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            loader.build()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NDI_LIGHTSHEET_UPSAMPLE_FALLBACK", None)
                self.assertNotIn("fallback", loader.stats())
            with mock.patch.dict(os.environ, {"NDI_LIGHTSHEET_UPSAMPLE_FALLBACK": "1"}):
                self.assertIn("fallback", loader.stats())


class TestClose(unittest.TestCase):
    def test_close_before_build_is_safe(self):
        loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
        loader.close()  # must not raise

    def test_close_shuts_the_fetcher_down(self):
        fetcher = _FakeFetcher()
        with mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            loader.build()
            loader.close()
            self.assertTrue(fetcher.closed)

    def test_a_fetcher_that_throws_on_close_does_not_escape(self):
        # A crash while shutting down the pool should not take the
        # program with it -- the viewer session is already ending.
        class Hostile(_FakeFetcher):
            def close(self):
                raise RuntimeError("gone")

        fetcher = Hostile()
        with mock.patch("ndi.pyramid.multiscale.layerSpec", return_value=([], fetcher)):
            loader = ImagePyramidLoader(_FakeSession(), _FakeDoc())
            loader.build()
            loader.close()  # must not raise


if __name__ == "__main__":
    unittest.main()
