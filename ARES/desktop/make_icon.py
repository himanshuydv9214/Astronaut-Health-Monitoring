"""Generate the ARES application icon (assets/ares.ico + ares.png) - cyan ring and core on navy."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "assets"


def draw(size: int = 1024) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(bg).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(6, 14, 30, 255))
    img.alpha_composite(bg)
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([s * .17, s * .17, s * .83, s * .83], outline=(63, 216, 255, 200), width=int(s * .07))
    g.ellipse([s * .40, s * .40, s * .60, s * .60], fill=(63, 216, 255, 230))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.035)))
    d = ImageDraw.Draw(img)
    d.ellipse([s * .19, s * .19, s * .81, s * .81], outline=(120, 232, 255, 255), width=int(s * .045))
    d.arc([s * .29, s * .29, s * .71, s * .71], start=200, end=330, fill=(63, 216, 255, 255), width=int(s * .025))
    d.arc([s * .29, s * .29, s * .71, s * .71], start=20, end=150, fill=(59, 130, 255, 255), width=int(s * .025))
    d.ellipse([s * .43, s * .43, s * .57, s * .57], fill=(220, 250, 255, 255))
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    big = draw()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "ares.png")
    big.save(OUT / "ares.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "ares.ico", OUT / "ares.png")
