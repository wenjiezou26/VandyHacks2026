"""Privacy lifecycle: read saves nothing, confirm saves only checked facts,
uploads are always released, logs stay clean, and "delete my data" only
touches the signed-in user's records. Synthetic records only."""

import asyncio
import io
import sys

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select
from starlette.datastructures import UploadFile

from app.db import engine
from app.main import app
from app.models import ApplicationRecord, AuthSession, LetterRecord, ProfileRecord, Reminder
from tests.conftest import auth_headers, upload_letter

# The modules themselves (the packages export their APIRouter as `router`,
# which shadows the module name).
docs_router = sys.modules["app.docs.router"]
apply_router_module = sys.modules["app.apply.router"]

client = TestClient(app)
ALICE, BOB = "alice-synthetic", "bob-synthetic"


@pytest.fixture(autouse=True)
def _reset_db():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


def _read(filename: str, user: str = ALICE, data: bytes = b"fake-image-bytes"):
    return client.post(
        "/letters/read",
        files={"file": (filename, io.BytesIO(data), "image/jpeg")},
        data={"language": "en"},
        headers=auth_headers(user),
    )


def _confirm(draft: dict, user: str = ALICE, facts: dict | None = None, save_identifiers: bool = False):
    return client.post(
        "/letters/confirm",
        json={
            "draft_token": draft["draft_token"],
            "facts": draft["facts"] if facts is None else facts,
            "save_identifiers": save_identifiers,
        },
        headers=auth_headers(user),
    )


def _count(model, user: str) -> int:
    with Session(engine) as session:
        return len(session.exec(select(model).where(model.user_id == user)).all())


# --- read saves nothing; confirm saves only checked, minimized facts ----------


def test_reading_saves_nothing():
    draft = _read("hra_sample.jpg").json()
    assert draft["letter_type"] == "hra_renewal_notice"
    assert _count(LetterRecord, ALICE) == 0
    assert _count(Reminder, ALICE) == 0
    with Session(engine) as session:
        assert session.get(ProfileRecord, ALICE) is None


def test_confirm_saves_minimized_facts_without_identifiers_by_default():
    draft = _read("ssa_sample.jpg").json()
    assert draft["identifiers"] == {
        "recipient_name": "Chen, Yu-lan",
        "recipient_address": "123 Northern Blvd, Apt 4B, Flushing, NY 11354",
    }
    assert "recipient_name" not in draft["facts"]

    saved = _confirm(draft).json()
    assert "recipient_name" not in saved["extracted_fields"]
    with Session(engine) as session:
        record = session.exec(select(LetterRecord)).one()
        assert set(record.extracted_fields) == {"gross_monthly_benefit", "part_b_deduction", "net_payment", "effective_date"}
        assert "Chen" not in (record.explanation or "")


def test_identifiers_saved_only_when_the_user_opts_in():
    draft = _read("ssa_sample.jpg").json()
    saved = _confirm(draft, facts={**draft["facts"], **draft["identifiers"]}, save_identifiers=True).json()
    assert saved["extracted_fields"]["recipient_name"] == "Chen, Yu-lan"


def test_free_text_summaries_and_bank_descriptions_are_not_kept():
    other = _read("photo.jpg").json()  # unrecognized -> "other" with an OCR summary
    assert other["letter_type"] == "other"
    assert _confirm(other).json()["extracted_fields"] == {}

    bank = _read("bank_sample.jpg").json()
    deposits = _confirm(bank).json()["extracted_fields"]["recurring_deposits"]
    assert deposits == [{"description": "", "amount": 1700.0}]


