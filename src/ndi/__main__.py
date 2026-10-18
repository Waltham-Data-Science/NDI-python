"""
NDI command-line entry point.

Usage:
    python -m ndi check      # Validate installation
    python -m ndi version    # Show version info
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m ndi <command>")
        print()
        print("Commands:")
        print("  check     Validate NDI installation")
        print("  version   Show version information")
        print("  update    Update NDI-python (--check: only report; --help: options)")
        print("  napari    View a spatial gene expression pyramid")
        return 0

    command = sys.argv[1]
    # Shift argv so subcommand sees itself as sys.argv[0]
    sys.argv = sys.argv[1:]

    if command == "check":
        from ndi.check import main as check_main

        return check_main()
    elif command == "napari":
        from ndi.gui.app.genepyramid.cli import main as napari_main

        return napari_main()
    elif command == "update":
        return _update_main(sys.argv[1:])
    elif command == "version":
        from ndi import version

        ver, url = version()
        print(f"NDI-python {ver}")
        print(f"Repository: {url}")
        return 0
    else:
        print(f"Unknown command: {command}")
        print("Run 'python -m ndi --help' for usage.")
        return 1


def _update_main(argv: list[str]) -> int:
    """``ndi update``: check for, and install, a newer NDI-python."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="ndi update",
        description="Update NDI-python to the latest version on its main branch.",
    )
    parser.add_argument("--check", action="store_true", help="only report; change nothing")
    parser.add_argument(
        "--json", action="store_true", help="with --check, print the full result as JSON"
    )
    parser.add_argument("--yes", action="store_true", help="do not ask before updating")
    parser.add_argument(
        "--allow-modified",
        action="store_true",
        help="with --yes, update even if you have changed NDI-python's code",
    )
    parser.add_argument("--force", action="store_true", help="reinstall even if up to date")
    args = parser.parse_args(argv)

    from ndi import update

    if args.check:
        result = update.check(Verbose=not args.json)
        if args.json:
            print(json.dumps(result, indent=2))
        return 0
    try:
        update.install(Confirm=not args.yes, AllowModified=args.allow_modified, Force=args.force)
    except update.UpdateError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
