"""
ndi.file.pfilemirror - Directory mirroring utility.

MATLAB equivalent: +ndi/+file/pfilemirror.m

In MATLAB, this mirrors .m files into .p (p-code) files.
In Python, this provides a general directory-mirror utility
that can copy/compile Python files or simply mirror a tree.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional


def pfilemirror(
    src_path: str,
    dest_path: str,
    *,
    copy_non_py_files: bool = False,
    copy_hidden_files: bool = False,
    verbose: bool = True,
    dry_run: bool = False,
    compile_pyc: bool = False,
) -> bool:
    """Mirror a directory tree, optionally compiling .py to .pyc.

    MATLAB equivalent: ndi.file.pfilemirror

    Recursively copies a source directory to a destination, creating
    the directory structure as needed.

    Args:
        src_path: Source directory path.
        dest_path: Destination directory path.
        copy_non_py_files: Copy non-.py files as well.
        copy_hidden_files: Copy hidden files (starting with ``'.'``).
        verbose: Print actions as they occur.
        dry_run: Display actions without executing them.
        compile_pyc: If True, compile .py files to .pyc instead of copying.

    Returns:
        True on success, False on failure.
    """
    src = Path(src_path)
    dest = Path(dest_path)

    if not src.is_dir():
        if verbose:
            print(f'Error: Source path {src} is not a directory')
        return False

    if not dest.exists():
        if verbose or dry_run:
            print(f'Action: Create directory {dest}')
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)

    for item in sorted(src.iterdir()):
        name = item.name

        # Skip . and .. (handled by iterdir), .git
        if name == '.git':
            continue
        if not copy_hidden_files and name.startswith('.'):
            continue

        if item.is_dir():
            sub_dest = dest / name
            if not sub_dest.exists():
                if verbose or dry_run:
                    print(f'Action: Create directory {sub_dest}')
                if not dry_run:
                    sub_dest.mkdir(parents=True, exist_ok=True)

            success = pfilemirror(
                str(item),
                str(sub_dest),
                copy_non_py_files=copy_non_py_files,
                copy_hidden_files=copy_hidden_files,
                verbose=verbose,
                dry_run=dry_run,
                compile_pyc=compile_pyc,
            )
            if not success:
                return False

        elif item.suffix == '.py':
            if compile_pyc:
                pyc_name = item.stem + '.pyc'
                dest_file = dest / pyc_name

                if verbose or dry_run:
                    print(f'Action: Compile {item} -> {dest_file}')
                if not dry_run:
                    import py_compile
                    try:
                        py_compile.compile(
                            str(item),
                            cfile=str(dest_file),
                            doraise=True,
                        )
                    except py_compile.PyCompileError as e:
                        if verbose:
                            print(f'Error compiling {item}: {e}')
                        return False
            else:
                dest_file = dest / name
                if verbose or dry_run:
                    print(f'Action: Copy {item} -> {dest_file}')
                if not dry_run:
                    shutil.copy2(str(item), str(dest_file))

        else:
            # Non-.py files
            if copy_non_py_files:
                dest_file = dest / name
                if verbose or dry_run:
                    print(f'Action: Copy {item} -> {dest_file}')
                if not dry_run:
                    shutil.copy2(str(item), str(dest_file))

    return True
