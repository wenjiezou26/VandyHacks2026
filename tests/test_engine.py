from app.rules.engine import Confidence, Profile, Status, evaluate


def _by_program(results, name):
    return next(r for r in results if r.program == name)


def test_a_single_senior_low_income_high_savings():
    profile = Profile(
        age=74,
        has_medicare=True,
        ss_gross_monthly=1700,
        savings=40_000,
    )
    results = evaluate(profile)
    msp = _by_program(results, "QMB")
    extra_help = _by_program(results, "Extra Help")
    snap = _by_program(results, "SNAP")

    assert msp.status == Status.LIKELY
    assert extra_help.status == Status.LIKELY
    assert "QMB" in extra_help.rule_applied
    assert snap.status == Status.LIKELY


def test_b_qi_tier():
    profile = Profile(age=70, has_medicare=True, ss_gross_monthly=2200)
    results = evaluate(profile)
    msp = _by_program(results, "QI")
    extra_help = _by_program(results, "Extra Help")

    assert msp.status == Status.LIKELY
    assert extra_help.status == Status.LIKELY
    assert "QI" in extra_help.rule_applied


def test_c_medigap_deduction_pushes_to_qi():
    profile = Profile(
        age=70,
        has_medicare=True,
        ss_gross_monthly=2600,
        medigap_premium_monthly=200,
    )
    results = evaluate(profile)
    msp = _by_program(results, "QI")

    assert msp.status == Status.LIKELY
    assert msp.numbers_used["countable_income_monthly"] == 2380.0


def test_d_earned_and_unearned_income_qmb():
    profile = Profile(
        age=70,
        has_medicare=True,
        ss_gross_monthly=900,
        earned_income_monthly=1500,
    )
    results = evaluate(profile)
    msp = _by_program(results, "QMB")

    assert msp.status == Status.LIKELY
    assert msp.numbers_used["countable_income_monthly"] == 1597.5


def test_e_married_couple_uses_couple_limits():
    profile = Profile(
        age=72,
        married=True,
        has_medicare=True,
        ss_gross_monthly=1200,
        ss_gross_monthly_spouse=1200,
    )
    results = evaluate(profile)
    msp = _by_program(results, "QMB")

    # combined 2400 - 20 disregard = 2380, under couple QMB limit (2489)
    assert msp.status == Status.LIKELY
    assert msp.numbers_used["countable_income_monthly"] == 2380.0


def test_married_living_separately_uses_single_limits_not_couple():
    # Verified against the Medicare Rights Center's 2026 NY MSP training
    # deck: income is combined and couple limits apply only when "married
    # and living together" -- living apart means each spouse is budgeted
    # as an individual. Same two incomes, opposite outcomes depending on
    # living_with_spouse.
    living_together = Profile(
        age=72,
        married=True,
        living_with_spouse=True,
        has_medicare=True,
        ss_gross_monthly=1700,
        ss_gross_monthly_spouse=3000,
    )
    living_apart = Profile(
        age=72,
        married=True,
        living_with_spouse=False,
        has_medicare=True,
        ss_gross_monthly=1700,
        ss_gross_monthly_spouse=3000,
    )

    together_result = _by_program(evaluate(living_together), "MSP")
    apart_result = _by_program(evaluate(living_apart), "QMB")

    # Combined income (1700+3000-20=4680) blows past even the couple QI
    # limit (3355) -> not_now.
    assert together_result.status == Status.NOT_NOW
    # Applicant's own income alone (1700-20=1680) qualifies for QMB under
    # the single limit (1836) -- spouse's income is correctly excluded.
    assert apart_result.status == Status.LIKELY
    assert apart_result.numbers_used["countable_income_monthly"] == 1680.0


def test_f_ssdi_disability_no_work_warning():
    profile = Profile(
        age=62,
        has_medicare=True,
        disability=True,
        ss_gross_monthly=1500,
        savings=2000,
    )
    results = evaluate(profile)
    msp_or_tier = next(r for r in results if r.program in ("QMB", "QI", "MSP"))
    snap = _by_program(results, "SNAP")

    assert msp_or_tier.status == Status.LIKELY
    assert snap.status == Status.LIKELY
    assert snap.warnings == []


def test_g_no_medicare_part_time_job_work_warning():
    profile = Profile(
        age=62,
        has_medicare=False,
        earned_income_monthly=1200,
    )
    results = evaluate(profile)
    msp = _by_program(results, "MSP")
    extra_help = _by_program(results, "Extra Help")
    snap = _by_program(results, "SNAP")

    assert msp.status == Status.NOT_NOW
    assert extra_help.status == Status.NOT_NOW
    assert snap.status == Status.LIKELY
    assert any("work requirement" in w.lower() for w in snap.warnings)


