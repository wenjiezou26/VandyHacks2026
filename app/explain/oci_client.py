"""OCI GenAI call that explains a ProgramResult in the user's language.

Same MOCK_MODE convention as app/docs/oci_client.py: mock is the default
and only tested path. The LLM is handed the already-decided status,
numbers_used, and rule_applied -- it writes prose, it never re-derives or
overrides the decision. Real-mode output is checked against
app.number_guard before being returned.
"""

from __future__ import annotations

import json
import threading

from app.number_guard import assert_numbers_preserved, format_dollar_amounts
from app.oci_genai import genai_chat, language_name, plain_text
from app.rules.engine import ProgramResult
from app.trace import call_with_fallback, is_mock_mode, was_fallback_used

STATUS_PHRASES = {
    "likely": "you likely qualify for",
    "possible": "you might qualify for",
    "not_now": "you don't qualify right now for",
    "already_enrolled": "you're already enrolled in",
    "missing_info": "we need more information to check",
}


def _status_value(result: ProgramResult) -> str:
    return result.status.value if hasattr(result.status, "value") else result.status


def _source_text(result: ProgramResult) -> str:
    data = {
        "program": result.program,
        "status": _status_value(result),
        "numbers_used": result.numbers_used,
        "rule_applied": result.rule_applied,
    }
    # A 0 here means "we don't calculate this amount" (e.g. HRA sets the
    # SNAP amount), not "$0". Given a 0, the model told users they'd get
    # nothing -- so only pass real amounts.
    if result.monthly_value:
        data["monthly_value"] = result.monthly_value
        data["annual_value"] = result.annual_value
    return json.dumps(data)


STATUS_PHRASES_ZH = {
    "likely": "您很可能符合",
    "possible": "您也许符合",
    "not_now": "您目前不符合",
    "already_enrolled": "您已经加入了",
    "missing_info": "我们需要更多信息才能判断您是否符合",
}


def _mock_explain_zh(result: ProgramResult) -> str:
    # Hand-written Chinese template for the offline demo; program names and
    # dollar amounts stay exactly as the rules engine produced them.
    phrase = STATUS_PHRASES_ZH.get(_status_value(result), "以下是")
    sentence = f"根据您信件上的数字，{phrase} {result.program} 的条件。"
    if result.monthly_value:
        sentence += f"每月大约可以帮您省下 ${result.monthly_value:,.2f}。"
    sentence += f"（{result.rule_applied_zh}）"
    return sentence


def _mock_explain(result: ProgramResult, language: str) -> str:
    if language.lower() in ("zh", "chinese"):
        return _mock_explain_zh(result)
    note = (
        ""
        if language.lower() in ("en", "english")
        else f" [MOCK_MODE: shown in English, not translated to {language}]"
    )
    phrase = STATUS_PHRASES.get(_status_value(result), "the result for")
    sentence = f"Based on the numbers on your letters, {phrase} {result.program}."
    if result.monthly_value:
        sentence += f" That could be worth about ${result.monthly_value:,.2f} a month."
    sentence += f" {result.rule_applied}."
    return sentence + note


def _real_explain(result: ProgramResult, language: str) -> str:
    source_text = _source_text(result)
    prompt = (
        f"Explain this benefits result to an older adult reading at a 6th-grade level, in {language_name(language)}, "
        "in 2-4 short sentences of plain text (no markdown). Copy every number, date and dollar amount exactly as given and add no "
        "other numbers; keep official English program names in parentheses. Only state facts that are in the data. "
        "Status 'likely' means they likely qualify. This is a check of their letters, not an application: "
        "never say they applied, were denied or were approved. "
        + (
            ""
            if result.monthly_value
            else "No benefit amount is given because the agency decides it: never say it is $0 or that the person gets nothing. "
        )
        + f"Data: {source_text}"
    )
    output = plain_text(genai_chat(prompt))
    assert_numbers_preserved(output, source_text)
    return output


def _english_list(items: list[str]) -> str:
    """"a", "a and b", "a, b, and c"."""
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def template_explanation(result: ProgramResult, language: str) -> str:
    """Fixed wording for preliminary and missing-information results: the
    stated conditions must never be paraphrased away, so no AI here."""
    from app.rules.engine import CONDITION_LABELS, MISSING_FACT_LABELS

    zh = language.lower() in ("zh", "chinese")
    if _status_value(result) == "missing_info":
        facts = [MISSING_FACT_LABELS[f][1 if zh else 0] for f in result.missing_fields]
        if zh:
            return f"还不能判断 {result.program}。需要先知道：" + "、".join(facts) + "。"
        return f"We can't check {result.program} yet. We need to know " + _english_list(facts) + "."
    conditions = [CONDITION_LABELS[f][1 if zh else 0] for f in result.assumptions]
    if zh:
        sentence = "初步估计：如果" + "，且".join(conditions) + f"，{STATUS_PHRASES_ZH.get(_status_value(result), '')} {result.program} 的条件。"
        if result.monthly_value:
            sentence += f"每月约 ${result.monthly_value:,.2f}。"
        return sentence + "回答下面的问题来确认。"
    sentence = "Preliminary estimate: if " + _english_list(conditions) + f", {STATUS_PHRASES.get(_status_value(result), 'the result for')} {result.program}."
    if result.monthly_value:
        sentence += f" That could be worth about ${result.monthly_value:,.2f} a month."
    return sentence + " Answer the question below to confirm."


# Same result + language -> same explanation, so repeat visits to Home,
# Benefits and the application pack don't re-run the AI each time.
_CACHE: dict[str, str] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 512


def _cache_key(result: ProgramResult, language: str) -> str:
    return json.dumps([_source_text(result), result.rule_applied_zh, language, is_mock_mode()], sort_keys=True)


def explain_program_result(result: ProgramResult, language: str) -> str:
    """Plain-language explanation of one ProgramResult: fixed wording for
    preliminary / missing-info results, OCI GenAI (cached) otherwise."""
    if result.preliminary or _status_value(result) == "missing_info":
        return format_dollar_amounts(template_explanation(result, language))
    key = _cache_key(result, language)
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    text = format_dollar_amounts(
        call_with_fallback(
            lambda: _real_explain(result, language),
            lambda: _mock_explain(result, language),
        )
    )
    if not was_fallback_used() or is_mock_mode():
        # Don't cache a fallback from a failed live call -- retry it next time.
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[key] = text
    return text
