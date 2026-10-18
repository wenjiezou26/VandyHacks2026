import pytest

from app.explain import explain_results, myth_busting_lines
from app.explain.oci_client import explain_program_result
from app.number_guard import assert_numbers_preserved
from app.rules.engine import Profile, Status, evaluate


def _by_program(results, name):
    return next(r for r in results if r.program == name)


def test_savings_myth_applies_to_msp_but_not_snap_or_standalone_extra_help():
    profile = Profile(age=74, has_medicare=True, ss_gross_monthly=1700, savings=40_000)
    results = evaluate(profile)

    qmb = _by_program(results, "QMB")
    extra_help = _by_program(results, "Extra Help")
    snap = _by_program(results, "SNAP")

    qmb_myths = myth_busting_lines(qmb, profile)
    snap_myths = myth_busting_lines(snap, profile)

    assert any("savings don't count" in line for line in qmb_myths)
    assert not any("savings don't count" in line for line in snap_myths)
    # Extra Help here is auto-via-MSP, so it gets the "you can still get it" myth,
    # not the savings myth (Extra Help isn't in the resource-free program set).
    extra_help_myths = myth_busting_lines(extra_help, profile)
    assert any("can still get Extra Help" in line for line in extra_help_myths)
    assert not any("savings don't count" in line for line in extra_help_myths)


def test_owns_home_myth_applies_broadly():
    profile = Profile(age=74, has_medicare=True, ss_gross_monthly=1700, owns_home=True)
    results = evaluate(profile)
    snap = _by_program(results, "SNAP")

    assert any("home doesn't count" in line for line in myth_busting_lines(snap, profile))


def test_no_myths_when_nothing_applies():
    profile = Profile(age=74, has_medicare=True, ss_gross_monthly=1700)
    results = evaluate(profile)
    snap = _by_program(results, "SNAP")

    assert myth_busting_lines(snap, profile) == []


def test_extra_help_standalone_not_now_gets_no_auto_myth():
    # income too high for MSP, also too high for standalone Extra Help
    profile = Profile(age=70, has_medicare=True, ss_gross_monthly=3000)
    results = evaluate(profile)
    extra_help = _by_program(results, "Extra Help")

    assert extra_help.status == Status.NOT_NOW
    assert myth_busting_lines(extra_help, profile) == []


def test_explain_results_mock_mode_returns_one_per_program():
    profile = Profile(age=74, has_medicare=True, ss_gross_monthly=1700, savings=40_000)
    results = evaluate(profile)

    explained = explain_results(results, profile, "en")

    assert len(explained) == len(results)
    programs = {e.program for e in explained}
    assert programs == {"QMB", "Extra Help", "SNAP"}
    for item in explained:
        assert item.explanation
        assert item.disclaimer == "Final decision is made by NY State / HRA / SSA, not this app."
        assert item.numbers_used
        assert item.rule_applied


def test_explain_results_non_english_flags_mock_untranslated():
    profile = Profile(age=74, has_medicare=True, ss_gross_monthly=1700)
    results = evaluate(profile)

    explained = explain_results(results, profile, "ko")

    assert all("MOCK_MODE" in e.explanation for e in explained)


def test_explain_program_result_mock_does_not_invent_numbers():
    import json

    profile = Profile(age=74, has_medicare=True, ss_gross_monthly=1700)
    results = evaluate(profile)
    qmb = _by_program(results, "QMB")

    explanation = explain_program_result(qmb, "en")
    # every number in the mock explanation must trace back to numbers_used,
    # rule_applied, or the Part B premium monthly_value it reports.
    source = json.dumps(qmb.numbers_used) + qmb.rule_applied + f"{qmb.monthly_value:.2f}"
    assert_numbers_preserved(explanation, source)


def test_number_guard_rejects_invented_numbers():
    with pytest.raises(ValueError):
        assert_numbers_preserved("You get $9,999 a month.", "You get $1,700 a month.")


def test_number_guard_allows_subset_of_source_numbers():
    assert_numbers_preserved("You get $1,700 a month.", "Gross: $1,700.00, Net: $1,497.10")


def test_dollar_amounts_are_formatted_like_the_facts_table():
    from app.number_guard import format_dollar_amounts

    assert format_dollar_amounts("You have $40000.0 and $1700.0.") == "You have $40,000.00 and $1,700.00."
    assert format_dollar_amounts("余额 40000.0 美元。") == "余额 $40,000.00。"
    assert format_dollar_amounts("$1,700.00, $20 later") == "$1,700.00, $20.00 later"


def test_hra_document_names_are_translated_with_their_notes():
    from app.i18n import document_name_zh

    assert document_name_zh("Proof of rent (lease or rent receipt)") == "房租证明（租约或房租收据）"
    assert document_name_zh("Proof of identity") == "身份证明"
    assert document_name_zh("Birth certificate") == "Birth certificate"  # unknown: left as written


def test_missing_info_list_reads_as_a_sentence():
    from app.explain.oci_client import template_explanation
    from app.rules.engine import ProgramResult, Status

    result = ProgramResult(program="MSP", status=Status.MISSING_INFO, missing_fields=["has_medicare", "ss_gross_monthly", "married"])
    assert ", and whether you're married" in template_explanation(result, "en")
