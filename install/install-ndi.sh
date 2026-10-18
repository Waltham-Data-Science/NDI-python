#!/bin/sh
# install-ndi.sh -- install NDI-python for end users on Linux and macOS.
#
#   curl -LsSf https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.sh | sh
#
# or double-click "Install NDI.command" (macOS), or run this file. Run it again
# to update. Developers want `pip install -e .` instead; this is for people
# who just want the `ndi`, `napariViewGEF` and `napariViewLightsheet` commands.
#
# Options:
#   --yes        do not ask before installing (MATLAB always passes this)
#   --no-path    do not add ~/.ndi/bin to the PATH in your shell start-up files
#   --uninstall  remove what this script installed, and nothing else
#
# WHAT IT TOUCHES. Everything lives under ~/.ndi, which NDI-matlab shares,
# and this script owns ONLY three folders and one file there:
#   ~/.ndi/bin           uv itself, plus the ndi / napariViewGEF / napariViewLightsheet commands
#   ~/.ndi/python        the Python interpreter uv downloads (UV_PYTHON_INSTALL_DIR)
#   ~/.ndi/venvs         the environment NDI is installed into (UV_TOOL_DIR)
#   ~/.ndi/install.json  which commit was installed, and when, so that
#                        ndi.update (and NDI-matlab's ndi.update.checkPython)
#                        can tell whether main has moved on since
# Everything else in ~/.ndi (NDI_Preferences.json, tools/, caches, ...) is
# never touched, by install or by --uninstall. Outside ~/.ndi it edits only
# your shell start-up files, inside a marked block (see add_to_path), unless
# --no-path; and uv keeps its download cache in its usual place
# (~/.cache/uv), which it shares with any other uv you use. No sudo, ever.
#
# FOR TESTING (CI uses these; end users never need them):
#   NDI_INSTALL_SOURCE         what to install instead of the main branch:
#                              a local checkout directory, or a URL
#   NDI_PYRAVIEW_FIND_LINKS    URL of the Pyraview wheel index (install/pyraview-wheels.html)
#   NDI_PYRAVIEW_CONSTRAINTS   URL or path of install/pyraview-constraints.txt
#   NDI_INSTALL_PYTHON         the uv Python request instead of 3.12, e.g.
#                              cpython-3.12-macos-x86_64 to get an Intel Mac's
#                              install on Apple Silicon (Rosetta 2)
#
# This is the contract NDI-matlab codes against: the folders above, the flags,
# exit status 0 only when the post-install check passed, and, on success, a
# last line of output reading `NDI installed: <absolute path of ~/.ndi/bin>`.
# Keep install/install-ndi.ps1 in step with it.

set -eu

# ---- pinned versions: the one place to change them ---------------------------
UV_VERSION="0.11.32"      # https://github.com/astral-sh/uv/releases
PYTHON_VERSION="3.12"
# ------------------------------------------------------------------------------

REPO_RAW="https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main"
DEFAULT_SOURCE="https://github.com/Waltham-Data-Science/NDI-python/archive/refs/heads/main.zip"
# gui: the PySide6 apps; napari: the two viewers; pyraview: signal pyramids.
EXTRAS="gui,napari,pyraview"

NDI_HOME="$HOME/.ndi"
BIN="$NDI_HOME/bin"
PYDIR="$NDI_HOME/python"
VENVS="$NDI_HOME/venvs"
RECEIPT="$NDI_HOME/install.json"
COMMITS_API="https://api.github.com/repos/Waltham-Data-Science/NDI-python/commits/main"
ARCHIVE_BASE="https://github.com/Waltham-Data-Science/NDI-python/archive"

PATH_BEGIN="# >>> NDI: added by install-ndi.sh; remove with install-ndi.sh --uninstall >>>"
PATH_END="# <<< NDI <<<"
# Marks a block added after a last line that had no newline, so --uninstall
# can take that newline away again and leave the file exactly as it was.
JOINED=" (newline added)"
# Marks a block in a file this script created, which --uninstall deletes.
CREATED=" (file created)"

say() { printf '%s\n' "$*"; }
fail() {
    # One line, on stderr, saying why. The caller sees nonzero.
    printf 'NDI install failed: %s\n' "$*" >&2
    exit 1
}

