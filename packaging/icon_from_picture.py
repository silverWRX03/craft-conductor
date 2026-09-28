"""Makes Craft Conductor's icons from the artwork (packaging/icon-source.jpg, made by icon_letters.py: stone "CC" on
lava-cracked bricks in a metal frame), with the white around it made transparent.

    pip install pillow && python packaging/icon_from_picture.py

Writes packaging/mcsm.ico (the Windows executable), src/mcsm/webui/icon.png (and icon-192/512.png, the
installed phone app) (the web UI, the
friend page and the invite page) and docs/icon.png (the README). Only the white that reaches
the picture's edge is removed (white inside the picture stays), and the cut edge is softened
and cleared of white so there's no halo on dark backgrounds.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "packaging" / "icon-source.jpg"
MARK = (255, 0, 255)


def cut_out(img: Image.Image, tolerance: int = 60) -> Image.Image:
    rgb = img.convert("RGB")
    filled = rgb.copy()
    w, h = filled.size
    # Flood the white in from every edge point that's white (the background is one piece,
    # but the frame's shadow can split it along an edge).
    for x in range(0, w, 8):
        for y in (0, h - 1):
            if min(filled.getpixel((x, y))) > 200:
                ImageDraw.floodfill(filled, (x, y), MARK, thresh=tolerance)
    for y in range(0, h, 8):
        for x in (0, w - 1):
            if min(filled.getpixel((x, y))) > 200:
                ImageDraw.floodfill(filled, (x, y), MARK, thresh=tolerance)
    r, g, b = filled.split()
    background = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 if v == 255 else 0),
                                                         g.point(lambda v: 255 if v == 0 else 0)),
                                     b.point(lambda v: 255 if v == 255 else 0))
    alpha = ImageChops.invert(background)
    alpha = alpha.filter(ImageFilter.MinFilter(5))       # trim the light fringe the JPEG left
    alpha = alpha.filter(ImageFilter.GaussianBlur(1.2))  # and soften the cut edge
    # Along the edge, the leftover colour is mixed with white: darken it back to the frame's.
    edge = alpha.point(lambda v: 255 if 0 < v < 250 else 0).filter(ImageFilter.MaxFilter(5))
    darker = rgb.point(lambda v: int(v * 0.55))
    rgb = Image.composite(darker, rgb, edge)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    box = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    return out.crop(box)


def square(img: Image.Image, size: int, margin: float = 0.02) -> Image.Image:
    inner = int(size * (1 - 2 * margin))
    scale = inner / max(img.size)
    fitted = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2), fitted)
    return canvas


def main() -> None:
    art = cut_out(Image.open(SOURCE))
    big = square(art, 512)
    square(art, 256).save(ROOT / "src" / "mcsm" / "webui" / "icon.png", optimize=True)  # (small: every page loads it)
    for size in (192, 512):  # the installed phone app (manifest.webmanifest) and its notifications
        square(art, size).save(ROOT / "src" / "mcsm" / "webui" / f"icon-{size}.png", optimize=True)
    big.save(ROOT / "docs" / "icon.png", optimize=True)
    square(art, 256).save(ROOT / "packaging" / "mcsm.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote src/mcsm/webui/icon.png (and icon-192/512), docs/icon.png, packaging/mcsm.ico")


if __name__ == "__main__":
    main()
