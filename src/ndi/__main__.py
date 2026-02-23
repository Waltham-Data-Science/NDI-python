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
        return 0

    command = sys.argv[1]
    # Shift argv so subcommand sees itself as sys.argv[0]
    sys.argv = sys.argv[1:]

    if command == "check":
        from ndi.check import main as check_main

        return check_main()
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


if __name__ == "__main__":
    sys.exit(main())
