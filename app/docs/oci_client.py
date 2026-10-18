"""OCI Document Understanding + GenAI calls, with an offline MOCK_MODE.

MOCK_MODE=true is the default and the only path exercised by the test
suite -- zero network calls, fully deterministic. When MOCK_MODE=false,
every call below attempts real OCI first; mock is only ever reached as a
fallback if that fails (see app.trace.call_with_fallback), and that
fallback is recorded on the request's trace so the UI can show it was
used, not hide it. The real-mode functions follow the OCI Python SDK's
documented shapes but are unverified against a live tenancy -- treat
them as a skeleton to wire up with real OCI credentials, not a tested
path.

The LLM is only ever asked to classify, extract, or explain -- never to
decide eligibility. See app/rules/engine.py for the decision logic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.i18n import document_name_zh
from app.number_guard import assert_numbers_preserved, format_dollar_amounts
from app.oci_genai import genai_chat, language_name, oci_config, parse_json_object, plain_text
from app.trace import call_real_or_sample, call_with_fallback

from .schemas import SCHEMA_BY_TYPE, LetterType


@dataclass
class OcrResult:
    raw_text: str
    key_values: dict


# ---------------------------------------------------------------------------
# Mock mode: deterministic canned responses so the demo works offline.
# ---------------------------------------------------------------------------

# The 5 demo fixtures (demo/fixtures/SPEC.md, Mei-ling Chen persona) each
# need their own distinct canned OCR text/fields -- a plain "ssa"/"bank"
# keyword match can't tell fixture 1 and fixture 5 apart (both are SSA
# letters). Checked by filename stem before the generic keyword fallback
# below, which stays for backward compatibility with older test fixtures.
_FIXTURE_TEXT_BY_STEM = {
    "01_ssa_benefit_letter": (
        "Social Security Administration\n"
        "MEI-LING CHEN\n"
        "123 SAMPLE AVE APT 4B, FLUSHING NY 11354\n"
        "Your monthly benefit amount is $1,700.00.\n"
        "Medicare Part B premium deduction: $202.90.\n"
        "Your net payment is $1,497.00.\n"
        "Date of birth: 1952-03-14.\n"
        "This change is effective 2025-12-01.\n"
        "Information About Supplemental Security Income Payments: "
        "You are not currently receiving Supplemental Security Income (SSI)."
    ),
    "02_bank_statement": (
        "Sample Community Bank Monthly Statement\n"
        "MEI-LING CHEN\n"
        "Ending balance: $40,000.00\n"
        "Recurring deposit: SSA TREAS 310 $1,497.00\n"
        "Rent payment: $950.00\n"
        "Con Edison electric: $68.21\n"
        "Sample Pharmacy: $42.15"
    ),
    "03_hra_snap_recert_notice": (
        "NYC Human Resources Administration\n"
        "SNAP Recertification Notice\n"
        "MEI-LING CHEN\n"
        "Household size: 1\n"
        "Household Members: MEI-LING CHEN, age 74, Head of Household\n"
        "Programs on this case: SNAP\n"
        "Your SNAP case must be recertified by 2026-11-10.\n"
        "Certification ends 2026-11-30.\n"
        "Because everyone in your household is age 60 or older and no one "
        "has earned income, you may use the Simplified SNAP Application/"
        "Recertification Form (LDSS-5166).\n"
        "Please submit: proof of income, proof of rent, proof of utilities, "
        "proof of medical expenses, proof of identity."
    ),
    "06_hra_heap_notice": (
        "NYC Human Resources Administration\n"
        "HEAP: Home Energy Assistance Program\n"
        "MEI-LING CHEN\n"
        "Household size: 1\n"
        "Household Members: MEI-LING CHEN, age 74, Head of Household\n"
        "Programs on this case: HEAP\n"
        "Income we used: Social Security only. No one in your household "
        "has earned income (wages or self-employment).\n"
        "Renew by 2026-12-15.\n"
        "This notice is about HEAP only. It is not a decision about food "
        "benefits or Medicaid.\n"
        "Please submit: proof of income, proof of identity, proof of utilities."
    ),
    "04_clinic_bill": (
        "Sample Family Clinic Patient Statement\n"
        "Provider: SAMPLE FAMILY CLINIC\n"
        "Patient: MEI-LING CHEN\n"
        "This is a Medicare claim.\n"
        "Line item: Office visit coinsurance $27.42 (coinsurance)\n"
        "Line item: Copy of medical records $10.00 (other, not a Medicare service)"
    ),
    "05_ssa_letter_variant": (
        "Social Security Administration\n"
        "ELENA PETROVA\n"
        "456 SAMPLE ST APT 2C, BROOKLYN NY 11223\n"
        "Your monthly benefit amount is $2,180.00.\n"
        "Medicare Part B premium deduction: $202.90.\n"
        "Your net payment is $1,977.00.\n"
        "Date of birth: 1955-07-02.\n"
        "This change is effective 2025-12-01."
    ),
    "07_ssa_letter_high_income": (
        "Social Security Administration\n"
        "ZHANG WEI\n"
        "789 SAMPLE BLVD APT 6F, FLUSHING NY 11354\n"
        "Your monthly benefit amount is $3,150.00.\n"
        "Medicare Part B premium deduction: $202.90.\n"
        "Your net payment is $2,947.10.\n"
        "Date of birth: 1951-05-20.\n"
        "This change is effective 2025-12-01."
    ),
}

_FIXTURE_EXTRACT_BY_STEM = {
    "01_ssa_benefit_letter": {
        "gross_monthly_benefit": 1700.00,
        "part_b_deduction": 202.90,
        "net_payment": 1497.00,
        "effective_date": "2025-12-01",
        "recipient_name": "MEI-LING CHEN",
        "recipient_address": "123 SAMPLE AVE APT 4B, FLUSHING NY 11354",
        "date_of_birth": "1952-03-14",
        "receives_ssi": False,
    },
    "02_bank_statement": {
        "ending_balance": 40000.00,
        "recurring_deposits": [{"description": "SSA TREAS 310", "amount": 1497.00}],
        "monthly_rent": 950.00,
        "utility_expenses": [{"description": "CON EDISON", "amount": 68.21}],
        "medical_expenses": [{"description": "SAMPLE PHARMACY", "amount": 42.15}],
    },
    "03_hra_snap_recert_notice": {
        "program": "SNAP",
        "deadline": "2026-11-10",
        "notice_date": "2026-10-05",
        "certification_end_date": "2026-11-30",
        "household_size": 1,
        "household_members": [{"name": "MEI-LING CHEN", "age": 74, "relationship": "head_of_household"}],
        "programs_on_case": ["SNAP"],
        "household_has_earned_income": False,
        "simplified_form_eligible": True,
        "simplified_form_id": "LDSS-5166",
        "interview_required": "telephone",
        "required_documents": [
            "proof of income",
            "proof of rent",
            "proof of utilities",
            "proof of medical expenses",
            "proof of identity",
        ],
    },
    # Fixture 6: same household facts as fixture 3, but for HEAP -- so it
    # never marks her as already on SNAP (see demo/fixtures/SPEC.md).
    "06_hra_heap_notice": {
        "program": "HEAP",
        "deadline": "2026-12-15",
        "notice_date": "2026-10-05",
        "household_size": 1,
        "household_members": [{"name": "MEI-LING CHEN", "age": 74, "relationship": "head_of_household"}],
        "programs_on_case": ["HEAP"],
        "household_has_earned_income": False,
        "required_documents": ["proof of income", "proof of identity", "proof of utilities"],
    },
    "04_clinic_bill": {
        "provider": "SAMPLE FAMILY CLINIC",
        "line_items": [
            {
                "description": "Office visit, established patient",
                "amount": 27.42,
                "category": "coinsurance",
                "service_date": "2026-12-18",
                "billed": 180.00,
                "medicare_approved": 137.09,
                "medicare_paid": 109.67,
            },
            {
                "description": "Copy of medical records",
                "amount": 10.00,
                "category": "other",
                "service_date": "2026-12-18",
                "billed": 10.00,
                "medicare_paid": 0.00,
            },
        ],
        "is_medicare_claim": True,
    },
    "05_ssa_letter_variant": {
        "gross_monthly_benefit": 2180.00,
        "part_b_deduction": 202.90,
        "net_payment": 1977.00,
        "effective_date": "2025-12-01",
        "recipient_name": "ELENA PETROVA",
        "recipient_address": "456 SAMPLE ST APT 2C, BROOKLYN NY 11223",
        "date_of_birth": "1955-07-02",
    },
    # Fixture 7: income over every limit -- the "not likely right now" demo.
    "07_ssa_letter_high_income": {
        "gross_monthly_benefit": 3150.00,
        "part_b_deduction": 202.90,
        "net_payment": 2947.10,
        "effective_date": "2025-12-01",
        "recipient_name": "ZHANG WEI",
        "recipient_address": "789 SAMPLE BLVD APT 6F, FLUSHING NY 11354",
        "date_of_birth": "1951-05-20",
    },
}

_MOCK_TEXT_BY_FILENAME_KEYWORD = {
    "ssa": (
        "Social Security Administration\n"
        "Chen, Yu-lan\n"
        "123 Northern Blvd, Apt 4B, Flushing, NY 11354\n"
        "Your monthly benefit amount is $1,700.00.\n"
        "Medicare Part B premium deduction: $202.90.\n"
        "Your net payment is $1,497.10.\n"
        "This change is effective 2026-01-01."
    ),
    "bank": (
        "Chase Checking Statement\n"
        "Ending balance: $40,000.00\n"
        "Recurring deposit: SSA TREAS 310 $1,700.00"
    ),
    "hra": (
        "HRA Human Resources Administration\n"
        "SNAP Recertification Notice\n"
        "Your SNAP case must be recertified by 2026-11-15.\n"
        "Please submit: proof of income, proof of residence, ID."
    ),
    "bill": (
        "Queens General Medical Billing\n"
        "Provider: Queens General Hospital\n"
        "Line item: Annual wellness visit copay $20.00 (copay)\n"
        "This is a Medicare claim."
    ),
    "stub": (
        "Sample Grocery Mart\n"
        "Earnings Statement -- Pay Stub\n"
        "Chen, Yu-lan\n"
        "Gross pay this period: $350.00\n"
        "Pay period: weekly"
    ),
}


def _mock_ocr(filename: str) -> OcrResult:
    key = filename.lower()
    for stem, text in _FIXTURE_TEXT_BY_STEM.items():
        if stem in key:
            return OcrResult(raw_text=text, key_values={})
    for keyword, text in _MOCK_TEXT_BY_FILENAME_KEYWORD.items():
        if keyword in key:
            return OcrResult(raw_text=text, key_values={})
    return OcrResult(raw_text="(unrecognized sample document)", key_values={})


def _mock_classify(raw_text: str) -> LetterType:
    text = raw_text.lower()
    if "social security administration" in text or "benefit amount" in text:
        return LetterType.SSA_BENEFIT_LETTER
    if "ending balance" in text:
        return LetterType.BANK_STATEMENT
    if "recertif" in text or "snap" in text or "human resources administration" in text:
        return LetterType.HRA_RENEWAL_NOTICE
    if "medicare claim" in text or "provider:" in text:
        return LetterType.MEDICAL_BILL
    if "medicare" in text and "notice" in text:
        return LetterType.MEDICARE_NOTICE
    if "pay stub" in text or "earnings statement" in text or "gross pay" in text:
        return LetterType.PAY_STUB
    return LetterType.OTHER


_FIXTURE_EXTRACT_BY_RAW_TEXT = {
    text: _FIXTURE_EXTRACT_BY_STEM[stem] for stem, text in _FIXTURE_TEXT_BY_STEM.items()
}


def _mock_extract(letter_type: LetterType, raw_text: str) -> dict:
    if raw_text in _FIXTURE_EXTRACT_BY_RAW_TEXT:
        return _FIXTURE_EXTRACT_BY_RAW_TEXT[raw_text]
    if letter_type == LetterType.SSA_BENEFIT_LETTER:
        return {
            "gross_monthly_benefit": 1700.00,
            "part_b_deduction": 202.90,
            "net_payment": 1497.10,
            "effective_date": "2026-01-01",
            "recipient_name": "Chen, Yu-lan",
            "recipient_address": "123 Northern Blvd, Apt 4B, Flushing, NY 11354",
        }
    if letter_type == LetterType.BANK_STATEMENT:
        return {
            "ending_balance": 40000.00,
            "recurring_deposits": [{"description": "SSA TREAS 310", "amount": 1700.00}],
        }
    if letter_type == LetterType.HRA_RENEWAL_NOTICE:
        return {
            "program": "SNAP",
            "deadline": "2026-11-15",
            "required_documents": ["proof of income", "proof of residence", "ID"],
        }
    if letter_type == LetterType.MEDICAL_BILL:
        return {
            "provider": "Queens General Hospital",
            "line_items": [
                {"description": "Annual wellness visit copay", "amount": 20.00, "category": "copay"}
            ],
            "is_medicare_claim": True,
        }
    if letter_type == LetterType.PAY_STUB:
        return {"employer": "Sample Grocery Mart", "gross_pay": 350.00, "pay_period": "weekly"}
    return {"summary": raw_text[:200]}


def _mock_explain_zh(letter_type: LetterType, fields: dict) -> str:
    # Hand-written Chinese templates for the offline demo; every number is
    # copied from the extracted fields, never retyped.
    if letter_type == LetterType.SSA_BENEFIT_LETTER:
        return (
            f"社会安全局 (Social Security) 每月给您 ${fields['gross_monthly_benefit']:,.2f}。"
            f"其中 ${fields['part_b_deduction']:,.2f} 被扣去交医疗保险 B 部分 (Medicare Part B) 的保费。"
            f"从 {fields['effective_date']} 起，您实际到账 ${fields['net_payment']:,.2f}。"
        )
    if letter_type == LetterType.BANK_STATEMENT:
        return (
            f"您的账户余额是 ${fields['ending_balance']:,.2f}。"
            "在纽约州，这些存款不会影响您申请医疗保险储蓄计划 (Medicare Savings Program, MSP)。"
        )
    if letter_type == LetterType.HRA_RENEWAL_NOTICE:
        docs = "、".join(document_name_zh(d) for d in fields.get("required_documents", []))
        return f"您的 {fields['program']} 福利需要在 {fields['deadline']} 之前续期。请提交：{docs}。"
    if letter_type == LetterType.MEDICAL_BILL:
        return (
            f"{fields['provider']} 给您寄来了一张账单。"
            "如果这是医疗保险 (Medicare) 的收费，而您有 QMB，您可能依法不用付这笔钱。"
        )
    if letter_type == LetterType.PAY_STUB:
        return f"这张工资单显示您每期（{fields['pay_period']}）的税前工资是 ${fields['gross_pay']:,.2f}。我们用它计算您每月的工作收入。"
    return "这封信的类型我们还不认识。请拿给社工看看。"


def _mock_explain(letter_type: LetterType, fields: dict, language: str) -> str:
    if language.lower() in ("zh", "chinese"):
        return _mock_explain_zh(letter_type, fields)
    note = (
        ""
        if language.lower() in ("en", "english")
        else f" [MOCK_MODE: shown in English, not translated to {language}]"
    )
    if letter_type == LetterType.SSA_BENEFIT_LETTER:
        return (
            f"Your Social Security gives you ${fields['gross_monthly_benefit']:,.2f} a month. "
            f"Medicare takes ${fields['part_b_deduction']:,.2f} for Part B. "
            f"You get ${fields['net_payment']:,.2f} deposited, starting {fields['effective_date']}."
            + note
        )
    if letter_type == LetterType.BANK_STATEMENT:
        return (
            f"Your account balance is ${fields['ending_balance']:,.2f}. "
            "In New York, savings like this don't count for the Medicare Savings Program (MSP)."
            + note
        )
    if letter_type == LetterType.HRA_RENEWAL_NOTICE:
        docs = ", ".join(fields.get("required_documents", []))
        return (
            f"Your {fields['program']} benefits need to be renewed by {fields['deadline']}. "
            f"Please send: {docs}."
            + note
        )
    if letter_type == LetterType.MEDICAL_BILL:
        return (
            f"{fields['provider']} sent you a bill. "
            "If this is a Medicare charge and you have QMB, you may not legally owe it -- "
            "check the Protect tab."
            + note
        )
    if letter_type == LetterType.PAY_STUB:
        return (
            f"This pay stub shows ${fields['gross_pay']:,.2f} gross pay per {fields['pay_period']} period. "
            "We used it to work out your monthly work income."
        ) + note
    return "This letter doesn't match a known type yet. Please show it to a caseworker." + note


# ---------------------------------------------------------------------------
# Real mode: OCI Document Understanding + Generative AI (untested skeleton).
# ---------------------------------------------------------------------------


def _real_ocr(image_bytes: bytes) -> OcrResult:
    import base64

    import oci
    from oci.ai_document.models import AnalyzeDocumentDetails, DocumentTextExtractionFeature, InlineDocumentDetails

    client = oci.ai_document.AIServiceDocumentClient(oci_config(), timeout=(10, 60))
    # Text extraction only: key-value extraction is limited to specific
    # document types (receipts, invoices, IDs), not general letters --
    # GenAI does the field extraction from the text instead.
    details = AnalyzeDocumentDetails(
        document=InlineDocumentDetails(data=base64.b64encode(image_bytes).decode("utf-8")),
        compartment_id=os.environ["OCI_COMPARTMENT_ID"],
        features=[DocumentTextExtractionFeature()],
    )
    response = client.analyze_document(analyze_document_details=details)
    pages = response.data.pages or []
    raw_text = "\n".join(line.text for page in pages for line in (page.lines or []) if line.text)
    if not raw_text.strip():
        raise RuntimeError("OCI Document Understanding found no text in the image")
    return OcrResult(raw_text=raw_text, key_values={})


def _real_classify(raw_text: str) -> LetterType:
    labels = [t.value for t in LetterType]
    prompt = (
        "Classify this letter into exactly one label: " + ", ".join(labels) + ". "
        "Reply with only the label.\n\nLetter text:\n" + raw_text
    )
    reply = genai_chat(prompt).strip().lower()
    # Tolerate "ssa_benefit_letter.", quotes, or a short sentence around it.
    for label in sorted(labels, key=len, reverse=True):
        if label in reply:
            return LetterType(label)
    return LetterType.OTHER


def _real_extract(letter_type: LetterType, raw_text: str, key_values: dict, retry_after_invalid: bool) -> dict:
    schema = SCHEMA_BY_TYPE[letter_type]
    instruction = (
        "Your previous answer was not valid JSON for this schema -- reply with ONLY corrected JSON. "
        if retry_after_invalid
        else ""
    )
    prompt = (
        f"{instruction}Extract fields as a JSON object only, matching this JSON schema: "
        f"{json.dumps(schema.model_json_schema())}. Use numbers (no $ or commas) for amounts and "
        "YYYY-MM-DD for dates. Ignore watermarks, stamps, barcodes and page headers/footers. "
        "Do not invent values not present in the text; use null for "
        f"optional fields you can't find.\n\nLetter text:\n{raw_text}"
    )
    return parse_json_object(genai_chat(prompt, json_mode=True))


def _dollars(value):
    """Every float in a letter's fields is a dollar amount (see schemas);
    give the model "$40,000.00", not 40000.0, so it copies that form."""
    if isinstance(value, float):
        return f"${value:,.2f}"
    if isinstance(value, dict):
        return {k: _dollars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dollars(v) for v in value]
    return value


def _real_explain(letter_type: LetterType, fields: dict, language: str) -> str:
    source_text = json.dumps(_dollars(fields), ensure_ascii=False)
    prompt = (
        f"Explain this {letter_type.value.replace('_', ' ')} to an older adult reading at a 6th-grade level, "
        f"in {language_name(language)}, in 2-4 short sentences of plain text (no markdown). Copy every number, date and dollar amount "
        "exactly as given (write dollar amounts like $1,234.56) and add no other numbers; keep official English program names in parentheses. "
        "Only state facts that are in the data -- don't add dates, reasons or advice that aren't there. "
        f"Data: {source_text}"
    )
    output = plain_text(genai_chat(prompt))
    assert_numbers_preserved(output, source_text)
    return output


# ---------------------------------------------------------------------------
# Public dispatch -- callers never branch on MOCK_MODE themselves. Real OCI
# is attempted whenever MOCK_MODE=false; mock is only ever reached as the
# deliberate default (MOCK_MODE=true) or as a fallback when real fails.
# ---------------------------------------------------------------------------


# Reading a letter's facts (OCR, type, fields) never falls back to sample
# data outside MOCK_MODE -- see app.trace.call_real_or_sample. Only the
# explanation (built from the real fields) may fall back to a template.


def ocr_document(image_bytes: bytes, filename: str) -> OcrResult:
    """OCI Document Understanding: read the text of the photo."""
    return call_real_or_sample(lambda: _real_ocr(image_bytes), lambda: _mock_ocr(filename))


def classify_letter(raw_text: str) -> LetterType:
    """OCI GenAI: classify the letter type from its OCR'd text."""
    return call_real_or_sample(lambda: _real_classify(raw_text), lambda: _mock_classify(raw_text))


def extract_fields(
    letter_type: LetterType, raw_text: str, key_values: dict, retry_after_invalid: bool = False
) -> dict:
    """OCI GenAI: extract typed fields for the given letter type."""
    return call_real_or_sample(
        lambda: _real_extract(letter_type, raw_text, key_values, retry_after_invalid),
        lambda: _mock_extract(letter_type, raw_text),
    )


def explain_letter(letter_type: LetterType, fields: dict, language: str) -> str:
    """OCI GenAI: plain-language explanation of this letter in the user's language."""
    return format_dollar_amounts(
        call_with_fallback(
            lambda: _real_explain(letter_type, fields, language),
            lambda: _mock_explain(letter_type, fields, language),
        )
    )
