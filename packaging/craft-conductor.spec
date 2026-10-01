# PyInstaller build for the standalone `craft-conductor` executable.
#   pip install pyinstaller && pyinstaller packaging/craft-conductor.spec
# Output: dist/craft-conductor (dist/craft-conductor.exe on Windows)
import os
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

root = Path(SPECPATH).parent


def license_files():
    """License texts for everything bundled into the executable, shipped inside it."""
    python = next((p for p in (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                               Path(sys.base_prefix) / "LICENSE.txt",
                               Path(sys.base_prefix) / "LICENSE") if p.is_file()), None)
    if python is None:
        raise SystemExit("can't find Python's LICENSE.txt; it must be bundled with the executable")
    dist = metadata.distribution("pyinstaller")
    copying = next((Path(dist.locate_file(f)) for f in dist.files or [] if f.name == "COPYING.txt"), None)
    if copying is None or not copying.is_file():
        raise SystemExit("can't find PyInstaller's COPYING.txt; it must be bundled with the executable")
    staged = Path(workpath) / "licenses"
    staged.mkdir(parents=True, exist_ok=True)
    for src, name in ((python, "PYTHON-LICENSE.txt"), (copying, "PYINSTALLER-COPYING.txt"),
                      (root / "LICENSE", "CRAFT-CONDUCTOR-LICENSE.txt"), (root / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")):
        (staged / name).write_bytes(src.read_bytes())
    return [(str(staged), "craft_conductor/licenses")]


a = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root / "src")],
    # The web UI's HTML/JS/CSS, loaded with importlib.resources at runtime.
    datas=[(str(root / "src" / "craft_conductor" / "webui"), "craft_conductor/webui"), *license_files()],
    hiddenimports=["craft_conductor.web"]  # imported lazily by the daemon
    + (["craft_conductor._buildkeys"] if (root / "src" / "craft_conductor" / "_buildkeys.py").is_file() else []),  # release builds' CurseForge key
    excludes=["tkinter", "unittest", "pydoc_data", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="craft-conductor",
    icon=str(root / "packaging" / "craft-conductor.ico"),  # made by packaging/icon_from_picture.py
    # Windows: no command window; everything happens in the browser (see craft_conductor/desktop.py).
    # macOS and Linux keep the terminal, where it's started from.
    console=sys.platform != "win32",
    upx=False,          # UPX-packed binaries trigger antivirus false positives
    strip=False,
)
