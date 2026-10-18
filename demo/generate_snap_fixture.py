"""Generates fixture 6 (demo/fixtures/06_hra_heap_notice.png): an HRA HEAP
(heating assistance) notice for the Mei-ling Chen persona.

Why it exists: fixture 3 is a SNAP recertification notice, so with it on
file SNAP always shows "already enrolled". This notice states the same
household facts (lives alone, age 74, no earned income) but is for HEAP,
not SNAP -- so SSA letter (fixture 1) + this notice shows SNAP as "likely",
with no questions asked. See demo/fixtures/SPEC.md, Fixture 6.

Same visual conventions as fixtures 1-5: red SAMPLE banner and footer,
diagonal watermark, generic colored badge (no real agency mark).

Run with: python demo/generate_snap_fixture.py
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

W, H = 1000, 1300
MARGIN = 70
INK = (30, 30, 30)
MUTED = (90, 90, 90)
RULE = (190, 190, 190)
RED = (190, 0, 0)
HRA_BROWN = (150, 90, 0)

_REGULAR = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
_BOLD = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _BOLD if bold else _REGULAR:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_heap_notice() -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Banner
    d.rectangle([0, 0, W, 44], fill=RED)
    d.text((MARGIN, 11), "SAMPLE – NOT A REAL DOCUMENT – HACKATHON DEMO", font=_font(19, True), fill="white")

    # Letterhead
    cx, cy, r = MARGIN + 36, 96, 36
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=HRA_BROWN)
    bf = _font(19, True)
    bw = d.textlength("HRA", font=bf)
    d.text((cx - bw / 2, cy - 11), "HRA", font=bf, fill="white")
    d.text((MARGIN + 90, 56), "NYC Human Resources Administration (SAMPLE)", font=_font(27, True), fill=INK)
    d.text((MARGIN + 90, 94), "HEAP: Home Energy Assistance Program", font=_font(20), fill=INK)
    for i, line in enumerate(["Notice Date:", "October 5, 2026"]):
        lw = d.textlength(line, font=_font(18))
        d.text((W - MARGIN - lw, 124 + i * 22), line, font=_font(18), fill=MUTED)
    d.line([(MARGIN, 170), (W - MARGIN, 170)], fill=RULE, width=2)

    # Case box
    y = 192
    d.rectangle([MARGIN, y, W - MARGIN, y + 132], outline=RULE, width=2)
    for i, (label, value) in enumerate(
        [("Case Name", "MEI-LING CHEN"), ("Case Number", "SAMPLE-000000"), ("Household Size", "1")]
    ):
        ry = y + 20 + i * 32
        d.text((MARGIN + 18, ry), label, font=_font(18), fill=MUTED)
        vf = _font(18, True)
        d.text((W - MARGIN - 18 - d.textlength(value, font=vf), ry), value, font=vf, fill=INK)

    # Household members table
    y = 348
    d.text((MARGIN, y), "Household Members", font=_font(20, True), fill=INK)
    y += 36
    cols = [MARGIN, 470, 600, W - MARGIN]
    d.rectangle([MARGIN, y, W - MARGIN, y + 34], fill=(236, 236, 236), outline=RULE)
    for x, head in zip(cols, ["Name", "Age", "Relationship"]):
        d.text((x + 10, y + 8), head, font=_font(15, True), fill=INK)
    d.rectangle([MARGIN, y + 34, W - MARGIN, y + 80], outline=RULE)
    for x, cell in zip(cols, ["MEI-LING CHEN", "74", "Head of Household"]):
        d.text((x + 10, y + 48), cell, font=_font(15), fill=INK)
    for x in cols[1:-1]:
        d.line([(x, y), (x, y + 80)], fill=RULE)

    # Body
    y += 112
    body = _font(19)

    def para(lines: list[str], font=body, fill=INK, gap: int = 10) -> None:
        nonlocal y
        for line in lines:
            d.text((MARGIN, y), line, font=font, fill=fill)
            y += 27
        y += gap

    para(["Programs on this case: HEAP"])
    para(
        [
            "Your HEAP Regular Benefit of $50.00 for the 2025–2026 heating",
            "season was paid to your utility, CON EDISON.",
        ]
    )
    para(
        [
            "Income we used: Social Security only. No one in your",
            "household has earned income (wages or self-employment).",
        ]
    )

    d.text((MARGIN, y), "Renew by: DECEMBER 15, 2026", font=_font(22, True), fill=(160, 0, 0))
    y += 42
    para(
        [
            "To get HEAP for the 2026–2027 heating season, return the",
            "renewal form by the date above.",
        ]
    )
    para(
        [
            "This notice is about HEAP only. It is not a decision about",
            "food benefits or Medicaid. You may apply for those",
            "programs separately.",
        ],
        gap=16,
    )

    d.text((MARGIN, y), "Send copies of these documents with your form:", font=_font(20, True), fill=INK)
    y += 34
    for item in [
        "Proof of income (for example, Social Security benefit letter)",
        "Proof of identity",
        "Proof of utility costs (for example, Con Edison bill)",
    ]:
        d.rectangle([MARGIN, y + 3, MARGIN + 18, y + 21], outline=INK, width=2)
        d.text((MARGIN + 30, y), item, font=_font(18), fill=INK)
        y += 32

    d.text((MARGIN, H - 44), "SAMPLE – NOT A REAL DOCUMENT", font=_font(16, True), fill=RED)

    # Diagonal watermark
    wm = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    ImageDraw.Draw(wm).text((W * 0.08, H * 0.40), "SAMPLE", font=_font(150, True), fill=(200, 0, 0, 60))
    wm = wm.rotate(35, center=(W / 2, H / 2))
    return Image.alpha_composite(img.convert("RGBA"), wm).convert("RGB")


def make_photo(page: Image.Image) -> Image.Image:
    """A phone-photo-looking copy: page on a table, slight tilt, warm light, blur, noise."""
    rng = random.Random(6)
    bg = Image.new("RGB", (1200, 1500), (120, 104, 88))
    tilted = page.rotate(-2.2, expand=True, fillcolor=(120, 104, 88), resample=Image.BICUBIC)
    bg.paste(tilted, (70, 60))
    shade = Image.new("RGB", bg.size, (255, 236, 205))
    photo = Image.blend(bg, shade, 0.12).filter(ImageFilter.GaussianBlur(0.8))
    px = photo.load()
    for _ in range(40000):
        x, y = rng.randrange(photo.width), rng.randrange(photo.height)
        r, g, b = px[x, y]
        n = rng.randint(-14, 14)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return photo


def main() -> None:
    page = make_heap_notice()
    page.save(FIXTURES_DIR / "06_hra_heap_notice.png")
    make_photo(page).save(FIXTURES_DIR / "06_hra_heap_notice_photo.jpg", quality=88)
    print("Wrote 06_hra_heap_notice.png and 06_hra_heap_notice_photo.jpg")


if __name__ == "__main__":
    main()
