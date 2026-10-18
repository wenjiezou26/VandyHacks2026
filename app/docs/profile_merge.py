"""Merge validated letter fields into a user's ProfileRecord.

Deterministic field-by-field logic, no LLM involved. A bank statement's
recurring deposit is only used as an income fallback when no documented
SSA benefit letter has already supplied ss_gross_monthly -- documented
numbers always win over estimated ones.
"""

from __future__ import annotations

from datetime import date

from app.models import ProfileRecord

from .schemas import LetterType


def _age_from_dob(dob: str, today: date | None = None) -> int:
    today = today or date.today()
    year, month, day = (int(p) for p in dob.split("-"))
    age = today.year - year
    if (today.month, today.day) < (month, day):
        age -= 1
    return age


# Pay-period -> factor that converts one stub's gross pay to a monthly
# figure, matching how the rules engine expects earned_income_monthly.
_MONTHLY_FACTOR = {
    "weekly": 52 / 12,
    "biweekly": 26 / 12,
    "semimonthly": 2,
    "monthly": 1,
}


def _monthly_from_pay_stub(gross_pay: float, pay_period: str) -> float:
    factor = _MONTHLY_FACTOR.get(pay_period, 1)
    return round(gross_pay * factor, 2)


def merge_fields_into_profile(
    profile: ProfileRecord, letter_type: LetterType, fields: dict, letter_id: int
) -> list[str]:
    updated: list[str] = []

    if letter_type == LetterType.SSA_BENEFIT_LETTER:
        profile.ss_gross_monthly = fields["gross_monthly_benefit"]
        profile.has_medicare = True
        profile.set_provenance("ss_gross_monthly", letter_id)
        profile.set_provenance("has_medicare", letter_id)
        updated += ["ss_gross_monthly", "has_medicare"]

        # An SSA letter's date of birth answers the "age" question itself
        # -- one less thing to ask about.
        if fields.get("date_of_birth"):
            profile.age = _age_from_dob(str(fields["date_of_birth"]))
            profile.set_provenance("age", letter_id)
            updated.append("age")

        # The letter states SSI status outright when it has anything to
        # report about it -- no need to ask.
        if fields.get("receives_ssi") is not None:
            profile.on_ssi = fields["receives_ssi"]
            profile.set_provenance("on_ssi", letter_id)
            updated.append("on_ssi")

    elif letter_type == LetterType.HRA_RENEWAL_NOTICE:
        if fields.get("program") == "SNAP":
            profile.on_snap = True
            profile.set_provenance("on_snap", letter_id)
            updated.append("on_snap")
        if fields.get("household_size"):
            profile.household_size = fields["household_size"]
            profile.set_provenance("household_size", letter_id)
            updated.append("household_size")

        # Exactly one named household member means she lives alone -- that
        # answers "married and living with spouse" (= no) without the
        # notice ever stating a marital status, and without asking.
        members = fields.get("household_members")
        if members and len(members) == 1:
            profile.married = False
            profile.living_with_spouse = False
            profile.set_provenance("married", letter_id)
            updated.append("married")

        # The notice lists which programs this case covers. Medicaid listed
        # means on Medicaid; NOT listed proves nothing (Medicaid is often a
        # separate case), so that isn't taken as "no".
        programs = fields.get("programs_on_case") or []
        if "medicaid" in {p.lower() for p in programs}:
            profile.on_medicaid = True
            profile.set_provenance("on_medicaid", letter_id)
            updated.append("on_medicaid")

        # The simplified-form eligibility condition some notices state
        # outright ("no one has earned income") answers
        # "earned_income_monthly" (= 0) without needing a pay stub.
        if fields.get("household_has_earned_income") is False and profile.earned_income_monthly is None:
            profile.earned_income_monthly = 0.0
            profile.set_provenance("earned_income_monthly", letter_id)
            updated.append("earned_income_monthly")

    elif letter_type == LetterType.BANK_STATEMENT:
        profile.savings = fields["ending_balance"]
        profile.set_provenance("savings", letter_id)
        updated.append("savings")

        if profile.ss_gross_monthly is None:
            deposits = fields.get("recurring_deposits") or []
            if deposits:
                profile.bank_deposit_monthly = max(d["amount"] for d in deposits)
                profile.set_provenance("bank_deposit_monthly", letter_id)
                updated.append("bank_deposit_monthly")

    elif letter_type == LetterType.MEDICARE_NOTICE:
        # A Medicare notice addressed to them documents Medicare enrollment.
        profile.has_medicare = True
        profile.set_provenance("has_medicare", letter_id)
        updated.append("has_medicare")

    elif letter_type == LetterType.PAY_STUB:
        # Answers the "earned_income_monthly" question directly -- the one
        # fact genuinely absent from every other letter type this app
        # reads, previously always asked rather than read from a document.
        profile.earned_income_monthly = _monthly_from_pay_stub(fields["gross_pay"], fields["pay_period"])
        profile.set_provenance("earned_income_monthly", letter_id)
        updated.append("earned_income_monthly")

    # medical_bill doesn't update Profile fields -- it drives the QMB
    # bill check (PROTECT) instead.

    return updated
