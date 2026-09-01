"""Generate ianOS PWA icons + chrome lockup from brand sources.

App icon source:  dashboard/public/ianOS.jpg  (full square, grid art)
Site logo source: dashboard/public/logo.png   (transparent wordmark)

JPG is fine as a design source; home screens and manifests need PNG. This
script resizes the icon square into every size the PWA / Safari / Android
expect, including a maskable 512 with an 80% safe zone so circular crops
don't clip the mark. It also trims logo.png into a tight lockup used by
the nav and boot screen (square canvas → wordmark aspect).

    .venv/bin/python scripts/make_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "dashboard" / "public"
ICON_SRC = PUBLIC / "ianOS.jpg"
LOGO_SRC = PUBLIC / "logo.png"
OUT = PUBLIC / "icons"
LOCKUP = PUBLIC / "logo-lockup.png"

# Near-black pad for maskable icons (matches --bg / theme_color).
PAD = (4, 5, 10, 255)


def square_png(src: Image.Image, size: int) -> Image.Image:
    img = src.convert("RGBA")
    if img.size != (size, size):
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def maskable_png(src: Image.Image, size: int, scale: float = 0.80) -> Image.Image:
    """Full canvas of PAD, artwork scaled into the center safe zone."""
    canvas = Image.new("RGBA", (size, size), PAD)
    inner = max(1, int(round(size * scale)))
    art = square_png(src, inner)
    offset = (size - inner) // 2
    canvas.paste(art, (offset, offset), art)
    return canvas


def content_bbox(img: Image.Image, alpha_floor: int = 16) -> tuple[int, int, int, int]:
    """Tight box around non-transparent pixels (left, top, right, bottom)."""
    alpha = img.getchannel("A")
    w, h = img.size
    px = alpha.load()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if px[x, y] > alpha_floor:
                if x < minx:
                    minx = x
                if y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y
    if maxx < 0:
        return (0, 0, w - 1, h - 1)
    return (minx, miny, maxx, maxy)


def write_lockup(src_path: Path, dest: Path, pad: int = 24) -> tuple[int, int]:
    """Crop transparent chrome from logo.png into a horizontal lockup PNG."""
    img = Image.open(src_path).convert("RGBA")
    left, top, right, bottom = content_bbox(img)
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(img.width - 1, right + pad)
    bottom = min(img.height - 1, bottom + pad)
    crop = img.crop((left, top, right + 1, bottom + 1))
    # Cap long edge so Vite serves a light asset; CSS scales from here.
    max_edge = 640
    if max(crop.size) > max_edge:
        scale = max_edge / max(crop.size)
        crop = crop.resize(
            (max(1, int(round(crop.width * scale))),
             max(1, int(round(crop.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    crop.save(dest, format="PNG", optimize=True)
    return crop.size


def main() -> int:
    if not ICON_SRC.exists():
        print(f"missing source icon: {ICON_SRC}", file=sys.stderr)
        return 1
    if not LOGO_SRC.exists():
        print(f"missing source logo: {LOGO_SRC}", file=sys.stderr)
        return 1

    src = Image.open(ICON_SRC)
    OUT.mkdir(parents=True, exist_ok=True)

    targets = [
        ("icon-180.png", 180, False),       # apple-touch-icon
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
        ("favicon-64.png", 64, False),
    ]
    for name, size, maskable in targets:
        out = maskable_png(src, size) if maskable else square_png(src, size)
        path = OUT / name
        out.save(path, format="PNG", optimize=True)
        kind = " maskable" if maskable else ""
        print(f"  {name:24} {size}x{size}{kind}")

    lw, lh = write_lockup(LOGO_SRC, LOCKUP)
    print(f"  {LOCKUP.name:24} {lw}x{lh} lockup")
    print(f"Icons from {ICON_SRC.name}; lockup from {LOGO_SRC.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
