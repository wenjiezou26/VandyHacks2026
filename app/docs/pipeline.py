"""Orchestrates the four document-pipeline steps for one uploaded letter.

OCR -> classify -> extract (validate, retry once) -> merge into Profile.
Raw image bytes are read into memory by the caller and never written to
disk or to the database -- this module never sees a file path.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlmodel import Session, select

from app.apply.normalize import FieldValueError, normalize
from app.i18n import document_name_zh, is_zh
from app.keep.reminders import create_reminder, to_reminder_out
from app.models import LetterRecord, ProfileRecord, Reminder
from app.number_guard import format_dollar_amounts
from app.privacy import EDITABLE_FIELDS, IDENTIFIER_FIELDS, describe_failure, minimize, transient
from app.protect.bill_check import check_qmb_bill
from app.protect.oci_client import draft_dispute_letter
from app.protect.schemas import DisputeLetter
from app.trace import Trace, is_mock_mode, mock_suffix, trace_to_out

from . import oci_client
from .profile_merge import merge_fields_into_profile
from .drafts import open_draft, sign_draft
from .schemas import SCHEMA_BY_TYPE, LetterDraftOut, LetterType, LetterUploadResponse


log = logging.getLogger("letterlens.oci")


class ExtractionError(Exception):
    pass


class LetterReadError(Exception):
    """The letter couldn't be read. Nothing was saved; the user can retry."""

    message_en = "We couldn't read this letter. Nothing was saved. Please try again with a clear, flat photo."
    message_zh = "我们没能读懂这封信，没有保存任何内容。请拍一张清楚、平整的照片再试一次。"


def _get_or_create_profile(session: Session, user_id: str) -> ProfileRecord:
    profile = session.get(ProfileRecord, user_id)
    if profile is None:
        profile = ProfileRecord(user_id=user_id)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def _action_items_and_deadline(
    letter_type: LetterType, fields: dict, language: str = "en"
) -> tuple[list[str], date | None]:
    zh = is_zh(language)
    if letter_type == LetterType.SSA_BENEFIT_LETTER:
        if zh:
            return (["这封信请留好备查，目前不需要做什么。", "请保存好——社工可能会问您每月福利（扣除前）的金额。"], None)
        return (
            [
                "This letter is for your records. No action needed right now.",
                "Keep it -- caseworkers may ask for your gross monthly benefit amount.",
            ],
            None,
        )
    if letter_type == LetterType.BANK_STATEMENT:
        if zh:
            return (["不需要做什么。我们用它来估算您的收入。"], None)
        return (["No action needed. We used this to estimate your income."], None)
    if letter_type == LetterType.HRA_RENEWAL_NOTICE:
        deadline = fields.get("deadline")
        required = fields.get("required_documents", [])
        if zh:
            docs = "、".join(document_name_zh(d) for d in required) or "通知里列出的文件"
            return ([f"请在 {deadline} 之前提交：{docs}"], deadline)
        docs = ", ".join(required) or "the documents listed in the notice"
        return ([f"Submit by {deadline}: {docs}"], deadline)
    if letter_type == LetterType.MEDICAL_BILL:
        if zh:
            return (
                ["付款前，请先对照您的医疗保险 (Medicare) 承保范围检查这张账单。", "如果您有 QMB，您可能依法不用付这笔钱——请按“检查这张账单”。"],
                None,
            )
        return (
            [
                "Check this bill against your Medicare coverage before paying.",
                "If you have QMB, you may not legally owe this -- tap \"Check this bill.\"",
            ],
            None,
        )
    if letter_type == LetterType.PAY_STUB:
        if zh:
            return (["不需要做什么。我们用它来确认您每月的工作收入。"], None)
        return (["No action needed. We used this to confirm your monthly work income."], None)
    if zh:
        return (["如果有不清楚的地方，请拿这封信给社工看看。"], None)
    return (["Review this letter with a caseworker if anything is unclear."], None)


