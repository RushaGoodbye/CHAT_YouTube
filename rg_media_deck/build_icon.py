"""Generate RG Media Deck icon in Windows ICO and PNG sizes.

No external asset downloads, proprietary fonts or internet access. Uses Pillow,
supplied only at build time. Supersampled vector-like shapes remain legible at
16x16, with dark navy, cyan play/clapper and Ukrainian yellow accent.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def generate(out_dir: str | Path | None = None) -> tuple[Path, Path]:
    root = Path(out_dir) if out_dir else Path(__file__).resolve().parent / "assets"
    root.mkdir(exist_ok=True, parents=True)
    n = 512
    image = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(n):
        for x in range(n):
            d = math.hypot(x - 240, y - 190) / 560
            pixels[x, y] = (
                round(10 + (1 - d) * 6),
                round(19 + (1 - d) * 18),
                round(32 + (1 - d) * 28), 255)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((30, 30, 481, 481), radius=104, fill=255)
    image.putalpha(mask)
    glow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.rounded_rectangle(
        (31, 31, 480, 480), radius=103,
        outline=(0, 151, 255, 190), width=18)
    image = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)), image)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (36, 36, 475, 475), radius=102,
        outline=(24, 184, 255, 255), width=12)
    draw.rounded_rectangle(
        (51, 51, 460, 460), radius=92,
        outline=(80, 221, 255, 78), width=3)
    # The large play symbol and white stripes remain identifiable when tiny.
    draw.rounded_rectangle(
        (105, 175, 407, 403), radius=31,
        fill=(5, 15, 31, 255), outline=(27, 154, 222, 255), width=9)
    draw.rounded_rectangle(
        (125, 194, 387, 385), radius=20, fill=(4, 20, 35, 255))
    draw.rounded_rectangle(
        (100, 156, 405, 231), radius=15,
        fill=(10, 24, 39, 255), outline=(117, 190, 232, 255), width=5)
    for x in (120, 183, 246, 309):
        draw.polygon(((x, 157), (x + 40, 157),
                      (x + 78, 225), (x + 38, 225)),
                     fill=(233, 242, 249, 255))
    draw.ellipse(
        (118, 175, 144, 201), fill=(143, 175, 196, 255),
        outline=(234, 250, 255, 255), width=3)
    draw.line((108, 237, 401, 237), fill=(42, 176, 240, 255), width=8)
    halo = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(halo).polygon(
        ((222, 265), (222, 364), (314, 314)), fill=(16, 207, 255, 255))
    image = Image.alpha_composite(image, halo.filter(ImageFilter.GaussianBlur(16)))
    image = Image.alpha_composite(image, halo)
    draw = ImageDraw.Draw(image)
    draw.polygon(
        ((237, 273), (237, 353), (310, 313)), fill=(205, 253, 255, 255))
    draw.polygon(
        ((275, 450), (456, 369), (456, 429), (377, 458)),
        fill=(255, 207, 30, 255))
    draw.line((275, 450, 405, 395), fill=(255, 239, 107, 230), width=7)
    alpha = image.getchannel("A")
    bounds = Image.new("L", (n, n), 0)
    ImageDraw.Draw(bounds).rounded_rectangle(
        (19, 19, 493, 493), radius=116, fill=255)
    image.putalpha(ImageChops.multiply(alpha, bounds))
    png = root / "RG_Media_Deck.png"
    ico = root / "RG_Media_Deck.ico"
    image.save(png, optimize=True)
    image.save(
        ico, format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
               (64, 64), (128, 128), (256, 256)])
    return ico, png


if __name__ == "__main__":
    icon, png = generate()
    print(f"RG_ICON_GENERATED {icon} {png}")