def test_h_bank_deposit_only_estimated_confidence():
    profile = Profile(
        age=75,
        has_medicare=True,
        bank_deposit_monthly=1500,
    )
    results = evaluate(profile)
    msp = _by_program(results, "QMB")

    assert msp.status == Status.LIKELY
    assert msp.confidence == Confidence.ESTIMATED


def test_i_already_on_medicaid_extra_help_already_enrolled():
    profile = Profile(
        age=70,
        has_medicare=True,
        on_medicaid=True,
        ss_gross_monthly=1200,
    )
    results = evaluate(profile)
    extra_help = _by_program(results, "Extra Help")
    snap = _by_program(results, "SNAP")

    assert extra_help.status == Status.ALREADY_ENROLLED
    assert snap is not None


def test_j_income_too_high_not_now_with_explanation():
    profile = Profile(age=70, has_medicare=True, ss_gross_monthly=3000)
    results = evaluate(profile)
    msp = _by_program(results, "MSP")
    extra_help = _by_program(results, "Extra Help")
    snap = _by_program(results, "SNAP")

    assert msp.status == Status.NOT_NOW
    assert "exceeds" in msp.rule_applied
    assert extra_help.status == Status.NOT_NOW
    assert snap.status == Status.NOT_NOW


def test_k_elderly_exempt_from_snap_gross_test_and_asset_test():
    # Fails the 200% FPL gross test ($2,700 > $2,660) but federal law (7 CFR
    # 273.9) exempts elderly households from that test -- net income
    # ($1,307.50) clears 100% FPL ($1,330) with no asset test, so this
    # should be LIKELY even with savings well above the $4,500 asset limit.
    profile = Profile(age=65, earned_income_monthly=2700, savings=10_000)
    results = evaluate(profile)
    snap = _by_program(results, "SNAP")

    assert snap.status == Status.LIKELY
    assert "elderly" in snap.rule_applied.lower()


def test_l_non_elderly_still_needs_net_and_asset_test():
    # Same income shape as test K, but under 60 and not disabled -- the
    # elderly/disabled exemption doesn't apply, so the old net+asset rule
    # still governs.
    high_savings = Profile(age=45, earned_income_monthly=2700, savings=10_000)
    low_savings = Profile(age=45, earned_income_monthly=2700, savings=2_000)

    high_savings_snap = _by_program(evaluate(high_savings), "SNAP")
    low_savings_snap = _by_program(evaluate(low_savings), "SNAP")

    assert high_savings_snap.status == Status.NOT_NOW
    assert low_savings_snap.status == Status.POSSIBLE


def test_snap_lists_savings_only_when_the_asset_test_decided():
    under_200 = _by_program(evaluate(Profile(age=70, has_medicare=True, ss_gross_monthly=1700, savings=40_000)), "SNAP")
    assert "savings" not in under_200.numbers_used
    asset_test = _by_program(evaluate(Profile(age=45, earned_income_monthly=2700, savings=10_000)), "SNAP")
    assert asset_test.numbers_used["savings"] == 10_000
    assert asset_test.numbers_used["asset_limit"] == 4500


def test_preliminary_result_lists_the_open_facts_it_depends_on():
    profile = Profile(
        nyc_resident=True, age=70, ss_gross_monthly=1700, has_medicare=True,
        unknown=frozenset({"earned_income_monthly", "married", "household_size", "savings",
                           "ss_gross_monthly_spouse", "earned_income_monthly_spouse",
                           "other_household_income_monthly"}),
    )
    msp = evaluate(profile)[0]
    assert msp.program == "QMB" and msp.status == Status.LIKELY
    assert msp.preliminary is True
    assert msp.missing_fields == ["earned_income_monthly", "married"]


def test_snap_net_test_counts_other_household_members_income():
    profile = Profile(
        nyc_resident=True, age=74, ss_gross_monthly=1700, has_medicare=True,
        household_size=2, other_household_income_monthly=10_000,
    )
    snap = next(r for r in evaluate(profile) if r.program == "SNAP")
    assert snap.status == Status.NOT_NOW


def test_unknown_income_is_missing_info_not_a_guess():
    profile = Profile(nyc_resident=True, age=70, has_medicare=True, unknown=frozenset({"ss_gross_monthly"}))
    assert {r.status for r in evaluate(profile)} == {Status.MISSING_INFO}