def read_letter(
    *, session: Session, image: bytes | bytearray, filename: str, language: str, user_id: str
) -> LetterDraftOut:
    """Read a photo and return a draft. Writes NOTHING to the database --
    the facts reach the user's profile only via confirm_letter()."""
    trace = Trace()
    doc_service = f"OCI Document Understanding{mock_suffix()}"
    genai_service = f"OCI Generative AI{mock_suffix()}"

    try:
        letter_type, validated = _read_letter(trace, image, filename, doc_service, genai_service)
    except Exception as exc:
        # Real OCI failed (MOCK_MODE never gets here): fail loudly instead
        # of substituting canned sample values. Log only the error type --
        # its message can repeat what was read from the letter.
        log.warning("Reading an uploaded letter failed (%s); nothing saved", describe_failure(exc))
        raise LetterReadError() from None

    fields = validated.model_dump(mode="json")
    action_items, deadline = _action_items_and_deadline(letter_type, fields, language)

    with trace.step("Explained it in your language", genai_service):
        # The explanation only sees what would be saved -- no name/address,
        # no bank descriptions -- since the explanation itself is saved.
        explanation = oci_client.explain_letter(letter_type, minimize(letter_type.value, fields), language)

    profile = session.get(ProfileRecord, user_id) or ProfileRecord(user_id=user_id)  # read-only
    bill_check = _bill_check(profile, fields, language) if letter_type == LetterType.MEDICAL_BILL else None
    is_sample = is_mock_mode()
    payload = {"t": letter_type.value, "f": fields, "s": is_sample, "e": explanation, "l": language}
    if bill_check and bill_check.dispute_letter:
        # Reused on confirm if nothing changed (saves two GenAI calls).
        payload["d"] = bill_check.dispute_letter.model_dump()
    token = sign_draft(user_id, payload)
    identifiers = {k: fields[k] for k in IDENTIFIER_FIELDS.get(letter_type.value, []) if fields.get(k)}
    return LetterDraftOut(
        draft_token=token,
        letter_type=letter_type,
        facts={**minimize(letter_type.value, fields), **transient(letter_type.value, fields)},
        identifiers=identifiers,
        editable=EDITABLE_FIELDS.get(letter_type.value, {}),
        explanation=explanation,
        action_items=action_items,
        deadline=deadline,
        bill_check=bill_check,
        is_sample=is_sample,
        trace=trace_to_out(trace),
    )


def _read_letter(trace: Trace, image_bytes: bytes, filename: str, doc_service: str, genai_service: str):
    with trace.step("Read the letter", doc_service):
        ocr = oci_client.ocr_document(image_bytes, filename)

    with trace.step("Identified the letter type", genai_service):
        letter_type = oci_client.classify_letter(ocr.raw_text)
    schema = SCHEMA_BY_TYPE[letter_type]

    with trace.step("Extracted the details", genai_service):
        raw_fields = oci_client.extract_fields(letter_type, ocr.raw_text, ocr.key_values)
        try:
            validated = schema.model_validate(raw_fields)
        except Exception:
            raw_fields = oci_client.extract_fields(
                letter_type, ocr.raw_text, ocr.key_values, retry_after_invalid=True
            )
            try:
                validated = schema.model_validate(raw_fields)
            except Exception as exc:
                raise ExtractionError(
                    f"Could not extract valid {letter_type.value} fields after retry"
                ) from exc
    return letter_type, validated




class CorrectionError(Exception):
    def __init__(self, message_en: str, message_zh: str):
        super().__init__(message_en)
        self.message_en = message_en
        self.message_zh = message_zh


def _normalize_list(raw) -> list[str]:
    """A list the user edited: one item per line (or comma), blanks dropped."""
    items = raw if isinstance(raw, list) else str(raw or "").replace(",", "\n").split("\n")
    cleaned = []
    for item in items:
        text = " ".join(str(item).split())
        if text and text not in cleaned:
            cleaned.append(text[:100])
    if len(cleaned) > 20:
        raise FieldValueError("Please list at most 20 items.", "最多列出20项。")
    return cleaned


def _apply_corrections(letter_type: str, extracted: dict, submitted: dict, save_identifiers: bool) -> tuple[dict, list[str]]:
    """Start from what was read, apply the user's corrections to the
    correctable facts (each checked by type), and keep only what's saved."""
    editable = EDITABLE_FIELDS.get(letter_type, {})
    identifiers = set(IDENTIFIER_FIELDS.get(letter_type, []))
    merged = dict(extracted)
    corrected = []
    for key, kind in editable.items():
        if key not in submitted or (key in identifiers and not save_identifiers):
            continue
        raw = submitted[key]
        try:
            if kind == "list":
                value = _normalize_list(raw)
            elif kind == "people":
                # Edited as one name per line; who's in the household is
                # what matters (e.g. one person = lives alone).
                if isinstance(raw, list):
                    raw = [p.get("name", "") if isinstance(p, dict) else p for p in raw]
                names = _normalize_list(raw)
                known = {m.get("name"): m for m in extracted.get(key) or [] if isinstance(m, dict)}
                value = [known.get(name, {"name": name}) for name in names]
            elif kind == "bool":
                if not isinstance(raw, bool):
                    raise FieldValueError("Please answer yes or no.", "请回答“是”或“不是”。")
                value = raw
            else:
                value = normalize(kind, "" if raw is None else str(raw))
                if kind == "money":
                    value = float(value)
        except FieldValueError as exc:
            raise CorrectionError(exc.message_en, exc.message_zh) from None
        if value != extracted.get(key) and str(value) != str(extracted.get(key)):
            corrected.append(key)
        merged[key] = value
    return minimize(letter_type, merged, keep_identifiers=save_identifiers), transient(letter_type, merged), corrected