def test_user_corrections_are_validated_saved_and_used():
    draft = _read("ssa_sample.jpg").json()
    bad = _confirm(draft, facts={**draft["facts"], "gross_monthly_benefit": "-5"})
    assert bad.status_code == 422 and bad.json()["detail_zh"]
    assert _count(LetterRecord, ALICE) == 0

    saved = _confirm(draft, facts={**draft["facts"], "gross_monthly_benefit": "1650"}).json()
    assert saved["extracted_fields"]["gross_monthly_benefit"] == 1650.0
    assert saved["corrected_fields"] == ["gross_monthly_benefit"]
    with Session(engine) as session:
        assert session.get(ProfileRecord, ALICE).ss_gross_monthly == 1650.0


def test_explanation_step_never_receives_identifiers(monkeypatch):
    from app.docs import oci_client

    seen = []
    real = oci_client.explain_letter
    monkeypatch.setattr(oci_client, "explain_letter", lambda t, f, lang: seen.append(dict(f)) or real(t, f, lang))
    draft = _read("ssa_sample.jpg").json()
    _confirm(draft, facts={**draft["facts"], "net_payment": "1400"})  # correction -> re-explained
    assert len(seen) == 2
    assert all("recipient_name" not in f and "recipient_address" not in f for f in seen)


# --- drafts can't be reused, altered or expired -------------------------------------


def test_another_users_draft_is_rejected():
    draft = _read("ssa_sample.jpg", user=ALICE).json()
    response = _confirm(draft, user=BOB)
    assert response.status_code == 410
    assert _count(LetterRecord, BOB) == 0


def test_tampered_draft_is_rejected():
    draft = _read("ssa_sample.jpg").json()
    body, mac = draft["draft_token"].split(".")
    flipped = ("A" if body[5] != "A" else "B")
    response = _confirm({**draft, "draft_token": f"{body[:5]}{flipped}{body[6:]}.{mac}"})
    assert response.status_code == 410


def test_expired_draft_is_rejected(monkeypatch):
    from app.docs import drafts

    draft = _read("ssa_sample.jpg").json()
    monkeypatch.setattr(drafts.time, "time", lambda: 10**12)
    assert _confirm(draft).status_code == 410


# --- the original is released on success, failure and cancellation ------------------


@pytest.fixture
def spy(monkeypatch):
    """Record every upload handle and buffer the letter endpoint touches."""
    seen = {"uploads": [], "buffers": []}
    real_read_and_close = docs_router.read_and_close

    async def recording_read_and_close(upload):
        seen["uploads"].append(upload)
        buffer = await real_read_and_close(upload)
        seen["buffers"].append(buffer)
        return buffer

    monkeypatch.setattr(docs_router, "read_and_close", recording_read_and_close)
    return seen


def _released(seen) -> bool:
    return (
        seen["uploads"]
        and all(u.file.closed for u in seen["uploads"])
        and all(not any(b) for b in seen["buffers"])  # our copy overwritten with zeros
    )


def test_original_released_after_success(spy):
    assert _read("ssa_sample.jpg").status_code == 200
    assert _released(spy)


def test_large_original_spooled_to_disk_is_closed(spy):
    # > 1 MB: Starlette rolls this upload over to a temporary file on disk.
    assert _read("ssa_sample.jpg", data=b"x" * (2 * 1024 * 1024)).status_code == 200
    assert spy["uploads"][0].file._rolled  # it really was on disk
    assert _released(spy)


def test_original_released_after_failed_reading(spy, monkeypatch):
    from app.docs import oci_client

    def ocr_down(image):
        raise RuntimeError("OCI unreachable")

    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setattr(oci_client, "_real_ocr", ocr_down)
    response = _read("ssa_sample.jpg")
    assert response.status_code == 502 and response.json()["retryable"] is True
    assert _released(spy)
    assert _count(LetterRecord, ALICE) == 0


def test_too_large_original_is_rejected_and_released(spy, monkeypatch):
    from app import uploads

    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 1024)
    assert _read("ssa_sample.jpg", data=b"x" * 5000).status_code == 413
    assert all(u.file.closed for u in spy["uploads"])