usage() {
    say "Usage: install-ndi.sh [--yes] [--no-path] [--uninstall]"
    say "  --yes        do not ask before installing"
    say "  --no-path    do not add ~/.ndi/bin to your PATH"
    say "  --uninstall  remove ~/.ndi/bin, ~/.ndi/python, ~/.ndi/venvs and the PATH lines"
}

YES=0
NO_PATH=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --yes | -y) YES=1 ;;
        --no-path) NO_PATH=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --help | -h) usage; exit 0 ;;
        *) usage >&2; fail "unknown option: $arg" ;;
    esac
done

[ -n "${HOME:-}" ] || fail "HOME is not set"

# MATLAB runs this with its own libraries first on LD_LIBRARY_PATH (Linux),
# which can break the system curl (NDI-matlab's systemCurlEnvPrefix exists for
# exactly that) and the Python that builds and checks NDI below. Nothing this
# script runs needs any of these. The same list, and the reasons, are in
# src/_ndi_launch.py, which does this for the viewers themselves.
unset LD_LIBRARY_PATH LD_PRELOAD DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH \
    DYLD_FRAMEWORK_PATH DYLD_INSERT_LIBRARIES PYTHONHOME PYTHONPATH

# ---- shell start-up files ----------------------------------------------------

# The files a new terminal reads, for the shells we know. zsh is the macOS
# default and bash the usual Linux one; a file that already exists is used
# whatever the login shell, so switching shells later still finds ~/.ndi/bin.
profile_files() {
    login_shell=$(basename "${SHELL:-sh}")
    for f in .zshrc .zprofile; do
        if [ "$login_shell" = zsh ] || [ -f "$HOME/$f" ]; then say "$HOME/$f"; fi
    done
    for f in .bashrc .profile; do
        if [ "$login_shell" = bash ] || [ -f "$HOME/$f" ]; then say "$HOME/$f"; fi
    done
    # A login bash reads .bash_profile INSTEAD of .profile when it exists
    # (macOS Terminal starts login shells), so it needs the block too.
    if [ -f "$HOME/.bash_profile" ]; then say "$HOME/.bash_profile"; fi
    # Any other shell: .profile at least.
    case "$login_shell" in zsh | bash) ;; *) say "$HOME/.profile" ;; esac
}

# Delete our marked block from one file, in place (keeping the file itself,
# so its permissions, owner and any symlink survive). If the block says it
# added a newline to the line before it, and that line is still the last,
# the newline goes too.
remove_block() {
    file=$1
    [ -f "$file" ] || return 0
    grep -qF "$PATH_BEGIN" "$file" || return 0
    tmp=$(mktemp)
    awk -v b="$PATH_BEGIN" -v j="$PATH_BEGIN$JOINED" -v c="$PATH_BEGIN$CREATED" -v e="$PATH_END" '
        $0 == b || $0 == j || $0 == c { if ($0 == j) joined = n; skip = 1; next }
        skip && $0 == e { skip = 0; next }
        !skip { line[++n] = $0 }
        END {
            for (i = 1; i <= n; i++) {
                printf "%s", line[i]
                if (!(joined && i == joined && i == n)) printf "\n"
            }
        }
    ' "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

# Idempotent: any earlier block is replaced, never duplicated. APPENDED to the
# PATH, not prepended, so the uv in ~/.ndi/bin never shadows a uv of your own.
add_to_path() {
    profile_files | sort -u | while IFS= read -r file; do
        begin=$PATH_BEGIN
        if [ ! -e "$file" ] || grep -qxF "$PATH_BEGIN$CREATED" "$file"; then
            begin="$PATH_BEGIN$CREATED"
        fi
        remove_block "$file"
        # A last line with no newline would run into our first one: add the
        # newline, and say so in the marker so --uninstall can remove it.
        if [ -s "$file" ] && [ -n "$(tail -c 1 "$file")" ]; then
            say >> "$file"
            begin="$PATH_BEGIN$JOINED"
        fi
        {
            say "$begin"
            # shellcheck disable=SC2016  # expanded when the shell starts, not now
            say 'case ":$PATH:" in *":$HOME/.ndi/bin:"*) ;; *) export PATH="$PATH:$HOME/.ndi/bin" ;; esac'
            say "$PATH_END"
        } >> "$file"
        say "  added ~/.ndi/bin to the PATH in $file"
    done
}

remove_from_path() {
    for file in "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bashrc" "$HOME/.profile" "$HOME/.bash_profile"; do
        if [ -f "$file" ] && grep -qF "$PATH_BEGIN" "$file"; then
            created=0
            if grep -qxF "$PATH_BEGIN$CREATED" "$file"; then created=1; fi
            remove_block "$file"
            say "  removed the NDI PATH lines from $file"
            # A file this script created, with nothing else in it: delete it.
            if [ "$created" = 1 ] && [ ! -s "$file" ]; then rm -f "$file"; fi
        fi
    done
}

# ---- uninstall ---------------------------------------------------------------

if [ "$UNINSTALL" = 1 ]; then
    say "Removing NDI from $NDI_HOME (bin, python, venvs, install.json) ..."
    for d in "$BIN" "$PYDIR" "$VENVS"; do
        # uv marks some of its files read-only; make them removable first.
        if [ -d "$d" ]; then chmod -R u+w "$d" 2>/dev/null || true; fi
        rm -rf "$d" || fail "could not remove $d"
    done
    rm -f "$RECEIPT" || fail "could not remove $RECEIPT"
    remove_from_path
    say "Your NDI settings and anything else in $NDI_HOME were left in place."
    say "NDI uninstalled: $BIN"
    exit 0
fi

# ---- install -----------------------------------------------------------------

case "$(uname -s)" in
    Linux | Darwin) ;;
    *) fail "this installer is for Linux and macOS; on Windows use install-ndi.ps1" ;;
