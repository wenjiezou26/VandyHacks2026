"""Fixed Chinese wording for short terms that come from letters.

Only exact, known phrases -- anything unrecognized is shown as written on
the letter rather than guessed at.
"""

from __future__ import annotations

DOCUMENT_NAMES_ZH = {
    "proof of income": "收入证明",
    "proof of residence": "居住证明",
    "proof of address": "地址证明",
    "id": "身份证明",
    "photo id": "带照片的身份证明",
    "proof of identity": "身份证明",
    "social security card": "社会安全卡",
    "medicare card": "医疗保险卡",
    "bank statement": "银行对账单",
    "proof of rent": "房租证明",
    "proof of utility costs": "水电费证明",
    "proof of utilities": "水电费证明",
    "proof of medical expenses": "医疗费用证明",
}

# Notes HRA prints after a document name, e.g. "Proof of rent (lease or
# rent receipt)".
DOCUMENT_NOTES_ZH = {
    "for example, social security benefit letter": "例如社会安全福利信",
    "lease or rent receipt": "租约或房租收据",
    "for example, electric bill": "例如电费账单",
    "60+ household members may deduct these": "60岁以上的家庭成员可以扣除这些费用",
}

COST_SHARING_ZH = {
    "deductible": "自付额",
    "coinsurance": "共同保险",
    "copay": "共付额",
    "other": "其他",
}


def is_zh(language: str) -> bool:
    return (language or "").lower() in ("zh", "chinese")


def document_name_zh(name: str) -> str:
    """Chinese for a document name as written on a letter; anything not
    recognized is left as written rather than guessed."""
    key = name.strip().lower()
    if key in DOCUMENT_NAMES_ZH:
        return DOCUMENT_NAMES_ZH[key]
    base, _, note = key.partition("(")
    base_zh = DOCUMENT_NAMES_ZH.get(base.strip())
    if base_zh is None:
        return name
    note = note.rstrip(")").strip()
    if not note:
        return base_zh
    note_zh = DOCUMENT_NOTES_ZH.get(note, name[name.index("(") + 1 :].rstrip(")").strip())
    return f"{base_zh}（{note_zh}）"