def test_original_released_when_the_request_is_cancelled(monkeypatch):
    # The client went away mid-read: the await is cancelled. Nothing is
    # half-saved (reading writes nothing) and the upload is still released.
    captured = {}

    async def cancelled(*args, **kwargs):
        captured["image"] = kwargs["image"]
        raise asyncio.CancelledError()

    monkeypatch.setattr(docs_router, "run_in_threadpool", cancelled)
    upload = UploadFile(file=io.BytesIO(b"original-photo-bytes"), filename="ssa.jpg")
    auth = AuthSession(token="t", user_id=ALICE, phone="0000000000")

    async def call():
        with Session(engine) as session:
            await docs_router.read_letter(file=upload, language="en", auth=auth, session=session)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call())
    assert upload.file.closed
    assert not any(captured["image"])
    assert _count(LetterRecord, ALICE) == 0


def test_document_photo_for_an_application_is_released(monkeypatch):
    apply_router = apply_router_module
    seen = []
    real = apply_router.read_and_close

    async def recording(upload):
        seen.append(upload)
        return await real(upload)

    monkeypatch.setattr(apply_router, "read_and_close", recording)
    headers = auth_headers(ALICE)
    app_id = client.post("/applications", json={"program": "MSP"}, headers=headers).json()["id"]
    response = client.post(
        f"/applications/{app_id}/documents/medicare_card",
        files={"file": ("card.jpg", io.BytesIO(b"card-photo"), "image/jpeg")},
        headers=headers,
    )
    assert response.status_code == 200
    assert seen and seen[0].file.closed


# --- logs ----------------------------------------------------------------------------


def test_failed_reading_logs_no_letter_contents(monkeypatch, caplog):
    from app.docs import oci_client

    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setattr(oci_client, "_real_ocr", lambda image: oci_client._mock_ocr("ssa.jpg"))
    monkeypatch.setattr(oci_client, "_real_classify", oci_client._mock_classify)
    # Invalid extraction that echoes the letter (as validation errors do).
    monkeypatch.setattr(
        oci_client, "_real_extract", lambda *a: {"gross_monthly_benefit": "Chen, Yu-lan 123 Northern Blvd"}
    )
    with caplog.at_level("WARNING"):
        assert _read("photo.jpg").status_code == 502
    assert "ValidationError" in caplog.text or "ExtractionError" in caplog.text
    assert "Chen" not in caplog.text and "Northern" not in caplog.text


# --- delete my saved information -----------------------------------------------------


def _make_data(user: str) -> None:
    headers = auth_headers(user)
    upload_letter(client, "ssa_sample.jpg", headers)
    upload_letter(client, "hra_sample.jpg", headers)
    client.post("/profile/answers", json={"key": "age", "value": "74"}, headers=headers)
    client.post("/applications", json={"program": "MSP"}, headers=headers)


def test_delete_my_data_removes_everything_saved_for_that_user_only():
    _make_data(ALICE)
    _make_data(BOB)
    with Session(engine) as session:
        session.exec(select(ApplicationRecord).where(ApplicationRecord.user_id == ALICE)).one().signature_png = (
            "data:image/png;base64,AAAA"
        )
        session.commit()

    response = client.post("/me/delete-data", json={"confirm": True}, headers=auth_headers(ALICE))
    assert response.status_code == 200
    assert response.json() == {"letters": 2, "reminders": 1, "profile": 1, "applications": 1, "sessions": 1}

    for model in (LetterRecord, Reminder, ProfileRecord, ApplicationRecord, AuthSession):
        assert _count(model, ALICE) == 0
    # Bob's data is untouched.
    assert _count(LetterRecord, BOB) == 2
    assert _count(ApplicationRecord, BOB) == 1
    assert _count(ProfileRecord, BOB) == 1


def test_delete_signs_the_user_out():
    _make_data(ALICE)
    client.post("/me/delete-data", json={"confirm": True}, headers=auth_headers(ALICE).copy())
    # auth_headers() re-creates the session for tests, so use the raw token.
    token_headers = {"Authorization": f"Bearer test-token-{ALICE}"}
    assert client.get("/letters", headers=token_headers).status_code == 401


