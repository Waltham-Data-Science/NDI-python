# Installing NDI

This folder installs NDI-python on **macOS** (Apple Silicon and Intel),
**Windows** and **Linux**, for people who want to *use* NDI: the `ndi`
command and the two napari viewers, `napariViewGEF` and
`napariViewLightsheet`, which NDI-matlab also opens. You do not need Python,
git, a compiler or administrator rights. (Developers working on NDI itself
should use `pip install -e .` in a clone instead.)

## Install

**macOS** — download [`Install NDI.command`](Install%20NDI.command) and
double-click it. The first time, macOS may say it cannot be opened because it
was downloaded from the internet: **right-click** (or Control-click) the file,
choose **Open**, then **Open** again. A Terminal window shows the progress and
waits for you to press Return at the end.

**Windows** — download [`Install NDI.cmd`](Install%20NDI.cmd) and
double-click it. If SmartScreen warns about it, choose **More info**, then
**Run anyway**. A window shows the progress and waits for a key press at the end.

**Linux, or from any terminal** — one line:

```sh
curl -LsSf https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.sh | sh
```

On Windows, the PowerShell equivalent:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -c "irm https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.ps1 | iex"
```

It takes a few minutes and about 3 GB of disk. When it finishes, **open a new
terminal window** and try `ndi check`.

## What it puts where

Everything goes in a hidden `.ndi` folder in your home folder
(`~/.ndi` on macOS and Linux, `%USERPROFILE%\.ndi` on Windows), which
NDI-matlab uses too. The installer owns only three folders and one file there:

| folder or file | what is in it |
|---|---|
| `.ndi/bin` | the `ndi`, `napariViewGEF` and `napariViewLightsheet` commands, and [uv](https://docs.astral.sh/uv/), the tool that installs them |
| `.ndi/python` | a private copy of Python 3.12 |
| `.ndi/venvs` | NDI and the packages it needs |
| `.ndi/install.json` | which commit of NDI was installed, and when, so `ndi update` (and NDI-matlab) can tell whether there is a newer one |

It never touches anything else in `.ndi`, such as your
`NDI_Preferences.json`. Outside `.ndi` it only adds `.ndi/bin` to the end of
your `PATH` (in `~/.zshrc` / `~/.zprofile` or `~/.bashrc` / `~/.profile`, inside
a block marked `NDI`; on Windows, your user `Path` setting). uv also keeps a
download cache in its usual place (`~/.cache/uv`, or `%LOCALAPPDATA%\uv\cache`
on Windows), which makes updates faster; `~/.ndi/bin/uv cache clean` empties it.

## Update

`ndi update --check` says whether a newer NDI is available, and `ndi update`
installs it (after asking). The navigator's **Update** button does the same,
and NDI-matlab's `ndi.update.install()` / Update button update this
installation too. Or run the installer again, the same way: it replaces NDI
with the latest version.

## Uninstall

```sh
curl -LsSf https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.sh | sh -s -- --uninstall
```

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.ps1))) -Uninstall"
```

(or run `install-ndi.sh --uninstall` / `install-ndi.ps1 -Uninstall` from this
folder). This removes `.ndi/bin`, `.ndi/python`, `.ndi/venvs`,
`.ndi/install.json` and the `PATH` lines, and leaves the rest of `.ndi` (your
settings) alone.

## Options

| `install-ndi.sh` | `install-ndi.ps1` | |
|---|---|---|
| `--yes` | `-Yes` | do not ask before installing |
| `--no-path` | `-NoPath` | do not change `PATH` |
| `--uninstall` | `-Uninstall` | remove what the installer installed |

## For MATLAB and for maintainers

NDI-matlab downloads and runs these same scripts with `--yes` / `-Yes`. The
script exits with status 0 only if the final check passed (the three
commands exist, both viewers answer `--help`, and `ndi check` passes); on
success the last line it prints is `NDI installed: <full path of .ndi/bin>`.
MATLAB starts the viewers with `NDI_FROM_MATLAB=1`, and they then drop
MATLAB's library paths before loading anything (see `src/_ndi_launch.py`).

The uv version is pinned at the top of each script (`UV_VERSION` /
`$UvVersion`). Pyraview comes only from its release wheels, through
[`pyraview-wheels.html`](pyraview-wheels.html) and
[`pyraview-constraints.txt`](pyraview-constraints.txt) here, so nothing is
compiled. `NDI_INSTALL_SOURCE` (a local checkout or a URL) installs something
other than the `main` branch; CI uses it, together with
`NDI_PYRAVIEW_FIND_LINKS`, `NDI_PYRAVIEW_CONSTRAINTS` and `NDI_INSTALL_PYTHON`,
to install the code under test (`.github/workflows/installer.yml`).
