"""Build icons from packaging/icon-source.png, preserving the supplied transparency.

    pip install pillow && python packaging/icon_from_picture.py

Writes packaging/craft-conductor.ico (the Windows executable), src/craft_conductor/webui/icon.png (and icon-192/512.png, the
installed phone app) (the web UI, the
friend page and the invite page), docs/icon.png (the README), and wiki/images/icon.png.
Only size and padding change. Pillow is a packaging dependency, not a runtime dependency.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packaging" / "icon-source.png"


def square(img: Image.Image, size: int, margin: float = 0.02) -> Image.Image:
    inner = int(size * (1 - 2 * margin))
    scale = inner / max(img.size)
    fitted = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    return canvas


def main() -> None:
    art = Image.open(SOURCE).convert("RGBA")  # supplied artwork already has a transparent background
    big = square(art, 512)
    square(art, 256).save(ROOT / "src" / "craft_conductor" / "webui" / "icon.png", optimize=True)  # (small: every page loads it)
    for size in (192, 512):  # the installed phone app (manifest.webmanifest) and its notifications
        square(art, size).save(ROOT / "src" / "craft_conductor" / "webui" / f"icon-{size}.png", optimize=True)
    big.save(ROOT / "docs" / "icon.png", optimize=True)
    big.save(ROOT / "wiki" / "images" / "icon.png", optimize=True)
    square(art, 256).save(ROOT / "packaging" / "craft-conductor.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote src/craft_conductor/webui/icon.png (and icon-192/512), docs/icon.png, packaging/craft-conductor.ico")


if __name__ == "__main__":
    main()
