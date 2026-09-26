# ndi.gui.app.lightsheetZarr

Sibling of `ndi.gui.app.genepyramid` for lightsheet OME-Zarr pyramids.
Provides the `napariViewLightsheet` console script that the MATLAB
`ndi.gui.app.LightsheetZarrManager` shells out to (via
`/usr/local/bin/napariViewLightsheet`) and the pure-Python
multiscale/viewer surface underneath.

## Layout

```
src/ndi/gui/app/lightsheetZarr/
    __init__.py                       # lazy re-exports (levelArrays / layerSpec / worldTransform)
    cli.py                            # napariViewLightsheet: --list / --report / open in napari
    viewer.py                         # require_napari() + openPyramid()
    multiscale.py                     # levelDocs / levelTable / worldTransform / levelArrays / layerSpec
    ndi_matlab_python_bridge.yaml     # bridge entry per public function
    README-lightsheet-zarr.md         # this file
```

## What is scaffolded, and what is next

Complete and working:

- CLI parsing + `--list` (enumerate pyramids in a session) + `--report`
  (per-level table).
- `_pick_pyramid` / `_resolve_reduction` (mean <-> max sibling swap).
- `require_napari` with the `pip install 'ndi[napari]'` hint.
- `openPyramid` builds a napari layer via `layerSpec`.
- `levelDocs` / `levelTable` / `worldTransform` fully implemented on
  top of the standard NDI query API.

Scaffold, with the specific hook named at the raise site:

- `multiscale.levelArrays` — enumerates levels and reads metadata; the
  per-chunk reader + `dask.delayed` block assembly is the follow-up
  hook. Uses `_fetch_chunk`, which currently raises `NotImplementedError`.
- `_fetch_chunk` — the actual
  `session.database_openbinarydoc(level_doc, 'chunk.bin_#')` call.
- `_attach_controls` — no-op in this PR. Follow-up adds `magicgui`
  panels for reduction / channel / level.

## pyproject.toml additions

Add to `[project.scripts]`:

```toml
napariViewLightsheet = "ndi.gui.app.lightsheetZarr.cli:main"
```

Existing `[project.optional-dependencies].napari` (napari + dask) already
covers this app. `require_napari()` in `viewer.py` names the extra when
it is missing.

## Install the shell wrapper

Same pattern as `napariViewGEF`: install `scripts/napariViewLightsheet`
at `/usr/local/bin/napariViewLightsheet`. The wrapper scrubs MATLAB's
`LD_LIBRARY_PATH` / `DYLD_*` before exec-ing the console script, so a
Python started from MATLAB does not pick up MATLAB's copies of libtiff /
libcurl / etc.

## Design notes

**One doc per level.** NDI documents are immutable, so each resolution
level of each reduction is its own `lightsheetZarrLevel` document. A
parent `lightsheetZarrPyramid` groups them via `depends_on`.

**Mean and max are separate parents.** A volume with both reductions
becomes two `lightsheetZarrPyramid` documents that share the same
subject + source file. The `--reduction` flag swaps between them by
querying for the sibling.

**Chunk bytes live in a `chunk.bin_#` file series** on the level
document; the reader pulls them through the NDI cloud cache, so
lightsheet reads stay on the HIPAA-compliant NDI cloud API and do not
open a separate zarr store or external URL.

## Related

- `ndi.gui.app.genepyramid` — the sibling GEF pyramid viewer this
  package mirrors. Read `cli.py` / `multiscale.py` / `viewer.py` there
  to understand the deferred-import discipline.
- MATLAB companion: `+ndi/+fun/+doc/+lightsheet/` and
  `+ndi/+gui/+app/LightsheetZarrManager.m` in NDI-matlab on branch
  `claude/lightsheet-zarr-ndi-viewer-djp5vk`.
- NDR helpers: `ndr.format.omezarr.probe` and `ndr.format.omezarr.reduce`
  on the same branch name in NDR-matlab / NDR-python.
