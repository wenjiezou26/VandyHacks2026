"""Integration test for the full Mei-ling Chen demo persona
(demo/fixtures/SPEC.md): FIND -> KEEP -> PROTECT across fixtures 1-4,
plus fixture 5 as the robustness check. Mock OCI (filename-dispatched),
real rules engine -- no network calls, fully deterministic.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from tests.conftest import auth_headers, upload_letter

from app.db import engine
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


def _upload(filename: str, headers: dict, language: str = "zh"):
    # Read the photo, then confirm the facts as read (the app's two steps).
    response = upload_letter(client, filename, headers, language)
    assert response.status_code == 200, response.json()
    return response.json()


def _benefits(headers: dict, language: str = "zh") -> dict:
    response = client.get("/benefits", params={"language": language}, headers=headers)
    assert response.status_code == 200, response.json()
    return {r["program"]: r for r in response.json()["results"]}


def _answer_basics(headers: dict) -> None:
    """Facts no sample letter contains, for a persona who lives alone with
    no work income: single, no earned income. (household_size comes from
    the HRA letter once it's uploaded; not needed here.)"""
    for key, value in [("earned_income_monthly", "0"), ("married", "no")]:
        assert client.post("/profile/answers", json={"key": key, "value": value}, headers=headers).status_code == 200


def test_find_qmb_and_extra_help_from_ssa_and_bank_letters():
    headers = auth_headers("meiling")
    _upload("01_ssa_benefit_letter.png", headers)
    _upload("02_bank_statement.png", headers)
    _answer_basics(headers)

    results = _benefits(headers)
    assert results["QMB"]["status"] == "likely"
    assert results["Extra Help"]["status"] in ("likely", "already_enrolled")
    # The letter's documented GROSS ($1,700), not the bank's NET deposit
    # ($1,497), must be what QMB's countable-income math used.
    assert results["QMB"]["numbers_used"]["countable_income_monthly"] == pytest.approx(1680.00)
    assert any("存款" in line for line in results["QMB"]["myth_busting_lines"])


def test_find_zero_questions_after_ssa_bank_and_hra_letters():
    """The core FIND demo flow: upload the SSA letter, bank statement, and
    HRA notice -- no manual answers at all -- and needed_questions() is
    empty. The HRA notice's single-person household_members list answers
    "married" (lives alone), and its "no one has earned income" statement answers
    earned_income_monthly -- all without asking."""
    headers = auth_headers("meiling_zero_q")
    _upload("01_ssa_benefit_letter.png", headers)
    _upload("02_bank_statement.png", headers)
    _upload("03_hra_snap_recert_notice.png", headers)

    response = client.get("/benefits", params={"language": "zh"}, headers=headers)
    body = response.json()
    assert body["questions"] == []

    results = {r["program"]: r for r in body["results"]}
    assert results["QMB"]["status"] == "likely"
    assert results["Extra Help"]["status"] == "likely"
    assert results["SNAP"]["status"] == "already_enrolled"


def test_find_age_is_read_from_the_ssa_letter_not_asked():
    headers = auth_headers("meiling_age")
    body = _upload("01_ssa_benefit_letter.png", headers)
    assert "age" in body["profile_fields_updated"]

    results = _benefits(headers)
    assert "age" not in results["SNAP"].get("missing_fields", [])


def test_keep_snap_recert_notice_sets_already_enrolled_and_deadline():
    headers = auth_headers("meiling_keep")
    _upload("01_ssa_benefit_letter.png", headers)
    _upload("02_bank_statement.png", headers)
    body = _upload("03_hra_snap_recert_notice.png", headers)

    assert body["deadline"] == "2026-11-10"
    assert body["reminder"]["program"] == "SNAP"
    assert body["reminder"]["deadline"] == "2026-11-10"

    results = _benefits(headers)
    assert results["SNAP"]["status"] == "already_enrolled"

    # household_size came from the letter -- one less thing asked about.
    assert "household_size" in body["profile_fields_updated"]


def test_keep_packet_readiness_have_partial_missing():
    headers = auth_headers("meiling_packet")
    _upload("01_ssa_benefit_letter.png", headers)
    _upload("02_bank_statement.png", headers)
    _upload("03_hra_snap_recert_notice.png", headers)

    reminders = client.get("/reminders", headers=headers).json()
    snap_reminder = next(r for r in reminders if r["program"] == "SNAP")
    status_by_item = {item["item"]: item["status"] for item in snap_reminder["packet"]["items"]}

    assert status_by_item["proof of income"] == "have"
    assert status_by_item["proof of rent"] == "partial"
    assert status_by_item["proof of utilities"] == "partial"
    assert status_by_item["proof of medical expenses"] == "partial"
    assert status_by_item["proof of identity"] == "missing"


def test_protect_flags_only_the_medicare_coinsurance_not_the_records_fee():
    headers = auth_headers("meiling_protect")
    _upload("01_ssa_benefit_letter.png", headers)
    client.post("/profile/on-qmb", params={"on_qmb": True}, headers=headers)

    body = _upload("04_clinic_bill.png", headers)
    bill_check = body["bill_check"]

    assert bill_check["has_flagged"] is True
    assert len(bill_check["flagged_line_items"]) == 1
    flagged = bill_check["flagged_line_items"][0]
    assert flagged["amount"] == pytest.approx(27.42)
    assert flagged["category"] == "coinsurance"
    # The $10 records-copy fee is explicitly NOT a Medicare-covered
    # service and must never be flagged.
    assert all("records" not in item["description"].lower() for item in bill_check["flagged_line_items"])

    assert bill_check["dispute_letter"] is not None
    assert "27.42" in bill_check["dispute_letter"]["english"]
    assert "10.00" not in bill_check["dispute_letter"]["english"].split("Total disputed amount")[0].split("\n")[-2]


def test_protect_does_not_flag_anything_when_not_on_qmb():
    headers = auth_headers("meiling_no_qmb")
    body = _upload("04_clinic_bill.png", headers)
    assert body["bill_check"]["has_flagged"] is False


def test_fixture_5_variant_is_read_independently_of_fixture_1():
    """Proves the mock dispatch (and, in real mode, the OCR pixels) is
    keyed per-fixture, not a single hardcoded SSA response -- fixture 5
    is a different person with different numbers using the same layout."""
    headers = auth_headers("elena")
    body = _upload("05_ssa_letter_variant.png", headers, language="ru")
    assert body["extracted_fields"]["gross_monthly_benefit"] == 2180.00
    assert body["extracted_fields"]["recipient_name"] == "ELENA PETROVA"
    _answer_basics(headers)

    results = _benefits(headers, language="ru")
    # Countable income $2,160/mo: over the QMB tier limit, within QI's.
    assert results["QI"]["status"] == "likely"
    assert results["Extra Help"]["status"] in ("likely", "already_enrolled")
    # Mock mode doesn't machine-translate into Russian -- it shows the
    # English text with an explicit MOCK_MODE note rather than silently
    # mistranslating or inventing Russian numbers.
    assert "MOCK_MODE" in results["QI"]["explanation"]


def test_snap_likely_from_ssa_letter_and_heap_notice_with_zero_questions():
    """Fixture 6 (HEAP notice) gives the same household facts as the SNAP
    recert notice without saying she's already on SNAP -- so SNAP is
    evaluated fresh and comes out likely, no questions asked."""
    headers = auth_headers("meiling_snap")
    _upload("01_ssa_benefit_letter.png", headers)
    _upload("02_bank_statement.png", headers)
    body = _upload("06_hra_heap_notice.png", headers)

    assert body["letter_type"] == "hra_renewal_notice"
    assert body["reminder"]["program"] == "HEAP"
    assert body["reminder"]["deadline"] == "2026-12-15"
    assert "on_snap" not in body["profile_fields_updated"]

    response = client.get("/benefits", params={"language": "zh"}, headers=headers)
    benefits = response.json()
    assert benefits["questions"] == []

    snap = {r["program"]: r for r in benefits["results"]}["SNAP"]
    assert snap["status"] == "likely"
    assert snap["numbers_used"]["household_gross_monthly_income"] == pytest.approx(1700.00)
    assert snap["numbers_used"]["fpl_200_monthly"] == pytest.approx(2660.00)
