"""Draws the app icon (bell + alert dot on the brand blue) → assets/icon.ico and assets/icon.png.
Dev-only: python scripts/make_icon.py (needs Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw

BLUE, WHITE, AMBER = (30, 64, 175), (255, 255, 255), (245, 158, 11)
S = 1024  # draw large, downscale for crisp small sizes


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=BLUE)
    # bell: dome + flared body + rim + clapper
    d.ellipse((322, 210, 702, 590), fill=WHITE)
    d.polygon([(322, 400), (702, 400), (772, 700), (252, 700)], fill=WHITE)
    d.rounded_rectangle((212, 680, 812, 760), radius=40, fill=WHITE)
    d.ellipse((442, 760, 582, 880), fill=WHITE)
    d.rounded_rectangle((482, 150, 542, 230), radius=30, fill=WHITE)
    # alert dot
    d.ellipse((650, 120, 900, 370), fill=AMBER, outline=BLUE, width=40)
    return im


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
    big.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", out / "icon.ico", out / "icon.png")
