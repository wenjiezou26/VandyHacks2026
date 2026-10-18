"""Generates the 5 demo fixture letters (+ "phone photo" variants) for the
Mei-ling Chen persona, plus the expected-extraction JSON for each, per
demo/fixtures/SPEC.md.

Every page gets a top banner and a diagonal watermark stating it is a
fictional hackathon demo document -- no real agency seal/logo is drawn
(generic colored-circle badge only), no real SSNs or phone numbers.

Run with: python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "demo" / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"

PAGE_SIZE = (1000, 1300)
MARGIN = 70
INK = (30, 30, 30)
MUTED = (90, 90, 90)
RULE = (190, 190, 190)
HEADER_FILL = (235, 235, 235)

_TRUETYPE_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = _BOLD_CANDIDATES if bold else _TRUETYPE_CANDIDATES
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


class Letter:
    """Draws one fixture page as a sequence of layout blocks."""

    def __init__(self):
        self.image = Image.new("RGB", PAGE_SIZE, "white")
        self.draw = ImageDraw.Draw(self.image)
        self.y = 60

    def letterhead(self, badge_text: str, badge_color, org_lines: list[str], ref_lines: list[str]) -> None:
        cx, cy, r = MARGIN + 36, 96, 36
        self.draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=badge_color)
        bf = _font(18, bold=True)
        bbox = self.draw.textbbox((0, 0), badge_text, font=bf)
        self.draw.text(
            (cx - (bbox[2] - bbox[0]) / 2, cy - (bbox[3] - bbox[1]) / 2 - bbox[1]),
            badge_text,
            font=bf,
            fill="white",
        )
        tx, ty = MARGIN + 90, 56
        for i, line in enumerate(org_lines):
            f = _font(28, bold=True) if i == 0 else _font(20)
            self.draw.text((tx, ty), line, font=f, fill=INK)
            ty += 36 if i == 0 else 26
        ry, rf = 56, _font(18)
        for line in ref_lines:
            w = self.draw.textlength(line, font=rf)
            self.draw.text((PAGE_SIZE[0] - MARGIN - w, ry), line, font=rf, fill=MUTED)
            ry += 24
        self.y = 160
        self.draw.line([(MARGIN, self.y), (PAGE_SIZE[0] - MARGIN, self.y)], fill=RULE, width=2)
        self.y += 22

    def address_block(self, lines: list[str]) -> None:
        f = _font(20)
        for line in lines:
            self.draw.text((MARGIN, self.y), line, font=f, fill=INK)
            self.y += 26
        self.y += 16

    def section_header(self, text: str) -> None:
        self.draw.text((MARGIN, self.y), text, font=_font(21, bold=True), fill=INK)
        self.y += 30

    def body(self, lines: list[str], color=INK, font_size=19) -> None:
        f = _font(font_size)
        for line in lines:
            self.draw.text((MARGIN, self.y), line, font=f, fill=color)
            self.y += 27
        self.y += 10

    def box(self, rows: list[tuple[str, str]], title: str | None = None, highlight_last: bool = False) -> None:
        pad = 18
        row_h = 32
        title_h = 32 if title else 0
        box_h = title_h + len(rows) * row_h + pad * 2
        x0, y0 = MARGIN, self.y
        x1 = PAGE_SIZE[0] - MARGIN
        self.draw.rectangle([x0, y0, x1, y0 + box_h], outline=RULE, width=2)
        ty = y0 + pad
        if title:
            self.draw.text((x0 + pad, ty), title, font=_font(19, bold=True), fill=INK)
            ty += title_h
        label_f = _font(18)
        value_f = _font(18, bold=True)
        for i, (label, value) in enumerate(rows):
            is_last = highlight_last and i == len(rows) - 1
            vf = _font(20, bold=True) if is_last else value_f
            self.draw.text((x0 + pad, ty), label, font=label_f, fill=MUTED)
            vw = self.draw.textlength(value, font=vf)
            self.draw.text((x1 - pad - vw, ty), value, font=vf, fill=INK)
            ty += row_h
        self.y = y0 + box_h + 22

    def table(self, headers: list[str], col_widths: list[int], rows: list[list[str]]) -> None:
        pad, line_h, row_h = 10, 18, 46
        max_header_lines = max(h.count("\n") + 1 for h in headers)
        header_h = max(34, max_header_lines * line_h + 16)
        x0, y0 = MARGIN, self.y
        x1 = x0 + sum(col_widths)
        self.draw.rectangle([x0, y0, x1, y0 + header_h], fill=HEADER_FILL, outline=RULE, width=1)
        hf = _font(15, bold=True)
        xf = x0
        for h, w in zip(headers, col_widths):
            lines = h.split("\n")
            ty = y0 + (header_h - line_h * len(lines)) / 2
            for line in lines:
                self.draw.text((xf + pad, ty), line, font=hf, fill=INK)
                ty += line_h
            xf += w
        y = y0 + header_h
        rf = _font(15)
        for row in rows:
            self.draw.rectangle([x0, y, x1, y + row_h], outline=RULE, width=1)
            xf = x0
            for cell, w in zip(row, col_widths):
                lines = cell.split("\n")
                ty = y + (row_h - 18 * len(lines)) / 2
                for line in lines:
                    self.draw.text((xf + pad, ty), line, font=rf, fill=INK)
                    ty += 18
                xf += w
            y += row_h
        xf = x0
        for w in col_widths:
            self.draw.line([(xf, y0), (xf, y)], fill=RULE, width=1)
            xf += w
        self.draw.line([(x1, y0), (x1, y)], fill=RULE, width=1)
        self.y = y + 22

    def checklist(self, items: list[str]) -> None:
        f = _font(18)
        box = 18
        for item in items:
            self.draw.rectangle([MARGIN, self.y + 3, MARGIN + box, self.y + 3 + box], outline=INK, width=2)
            self.draw.text((MARGIN + box + 12, self.y), item, font=f, fill=INK)
            self.y += 32

    def barcode_strip(self) -> None:
        rng = random.Random(42)
        x = 20
        while x < 50:
            w = rng.choice([2, 2, 4])
            self.draw.rectangle([x, 40, x + w, 240], fill="black")
            x += w + rng.choice([3, 5])

    def finish(self, name: str) -> Path:
        self.draw.rectangle([(0, 0), (PAGE_SIZE[0], 44)], fill=(190, 0, 0))
        self.draw.text(
            (MARGIN, 12),
            "SAMPLE – NOT A REAL DOCUMENT – HACKATHON DEMO",
            font=_font(18, bold=True),
            fill="white",
        )
        watermark_font = _font(120, bold=True)
        watermark = Image.new("RGBA", PAGE_SIZE, (255, 255, 255, 0))
        wm_draw = ImageDraw.Draw(watermark)
        wm_draw.text(
            (PAGE_SIZE[0] * 0.05, PAGE_SIZE[1] * 0.42),
            "SAMPLE",
            font=watermark_font,
            fill=(190, 0, 0, 55),
        )
        watermark = watermark.rotate(28, expand=False, center=(PAGE_SIZE[0] / 2, PAGE_SIZE[1] / 2))
        image = Image.alpha_composite(self.image.convert("RGBA"), watermark).convert("RGB")
        footer = Image.new("RGBA", PAGE_SIZE, (255, 255, 255, 0))
        ImageDraw.Draw(footer).text(
            (MARGIN, PAGE_SIZE[1] - 36),
            "SAMPLE – NOT A REAL DOCUMENT",
            font=_font(16, bold=True),
            fill=(190, 0, 0, 255),
        )
        image = Image.alpha_composite(image.convert("RGBA"), footer).convert("RGB")

        path = FIXTURES_DIR / f"{name}.png"
        image.save(path, "PNG")
        print(f"Wrote {path.relative_to(ROOT)}")
        make_phone_photo(image, FIXTURES_DIR / f"{name}_photo.jpg")
        return path


def make_phone_photo(image: Image.Image, dst_path: Path) -> None:
    """Slight rotation + perspective skew + soft shadow, lower JPEG quality
    -- so the demo can show "a phone photo of a letter", not a clean scan."""
    rng = random.Random(hash(dst_path.name) % (2**31))
    angle = rng.uniform(-4, 4)
    rotated = image.rotate(angle, expand=True, fillcolor="white", resample=Image.BICUBIC)

    w, h = rotated.size
    skew = rng.uniform(0.01, 0.025) * w
    coeffs = (1, skew / h, -skew / 2, 0, 1, 0)
    skewed = rotated.transform((w, h), Image.AFFINE, coeffs, fillcolor="white", resample=Image.BICUBIC)

    pad = 60
    canvas = Image.new("RGB", (w + pad * 2, h + pad * 2), (230, 230, 232))
    shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow).rectangle([pad - 10, pad - 10, pad + w + 10, pad + h + 10], fill=90)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.paste((60, 60, 65), (0, 0), shadow)
    canvas.paste(skewed, (pad, pad))

    canvas.save(dst_path, "JPEG", quality=75)
    print(f"Wrote {dst_path.relative_to(ROOT)}")


def _write_expected(name: str, data: dict) -> None:
    path = EXPECTED_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Fixture 1 -- SSA Benefit Verification Letter
# ---------------------------------------------------------------------------


def make_fixture_1() -> None:
    name = "01_ssa_benefit_letter"
    l = Letter()
    l.barcode_strip()
    l.letterhead(
        "SSA",
        (0, 90, 60),
        ["Social Security Administration", "Benefit Verification Letter"],
        ["Date: October 1, 2026", "BNC#: SAMPLE-26X0001"],
    )
    l.address_block(["MEI-LING CHEN", "123 SAMPLE AVE APT 4B", "FLUSHING NY 11354"])
    l.body(
        [
            "You asked us for information from your record. The information",
            "below is what you requested.",
        ]
    )
    l.section_header("Information About Current Social Security Benefits")
    l.box(
        [
            ("Full monthly Social Security benefit before deductions", "$1,700.00"),
            ("Medical insurance (Medicare Part B) premium deduction", "$202.90"),
            ("Regular monthly Social Security payment", "$1,497.00"),
            ("Effective", "December 2025"),
        ],
        highlight_last=False,
    )
    l.body(
        [
            "Social Security benefits for a given month are paid the following",
            "month, on or about the third of each month.",
        ],
        font_size=17,
        color=MUTED,
    )
    l.section_header("Type of Social Security Benefit Information")
    l.body(["You are entitled to monthly retirement benefits.", "Date of birth: March 14, 1952"])
    l.section_header("Medicare Information")
    l.body(
        [
            "You are entitled to hospital insurance under Medicare beginning",
            "March 2017. You are entitled to medical insurance under Medicare",
            "beginning March 2017.",
        ]
    )
    l.section_header("Information About Supplemental Security Income Payments")
    l.body(["You are not currently receiving Supplemental Security Income (SSI)."])
    l.body(["Social Security Number: XXX-XX-0000 (SAMPLE)"], font_size=17, color=MUTED)
    l.finish(name)

    _write_expected(
        name,
        {
            "letter_type": "ssa_benefit_letter",
            "gross_monthly_benefit": 1700.00,
            "part_b_deduction": 202.90,
            "net_payment": 1497.00,
            "effective_date": "2025-12-01",
            "benefit_type": "retirement",
            "date_of_birth": "1952-03-14",
            "has_medicare_part_a": True,
            "has_medicare_part_b": True,
            "receives_ssi": False,
            "recipient_name": "MEI-LING CHEN",
            "recipient_address": "123 SAMPLE AVE APT 4B, FLUSHING NY 11354",
        },
    )


# ---------------------------------------------------------------------------
# Fixture 2 -- Bank Statement
# ---------------------------------------------------------------------------


def make_fixture_2() -> None:
    name = "02_bank_statement"
    l = Letter()
    l.letterhead(
        "BK",
        (20, 60, 140),
        ["Sample Community Bank", "Monthly Statement"],
        ["Period:", "09/01/2026 – 09/30/2026"],
    )
    l.address_block(["MEI-LING CHEN", "123 SAMPLE AVE APT 4B, FLUSHING NY 11354"])
    l.section_header("Account Summary")
    l.table(
        ["Account", "Beginning", "Ending"],
        [330, 265, 265],
        [
            ["Checking  ****0000", "$1,201.50", "$1,487.60"],
            ["Savings  ****0001", "$38,509.20", "$38,512.40"],
            ["TOTAL", "", "$40,000.00"],
        ],
    )
    l.section_header("Checking Activity")
    l.table(
        ["Date", "Description", "Amount", "Balance"],
        [110, 380, 180, 190],
        [
            ["09/03", "SSA TREAS 310 XXSOC SEC\nDEPOSIT", "+1,497.00", "2,698.50"],
            ["09/05", "CHECK #1042  RENT", "-950.00", "1,748.50"],
            ["09/12", "CON EDISON  ELECTRIC", "-68.21", "1,680.29"],
            ["09/18", "SAMPLE PHARMACY", "-42.15", "1,638.14"],
            ["09/24", "SAMPLE GROCERY MART", "-150.54", "1,487.60"],
        ],
    )
    l.section_header("Savings Activity")
    l.table(["Date", "Description", "Amount", "Balance"], [110, 380, 180, 190], [["09/30", "INTEREST PAID", "+3.20", "38,512.40"]])
    l.finish(name)

    _write_expected(
        name,
        {
            "letter_type": "bank_statement",
            "total_ending_balance": 40000.00,
            "accounts": [
                {"type": "checking", "ending_balance": 1487.60},
                {"type": "savings", "ending_balance": 38512.40},
            ],
            "recurring_deposits": [{"source": "SSA", "amount": 1497.00}],
            "monthly_rent": 950.00,
            "utility_expenses": [{"payee": "CON EDISON", "amount": 68.21}],
            "medical_expenses": [{"payee": "SAMPLE PHARMACY", "amount": 42.15}],
        },
    )


# ---------------------------------------------------------------------------
# Fixture 3 -- HRA SNAP Recertification Notice
# ---------------------------------------------------------------------------


def make_fixture_3() -> None:
    name = "03_hra_snap_recert_notice"
    l = Letter()
    l.letterhead(
        "HRA",
        (150, 90, 0),
        ["NYC Human Resources Administration (SAMPLE)", "SNAP: Time to Recertify"],
        ["Notice Date:", "October 5, 2026"],
    )
    l.box(
        [
            ("Case Name", "MEI-LING CHEN"),
            ("Case Number", "SAMPLE-000000"),
            ("Household Size", "1"),
        ]
    )
    l.section_header("Household Members")
    l.table(
        ["Name", "Age", "Relationship"],
        [400, 130, 330],
        [["MEI-LING CHEN", "74", "Head of Household"]],
    )
    l.body(["Programs on this case: SNAP"])
    l.body(["Your current SNAP certification period ends on NOVEMBER 30, 2026."])
    l.draw.text((MARGIN, l.y), "Due: NOVEMBER 10, 2026", font=_font(23, bold=True), fill=(150, 0, 0))
    l.y += 40
    l.body(
        [
            "To keep getting SNAP without interruption, submit your",
            "recertification form by the due date above.",
        ]
    )
    l.body(
        [
            "Because everyone in your household is age 60 or older and no one",
            "has earned income, you may use the Simplified SNAP",
            "Application/Recertification Form (LDSS-5166).",
        ]
    )
    l.body(["After you submit your form, you must complete a telephone interview."], font_size=17, color=MUTED)
    l.section_header("Send copies of these documents with your form:")
    l.checklist(
        [
            "Proof of income (for example, Social Security benefit letter)",
            "Proof of rent (lease or rent receipt)",
            "Proof of utility costs (for example, electric bill)",
            "Proof of medical expenses (60+ household members may deduct these)",
            "Proof of identity",
        ]
    )
    l.finish(name)

    _write_expected(
        name,
        {
            "letter_type": "hra_renewal_notice",
            "program": "SNAP",
            "notice_date": "2026-10-05",
            "deadline": "2026-11-10",
            "certification_end_date": "2026-11-30",
            "household_size": 1,
            "household_members": [{"name": "MEI-LING CHEN", "age": 74, "relationship": "head_of_household"}],
            "programs_on_case": ["SNAP"],
            "household_has_earned_income": False,
            "simplified_form_eligible": True,
            "simplified_form_id": "LDSS-5166",
            "interview_required": "telephone",
            "required_documents": [
                "proof_of_income",
                "proof_of_rent",
                "proof_of_utilities",
                "proof_of_medical_expenses",
                "proof_of_identity",
            ],
        },
    )


# ---------------------------------------------------------------------------
# Fixture 4 -- Clinic Patient Statement
# ---------------------------------------------------------------------------


def make_fixture_4() -> None:
    name = "04_clinic_bill"
    l = Letter()
    l.letterhead(
        "QGH",
        (0, 80, 160),
        ["Sample Family Clinic", "Patient Statement"],
        ["Statement Date:", "January 15, 2027"],
    )
    l.address_block(
        [
            "Patient: MEI-LING CHEN",
            "Account #: SAMPLE-ACCT-7781",
            "Insurance on file: Medicare Part B   Medicare #: SAMPLE-MBI-0000",
        ]
    )
    l.section_header("Your Claims & Costs This Period")
    l.table(
        ["Date", "Service", "Billed", "Medicare\nApproved", "Medicare\nPaid", "You Owe"],
        [100, 260, 110, 130, 120, 140],
        [
            ["12/18/2026", "Office visit,\nestablished patient", "$180.00", "$137.09", "$109.67", "$27.42\n(coinsurance)"],
            ["12/18/2026", "Copy of medical\nrecords (requested)", "$10.00", "Not a Medicare\nservice", "$0.00", "$10.00"],
        ],
    )
    l.box([("TOTAL BALANCE DUE", "$37.42")])
    l.body(["Please pay by February 10, 2027."], font_size=17, color=MUTED)
    l.finish(name)

    _write_expected(
        name,
        {
            "letter_type": "medical_bill",
            "provider": "SAMPLE FAMILY CLINIC",
            "statement_date": "2027-01-15",
            "is_medicare_claim": True,
            "line_items": [
                {
                    "service_date": "2026-12-18",
                    "description": "Office visit, established patient",
                    "billed": 180.00,
                    "medicare_approved": 137.09,
                    "medicare_paid": 109.67,
                    "patient_amount": 27.42,
                    "category": "coinsurance",
                },
                {
                    "service_date": "2026-12-18",
                    "description": "Copy of medical records",
                    "billed": 10.00,
                    "medicare_approved": None,
                    "medicare_paid": 0.00,
                    "patient_amount": 10.00,
                    "category": "other",
                },
            ],
            "total_due": 37.42,
            "due_date": "2027-02-10",
        },
    )


# ---------------------------------------------------------------------------
# Fixture 5 -- Robustness variant (different persona/numbers/layout reuse)
# ---------------------------------------------------------------------------


def make_fixture_5() -> None:
    name = "05_ssa_letter_variant"
    l = Letter()
    l.barcode_strip()
    l.letterhead(
        "SSA",
        (0, 90, 60),
        ["Social Security Administration", "Benefit Verification Letter"],
        ["Date: October 1, 2026", "BNC#: SAMPLE-26X0002"],
    )
    l.address_block(["ELENA PETROVA", "456 SAMPLE ST APT 2C", "BROOKLYN NY 11223"])
    l.body(
        [
            "You asked us for information from your record. The information",
            "below is what you requested.",
        ]
    )
    l.section_header("Information About Current Social Security Benefits")
    l.box(
        [
            ("Full monthly Social Security benefit before deductions", "$2,180.00"),
            ("Medical insurance (Medicare Part B) premium deduction", "$202.90"),
            ("Regular monthly Social Security payment", "$1,977.00"),
            ("Effective", "December 2025"),
        ]
    )
    l.section_header("Type of Social Security Benefit Information")
    l.body(["You are entitled to monthly retirement benefits.", "Date of birth: July 2, 1955"])
    l.section_header("Medicare Information")
    l.body(["You are entitled to hospital and medical insurance under Medicare."])
    l.body(["Social Security Number: XXX-XX-0000 (SAMPLE)"], font_size=17, color=MUTED)
    l.finish(name)

    _write_expected(
        name,
        {
            "letter_type": "ssa_benefit_letter",
            "gross_monthly_benefit": 2180.00,
            "part_b_deduction": 202.90,
            "net_payment": 1977.00,
            "effective_date": "2025-12-01",
            "benefit_type": "retirement",
            "date_of_birth": "1955-07-02",
            "has_medicare_part_a": True,
            "has_medicare_part_b": True,
            "recipient_name": "ELENA PETROVA",
            "recipient_address": "456 SAMPLE ST APT 2C, BROOKLYN NY 11223",
        },
    )


# ---------------------------------------------------------------------------
# Fixture 7 -- Income too high: a "not likely right now" result
# ---------------------------------------------------------------------------


def make_fixture_7() -> None:
    """Same layout as fixture 5, but $3,150/month: over the QI limit, the
    Extra Help limit and (living alone) SNAP's -- so the demo can show
    what "not likely right now" looks like."""
    name = "07_ssa_letter_high_income"
    l = Letter()
    l.barcode_strip()
    l.letterhead(
        "SSA",
        (0, 90, 60),
        ["Social Security Administration", "Benefit Verification Letter"],
        ["Date: October 1, 2026", "BNC#: SAMPLE-26X0007"],
    )
    l.address_block(["ZHANG WEI", "789 SAMPLE BLVD APT 6F", "FLUSHING NY 11354"])
    l.body(
        [
            "You asked us for information from your record. The information",
            "below is what you requested.",
        ]
    )
    l.section_header("Information About Current Social Security Benefits")
    l.box(
        [
            ("Full monthly Social Security benefit before deductions", "$3,150.00"),
            ("Medical insurance (Medicare Part B) premium deduction", "$202.90"),
            ("Regular monthly Social Security payment", "$2,947.10"),
            ("Effective", "December 2025"),
        ]
    )
    l.section_header("Type of Social Security Benefit Information")
    l.body(["You are entitled to monthly retirement benefits.", "Date of birth: May 20, 1951"])
    l.section_header("Medicare Information")
    l.body(["You are entitled to hospital and medical insurance under Medicare."])
    l.body(["Social Security Number: XXX-XX-0000 (SAMPLE)"], font_size=17, color=MUTED)
    l.finish(name)

    _write_expected(
        name,
        {
            "letter_type": "ssa_benefit_letter",
            "gross_monthly_benefit": 3150.00,
            "part_b_deduction": 202.90,
            "net_payment": 2947.10,
            "effective_date": "2025-12-01",
            "benefit_type": "retirement",
            "date_of_birth": "1951-05-20",
            "has_medicare_part_a": True,
            "has_medicare_part_b": True,
            "recipient_name": "ZHANG WEI",
            "recipient_address": "789 SAMPLE BLVD APT 6F, FLUSHING NY 11354",
        },
    )


FIXTURES = {
    "1": lambda: make_fixture_1(),
    "2": lambda: make_fixture_2(),
    "3": lambda: make_fixture_3(),
    "4": lambda: make_fixture_4(),
    "5": lambda: make_fixture_5(),
    "7": lambda: make_fixture_7(),
}


def main() -> None:
    """All fixtures, or only the numbers given (python scripts/make_fixtures.py 7)
    -- regenerating one never rewrites the others' images."""
    import sys

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    for number in sys.argv[1:] or list(FIXTURES):
        FIXTURES[number]()


if __name__ == "__main__":
    main()
