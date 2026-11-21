"""Build the Craft Conductor Ping helper jars (helpers/ping/) and ship them in the package.

Builds every helper: the Paper/Purpur plugin, the Fabric/Quilt mod (Fabric Loom, which downloads
the Minecraft server jar and its mappings into Gradle's cache the first time), the NeoForge mod
(ModDevGradle, which downloads NeoForge and Minecraft 1.20.4 the same way), the Forge 1.20.1 mod
(ModDevGradle's legacyforge plugin, which downloads Forge 47 and Minecraft 1.20.1 and reobfuscates the
mod to Forge's own names) and the Forge mod for 1.20.2 and newer (ModDevGradle with Minecraft 1.20.2 and
Forge 48's jars; its 1.20.2 to 1.20.4 jar renamed to Forge's own names with legacyforge's tools).

    python tools/build_helpers.py           build, then copy the jars into src/craft_conductor/helpers/
    python tools/build_helpers.py --check   build into a temporary folder and exit 1 when a shipped
                                            jar's SHA-256 differs (or a shipped jar has no source)

Needs a JDK (21 builds every helper) and Gradle 8.10.2: the ``gradle`` on PATH, or the program named
by the GRADLE environment variable. There is no Gradle wrapper in the repository. Craft Conductor
itself needs neither at run time.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "helpers" / "ping"
SHIPPED = ROOT / "src" / "craft_conductor" / "helpers"
JAR_GLOB = "craft_conductor_ping-*.jar"


def find_gradle() -> str:
    found = os.environ.get("GRADLE") or shutil.which("gradle")
    if not found:
        sys.exit("Gradle not found: put gradle (8.10.2) on PATH or set GRADLE to its program.")
    return found


def build() -> list[Path]:
    """Run Gradle and return the jars it made (``assemble``: the Fabric mod's is Loom's remapped jar,
    the Forge mods' for up to 1.20.4 the reobfuscated ones; two Fabric jars, two NeoForge jars and three
    Forge jars, see helpers/ping/README.md)."""
    for old in PROJECT.glob("*/build/libs"):
        shutil.rmtree(old, ignore_errors=True)
    cmd = [find_gradle(), "-p", str(PROJECT), "--no-daemon", "--console=plain", "-q", "assemble"]
    if subprocess.run(cmd, check=False).returncode:
        sys.exit("The Gradle build failed.")
    jars = sorted(PROJECT.glob(f"*/build/libs/{JAR_GLOB}"))
    if not jars:
        sys.exit("The Gradle build made no jars.")
    return jars


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="build into a temporary folder and fail when a shipped jar differs")
    args = ap.parse_args(argv)
    built = build()
    if not args.check:
        SHIPPED.mkdir(parents=True, exist_ok=True)
        for old in SHIPPED.glob(JAR_GLOB):
            old.unlink()
        for jar in built:
            shutil.copyfile(jar, SHIPPED / jar.name)
            print(f"shipped {jar.name}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        fresh: dict[str, str] = {}
        for jar in built:
            copy = Path(tmp) / jar.name
            shutil.copyfile(jar, copy)
            fresh[jar.name] = sha256(copy)
    shipped = {p.name: sha256(p) for p in SHIPPED.glob(JAR_GLOB)}
    problems = []
    for name, digest in sorted(fresh.items()):
        if name not in shipped:
            problems.append(f"{name}: built, but not shipped in {SHIPPED}")
        elif shipped[name] != digest:
            problems.append(f"{name}: the shipped jar differs from a fresh build "
                            f"(shipped {shipped[name][:12]}, built {digest[:12]})")
    for name in sorted(set(shipped) - set(fresh)):
        problems.append(f"{name}: shipped, but the source no longer builds it")
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print("Run `python tools/build_helpers.py` and commit the jars "
              "(or take the jars from the CI artifact).", file=sys.stderr)
        return 1
    print(f"{len(fresh)} shipped helper jar(s) match a fresh build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
