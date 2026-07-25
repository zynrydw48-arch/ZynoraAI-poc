"""Sprint 8, recolored for the NYXUS AI rebrand: one-off build tool (not
shipped) generating packaging/app_icon.ico -- a flat rounded-square icon in
the brand's deep navy with a gold magnifying-glass glyph, echoing the
"search" icon already used in the UI (memoryos/ui/icons/*/search.svg).
Run once; re-run only if the design changes.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
BG_COLOR = (11, 19, 43, 255)  # #0B132B, brand deep navy
GLYPH_COLOR = (212, 175, 55, 255)  # #D4AF37, brand gold
CORNER_RADIUS = 48
ICO_SIZES = (256, 128, 64, 48, 32, 16)


def build_base_image() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=CORNER_RADIUS, fill=BG_COLOR)

    circle_center = (108, 108)
    circle_radius = 52
    stroke_width = 22

    bbox = [
        circle_center[0] - circle_radius,
        circle_center[1] - circle_radius,
        circle_center[0] + circle_radius,
        circle_center[1] + circle_radius,
    ]
    draw.ellipse(bbox, outline=GLYPH_COLOR, width=stroke_width)

    angle = math.radians(45)
    start_radius = circle_radius + stroke_width / 2 - 4
    start_x = circle_center[0] + start_radius * math.cos(angle)
    start_y = circle_center[1] + start_radius * math.sin(angle)
    end_x, end_y = 205, 205
    draw.line([start_x, start_y, end_x, end_y], fill=GLYPH_COLOR, width=stroke_width)

    # Round the handle's far end so it doesn't look chopped off.
    r = stroke_width / 2
    draw.ellipse([end_x - r, end_y - r, end_x + r, end_y + r], fill=GLYPH_COLOR)

    return img


def main() -> None:
    base = build_base_image()
    out_path = Path(__file__).resolve().parent / "app_icon.ico"
    base.save(out_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
