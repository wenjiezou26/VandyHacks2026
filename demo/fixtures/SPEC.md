# LetterLens — Demo Fixture Spec

All documents below are FICTIONAL demo fixtures for a hackathon. Every page must carry
"SAMPLE – NOT A REAL DOCUMENT – HACKATHON DEMO" as a top banner AND a large diagonal watermark.
No real agency seals or logos (generic colored-circle badge only), no real SSNs, no real phone numbers.

---

## Demo story (one persona, three moments)

**Persona:** Mei-ling Chen (陈美玲), age 74, lives alone in Flushing, Queens. Speaks Mandarin, reads Simplified Chinese, very little English.
Already receives SNAP. Has never heard of the Medicare Savings Program. Assumes her savings disqualify her.

1. **FIND (October 2026):** Her daughter photographs the SSA letter + bank statement →
   app finds QMB (Medicare Savings Program) + Extra Help (automatic via QMB), explains in Simplified Chinese
   that savings don't count in New York.
2. **KEEP (October 2026):** She photographs an HRA SNAP recertification notice →
   app explains the deadline in Simplified Chinese, sets a reminder, points her to the simplified senior form,
   and builds a document checklist (most items already covered by letters she uploaded).
3. **PROTECT (January 2027, after QMB approval):** She photographs a clinic bill →
   app flags the Medicare coinsurance charge as one a QMB member should not be billed for,
   but correctly does NOT flag the non-Medicare records fee. Drafts a dispute letter (English + Simplified Chinese).

---

## Fixture 1 — SSA Benefit Verification Letter (FIND)
File: `demo/fixtures/01_ssa_benefit_letter.png`
Layout: modeled on the public SSA sample Benefit Verification Letter (letterhead text, reference block, boxed benefit summary).

Expected extraction:
```json
{
  "letter_type": "ssa_benefit_letter",
  "gross_monthly_benefit": 1700.00,
  "part_b_deduction": 202.90,
  "net_payment": 1497.00,
  "effective_date": "2025-12",
  "benefit_type": "retirement",
  "date_of_birth": "1952-03-14",
  "has_medicare_part_a": true,
  "has_medicare_part_b": true
}
```

---

## Fixture 2 — Bank Statement (FIND)
File: `demo/fixtures/02_bank_statement.png`

Expected extraction:
```json
{
  "letter_type": "bank_statement",
  "total_ending_balance": 40000.00,
  "accounts": [
    {"type": "checking", "ending_balance": 1487.60},
    {"type": "savings", "ending_balance": 38512.40}
  ],
  "recurring_deposits": [{"source": "SSA", "amount": 1497.00}],
  "monthly_rent": 950.00,
  "utility_expenses": [{"payee": "CON EDISON", "amount": 68.21}],
  "medical_expenses": [{"payee": "SAMPLE PHARMACY", "amount": 42.15}]
}
```
Note: the bank deposit ($1,497.00) is NET. The engine must use the SSA letter's GROSS ($1,700.00) when both are present,
and record that the gross came from Fixture 1.

---

## Fixture 3 — HRA SNAP Recertification Notice (KEEP)
File: `demo/fixtures/03_hra_snap_recert_notice.png`

Expected extraction:
```json
{
  "letter_type": "hra_renewal_notice",
  "program": "SNAP",
  "notice_date": "2026-10-05",
  "deadline": "2026-11-10",
  "certification_end_date": "2026-11-30",
  "household_size": 1,
  "simplified_form_eligible": true,
  "simplified_form_id": "LDSS-5166",
  "interview_required": "telephone",
  "required_documents": ["proof_of_income", "proof_of_rent", "proof_of_utilities", "proof_of_medical_expenses", "proof_of_identity"]
}
```
Expected KEEP packet status (using Fixtures 1–2 already uploaded):
- proof_of_income → HAVE (SSA letter, Fixture 1)
- proof_of_rent → PARTIAL (rent payment visible on bank statement; lease or receipt still recommended)
- proof_of_utilities → MISSING (bank shows Con Edison payment; the actual bill is needed)
- proof_of_medical_expenses → PARTIAL (pharmacy charge on bank statement; receipts recommended)
- proof_of_identity → MISSING
Deadline reminder: 2026-11-10 (show days remaining).

---

## Fixture 4 — Clinic Patient Statement (PROTECT)
File: `demo/fixtures/04_clinic_bill.png`
Demo assumption: by this date the persona is enrolled in QMB (set `profile.msp_status = "QMB_ACTIVE"` in the demo seed for this step).

Expected extraction:
```json
{
  "letter_type": "medical_bill",
  "provider": "SAMPLE FAMILY CLINIC",
  "statement_date": "2027-01-15",
  "is_medicare_claim": true,
  "line_items": [
    {"date": "2026-12-18", "description": "Office visit, established patient", "billed": 180.00,
     "medicare_approved": 137.09, "medicare_paid": 109.67, "patient_amount": 27.42, "category": "coinsurance"},
    {"date": "2026-12-18", "description": "Copy of medical records", "billed": 10.00,
     "medicare_approved": null, "medicare_paid": 0.00, "patient_amount": 10.00, "category": "other"}
  ],
  "total_due": 37.42,
  "due_date": "2027-02-10"
}
```
Expected PROTECT result (persona has QMB_ACTIVE):
- FLAG line 1: $27.42 Medicare coinsurance → "As a QMB member, you should not be billed for this."
- DO NOT FLAG line 2: $10.00 records fee is not a Medicare-covered service.
- Corrected amount she may owe: $10.00 (not $37.42).
- Draft dispute letter to provider (English) + side-by-side Simplified Chinese translation.

---

## Fixture 5 — Robustness variant (different persona, different numbers)
File: `demo/fixtures/05_ssa_letter_variant.png`
Purpose: prove the pipeline reads pixels, not filenames or hardcoded values.
Same layout as Fixture 1, with:
- Name: ELENA PETROVA (SAMPLE), BNC#: SAMPLE-26X0002, DOB: July 2, 1955
- Gross benefit: $2,180.00, Part B deduction: $202.90, regular payment: $1,977.00
- Language for explanation: Russian

Expected: countable income $2,160 → QI (MSP) + Extra Help (automatic). No asset data → status notes "savings not needed in New York for MSP".

---

## Fixture 6 — HRA HEAP Notice (SNAP demo)
File: `demo/fixtures/06_hra_heap_notice.png` (photo version: `06_hra_heap_notice_photo.jpg`).
Generated by `demo/generate_snap_fixture.py`.
Purpose: show SNAP as **likely eligible**. Fixture 3 is a SNAP recertification notice, so with it on file
SNAP always shows "already enrolled". This notice lists the same household facts (lives alone, age 74, no
earned income) but is for HEAP (heating assistance), so it never marks her as already on SNAP.
The page deliberately never says "SNAP", so a real-OCR extraction can't read `program` as SNAP.

Demo: upload Fixture 1 (SSA letter) + Fixture 6 (bank statement optional; do NOT upload Fixture 3).

Expected extraction: see `expected/06_hra_heap_notice.json`.

Expected FIND result:
- Zero questions asked (household size, lives alone, and no earned income come from this notice; income + age from Fixture 1).
- SNAP → LIKELY: household gross $1,700.00/mo <= 200% FPL $2,660.00/mo (household of 1).
- With Fixture 2 uploaded too, the $40,000 savings don't change SNAP (no asset test under the 200% FPL route).
- KEEP: HEAP renewal reminder for 2026-12-15.
