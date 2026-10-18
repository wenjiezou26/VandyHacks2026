"""Combine a deterministic ProgramResult with its GenAI explanation and
myth-busting lines. Eligibility is already decided by app.rules.engine --
nothing here can change status, numbers_used, or rule_applied.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.rules.engine import Profile, ProgramResult

from . import oci_client
from .myths import myth_busting_lines


@dataclass
class ExplainedProgramResult:
    program: str
    status: str
    monthly_value: float
    annual_value: float
    numbers_used: dict
    rule_applied: str
    confidence: str
    missing_fields: list[str]
    warnings: list[str]
    disclaimer: str
    explanation: str
    myth_busting_lines: list[str] = field(default_factory=list)
    # rule_applied / warnings / disclaimer above are in the requested
    # language (Chinese for "zh"); the official English rule is always here
    # too, for the bilingual caseworker card.
    rule_applied_en: str = ""
    # A preliminary estimate holds only if `assumptions` (conditions, e.g.
    # "no work income") are true; not a decision.
    preliminary: bool = False
    assumptions: list[str] = field(default_factory=list)


def explain_results(
    results: list[ProgramResult], profile: Profile, language: str
) -> list[ExplainedProgramResult]:
    zh = language.lower() in ("zh", "chinese")
    # The AI calls are independent and slow (seconds each): run them together.
    with ThreadPoolExecutor(max_workers=max(1, len(results))) as pool:
        explanations = list(pool.map(lambda r: oci_client.explain_program_result(r, language), results))
    explained: list[ExplainedProgramResult] = []
    for result, explanation in zip(results, explanations):
        explained.append(
            ExplainedProgramResult(
                program=result.program,
                status=result.status.value,
                monthly_value=result.monthly_value,
                annual_value=result.annual_value,
                numbers_used=result.numbers_used,
                rule_applied=result.rule_applied_zh if zh else result.rule_applied,
                confidence=result.confidence.value,
                missing_fields=list(result.missing_fields),
                warnings=list(result.warnings_zh if zh else result.warnings),
                disclaimer=result.disclaimer_zh if zh else result.disclaimer,
                explanation=explanation,
                myth_busting_lines=myth_busting_lines(result, profile, language),
                rule_applied_en=result.rule_applied,
                preliminary=result.preliminary,
                assumptions=list(result.assumptions),
            )
        )
    return explained
