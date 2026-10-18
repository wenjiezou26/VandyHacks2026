"""Guard against GenAI output inventing numbers that weren't in its input.

Used by both the document pipeline (app/docs) and the explanation layer
(app/explain) to enforce the hard rule: the LLM explains, it never
introduces a number, date, or dollar amount that wasn't already in the
facts we gave it.
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


def numbers_in(text: str) -> set[float]:
    """Numeric values mentioned in text, as floats so "$1,700" and
    "1700.00" compare equal regardless of formatting."""
    numbers = set()
    for match in _NUMBER_RE.findall(text):
        cleaned = match.replace(",", "")
        if cleaned in ("", "."):
            continue
        numbers.add(float(cleaned))
    return numbers


def assert_numbers_preserved(output_text: str, source_text: str) -> None:
    unknown = numbers_in(output_text) - numbers_in(source_text)
    if unknown:
        raise ValueError(f"GenAI output introduced numbers not present in source data: {unknown}")


_AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
_DOLLAR_RE = re.compile(r"\$\s?" + _AMOUNT)
_TRAILING_UNIT_RE = re.compile(_AMOUNT + r"\s?(?:美元|dollars\b)")


def _money(match: re.Match) -> str:
    whole, fraction = match.group(1), match.group(2) or ""
    return f"${float(whole.replace(',', '') + fraction):,.2f}"


def format_dollar_amounts(text: str | None) -> str | None:
    """Write every dollar amount the way the facts table does ($1,700.00),
    whatever the model or template produced ("$1700.0", "1700.0 美元")."""
    if not text:
        return text
    return _TRAILING_UNIT_RE.sub(_money, _DOLLAR_RE.sub(_money, text))