def test_delete_requires_sign_in_and_confirmation():
    _make_data(ALICE)
    assert client.post("/me/delete-data", json={"confirm": True}).status_code == 401
    assert client.post("/me/delete-data", json={"confirm": False}, headers=auth_headers(ALICE)).status_code == 422
    assert _count(LetterRecord, ALICE) == 2


def test_privacy_info_reports_sample_mode():
    body = client.get("/privacy/info").json()
    assert body == {"sample_mode": True, "oci_region": None, "original_photos_stored": False}


def test_user_can_remove_a_wrongly_read_list_item():
    draft = _read("hra_sample.jpg").json()
    assert draft["editable"]["required_documents"] == "list"
    saved = _confirm(draft, facts={**draft["facts"], "required_documents": "proof of income\n\nID\n"}).json()
    assert saved["extracted_fields"]["required_documents"] == ["proof of income", "ID"]
    assert saved["corrected_fields"] == ["required_documents"]
    assert saved["reminder"]["checklist"] == ["proof of income", "ID"]


def test_explanation_only_sees_saved_facts(monkeypatch):
    # Bank deposit descriptions aren't saved, so the (saved) explanation
    # mustn't be built from them either.
    from app.docs import oci_client

    seen = []
    real = oci_client.explain_letter
    monkeypatch.setattr(oci_client, "explain_letter", lambda t, f, lang: seen.append(f) or real(t, f, lang))
    _read("bank_sample.jpg")
    assert seen[0]["recurring_deposits"] == [{"description": "", "amount": 1700.0}]


def test_date_of_birth_sets_age_but_is_not_stored(monkeypatch):
    from app.docs import oci_client

    real_extract = oci_client._mock_extract

    def with_dob(letter_type, raw_text):
        fields = real_extract(letter_type, raw_text)
        if letter_type.value == "ssa_benefit_letter":
            fields["date_of_birth"] = "1952-03-05"
        return fields

    monkeypatch.setattr(oci_client, "_mock_extract", with_dob)
    draft = _read("ssa_sample.jpg").json()
    assert draft["facts"]["date_of_birth"] == "1952-03-05"  # shown and correctable
    saved = _confirm(draft).json()
    assert "date_of_birth" not in saved["extracted_fields"]
    with Session(engine) as session:
        profile = session.get(ProfileRecord, ALICE)
        assert profile.age >= 74 and profile.is_known("age")
        record = session.exec(select(LetterRecord)).one()
        assert "1952" not in str(record.extracted_fields) and "1952" not in (record.explanation or "")


def test_pay_stub_keeps_pay_but_not_employer_or_pay_date():
    draft = _read("pay_stub_sample.jpg").json()
    assert draft["letter_type"] == "pay_stub"
    saved = _confirm(draft).json()
    assert set(saved["extracted_fields"]) == {"gross_pay", "pay_period"}


def test_facts_derived_from_the_hra_notice_can_be_corrected():
    draft = _read("03_hra_snap_recert_notice.png").json()
    assert draft["editable"]["household_members"] == "people"
    assert len(draft["facts"]["household_members"]) == 1
    facts = dict(draft["facts"], household_members="Mei-ling Chen\nWei Chen", household_has_earned_income=True)
    assert _confirm(draft, facts=facts).status_code == 200
    with Session(engine) as session:
        profile = session.get(ProfileRecord, ALICE)
        # Two people: "lives alone" is no longer inferred, and work income
        # is left unknown rather than taken as $0.
        assert not profile.is_known("married")
        assert not profile.is_known("earned_income_monthly")
        letter = session.exec(select(LetterRecord).where(LetterRecord.user_id == ALICE)).one()
        assert "household_members" not in letter.extracted_fields  # used once, never saved
