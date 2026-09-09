"""Generate the app icons and splash art from the brand logo.

    .venv/bin/pip install Pillow
    .venv/bin/python scripts/make_icons.py

WHY THIS IS A SCRIPT AND NOT A ONE-OFF. The outputs are committed, so nothing
in a build depends on running it — but "how was this 1024px PNG made" is a
question that gets asked the first time the logo changes, and the honest answers
are either this file or nobody remembers. Pillow is a DEV-ONLY dependency and is
deliberately not in requirements.txt: the API never opens an image.

THE SOURCE IS THE PDF, NOT THE POSTER PNG. Voyage_Outdoor_Logo_Separate.png is a
presentation render — the mark sits on a dark vignette with a glow, and every
pixel of that background is partially opaque, so there is no clean edge to cut
on. The PDF is vector and renders to a mark on genuine transparency.

Sizes and rules come from the Expo SDK 54 docs:

  * The top-level icon must be 1024x1024, square, and carry NO transparency.
    iOS flattens an alpha channel to black, which is how an icon ends up with a
    black wedge behind the mark on someone's home screen.
  * iOS 18 takes light / dark / tinted variants. The brand guide already draws
    the first two — "APP ICON (LIGHT)" on white, "APP ICON (DARK)" on navy — so
    these are the designer's intent rather than an invention here.
  * The Android adaptive foreground is 1024x1024 but only the centre 66% is
    guaranteed visible, and the tightest mask in the wild is a circle. So the
    mark is sized to fit INSIDE that circle, not inside a 66% square: a
    1.625-aspect box inscribed in a circle of diameter D is D/1.174 wide, which
    is 576px here. Sizing to the square instead puts the V's top corners under
    the mask on a Pixel.
"""
from __future__ import annotations

import pathlib

from PIL import Image

SRC_PDF_RENDER = pathlib.Path("/tmp/vo/logo3000.png")
OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "assets"

# From the brand guide, section 5.
MOUNTAIN_NAVY = "#0B1E2D"
WHITE = "#FFFFFF"

CANVAS = 1024
#: Fraction of the canvas width the mark spans on a full-bleed icon. The guide's
#: own app-icon tiles sit around here; much larger and the mark touches the
#: corner radius, much smaller and it reads as a sticker on a tile.
ICON_MARK_W = 0.78
#: Adaptive-icon foreground: fits the circle mask, per the note above.
ADAPTIVE_MARK_W = 576 / CANVAS


def mark() -> Image.Image:
    """The V mark alone, cropped to its own ink."""
    if not SRC_PDF_RENDER.exists():
        raise SystemExit(
            f"Render the logo first:\n"
            f"  sips -s format png -Z 3000 "
            f"~/Downloads/Voyage_Outdoor_Logo_Separate.pdf --out {SRC_PDF_RENDER}")
    page = Image.open(SRC_PDF_RENDER).convert("RGBA")
    # The logo lock-up stacks mark / VOYAGE / OUTDOOR / tagline with clear gaps.
    # These bounds were found by scanning for fully transparent rows; the crop
    # below takes the first band and then tightens to the ink itself.
    band = page.crop((980, 549, 2030, 1191))
    threshold = band.getchannel("A").point(lambda v: 255 if v > 24 else 0)
    return band.crop(threshold.getbbox())


def placed(m: Image.Image, width_frac: float, bg: str | None) -> Image.Image:
    """The mark centred on a square canvas, optionally over an opaque colour."""
    w = round(CANVAS * width_frac)
    h = round(w * m.height / m.width)
    scaled = m.resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(scaled, ((CANVAS - w) // 2, (CANVAS - h) // 2), scaled)
    if bg is None:
        return canvas
    # Flatten. `convert("RGB")` here rather than leaving an all-opaque RGBA:
    # the requirement is no alpha CHANNEL, not merely no transparent pixels.
    plate = Image.new("RGBA", (CANVAS, CANVAS), bg)
    return Image.alpha_composite(plate, canvas).convert("RGB")


def tinted(m: Image.Image) -> Image.Image:
    """Grayscale on transparency, for iOS 18's tinted home screen.

    Luminance rather than a silhouette of the alpha channel. A flat cut-out
    loses the wave and the mountain ridge — the two things that distinguish this
    mark from any other letter V — whereas luminance keeps them as tonal steps
    for the system tint to colour.
    """
    grey = m.convert("L").convert("RGBA")
    grey.putalpha(m.getchannel("A"))
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    w = round(CANVAS * ICON_MARK_W)
    h = round(w * m.height / m.width)
    scaled = grey.resize((w, h), Image.LANCZOS)
    canvas.paste(scaled, ((CANVAS - w) // 2, (CANVAS - h) // 2), scaled)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    m = mark()
    print(f"mark {m.size} · aspect {m.width / m.height:.3f}")

    files = {
        # Top-level fallback and iOS dark: the guide's primary app icon.
        "icon.png":         placed(m, ICON_MARK_W, MOUNTAIN_NAVY),
        "icon-light.png":   placed(m, ICON_MARK_W, WHITE),
        "icon-tinted.png":  tinted(m),
        # Android draws its own background colour behind this.
        "adaptive-icon.png": placed(m, ADAPTIVE_MARK_W, None),
        # Splash art is the mark on transparency; the plugin supplies the
        # background per colour scheme.
        "splash-icon.png":  placed(m, 0.86, None),
        "favicon.png":      placed(m, ICON_MARK_W, MOUNTAIN_NAVY).resize(
                                (48, 48), Image.LANCZOS),
    }
    for name, image in files.items():
        path = OUT / name
        image.save(path)
        print(f"  {name:20} {image.size[0]}x{image.size[1]} {image.mode:4} "
              f"{path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
