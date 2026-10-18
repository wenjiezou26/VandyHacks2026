"""Data-minimization rules and log-safe error descriptions.

See docs/PRIVACY.md for the full document lifecycle.
"""

from __future__ import annotations

# Fields kept after the user confirms a letter -- only what eligibility,
# reminders, the bill check or re-showing the letter actually use. Full OCR
# text is never kept; free-text summaries are dropped.
SAVED_FIELDS: dict[str, list[str]] = {
    "ssa_benefit_letter": ["gross_monthly_benefit", "part_b_deduction", "net_payment", "effective_date"],
    # rent/utility/medical payments let the renewal checklist mark items "partial".
    "bank_statement": ["ending_balance", "recurring_deposits", "monthly_rent", "utility_expenses", "medical_expenses"],
    "hra_renewal_notice": ["program", "deadline", "required_documents", "household_size"],
    "medical_bill": ["provider", "line_items", "is_medicare_claim"],
    # Employer and pay date aren't used, so they aren't kept.
    "pay_stub": ["gross_pay", "pay_period"],
    "medicare_notice": [],
    "other": [],
}

# Used once when the facts are saved (to update the profile), then dropped:
# date of birth only serves to work out age, and age is what's kept. The HRA
# notice's household list/programs/earned-income statement similarly only
# serve to derive married/on_medicaid/earned_income_monthly -- those derived
# booleans are what's kept, never the raw household roster or program list.
TRANSIENT_FIELDS: dict[str, list[str]] = {
    "ssa_benefit_letter": ["date_of_birth", "receives_ssi"],
    "hra_renewal_notice": ["household_members", "programs_on_case", "household_has_earned_income"],
}

# Lists of payments whose free-text descriptions can name people or payers;
# only the amounts are kept.
_AMOUNT_ONLY_LISTS = ("recurring_deposits", "utility_expenses", "medical_expenses")

# Personal identifiers a letter can carry. Saved only when the user ticks
# "use for my application", and never sent to the explanation step.
IDENTIFIER_FIELDS: dict[str, list[str]] = {
    "ssa_benefit_letter": ["recipient_name", "recipient_address"],
}

# Facts the user can correct before saving, and how each is checked
# (kinds from app.apply.normalize, plus "bool", "list" and "people" --
# a household list edited as one name per line).
EDITABLE_FIELDS: dict[str, dict[str, str]] = {
    "ssa_benefit_letter": {
        "date_of_birth": "date",
        "gross_monthly_benefit": "money",
        "part_b_deduction": "money",
        "net_payment": "money",
        "effective_date": "date",
        "recipient_name": "text",
        "recipient_address": "text",
        "receives_ssi": "bool",
    },
    "hra_renewal_notice": {
        "program": "text",
        "deadline": "date",
        "required_documents": "list",
        "household_size": "count",
        "household_members": "people",
        "programs_on_case": "list",
        "household_has_earned_income": "bool",
    },
    "bank_statement": {"ending_balance": "money", "monthly_rent": "money"},
    "medical_bill": {"provider": "text", "is_medicare_claim": "bool"},
    "pay_stub": {"gross_pay": "money", "pay_period": "text"},
}


def without_identifiers(letter_type: str, fields: dict) -> dict:
    drop = set(IDENTIFIER_FIELDS.get(letter_type, []))
    return {k: v for k, v in fields.items() if k not in drop}


def minimize(letter_type: str, fields: dict, keep_identifiers: bool = False) -> dict:
    """The subset of a letter's fields that is saved."""
    keep = list(SAVED_FIELDS.get(letter_type, []))
    if keep_identifiers:
        keep += IDENTIFIER_FIELDS.get(letter_type, [])
    saved = {k: fields[k] for k in keep if fields.get(k) not in (None, "", [])}
    for key in _AMOUNT_ONLY_LISTS:
        if key in saved:
            saved[key] = [{"description": "", "amount": d["amount"]} for d in saved[key]]
    return saved


def transient(letter_type: str, fields: dict) -> dict:
    """Facts used once when saving (e.g. date of birth -> age), never stored."""
    return {k: fields[k] for k in TRANSIENT_FIELDS.get(letter_type, []) if fields.get(k) not in (None, "")}


def describe_failure(exc: BaseException) -> str:
    """Log-safe description of an error: its type and any OCI status/code,
    never its message -- validation errors and some service errors repeat
    the input, which here is someone's letter."""
    parts = [type(exc).__name__]
    for attr in ("status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, (int, str)) and value != "":
            parts.append(f"{attr}={value}")
    return " ".join(parts)