esac

download() { # url dest
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --tlsv1.2 -LsSf "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --https-only "$1" -O "$2"
    else
        return 1
    fi
}

say "NDI installer"
say "  installs into: $NDI_HOME (bin, python, venvs)"
say "  needs about 3 GB of disk and a few minutes on a good connection"
if [ "$YES" = 0 ] && (: < /dev/tty) 2>/dev/null; then
    printf 'Continue? [Y/n] '
    read -r answer < /dev/tty || answer=""
    case "$answer" in
        "" | [Yy] | [Yy][Ee][Ss]) ;;
        *) fail "cancelled" ;;
    esac
fi

mkdir -p "$BIN" "$PYDIR" "$VENVS" || fail "could not create folders in $NDI_HOME"

# 1. uv, pinned. Astral's versioned installer, told to put uv in ~/.ndi/bin.
# UV_UNMANAGED_INSTALL also stops it writing an update receipt in
# ~/.config/uv, which would otherwise redirect a `uv self update` of a uv you
# already have to this copy, and stops it editing your PATH itself.
uv_version() { "$BIN/uv" --version 2>/dev/null | awk '{print $2}'; }
if [ -x "$BIN/uv" ] && [ "$(uv_version)" = "$UV_VERSION" ]; then
    say "uv $UV_VERSION is already in $BIN"
else
    say "Downloading uv $UV_VERSION ..."
    tmp=$(mktemp)
    download "https://astral.sh/uv/$UV_VERSION/install.sh" "$tmp" \
        || { rm -f "$tmp"; fail "could not download the uv installer from astral.sh (need curl or wget, and a connection)"; }
    if ! UV_INSTALL_DIR="$BIN" UV_UNMANAGED_INSTALL="$BIN" UV_NO_MODIFY_PATH=1 \
        sh "$tmp" --quiet; then
        rm -f "$tmp"
        fail "the uv installer did not succeed"
    fi
    rm -f "$tmp"
    [ "$(uv_version)" = "$UV_VERSION" ] || fail "uv $UV_VERSION did not end up in $BIN"
fi

# 2. NDI, as a uv "tool": its own environment, its own managed Python, and
# its commands linked into ~/.ndi/bin. Each setting keeps uv inside the three
# folders above and away from anything else on this machine:
export UV_PYTHON_INSTALL_DIR="$PYDIR"   # the interpreter
export UV_TOOL_DIR="$VENVS"             # the environment
export UV_TOOL_BIN_DIR="$BIN"           # the commands
export UV_PYTHON_PREFERENCE=only-managed  # never a system/Homebrew/conda Python that may vanish
export UV_NO_CONFIG=1                   # ignore any uv.toml of yours
export UV_NO_MODIFY_PATH=1