def confirm_letter(
    *, session: Session, user_id: str, draft_token: str, facts: dict, save_identifiers: bool, language: str
) -> LetterUploadResponse:
    """Save a draft the user has checked: only the minimized facts, then
    update the profile, reminders and bill check from them."""
    draft = open_draft(user_id, draft_token)  # raises DraftInvalid
    letter_type = LetterType(draft["t"])
    saved, used_once, corrected = _apply_corrections(letter_type.value, draft["f"], facts or {}, save_identifiers)

    schema = SCHEMA_BY_TYPE[letter_type]
    try:
        validated = schema.model_validate({**saved, **used_once})
    except Exception:
        raise CorrectionError("Some of these facts aren't valid.", "有些内容格式不对。") from None
    fields = saved
    action_items, deadline = _action_items_and_deadline(letter_type, fields, language)

    explanation = draft["e"]
    if corrected or draft.get("l") != language:
        explanation = oci_client.explain_letter(letter_type, minimize(letter_type.value, fields), language)

    letter_record = LetterRecord(
        user_id=user_id,
        letter_type=letter_type.value,
        extracted_fields=fields,
        is_sample=bool(draft["s"]),
        explanation=explanation,
        explanation_language=language,
        corrected_fields=corrected,
    )
    reuse = draft.get("d") if not corrected and draft.get("l") == language else None
    return _save_and_respond(
        session, Trace(), letter_record, letter_type, validated, fields, action_items, deadline, language,
        reuse_dispute_letter=reuse,
        used_once=used_once,
    )


def _save_and_respond(
    session: Session,
    trace: Trace,
    letter_record: LetterRecord,
    letter_type: LetterType,
    validated,
    fields: dict,
    action_items: list[str],
    deadline,
    language: str,
    reuse_dispute_letter: dict | None = None,
    used_once: dict | None = None,
) -> LetterUploadResponse:
    user_id = letter_record.user_id
    explanation = letter_record.explanation
    session.add(letter_record)
    session.commit()
    session.refresh(letter_record)

    profile = _get_or_create_profile(session, user_id)
    # Transient facts (date of birth) update the profile but aren't stored.
    updated_fields = merge_fields_into_profile(profile, letter_type, {**fields, **(used_once or {})}, letter_record.id)
    session.add(profile)
    session.commit()

    reminder_out = None
    bill_check_out = None

    if letter_type == LetterType.HRA_RENEWAL_NOTICE:
        reminder_row = create_reminder(
            session,
            user_id=user_id,
            letter_id=letter_record.id,
            program=fields["program"],
            deadline=validated.deadline,
            checklist=fields.get("required_documents", []),
        )
        reminder_out = to_reminder_out(session, reminder_row)

    if letter_type == LetterType.MEDICAL_BILL:
        bill_check_out = _bill_check(profile, fields, language, reuse_dispute_letter)

    return LetterUploadResponse(
        letter_id=letter_record.id,
        letter_type=letter_type,
        extracted_fields=fields,
        explanation=explanation,
        action_items=action_items,
        deadline=deadline,
        profile_fields_updated=updated_fields,
        reminder=reminder_out,
        bill_check=bill_check_out,
        trace=trace_to_out(trace),
        is_sample=bool(letter_record.is_sample),
        created_at=letter_record.created_at,
        corrected_fields=list(letter_record.corrected_fields or []),
    )


def _bill_check(profile: ProfileRecord, fields: dict, language: str, reuse_dispute_letter: dict | None = None):
    result = check_qmb_bill(
        on_qmb=profile.on_qmb,
        provider=fields["provider"],
        is_medicare_claim=fields["is_medicare_claim"],
        line_items=fields.get("line_items", []),
    )
    if result.has_flagged:
        if reuse_dispute_letter:
            result.dispute_letter = DisputeLetter.model_validate(reuse_dispute_letter)
        else:
            result.dispute_letter = draft_dispute_letter(fields["provider"], result.flagged_line_items, language)
    return result


class LetterNotFound(Exception):
    pass


def get_letter(session: Session, user_id: str, letter_id: int, language: str) -> LetterUploadResponse:
    """Reopen a saved letter -- only its owner can. Another user's letter
    is reported as not found, so ids can't be probed."""
    record = session.get(LetterRecord, letter_id)
    if record is None or record.user_id != user_id:
        raise LetterNotFound()

    letter_type = LetterType(record.letter_type)
    fields = record.extracted_fields or {}
    action_items, deadline = _action_items_and_deadline(letter_type, fields, language)

    explanation = record.explanation
    if not explanation or record.explanation_language != language:
        # Saved in another language (or saved before explanations were kept).
        explanation = oci_client.explain_letter(letter_type, fields, language)
    # Explanations saved before amounts were formatted said "$40000.0".
    explanation = format_dollar_amounts(explanation)

    reminder = session.exec(select(Reminder).where(Reminder.letter_id == record.id)).first()
    bill_check = None
    if letter_type == LetterType.MEDICAL_BILL:
        bill_check = _bill_check(_get_or_create_profile(session, user_id), fields, language)

    return LetterUploadResponse(
        letter_id=record.id,
        letter_type=letter_type,
        extracted_fields=fields,
        explanation=explanation,
        action_items=action_items,
        deadline=deadline,
        profile_fields_updated=[],
        reminder=to_reminder_out(session, reminder) if reminder else None,
        bill_check=bill_check,
        # Saved before this flag existed = MOCK_MODE sample (real OCI never ran).
        is_sample=record.is_sample is not False,
        created_at=record.created_at,
        corrected_fields=list(record.corrected_fields or []),
    )
