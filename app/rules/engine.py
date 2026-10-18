"""Deterministic benefits rules engine.

This module decides eligibility. No LLM call ever enters this file -- the
LLM only extracts fields into a Profile and explains a ProgramResult after
the fact. Every result carries the numbers used, the rule applied, a
confidence label, and the standard decision-authority disclaimer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from . import limits
from .income import countable_income_msp, estimate_gross_from_deposit

FINAL_DECISION_DISCLAIMER = (
    "Final decision is made by NY State / HRA / SSA, not this app."
)
FINAL_DECISION_DISCLAIMER_ZH = "最终决定由纽约州 / HRA / SSA 作出，而非本应用。"
NEAR_LIMIT_WARNING = "Income is within 5% of the limit -- we recommend applying anyway."
NEAR_LIMIT_WARNING_ZH = "收入在上限的5%以内——我们仍然建议您申请。"
NEAR_LIMIT_PCT = 0.05


class Status(str, Enum):
    LIKELY = "likely"
    POSSIBLE = "possible"
    NOT_NOW = "not_now"
    ALREADY_ENROLLED = "already_enrolled"
    MISSING_INFO = "missing_info"


class Confidence(str, Enum):
    DOCUMENTED = "documented"
    ESTIMATED = "estimated"
    NEAR_LIMIT = "near_limit"


@dataclass
class Profile:
    nyc_resident: bool = True
    age: int = 0
    married: bool = False
    # Verified 2026-10-17 against the Medicare Rights Center's 2026 NY MSP
    # training deck: income is combined and couple limits apply only when
    # "married and living together." A married applicant living apart from
    # their spouse is budgeted as an individual using single limits.
    # Defaults to True so existing married=True profiles behave exactly as
    # before -- this field only matters when explicitly set to False.
    living_with_spouse: bool = True

    has_medicare: bool = False
    on_medicaid: bool = False
    on_ssi: bool = False
    disability: bool = False

    ss_gross_monthly: float | None = None
    ss_gross_monthly_spouse: float | None = None
    earned_income_monthly: float | None = None
    earned_income_monthly_spouse: float | None = None
    medigap_premium_monthly: float = 0.0
    medigap_premium_monthly_spouse: float = 0.0
    # Fallback when the only document seen is a bank statement.
    bank_deposit_monthly: float | None = None

    savings: float = 0.0
    household_size: int = 1
    owns_home: bool = False
    # Documented current enrollment -- distinct from this engine's computed
    # "likely eligible for QMB", used by the PROTECT illegal-billing check.
    on_qmb: bool = False
    # Documented current SNAP enrollment (e.g. an HRA recertification
    # notice was uploaded) -- SNAP should show "already enrolled", not
    # re-run the likely/possible eligibility check as if applying fresh.
    on_snap: bool = False

    # Income of other people in the household (not self/spouse). SNAP only.
    other_household_income_monthly: float = 0.0

    # Field names nobody has told us yet. The values above are only trusted
    # for fields NOT in this set: an unknown income is not $0 and unknown
    # Medicare enrollment is not "not enrolled". A program that needs an
    # unknown fact comes back MISSING_INFO listing it in missing_fields.
    # Empty by default, so a hand-built Profile means exactly what it says.
    unknown: frozenset[str] = frozenset()
    # Facts filled with a stand-in value only to test what else matters
    # (see evaluate()). Their stand-in values must never appear in a reason.
    placeholders: frozenset[str] = frozenset()


# What each fact is called when we tell the user it's missing.
MISSING_FACT_LABELS = {
    "has_medicare": ("whether you have Medicare", "您是否有医疗保险 (Medicare)"),
    "ss_gross_monthly": ("your monthly Social Security", "您每月的社会安全福利"),
    "earned_income_monthly": ("your monthly income from work", "您每月的工作收入"),
    "married": ("whether you're married and live with your spouse", "您是否已婚并与配偶同住"),
    "ss_gross_monthly_spouse": ("your spouse's monthly Social Security", "配偶每月的社会安全福利"),
    "earned_income_monthly_spouse": ("your spouse's monthly income from work", "配偶每月的工作收入"),
    "household_size": ("how many people live in your home", "家里住几个人"),
    "other_household_income_monthly": ("other household members' monthly income", "家中其他人每月的收入"),
    "age": ("your age", "您的年龄"),
    "savings": ("your savings", "您的存款"),
}


@dataclass
class ProgramResult:
    program: str
    status: Status
    monthly_value: float = 0.0
    annual_value: float = 0.0
    numbers_used: dict = field(default_factory=dict)
    rule_applied: str = ""
    confidence: Confidence = Confidence.DOCUMENTED
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = FINAL_DECISION_DISCLAIMER
    # Chinese versions, written next to the English at each rule below so
    # both are built from the same numbers -- never translated after the fact.
    rule_applied_zh: str = ""
    warnings_zh: list[str] = field(default_factory=list)
    # True when this result holds only if facts nobody has confirmed yet are
    # as stated in `assumptions` (e.g. "no work income"). Shown as a
    # preliminary estimate with those conditions -- never as a decision.
    preliminary: bool = False
    assumptions: list[str] = field(default_factory=list)
    disclaimer_zh: str = FINAL_DECISION_DISCLAIMER_ZH


def _near_limit(value: float, limit_value: float, pct: float = NEAR_LIMIT_PCT) -> bool:
    return limit_value * (1 - pct) <= value <= limit_value


def _counts_as_couple(profile: Profile) -> bool:
    """Whether spouse income is combined and couple limits apply. Married
    alone isn't enough -- a couple living apart is budgeted as two
    individuals, each against single limits."""
    return profile.married and profile.living_with_spouse


def _unknown(profile: Profile, fields: list[str]) -> list[str]:
    return [f for f in fields if f in profile.unknown]


def _income_facts(profile: Profile) -> list[str]:
    """Facts needed to total this person's (and a live-in spouse's) income."""
    facts = ["ss_gross_monthly", "earned_income_monthly", "married"]
    if "married" not in profile.unknown and _counts_as_couple(profile):
        facts += ["ss_gross_monthly_spouse", "earned_income_monthly_spouse"]
    return facts


def _missing_info(program: str, missing: list[str], confidence: Confidence = Confidence.DOCUMENTED) -> ProgramResult:
    return ProgramResult(
        program=program,
        status=Status.MISSING_INFO,
        rule_applied="Need to know: " + ", ".join(MISSING_FACT_LABELS[f][0] for f in missing),
        rule_applied_zh="还需要知道：" + "、".join(MISSING_FACT_LABELS[f][1] for f in missing),
        missing_fields=list(missing),
        confidence=confidence,
    )


def _gross_ss_income(profile: Profile) -> tuple[float, float, Confidence]:
    confidence = Confidence.DOCUMENTED
    ss_self = profile.ss_gross_monthly
    if ss_self is None and profile.bank_deposit_monthly is not None:
        ss_self = estimate_gross_from_deposit(profile.bank_deposit_monthly)
        confidence = Confidence.ESTIMATED
    ss_self = ss_self or 0.0
    ss_spouse = (profile.ss_gross_monthly_spouse or 0.0) if _counts_as_couple(profile) else 0.0
    return ss_self, ss_spouse, confidence


def _evaluate_msp(
    profile: Profile, countable: float, income_confidence: Confidence
) -> ProgramResult:
    if "has_medicare" in profile.unknown:
        return _missing_info("MSP", ["has_medicare"] + _unknown(profile, _income_facts(profile)))
    if not profile.has_medicare:
        return ProgramResult(
            program="MSP",
            status=Status.NOT_NOW,
            rule_applied="Medicare Savings Program requires Medicare enrollment",
            rule_applied_zh="医疗保险储蓄计划 (Medicare Savings Program) 要求已加入医疗保险 (Medicare)",
        )

    missing = _unknown(profile, _income_facts(profile))
    if missing:
        return _missing_info("MSP", missing, income_confidence)

    is_couple = _counts_as_couple(profile)
    qmb_limit = (
        limits.QMB_INCOME_LIMIT_COUPLE_MONTHLY.value
        if is_couple
        else limits.QMB_INCOME_LIMIT_SINGLE_MONTHLY.value
    )
    qi_limit = (
        limits.QI_INCOME_LIMIT_COUPLE_MONTHLY.value
        if is_couple
        else limits.QI_INCOME_LIMIT_SINGLE_MONTHLY.value
    )
    household = "couple" if is_couple else "single"
    household_zh = "夫妻" if is_couple else "单身"
    numbers_used = {
        "countable_income_monthly": round(countable, 2),
        "qmb_limit_monthly": qmb_limit,
        "qi_limit_monthly": qi_limit,
    }

    if countable <= qmb_limit:
        program, status = "QMB", Status.LIKELY
        rule = (
            f"Countable income ${countable:,.2f}/mo <= QMB limit "
            f"${qmb_limit:,.2f}/mo ({household}); NY MSP has no asset test"
        )
        rule_zh = (
            f"可计算收入每月 ${countable:,.2f} <= QMB 上限每月 ${qmb_limit:,.2f}（{household_zh}）；"
            "纽约州 MSP 不审查存款资产"
        )
        confidence = (
            Confidence.NEAR_LIMIT
            if _near_limit(countable, qmb_limit)
            else income_confidence
        )
    elif countable <= qi_limit:
        program, status = "QI", Status.LIKELY
        rule = (
            f"Countable income ${countable:,.2f}/mo <= QI limit "
            f"${qi_limit:,.2f}/mo ({household}); NY MSP has no asset test"
        )
        rule_zh = (
            f"可计算收入每月 ${countable:,.2f} <= QI 上限每月 ${qi_limit:,.2f}（{household_zh}）；"
            "纽约州 MSP 不审查存款资产"
        )
        confidence = (
            Confidence.NEAR_LIMIT
            if _near_limit(countable, qi_limit)
            else income_confidence
        )
    else:
        program, status = "MSP", Status.NOT_NOW
        gap = countable - qi_limit
        rule = (
            f"Countable income ${countable:,.2f}/mo exceeds QI limit "
            f"${qi_limit:,.2f}/mo ({household}) by ${gap:,.2f}/mo; "
            "income would need to drop by that amount to qualify"
        )
        rule_zh = (
            f"可计算收入每月 ${countable:,.2f}，超过 QI 上限每月 ${qi_limit:,.2f}（{household_zh}）"
            f"${gap:,.2f}；收入需要减少这么多才符合条件"
        )
        confidence = income_confidence

    result = ProgramResult(
        program=program,
        status=status,
        monthly_value=limits.MEDICARE_PART_B_PREMIUM_MONTHLY.value if status == Status.LIKELY else 0.0,
        annual_value=(limits.MEDICARE_PART_B_PREMIUM_MONTHLY.value * 12) if status == Status.LIKELY else 0.0,
        numbers_used=numbers_used,
        rule_applied=rule,
        rule_applied_zh=rule_zh,
        confidence=confidence,
    )
    if result.confidence == Confidence.NEAR_LIMIT:
        result.warnings.append(NEAR_LIMIT_WARNING)
        result.warnings_zh.append(NEAR_LIMIT_WARNING_ZH)
    return result


def _evaluate_extra_help(
    profile: Profile, msp: ProgramResult, countable: float, income_confidence: Confidence
) -> ProgramResult:
    if profile.on_medicaid or profile.on_ssi:
        return ProgramResult(
            program="Extra Help",
            status=Status.ALREADY_ENROLLED,
            rule_applied="Automatic via Medicaid/SSI enrollment",
            rule_applied_zh="因已加入 Medicaid/SSI 而自动获得",
        )

    if "has_medicare" in profile.unknown:
        return _missing_info("Extra Help", ["has_medicare"])
    if not profile.has_medicare:
        return ProgramResult(
            program="Extra Help",
            status=Status.NOT_NOW,
            rule_applied="Extra Help (Medicare Part D Low-Income Subsidy) requires Medicare",
            rule_applied_zh="Extra Help（医疗保险 D 部分低收入补助）要求已加入医疗保险 (Medicare)",
        )

    if msp.status == Status.LIKELY:
        return ProgramResult(
            program="Extra Help",
            status=Status.LIKELY,
            rule_applied=f"Comes automatically once enrolled in {msp.program} (Medicare Savings Program)",
            rule_applied_zh=f"加入 {msp.program}（医疗保险储蓄计划）后自动获得",
            numbers_used=msp.numbers_used,
            confidence=msp.confidence,
            warnings=list(msp.warnings),
            warnings_zh=list(msp.warnings_zh),
        )

    if msp.status == Status.MISSING_INFO:
        return _missing_info("Extra Help", msp.missing_fields, msp.confidence)
    if "savings" in profile.unknown:
        return _missing_info("Extra Help", ["savings"], income_confidence)

    is_couple = _counts_as_couple(profile)
    income_limit = (
        limits.EXTRA_HELP_INCOME_LIMIT_COUPLE_ANNUAL.value
        if is_couple
        else limits.EXTRA_HELP_INCOME_LIMIT_SINGLE_ANNUAL.value
    )
    resource_limit = (
        limits.EXTRA_HELP_RESOURCE_LIMIT_COUPLE.value
        if is_couple
        else limits.EXTRA_HELP_RESOURCE_LIMIT_SINGLE.value
    )
    annual_income = countable * 12
    numbers_used = {
        "annual_countable_income": round(annual_income, 2),
        "income_limit_annual": income_limit,
        "savings": profile.savings,
        "resource_limit": resource_limit,
    }
    if annual_income <= income_limit and profile.savings <= resource_limit:
        status = Status.LIKELY
        rule = (
            f"Annual countable income ${annual_income:,.2f} <= limit ${income_limit:,.2f} "
            f"and savings ${profile.savings:,.2f} <= resource limit ${resource_limit:,.2f}"
        )
        rule_zh = (
            f"全年可计算收入 ${annual_income:,.2f} <= 上限 ${income_limit:,.2f}，"
            f"存款 ${profile.savings:,.2f} <= 资产上限 ${resource_limit:,.2f}"
        )
    elif "savings" in profile.placeholders:
        # Savings unknown but irrelevant here: income alone is over the limit.
        status = Status.NOT_NOW
        numbers_used = {"annual_countable_income": round(annual_income, 2), "income_limit_annual": income_limit}
        rule = f"Annual countable income ${annual_income:,.2f} is over the limit ${income_limit:,.2f}"
        rule_zh = f"全年可计算收入 ${annual_income:,.2f} 超过上限 ${income_limit:,.2f}"
    else:
        status = Status.NOT_NOW
        rule = (
            f"Annual countable income ${annual_income:,.2f} vs limit ${income_limit:,.2f}, "
            f"savings ${profile.savings:,.2f} vs resource limit ${resource_limit:,.2f}"
        )
        rule_zh = (
            f"全年可计算收入 ${annual_income:,.2f}，上限 ${income_limit:,.2f}；"
            f"存款 ${profile.savings:,.2f}，资产上限 ${resource_limit:,.2f}"
        )
    return ProgramResult(
        program="Extra Help",
        status=status,
        numbers_used=numbers_used,
        rule_applied=rule,
        rule_applied_zh=rule_zh,
        confidence=income_confidence,
    )


def _evaluate_snap(
    profile: Profile, gross_self: float, gross_spouse: float, countable: float, income_confidence: Confidence
) -> ProgramResult:
    if profile.on_snap:
        return ProgramResult(
            program="SNAP",
            status=Status.ALREADY_ENROLLED,
            rule_applied="Already enrolled in SNAP (recertification notice on file)",
            rule_applied_zh="已加入 SNAP（已收到续期通知）",
        )

    facts = _income_facts(profile) + ["household_size"]
    couple_size = 2 if "married" not in profile.unknown and _counts_as_couple(profile) else 1
    if "household_size" not in profile.unknown and profile.household_size > couple_size:
        facts.append("other_household_income_monthly")
    missing = _unknown(profile, facts)
    if missing:
        return _missing_info("SNAP", missing, income_confidence)

    household_size = max(profile.household_size, 2 if _counts_as_couple(profile) else 1)
    fpl_annual = limits.FPL_100_SINGLE_ANNUAL.value + limits.FPL_INCREMENT_PER_ADDITIONAL_PERSON.value * (
        household_size - 1
    )
    fpl_100_monthly = fpl_annual / 12
    fpl_200_monthly = fpl_100_monthly * 2

    # Other members' income only exists if there are other members.
    other_income = (profile.other_household_income_monthly or 0.0) if household_size > couple_size else 0.0
    household_gross_monthly = gross_self + gross_spouse + (
        (profile.earned_income_monthly or 0.0)
        + ((profile.earned_income_monthly_spouse or 0.0) if _counts_as_couple(profile) else 0.0)
        + other_income
    )
    # The net income test is for the whole household, not just the couple.
    countable += other_income

    # Federal law (7 CFR 273.9; confirmed 2026-10-17 against fns.usda.gov and
    # eCFR) exempts households with an elderly (60+) or disabled member from
    # the gross income test entirely -- they only have to meet the net
    # income test, with no asset test tied to that exemption. The 200% FPL
    # gross test below is a separate, NY-specific BBCE path that most
    # households (elderly or not) can also use -- it isn't replaced by the
    # exemption, just not the only route for this app's elderly user base.
    household_has_elderly_or_disabled = profile.age >= 60 or profile.disability

    numbers_used = {
        "household_gross_monthly_income": round(household_gross_monthly, 2),
        "fpl_200_monthly": round(fpl_200_monthly, 2),
        "fpl_100_monthly": round(fpl_100_monthly, 2),
    }

    if household_gross_monthly <= fpl_200_monthly:
        status = Status.LIKELY
        rule = (
            f"Household gross income ${household_gross_monthly:,.2f}/mo <= 200% FPL "
            f"${fpl_200_monthly:,.2f}/mo; exact benefit amount set by HRA"
        )
        rule_zh = (
            f"家庭总收入每月 ${household_gross_monthly:,.2f} <= 贫困线200% 每月 "
            f"${fpl_200_monthly:,.2f}；具体福利金额由 HRA 决定"
        )
    elif "age" in profile.unknown and not profile.disability and countable <= fpl_100_monthly:
        # Over 200% FPL: whether the elderly exemption applies depends on age.
        return _missing_info("SNAP", ["age"], income_confidence)
    elif household_has_elderly_or_disabled and countable <= fpl_100_monthly:
        status = Status.LIKELY
        rule = (
            f"Household gross income ${household_gross_monthly:,.2f}/mo exceeds 200% FPL, but "
            "federal law exempts households with an elderly (60+) or disabled member from the "
            f"gross income test (7 CFR 273.9) -- net income ${countable:,.2f}/mo <= 100% FPL "
            f"${fpl_100_monthly:,.2f}/mo is enough on its own, no asset test applies"
        )
        rule_zh = (
            f"家庭总收入每月 ${household_gross_monthly:,.2f} 超过贫困线200%，但联邦法律 (7 CFR 273.9) "
            "规定有60岁以上老人或残障成员的家庭不用通过总收入审查——"
            f"净收入每月 ${countable:,.2f} <= 贫困线100% 每月 ${fpl_100_monthly:,.2f} 就足够，"
            "也不审查资产"
        )
    elif countable <= fpl_100_monthly and "savings" in profile.unknown:
        return _missing_info("SNAP", ["savings"], income_confidence)
    elif countable <= fpl_100_monthly and profile.savings <= limits.SNAP_ASSET_LIMIT.value:
        status = Status.POSSIBLE
        rule = (
            f"Household gross income ${household_gross_monthly:,.2f}/mo exceeds 200% FPL, "
            f"but net income ${countable:,.2f}/mo <= 100% FPL ${fpl_100_monthly:,.2f}/mo "
            f"and savings ${profile.savings:,.2f} <= asset limit ${limits.SNAP_ASSET_LIMIT.value:,.2f}"
        )
        rule_zh = (
            f"家庭总收入每月 ${household_gross_monthly:,.2f} 超过贫困线200%，"
            f"但净收入每月 ${countable:,.2f} <= 贫困线100% 每月 ${fpl_100_monthly:,.2f}，"
            f"且存款 ${profile.savings:,.2f} <= 资产上限 ${limits.SNAP_ASSET_LIMIT.value:,.2f}"
        )
    else:
        status = Status.NOT_NOW
        rule = (
            f"Household gross income ${household_gross_monthly:,.2f}/mo exceeds 200% FPL "
            f"${fpl_200_monthly:,.2f}/mo and net/asset test also fails"
        )
        rule_zh = (
            f"家庭总收入每月 ${household_gross_monthly:,.2f} 超过贫困线200% 每月 "
            f"${fpl_200_monthly:,.2f}，净收入/资产审查也未通过"
        )

    # Savings and the asset limit are "numbers used" only when the asset test
    # actually decided the result (otherwise an AI explanation invented a
    # comparison from them in live testing).
    if status == Status.POSSIBLE or (status == Status.NOT_NOW and countable <= fpl_100_monthly):
        numbers_used["savings"] = profile.savings
        numbers_used["asset_limit"] = limits.SNAP_ASSET_LIMIT.value

    warnings, warnings_zh = [], []
    if 60 <= profile.age <= 64 and not profile.disability and not profile.on_ssi:
        warnings.append(
            "SNAP work requirements may apply for adults age 60-64 unless disabled or exempt; confirm with HRA."
        )
        warnings_zh.append("60至64岁的成年人可能需要满足 SNAP 工作要求（残障或豁免者除外）；请向 HRA 确认。")

    return ProgramResult(
        program="SNAP",
        status=status,
        numbers_used=numbers_used,
        rule_applied=rule,
        rule_applied_zh=rule_zh,
        confidence=income_confidence,
        warnings=warnings,
        warnings_zh=warnings_zh,
    )


def _evaluate_known(profile: Profile) -> list[ProgramResult]:
    """Evaluate with every fact taken as given (profile.unknown ignored by callers)."""
    if not profile.nyc_resident:
        return [
            ProgramResult(
                program=name,
                status=Status.NOT_NOW,
                rule_applied="Program requires NYC / NY State residency",
                rule_applied_zh="此计划要求居住在纽约市 / 纽约州",
            )
            for name in ("MSP", "Extra Help", "SNAP")
        ]

    is_couple = _counts_as_couple(profile)
    ss_self, ss_spouse, income_confidence = _gross_ss_income(profile)
    earned_self = profile.earned_income_monthly or 0.0
    earned_spouse = (profile.earned_income_monthly_spouse or 0.0) if is_couple else 0.0

    countable = countable_income_msp(
        unearned_self=ss_self,
        unearned_spouse=ss_spouse,
        earned_self=earned_self,
        earned_spouse=earned_spouse,
        medigap_self=profile.medigap_premium_monthly,
        medigap_spouse=profile.medigap_premium_monthly_spouse,
        married=is_couple,
    )

    msp = _evaluate_msp(profile, countable, income_confidence)
    extra_help = _evaluate_extra_help(profile, msp, countable, income_confidence)
    snap = _evaluate_snap(profile, ss_self, ss_spouse, countable, income_confidence)

    return [msp, extra_help, snap]


# --- Preliminary estimates ------------------------------------------------------
#
# With some facts unknown, evaluate() still says what it can:
#   - it fills each unknown fact with a base value and checks, one fact at a
#     time, whether other plausible values would change any program's
#     outcome ("probes");
#   - facts that change nothing aren't asked about;
#   - facts that do change the outcome become questions. If they are all
#     facts we can state as a condition ("if you have no work income"), the
#     result is a PRELIMINARY estimate under those stated conditions;
#     otherwise (e.g. no income figure at all) the program is MISSING_INFO.
# Nothing is ever stored or shown as a fact: conditions are spelled out.

FACT_ORDER = [
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

# Facts a preliminary estimate may be conditioned on, with the value used.
CONDITION_VALUES = {
    "has_medicare": True,
    "earned_income_monthly": 0.0,
    "married": False,
    "ss_gross_monthly_spouse": 0.0,
    "earned_income_monthly_spouse": 0.0,
    "household_size": 1,
    "other_household_income_monthly": 0.0,
}

# Facts that can't be stated as a condition -- without them there's no estimate.
_PLACEHOLDER_VALUES = {"ss_gross_monthly": 0.0, "age": 0, "savings": 0.0}

CONDITION_LABELS = {
    "has_medicare": ("you have Medicare", "您有医疗保险 (Medicare)"),
    "earned_income_monthly": ("you have no income from work", "您没有工作收入"),
    "married": ("you aren't married and living with a spouse", "您没有与配偶同住"),
    "ss_gross_monthly_spouse": ("your spouse gets no Social Security", "配偶没有社会安全福利"),
    "earned_income_monthly_spouse": ("your spouse has no income from work", "配偶没有工作收入"),
    "household_size": ("you live alone", "您一个人住"),
    "other_household_income_monthly": ("no one else in your home has income", "家中其他人没有收入"),
}

_BIG = 10_000.0


def _probes(fact: str, profile: Profile) -> list[dict]:
    """Other plausible values of an unknown fact to test against."""
    unknown = profile.unknown
    if fact == "married":
        spouse_high = {
            k: _BIG for k in ("ss_gross_monthly_spouse", "earned_income_monthly_spouse") if k in unknown
        }
        return [{"married": True}, {"married": True, **spouse_high}]
    if fact == "household_size":
        probes = [{"household_size": 8}]
        if "other_household_income_monthly" in unknown:
            probes.append({"household_size": 8, "other_household_income_monthly": _BIG})
        return probes
    if fact == "has_medicare":
        return [{"has_medicare": False}]
    if fact == "age":
        return [{"age": 70}]
    if fact == "savings":
        return [{"savings": 10_000_000.0}]
    return [{fact: _BIG}]  # incomes


def _with(profile: Profile, values: dict) -> Profile:
    values = dict(values)
    if "married" in values:
        values["living_with_spouse"] = values["married"]
    placeholders = frozenset(f for f in profile.unknown if f in _PLACEHOLDER_VALUES)
    return replace(profile, unknown=frozenset(), placeholders=placeholders, **values)


def _outcome(result: ProgramResult) -> tuple:
    return (result.program, result.status)


def _conditional(result: ProgramResult, conditions: list[str]) -> ProgramResult:
    en = " and ".join(CONDITION_LABELS[f][0] for f in conditions)
    zh = "，且".join(CONDITION_LABELS[f][1] for f in conditions)
    return replace(
        result,
        preliminary=True,
        assumptions=list(conditions),
        missing_fields=list(conditions),
        rule_applied=f"If {en}: {result.rule_applied}",
        rule_applied_zh=f"如果{zh}：{result.rule_applied_zh}",
    )


_PROGRAM_SLOTS = ("MSP", "Extra Help", "SNAP")


def evaluate(profile: Profile) -> list[ProgramResult]:
    if not profile.unknown or not profile.nyc_resident:
        return _evaluate_known(profile)

    unknown = [f for f in FACT_ORDER if f in profile.unknown]
    base_values = {f: CONDITION_VALUES.get(f, _PLACEHOLDER_VALUES.get(f)) for f in unknown}
    base = _evaluate_known(_with(profile, base_values))

    changes: list[list[str]] = [[] for _ in base]
    for fact in unknown:
        for probe in _probes(fact, profile):
            probed = _evaluate_known(_with(profile, {**base_values, **probe}))
            for i, (before, after) in enumerate(zip(base, probed)):
                if _outcome(before) != _outcome(after) and fact not in changes[i]:
                    changes[i].append(fact)

    results = []
    for slot, result, facts in zip(_PROGRAM_SLOTS, base, changes):
        blocking = [f for f in facts if f in _PLACEHOLDER_VALUES]
        if blocking:
            results.append(_missing_info(slot, facts, result.confidence))
        elif facts:
            results.append(_conditional(result, facts))
        else:
            results.append(result)  # no open question could change it
    return results