# Which commit is being installed, for ~/.ndi/install.json (step 4). For the
# default source, ask GitHub for main's current commit and install exactly
# that commit's archive, so the receipt cannot name a different commit from
# the one installed. If GitHub's API cannot be reached (offline, rate limit),
# install main as before and record no commit; ndi.update then falls back to
# the install time. A local checkout records its HEAD when git is there.
COMMIT=""
SOURCE="${NDI_INSTALL_SOURCE:-$DEFAULT_SOURCE}"
if [ -z "${NDI_INSTALL_SOURCE:-}" ]; then
    tmp=$(mktemp)
    if download "$COMMITS_API" "$tmp" 2>/dev/null; then
        # The commit's own sha is the first "sha" at the top level (2 spaces in).
        COMMIT=$(sed -n 's/^  "sha": "\([0-9a-f]\{40\}\)".*$/\1/p' "$tmp" | head -n 1)
    fi
    rm -f "$tmp"
    if [ -n "$COMMIT" ]; then
        SOURCE="$ARCHIVE_BASE/$COMMIT.zip"
    fi
elif [ -d "$SOURCE" ] && command -v git >/dev/null 2>&1; then
    COMMIT=$(git -C "$SOURCE" rev-parse HEAD 2>/dev/null || true)
fi
if [ -d "$SOURCE" ]; then
    # A local checkout (CI): a file URL to its absolute path.
    SOURCE="file://$(cd "$SOURCE" && pwd -P | sed 's/ /%20/g')"
elif [ -f "$SOURCE" ]; then
    # A local wheel or source archive.
    SOURCE="file://$(cd "$(dirname "$SOURCE")" && pwd -P | sed 's/ /%20/g')/$(basename "$SOURCE" | sed 's/ /%20/g')"
fi
FIND_LINKS="${NDI_PYRAVIEW_FIND_LINKS:-$REPO_RAW/install/pyraview-wheels.html}"
CONSTRAINTS="${NDI_PYRAVIEW_CONSTRAINTS:-$REPO_RAW/install/pyraview-constraints.txt}"

say "Installing NDI from $SOURCE ..."
# --reinstall (which implies --refresh) so that running this again really
#   updates: NDI and its GitHub-archive dependencies are re-fetched.
# Pyraview is not on PyPI: its release wheels are found through FIND_LINKS,
#   CONSTRAINTS pins the version, and --no-build-package makes a missing wheel
#   an error rather than a C++ compile. See pyproject.toml's pyraview extra.
# PATH includes ~/.ndi/bin for this one command only, so uv does not warn
#   that the folder is not on the PATH; step 4 deals with that.
PATH="$BIN:$PATH" "$BIN/uv" tool install \
    --python "${NDI_INSTALL_PYTHON:-$PYTHON_VERSION}" \
    --reinstall \
    --find-links "$FIND_LINKS" \
    --constraints "$CONSTRAINTS" \
    --no-build-package pyraview \
    "ndi[$EXTRAS] @ $SOURCE" \
    || fail "uv could not install NDI (see the messages above)"

# 3. Check the result: the commands MATLAB will call, and `ndi check`.
say "Checking the installation ..."
for cmd in ndi napariViewGEF napariViewLightsheet; do
    [ -x "$BIN/$cmd" ] || fail "$BIN/$cmd is missing"
done
for cmd in napariViewGEF napariViewLightsheet; do
    "$BIN/$cmd" --help > /dev/null || fail "$cmd --help did not run"
done
log=$(mktemp)
if ! "$BIN/ndi" check > "$log" 2>&1; then
    cat "$log"
    rm -f "$log"
    fail "ndi check reported problems (see above)"
fi
rm -f "$log"
say "  ndi check: all checks passed"

# 4. The receipt: what was installed, from where, and when. Written only
# after the check passed, so it never describes an install that failed.
if [ -n "$COMMIT" ]; then commit_json="\"$COMMIT\""; else commit_json=null; fi
printf '{\n  "commit": %s,\n  "source": "%s",\n  "installedAt": "%s",\n  "installer": "install-ndi.sh"\n}\n' \
    "$commit_json" "$SOURCE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RECEIPT" \
    || fail "could not write $RECEIPT"
if [ -n "$COMMIT" ]; then
    say "  installed commit $COMMIT"
fi

# 5. PATH.
if [ "$NO_PATH" = 0 ]; then
    add_to_path
    say "Open a new terminal window to use the ndi, napariViewGEF and napariViewLightsheet commands."
else
    say "PATH left alone (--no-path); the commands are in $BIN"
fi

say "NDI installed: $BIN"
