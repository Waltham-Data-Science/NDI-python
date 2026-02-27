#!/usr/bin/env python3
"""
NDI-python installer.

One-command setup for NDI-python and all its dependencies.
Equivalent to MATLAB's ndi_install.m — run once after cloning.

Usage:
    python ndi_install.py                    # Fresh install
    python ndi_install.py --update           # Update existing deps
    python ndi_install.py --tools-dir DIR    # Custom clone location
    python ndi_install.py --verbose          # Detailed output

What it does:
    1. Checks prerequisites (git, Python >= 3.10)
    2. Clones vhlab-toolbox-python to ~/.ndi/tools/ (not on PyPI)
    3. Writes a .pth file so Python finds it automatically
    4. Installs NDI-python and all pip dependencies (DID-python via pip)
    5. Validates the installation
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEPENDENCIES = [
    {
        "name": "vhlab-toolbox-python",
        "repo": "https://github.com/VH-Lab/vhlab-toolbox-python.git",
        "branch": "main",
        "python_path": ".",
        "description": "VH-Lab data utilities and file formats (not on PyPI)",
    },
]

DEFAULT_TOOLS_DIR = Path.home() / ".ndi" / "tools"

PTH_FILENAME = "ndi-deps.pth"

# Additional pip dependencies not covered by pyproject.toml's [project.optional-dependencies].
PIP_DEPS = [
    "scipy>=1.9.0",
    "pandas>=1.5.0",
    "matplotlib>=3.5.0",
    "portalocker>=2.0.0",
    "openminds>=0.2.0",
    "opencv-python-headless>=4.5.0",
]

PIP_DEV_DEPS = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_verbose = False


def info(msg: str) -> None:
    print(f"  {msg}")


def detail(msg: str) -> None:
    if _verbose:
        print(f"    {msg}")


def success(msg: str) -> None:
    print(f"  [OK] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def heading(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def check_prerequisites() -> list[str]:
    """Check that git and Python >= 3.10 are available. Return errors."""
    errors = []

    # Python version
    if sys.version_info < (3, 10):
        errors.append(
            f"Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}"
        )

    # Git
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            errors.append("git is installed but returned an error")
        else:
            detail(result.stdout.strip())
    except FileNotFoundError:
        errors.append("git is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        errors.append("git --version timed out")

    return errors


# ---------------------------------------------------------------------------
# Virtual environment detection
# ---------------------------------------------------------------------------


def in_venv() -> bool:
    """Check if running inside a virtual environment."""
    return sys.prefix != sys.base_prefix


def get_site_packages() -> Path | None:
    """Find the site-packages directory for .pth file placement."""
    purelib = sysconfig.get_path("purelib")
    if purelib and Path(purelib).is_dir():
        return Path(purelib)
    return None


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def git_clone(repo_url: str, target_dir: Path, branch: str) -> bool:
    """Clone a repository. Returns True on success."""
    detail(f"git clone --branch {branch} --single-branch {repo_url}")
    result = subprocess.run(
        [
            "git",
            "clone",
            "--branch",
            branch,
            "--single-branch",
            repo_url,
            str(target_dir),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        fail(f"git clone failed: {result.stderr.strip()}")
        return False
    return True


def git_has_changes(repo_dir: Path) -> bool:
    """Check if a repo has uncommitted changes."""
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return bool(result.stdout.strip())


def git_update(repo_dir: Path) -> bool:
    """Update a repository with stash/pull/pop. Returns True on success."""
    stashed = False

    # Stash if there are local changes
    if git_has_changes(repo_dir):
        detail("Stashing local changes...")
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "stash"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            stashed = True
        else:
            warn(f"git stash failed: {result.stderr.strip()}")

    # Pull
    detail("git pull --ff-only")
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "pull", "--ff-only"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        warn(f"git pull failed: {result.stderr.strip()}")
        # Still try to pop stash
        if stashed:
            subprocess.run(
                ["git", "-C", str(repo_dir), "stash", "pop"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        return False

    detail(result.stdout.strip())

    # Pop stash
    if stashed:
        detail("Restoring stashed changes...")
        pop_result = subprocess.run(
            ["git", "-C", str(repo_dir), "stash", "pop"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if pop_result.returncode != 0:
            warn("Could not restore stashed changes (may need manual merge)")

    return True


def clone_or_update(name: str, repo_url: str, target_dir: Path, branch: str, update: bool) -> bool:
    """Clone a repo if not present, or update if --update flag is set."""
    if target_dir.exists():
        if update:
            info(f"Updating {name}...")
            return git_update(target_dir)
        else:
            info(f"{name} already cloned at {target_dir}")
            detail("Use --update to pull latest changes")
            return True
    else:
        info(f"Cloning {name}...")
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        return git_clone(repo_url, target_dir, branch)


# ---------------------------------------------------------------------------
# .pth file management
# ---------------------------------------------------------------------------


def write_pth_file(site_packages: Path, tools_dir: Path) -> Path | None:
    """Write ndi-deps.pth file with paths to cloned dependencies."""
    pth_path = site_packages / PTH_FILENAME
    lines = []

    for dep in DEPENDENCIES:
        dep_dir = tools_dir / dep["name"]
        python_path = dep_dir / dep["python_path"] if dep["python_path"] != "." else dep_dir
        if python_path.is_dir():
            lines.append(str(python_path))
        else:
            warn(f"Path not found: {python_path} (for {dep['name']})")

    if not lines:
        fail("No valid dependency paths to write")
        return None

    try:
        pth_path.write_text("\n".join(lines) + "\n")
        detail(f"Wrote {pth_path}")
        for line in lines:
            detail(f"  {line}")
        return pth_path
    except OSError as e:
        fail(f"Could not write {pth_path}: {e}")
        return None


# ---------------------------------------------------------------------------
# pip installation
# ---------------------------------------------------------------------------


def find_ndi_root() -> Path | None:
    """Find the NDI-python repo root (directory containing pyproject.toml)."""
    # Try relative to this script
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "pyproject.toml").exists():
        return script_dir

    # Try current working directory
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists():
        return cwd

    return None


def pip_install(packages: list[str], extra_args: list[str] | None = None) -> bool:
    """Run pip install with the given packages."""
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + (extra_args or []) + packages
    detail(f"pip install {' '.join(packages[:3])}{'...' if len(packages) > 3 else ''}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        # Show stderr but filter out the common "already satisfied" noise
        err = result.stderr.strip()
        if err:
            for line in err.split("\n"):
                if "already satisfied" not in line.lower():
                    detail(line)
        return False
    return True


def install_ndi_and_deps(ndi_root: Path, include_dev: bool = False) -> bool:
    """Install NDI-python (editable) and all pip dependencies."""
    ok = True

    # Install NDI in editable mode (pip resolves DID-python from pyproject.toml)
    info("Installing NDI-python (editable)...")
    extras = "tutorials"
    if include_dev:
        extras = "dev,tutorials"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            f".[{extras}]",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ndi_root),
    )
    if result.returncode != 0:
        fail(f"pip install -e failed: {result.stderr.strip()}")
        ok = False
    else:
        success("NDI-python installed")

    # Install all pip dependencies explicitly
    info("Installing pip dependencies...")
    deps = list(PIP_DEPS)
    if include_dev:
        deps.extend(PIP_DEV_DEPS)
    if not pip_install(deps):
        fail("Some pip dependencies failed to install")
        ok = False
    else:
        success(f"Installed {len(deps)} packages")

    return ok


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate() -> tuple[int, int]:
    """Run validation checks. Returns (passed, total)."""
    checks = [
        ("ndi core package", "ndi"),
        ("ndi.document", "ndi.document"),
        ("ndi.query", "ndi.query"),
        ("ndi.database", "ndi.database"),
        ("DID (did.document)", "did.document"),
        ("DID (did.implementations.sqlitedb)", "did.implementations.sqlitedb"),
        ("DID (did.datastructures)", "did.datastructures"),
        ("vhlab-toolbox (vlt)", "vlt"),
        ("numpy", "numpy"),
        ("networkx", "networkx"),
        ("jsonschema", "jsonschema"),
        ("requests", "requests"),
        ("pandas", "pandas"),
        ("matplotlib", "matplotlib"),
        ("scipy", "scipy"),
    ]

    passed = 0
    total = len(checks)

    for name, module in checks:
        try:
            importlib.import_module(module)
            success(name)
            passed += 1
        except ImportError as e:
            fail(f"{name}: {e}")

    # ndi_common check
    total += 1
    try:
        from ndi.common import PathConstants

        folder = PathConstants.COMMON_FOLDER
        if folder.is_dir():
            success(f"ndi_common data folder ({folder})")
            passed += 1
        else:
            fail(f"ndi_common folder not found at {folder}")
    except Exception as e:
        fail(f"ndi_common: {e}")

    # Cloud credentials (informational, not a pass/fail)
    username = os.environ.get("NDI_CLOUD_USERNAME", "")
    if username:
        info(f"[INFO] NDI Cloud credentials: configured ({username})")
    else:
        info("[INFO] NDI Cloud credentials: not set (needed for tutorials)")

    # Smoke test
    total += 1
    try:
        from ndi.document import Document

        doc = Document("base")
        if doc.id:
            success("Smoke test: Document('base') created")
            passed += 1
        else:
            fail("Smoke test: Document created but has no ID")
    except Exception as e:
        fail(f"Smoke test: {e}")

    return passed, total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    global _verbose

    parser = argparse.ArgumentParser(
        description="NDI-python installer — one-command setup for all dependencies.",
        epilog="After installation, run 'python -m ndi check' to verify.",
    )
    parser.add_argument(
        "--tools-dir",
        type=Path,
        default=DEFAULT_TOOLS_DIR,
        help=f"Where to clone VH-Lab dependencies (default: {DEFAULT_TOOLS_DIR})",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing dependency clones (git pull)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also install development tools (pytest, black, ruff)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip post-install validation",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output",
    )
    args = parser.parse_args()
    _verbose = args.verbose

    heading("NDI-python Installer")

    # ── Step 1: Prerequisites ──────────────────────────────────────────
    print("\n[1/5] Checking prerequisites...")
    errors = check_prerequisites()
    if errors:
        for e in errors:
            fail(e)
        return 1
    success(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    success("git available")

    # Check venv
    if in_venv():
        success(f"Virtual environment active ({sys.prefix})")
    else:
        warn("Not running in a virtual environment.")
        warn("It is strongly recommended to create one first:")
        warn("  python -m venv venv && source venv/bin/activate")
        # Continue anyway — user may know what they're doing

    # ── Step 2: Clone dependencies ─────────────────────────────────────
    print("\n[2/5] Setting up VH-Lab dependencies...")
    tools_dir = args.tools_dir.expanduser().resolve()
    all_cloned = True

    for dep in DEPENDENCIES:
        target = tools_dir / dep["name"]
        ok = clone_or_update(dep["name"], dep["repo"], target, dep["branch"], args.update)
        if not ok:
            all_cloned = False

    if not all_cloned:
        fail("Some dependencies could not be cloned")
        return 1
    success(f"Dependencies ready at {tools_dir}")

    # ── Step 3: Write .pth file ────────────────────────────────────────
    print("\n[3/5] Configuring Python path...")
    site_packages = get_site_packages()
    if site_packages is None:
        fail("Could not find site-packages directory")
        warn("You may need to set PYTHONPATH manually:")
        for dep in DEPENDENCIES:
            dep_dir = tools_dir / dep["name"]
            python_path = dep_dir / dep["python_path"] if dep["python_path"] != "." else dep_dir
            warn(f"  {python_path}")
        return 1

    pth_file = write_pth_file(site_packages, tools_dir)
    if pth_file is None:
        return 1
    success(f".pth file written to {pth_file}")

    # Reload site paths so validation can find the new packages
    import importlib
    import site

    importlib.reload(site)
    # Add paths directly for this process
    for dep in DEPENDENCIES:
        dep_dir = tools_dir / dep["name"]
        python_path = (
            str(dep_dir / dep["python_path"]) if dep["python_path"] != "." else str(dep_dir)
        )
        if python_path not in sys.path:
            sys.path.insert(0, python_path)

    # ── Step 4: Install packages ───────────────────────────────────────
    print("\n[4/5] Installing packages...")
    ndi_root = find_ndi_root()
    if ndi_root is None:
        fail("Cannot find NDI-python repo root (pyproject.toml)")
        fail("Run this script from inside the NDI-python directory")
        return 1

    if not install_ndi_and_deps(ndi_root, include_dev=args.dev):
        warn("Some packages may not have installed correctly")

    # ── Step 5: Validate ───────────────────────────────────────────────
    if args.no_validate:
        print("\n[5/5] Validation skipped (--no-validate)")
    else:
        print("\n[5/5] Validating installation...")
        # Clear module cache so validation imports fresh
        for key in list(sys.modules.keys()):
            if key.startswith(("ndi", "did", "vlt")):
                del sys.modules[key]

        passed, total = validate()

        heading("Installation Complete")
        if passed == total:
            print(f"\n  All {total} checks passed. NDI-python is ready to use.")
        else:
            print(f"\n  {passed}/{total} checks passed.")
            if passed < total:
                print("  Some checks failed — see above for details.")

        print("\n  Next steps:")
        print("    python -m ndi check          # Re-run validation anytime")
        print("    python -m ndi version         # Show version info")
        print("    python tutorials/tutorial_67f723d574f5f79c6062389d.py  # Run a tutorial")
        print()

    return 0 if not args.no_validate else 0


if __name__ == "__main__":
    sys.exit(main())
