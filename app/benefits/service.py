"""Bridges the persisted ProfileRecord to the pure rules engine + explain
layer. Nothing here decides eligibility or writes explanations -- it only
converts the storage shape and calls app.rules.engine.evaluate /
app.explain.explain_results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session

from app.apply.normalize import normalize
from app.explain import ExplainedProgramResult, explain_results
from app.models import LetterRecord, ProfileRecord
from app.rules.engine import Profile, Status, evaluate
from app.trace import Trace, mock_suffix, trace_to_out, TraceStepOut


# Facts the rules engine needs that a missing provenance entry makes UNKNOWN
# (see ProfileRecord.field_sources). Order = the order questions are asked.
PROFILE_FACTS = [
    "has_medicare",
    "ss_gross_monthly",
    "earned_income_monthly",
    "married",
    "ss_gross_monthly_spouse",
    "earned_income_monthly_spouse",
    "household_size",
    "other_household_income_monthly",
    "age",
    "savings",
]


def unknown_facts(record: ProfileRecord) -> frozenset[str]:
    unknown = {f for f in PROFILE_FACTS if not record.is_known(f)}
    # A recurring bank deposit is an accepted (estimated) stand-in for an
    # SSA letter's gross benefit.
    if record.bank_deposit_monthly is not None:
        unknown.discard("ss_gross_monthly")
    return frozenset(unknown)


def profile_record_to_profile(record: ProfileRecord) -> Profile:
    return Profile(
        nyc_resident=record.nyc_resident,
        age=record.age or 0,
        married=bool(record.married),
        living_with_spouse=record.living_with_spouse,
        has_medicare=bool(record.has_medicare),
        on_medicaid=record.on_medicaid,
        on_ssi=record.on_ssi,
        disability=record.disability,
        ss_gross_monthly=record.ss_gross_monthly,
        ss_gross_monthly_spouse=record.ss_gross_monthly_spouse,
        earned_income_monthly=record.earned_income_monthly,
        earned_income_monthly_spouse=record.earned_income_monthly_spouse,
        medigap_premium_monthly=record.medigap_premium_monthly,
        medigap_premium_monthly_spouse=record.medigap_premium_monthly_spouse,
        bank_deposit_monthly=record.bank_deposit_monthly,
        savings=record.savings or 0.0,
        household_size=record.household_size or 1,
        owns_home=record.owns_home,
        on_qmb=record.on_qmb,
        on_snap=record.on_snap,
        other_household_income_monthly=record.other_household_income_monthly or 0.0,
        unknown=unknown_facts(record),
    )


def rank_questions(results: list) -> tuple[list[str], dict[str, list[str]]]:
    """Facts that could change at least one result (the engine only lists a
    fact when it does), most useful first: facts without which there's no
    estimate at all, then those affecting the most programs."""
    affects: dict[str, list[str]] = {}
    for r in results:
        for f in r.missing_fields:
            affects.setdefault(f, []).append(r.program)
    blocking = {f for r in results if r.status == Status.MISSING_INFO for f in r.missing_fields}
    order = {f: i for i, f in enumerate(PROFILE_FACTS)}
    ranked = sorted(affects, key=lambda f: (f not in blocking, -len(affects[f]), order.get(f, 99)))
    return ranked, affects


def uses_sample_data(session: Session, record: ProfileRecord) -> bool:
    """True if any value behind the results came from a sample letter.
    Letters saved before is_sample existed were all MOCK_MODE samples
    (real OCI had never run), so None counts as sample."""
    letter_ids = {v for v in (record.field_sources or {}).values() if isinstance(v, int)}
    for letter_id in letter_ids:
        letter = session.get(LetterRecord, letter_id)
        if letter is not None and letter.is_sample is not False:
            return True
    return False


@dataclass
class BenefitsResult:
    results: list[ExplainedProgramResult]
    trace: list[TraceStepOut]
    # Facts to ask for, in order, so "More information needed" can resolve.
    questions: list[str] = field(default_factory=list)
    # question -> programs whose result it could change
    question_programs: dict = field(default_factory=dict)
    # True when any number behind these results came from sample letters.
    uses_sample_data: bool = False


def get_benefits(session: Session, user_id: str, language: str) -> BenefitsResult:
    trace = Trace()
    record = session.get(ProfileRecord, user_id) or ProfileRecord(user_id=user_id)
    profile = profile_record_to_profile(record)

    # Unknown facts come back as MISSING_INFO with the facts listed, so a
    # brand-new user sees "More information needed", never a guess.
    with trace.step("Checked eligibility", "Rules engine (no AI)"):
        results = evaluate(profile)

    with trace.step("Explained each result", f"OCI Generative AI{mock_suffix()}"):
        explained = explain_results(results, profile, language)

    questions, question_programs = rank_questions(results)
    return BenefitsResult(
        results=explained,
        trace=trace_to_out(trace),
        questions=questions,
        question_programs=question_programs,
        uses_sample_data=uses_sample_data(session, record),
    )


# How each question's answer is checked and stored on the profile.
_ANSWER_KINDS = {
    "has_medicare": "yesno",
    "married": "yesno",
    "household_size": "count",
    "age": "age",
    "ss_gross_monthly": "money",
    "earned_income_monthly": "money",
    "ss_gross_monthly_spouse": "money",
    "earned_income_monthly_spouse": "money",
    "other_household_income_monthly": "money",
    "savings": "money",
}


class AnswerError(Exception):
    def __init__(self, message_en: str, message_zh: str = "", status_code: int = 422):
        super().__init__(message_en)
        self.message_en = message_en
        self.message_zh = message_zh or message_en
        self.status_code = status_code


def save_answer(session: Session, user_id: str, key: str, raw: str) -> str:
    """Store the user's answer to one missing fact. Returns the stored value."""
    kind = _ANSWER_KINDS.get(key)
    if kind is None:
        raise AnswerError(f"Unknown question {key}.", status_code=404)
    try:
        value = normalize(kind, raw)
    except ValueError as exc:
        raise AnswerError(getattr(exc, "message_en", str(exc)), getattr(exc, "message_zh", "")) from exc

    record = session.get(ProfileRecord, user_id) or ProfileRecord(user_id=user_id)
    if kind == "yesno":
        setattr(record, key, value == "yes")
        if key == "married":
            # The question is "married AND living with your spouse".
            record.living_with_spouse = value == "yes"
    elif kind in ("count", "age"):
        setattr(record, key, int(value))
    else:
        setattr(record, key, float(value))
    record.set_provenance(key, "user")
    session.add(record)
    session.commit()
    return value
