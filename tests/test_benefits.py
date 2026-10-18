import io

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, upload_letter
from sqlmodel import SQLModel

from app.db import engine
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


def _upload(filename: str, language: str = "en", user_id: str = "demo"):
    return upload_letter(client, filename, auth_headers(user_id), language)


def _answer(key: str, value: str, user_id: str = "demo"):
    return client.post("/profile/answers", json={"key": key, "value": value}, headers=auth_headers(user_id))


def _by_program(user_id: str = "demo") -> dict:
    body = client.get("/benefits", headers=auth_headers(user_id)).json()
    return {b["program"]: b for b in body["results"]}, body


def test_new_user_gets_more_information_needed_not_a_guess():
    # Nothing known yet: unknown income is not $0, unknown Medicare is not "no".
    results, body = _by_program("nobody")
    assert {r["status"] for r in results.values()} == {"missing_info"}
    assert not any(r["preliminary"] for r in results.values())
    # Facts that block every result come first; Social Security income
    # matters to all three programs.
    assert body["questions"][0] == "ss_gross_monthly"
    assert set(body["question_programs"]["ss_gross_monthly"]) == {"MSP", "Extra Help", "SNAP"}
    assert all(r["monthly_value"] == 0 for r in results.values())


def test_ssa_letter_alone_gives_a_preliminary_result_with_its_conditions():
    _upload("ssa_sample.jpg")
    results, body = _by_program()
    # Shown right away, but marked preliminary: it depends on facts not yet
    # known, which are listed rather than guessed.
    assert results["QMB"]["status"] == "likely"
    assert results["QMB"]["preliminary"] is True
    assert set(results["QMB"]["missing_fields"]) == {"earned_income_monthly", "married"}
    assert results["QMB"]["assumptions"]
    assert "has_medicare" not in body["questions"]  # the SSA letter shows a Part B deduction
    assert body["questions"][:2] == ["earned_income_monthly", "married"]
    assert body["uses_sample_data"] is True  # MOCK_MODE letters are samples


def test_answering_the_questions_resolves_results():
    _upload("ssa_sample.jpg")
    assert _answer("earned_income_monthly", "none").json()["value"] == "0"
    assert _answer("married", "no").status_code == 200
    _answer("household_size", "1")
    results, body = _by_program()

    assert results["QMB"]["status"] == "likely"
    assert results["QMB"]["preliminary"] is False
    assert results["QMB"]["numbers_used"]["countable_income_monthly"] == 1680.0
    assert results["Extra Help"]["status"] == "likely"
    assert results["SNAP"]["status"] == "likely"
    assert body["questions"] == []


def test_married_living_together_asks_for_spouse_income():
    _upload("ssa_sample.jpg")
    _answer("earned_income_monthly", "0")
    _answer("married", "yes")
    results, _ = _by_program()
    assert results["QMB"]["preliminary"] is True
    assert set(results["QMB"]["missing_fields"]) == {"ss_gross_monthly_spouse", "earned_income_monthly_spouse"}


def test_bigger_household_asks_for_other_members_income():
    _upload("ssa_sample.jpg")
    _answer("earned_income_monthly", "0")
    _answer("married", "no")
    _answer("household_size", "3")
    results, _ = _by_program()
    assert results["SNAP"]["missing_fields"] == ["other_household_income_monthly"]


def test_unknown_medicare_is_asked_not_assumed_no():
    _upload("bank_sample.jpg")  # income estimate + savings, nothing about Medicare
    results, body = _by_program()
    msp = next(r for r in results.values() if r["program"] in ("QMB", "SLMB", "QI", "MSP"))
    assert msp["preliminary"] is True
    assert "has_medicare" in msp["missing_fields"]
    assert "has_medicare" in body["questions"]
    _answer("has_medicare", "no")
    results, body = _by_program()
    assert results["MSP"]["status"] == "not_now"
    assert results["MSP"]["preliminary"] is False
    assert "has_medicare" not in body["questions"]  # answered: never asked again


@pytest.mark.parametrize(
    "key,value",
    [("earned_income_monthly", "-500"), ("household_size", "0"), ("household_size", "1.5"), ("age", "500")],
)
def test_bad_answers_are_rejected(key, value):
    response = _answer(key, value)
    assert response.status_code == 422
    assert response.json()["detail_zh"]


def test_unknown_question_is_rejected():
    assert _answer("favorite_color", "blue").status_code == 404


def test_answers_need_sign_in():
    assert client.post("/profile/answers", json={"key": "age", "value": "70"}).status_code == 401


def test_benefits_language_param_passed_through():
    _upload("ssa_sample.jpg")
    response = client.get("/benefits", params={"language": "zh"}, headers=auth_headers("demo"))
    results = response.json()["results"]
    # Preliminary results use a fixed, translated template.
    assert all("初步估计" in b["explanation"] for b in results)
    for key, value in [("earned_income_monthly", "0"), ("married", "no"), ("household_size", "1")]:
        _answer(key, value)
    response = client.get("/benefits", params={"language": "ko"}, headers=auth_headers("demo"))
    results = response.json()["results"]
    assert all("MOCK_MODE" in b["explanation"] for b in results)


def test_benefits_trace_shows_rules_engine_not_ai_for_eligibility():
    _upload("ssa_sample.jpg")
    response = client.get("/benefits", headers=auth_headers("demo"))
    trace = response.json()["trace"]

    step_names = [s["name"] for s in trace]
    assert "Checked eligibility" in step_names

    eligibility_step = next(s for s in trace if s["name"] == "Checked eligibility")
    assert eligibility_step["service"] == "Rules engine (no AI)"
    assert eligibility_step["success"] is True

    explain_step = next(s for s in trace if s["name"] == "Explained each result")
    assert "OCI Generative AI" in explain_step["service"]


def test_unknown_savings_are_not_shown_as_zero():
    _upload("ssa_sample.jpg")
    for key, value in [("earned_income_monthly", "0"), ("married", "no"), ("household_size", "1")]:
        _answer(key, value)
    results, _ = _by_program()
    assert results["SNAP"]["status"] == "likely"
    assert "savings" not in results["SNAP"]["numbers_used"]
    _answer("savings", "2000")
    results, _ = _by_program()
    # Under 200% of the poverty line savings don't matter, so they aren't
    # listed as "numbers used" even once known.
    assert "savings" not in results["SNAP"]["numbers_used"]


def test_questions_are_ranked_by_how_much_they_can_change():
    """Each question lists the programs whose result it could change, and
    the ones affecting the most programs come first. Facts that change
    nothing (e.g. household size once SNAP is settled) aren't asked."""
    _upload("ssa_sample.jpg")
    _, body = _by_program()
    programs = body["question_programs"]
    counts = [len(programs[q]) for q in body["questions"]]
    assert counts == sorted(counts, reverse=True)
    assert programs["household_size"] == ["SNAP"]
    for key, value in [("earned_income_monthly", "0"), ("married", "no"), ("household_size", "1")]:
        _answer(key, value)
    _, body = _by_program()
    assert body["questions"] == []
