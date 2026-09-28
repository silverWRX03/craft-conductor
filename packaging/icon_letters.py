"""Craft Conductor's icon artwork: the original picture (packaging/icon-art-mcsm.jpg: stone "MCSM"
letters on lava-cracked bricks in a metal frame) with the letters replaced by "CC", keeping the
frame and the bricks.

    pip install pillow numpy && python packaging/icon_letters.py && python packaging/icon_from_picture.py

The wall behind the old letters is filled with brick from just above them (blended in only where
the letters were), then the picture's own stone C is cut out and placed twice, larger, with a
shadow and a faint lava glow. Writes packaging/icon-source.jpg.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
SRC = HERE / "icon-art-mcsm.jpg"
img = Image.open(SRC).convert("RGB")
a = np.asarray(img).astype(float)
mx, mn = a.max(-1), a.min(-1)
sat = (mx - mn) / np.maximum(mx, 1)
stone = (sat < 0.22) & (mx > 70)
region = np.zeros_like(stone); region[365:560, 205:912] = True
letters = Image.fromarray(((stone & region) * 255).astype("uint8"))
# solid letters (holes and cracks closed), plus their 3D sides and shadow around them
solid = letters.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
cover = solid.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(10))

# 1. The wall without the letters: brick texture from above the letters, blended in where they were.
patch = img.copy()
band = img.crop((205, 150, 912, 150 + 230))
patch.paste(band, (205, 350))
wall = Image.composite(patch, img, cover)

# 2. The stone C, cut out with its own shading.
cbox = (410, 360, 556, 560)
cmask = solid.crop(cbox).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
cimg = img.crop(cbox)
scale = 1.5
size = (round(cimg.width * scale), round(cimg.height * scale))
cimg, cmask = cimg.resize(size, Image.LANCZOS), cmask.resize(size, Image.LANCZOS)

out = wall.copy()
gap = 40
total = size[0] * 2 + gap
x0 = (205 + 912) // 2 - total // 2 + 6
y0 = 462 - size[1] // 2
for x in (x0, x0 + size[0] + gap):
    # a soft dark shadow down and to the right, then a faint lava glow round the edge
    sh = Image.new("L", out.size, 0); sh.paste(cmask, (x + 10, y0 + 12))
    sh = sh.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.75))
    out = Image.composite(Image.new("RGB", out.size, (15, 5, 3)), out, sh)
    glow = Image.new("L", out.size, 0); glow.paste(cmask.filter(ImageFilter.MaxFilter(7)), (x, y0))
    glow = glow.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.35))
    out = Image.composite(Image.new("RGB", out.size, (255, 80, 20)), out, glow)
    out.paste(cimg, (x, y0), cmask)
out.save(HERE / "icon-source.jpg", quality=95)
