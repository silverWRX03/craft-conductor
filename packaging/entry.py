"""Entry point for the standalone executable built by PyInstaller (see craft-conductor.spec)."""

import sys

from craft_conductor.cli import main

if __name__ == "__main__":
    sys.exit(main())
