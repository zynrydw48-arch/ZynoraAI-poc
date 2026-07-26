"""Zynora AI rebrand: one-off build tool (not shipped) generating
packaging/app_icon.ico from the real brand mark in packaging/zynora_logo.png
(the marketing lockup: "Z" glyph + ZYNORA wordmark + tagline on black).
Crops just the glyph, centers it on a plain square matching the source
image's own near-black background, and exports the standard ICO size set.
Run once; re-run only if packaging/zynora_logo.png changes.
"""

from pathlib import Path

from PIL import Image

SOURCE_LOGO = Path(__file__).resolve().parent / "zynora_logo.png"

# Bounding box of the "Z" glyph within the source lockup image (excludes the
# ZYNORA wordmark and tagline below it), found via brightness thresholding
# (glyph gold/glossy-highlight pixels are far brighter than the near-black
# background) with ~8% padding added on each side.
GLYPH_CROP_BOX = (300, 198, 960, 858)

BG_COLOR = (7, 7, 9, 255)  # sampled from the source image's own background
ICO_SIZES = (256, 128, 64, 48, 32, 16)


def build_base_image() -> Image.Image:
    source = Image.open(SOURCE_LOGO).convert("RGBA")
    glyph = source.crop(GLYPH_CROP_BOX)

    size = max(glyph.width, glyph.height)
    canvas = Image.new("RGBA", (size, size), BG_COLOR)
    offset = ((size - glyph.width) // 2, (size - glyph.height) // 2)
    canvas.alpha_composite(glyph, offset)
    return canvas.resize((256, 256), Image.LANCZOS)


def main() -> None:
    base = build_base_image()
    out_path = Path(__file__).resolve().parent / "app_icon.ico"
    base.save(out_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
