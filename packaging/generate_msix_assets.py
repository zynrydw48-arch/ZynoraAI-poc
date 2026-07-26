"""Zynora AI rebrand: one-off build tool (not shipped) generating the PNG
assets an MSIX package needs (Square44x44Logo, Square150x150Logo,
Wide310x150Logo, StoreLogo, SplashScreen, etc.) from the real brand mark in
packaging/zynora_logo.png, instead of a procedurally-drawn placeholder glyph.
Crops just the "Z" mark and centers it on each target canvas, filled with the
source image's own near-black background. Run once; re-run only if
packaging/zynora_logo.png or the required asset list changes.
"""

from pathlib import Path

from PIL import Image

SOURCE_LOGO = Path(__file__).resolve().parent / "zynora_logo.png"
GLYPH_CROP_BOX = (300, 198, 960, 858)  # see generate_icon.py for how this was derived
BG_COLOR = (7, 7, 9, 255)

OUT_DIR = Path(__file__).resolve().parent / "msix" / "Assets"

# name -> (width, height); square logos use square canvases, the wide tile
# and splash screen are drawn on their own (wider) canvas with the same
# glyph centered and re-scaled to fit.
ASSET_SIZES = {
    "Square44x44Logo.png": (44, 44),
    "Square71x71Logo.png": (71, 71),
    "Square150x150Logo.png": (150, 150),
    "Square310x310Logo.png": (310, 310),
    "Wide310x150Logo.png": (310, 150),
    "StoreLogo.png": (50, 50),
    "SplashScreen.png": (620, 300),
}


def _load_glyph() -> Image.Image:
    source = Image.open(SOURCE_LOGO).convert("RGBA")
    return source.crop(GLYPH_CROP_BOX)


def _build_canvas(glyph: Image.Image, width: int, height: int) -> Image.Image:
    """A background-filled canvas of the given (possibly non-square) size,
    with the glyph centered and scaled to fit the shorter dimension."""
    canvas = Image.new("RGBA", (width, height), BG_COLOR)

    icon_size = min(width, height)
    resized_glyph = glyph.resize((icon_size, icon_size), Image.LANCZOS)

    offset = ((width - icon_size) // 2, (height - icon_size) // 2)
    canvas.alpha_composite(resized_glyph, offset)
    return canvas


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    glyph = _load_glyph()
    for filename, (width, height) in ASSET_SIZES.items():
        image = _build_canvas(glyph, width, height)
        out_path = OUT_DIR / filename
        image.save(out_path, format="PNG")
        print(f"wrote {out_path} ({width}x{height})")


if __name__ == "__main__":
    main()
