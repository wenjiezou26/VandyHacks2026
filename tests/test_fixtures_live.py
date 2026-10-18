"""Golden test: each demo fixture against REAL OCI (MOCK_MODE=false).

Skipped by default -- requires live OCI credentials (OCI_CONFIG_PATH,
OCI_COMPARTMENT_ID, OCI_GENAI_MODEL_ID; see scripts/check_oci.py) and
costs real API calls, so it never runs in CI or a normal `pytest` pass.

    RUN_LIVE=1 MOCK_MODE=false python -m pytest tests/test_fixtures_live.py -v

For each fixture (both the clean PNG and the "phone photo" JPG), the file
is copied to a randomized temp filename first -- MOCK_MODE dispatches by
filename keyword, so if results survived a rename unchanged that would
prove nothing. This test calls app.docs.oci_client._real_* directly, so
whatever pixels are in the file are genuinely what gets OCR'd.

Money fields are compared exact to the cent, dates exact, list fields
compared order-insensitively. Reports a pass/fail table per fixture per
field rather than stopping at the first mismatch, so one bad field
doesn't hide information about the rest.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import string
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "demo" / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"

RUN_LIVE = os.getenv("RUN_LIVE") == "1"
SKIP_REASON = "Live OCI test -- set RUN_LIVE=1 and MOCK_MODE=false to run (needs real credentials)."

FIXTURE_STEMS = [
    "01_ssa_benefit_letter",
    "02_bank_statement",
    "03_hra_snap_recert_notice",
    "04_clinic_bill",
    "05_ssa_letter_variant",
    "07_ssa_letter_high_income",
]


def _random_filename(suffix: str) -> str:
    stem = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    return f"{stem}{suffix}"


def _compare(expected: dict, actual: dict, path: str, rows: list[tuple[str, bool, str]]) -> None:
    for key, exp_value in expected.items():
        full_path = f"{path}.{key}" if path else key
        act_value = actual.get(key)
        if isinstance(exp_value, float):
            ok = isinstance(act_value, (int, float)) and abs(act_value - exp_value) < 0.005
            rows.append((full_path, ok, f"expected {exp_value}, got {act_value}"))
        elif isinstance(exp_value, list):
            if exp_value and isinstance(exp_value[0], dict):
                ok = len(act_value or []) == len(exp_value)
                rows.append((full_path, ok, f"expected {len(exp_value)} items, got {len(act_value or [])}"))
                for i, exp_item in enumerate(exp_value):
                    if isinstance(act_value, list) and i < len(act_value):
                        _compare(exp_item, act_value[i], f"{full_path}[{i}]", rows)
            else:
                ok = sorted(exp_value) == sorted(act_value or [])
                rows.append((full_path, ok, f"expected {exp_value}, got {act_value}"))
        else:
            ok = act_value == exp_value
            rows.append((full_path, ok, f"expected {exp_value!r}, got {act_value!r}"))


@pytest.mark.skipif(not RUN_LIVE, reason=SKIP_REASON)
@pytest.mark.parametrize("stem", FIXTURE_STEMS)
@pytest.mark.parametrize("variant", ["png", "photo"])
def test_fixture_against_real_oci(stem, variant):
    from app.docs import oci_client
    from app.docs.schemas import SCHEMA_BY_TYPE, LetterType

    suffix = ".png" if variant == "png" else "_photo.jpg"
    src = FIXTURES_DIR / f"{stem}{suffix}"
    assert src.exists(), f"fixture image missing: {src}"
    expected = json.loads((EXPECTED_DIR / f"{stem}.json").read_text())

    with tempfile.TemporaryDirectory() as tmp:
        # Random filename: prove the pipeline reads pixels, not the name.
        renamed = Path(tmp) / _random_filename(src.suffix)
        shutil.copy(src, renamed)
        image_bytes = renamed.read_bytes()

        ocr = oci_client._real_ocr(image_bytes)
        assert ocr.raw_text.strip(), "OCI Document Understanding returned no text"

        letter_type = oci_client._real_classify(ocr.raw_text)
        assert letter_type.value == expected["letter_type"], (
            f"classified as {letter_type.value}, expected {expected['letter_type']}"
        )

        schema = SCHEMA_BY_TYPE[letter_type]
        raw_fields = oci_client._real_extract(letter_type, ocr.raw_text, ocr.key_values, retry_after_invalid=False)
        validated = schema.model_validate(raw_fields)
        actual = validated.model_dump(mode="json")

    rows: list[tuple[str, bool, str]] = []
    expected_fields = {k: v for k, v in expected.items() if k != "letter_type"}
    _compare(expected_fields, actual, "", rows)

    print(f"\n--- {stem} ({variant}) ---")
    for field, ok, detail in rows:
        print(f"  [{'OK' if ok else 'FAIL'}] {field}: {detail}")

    failures = [f"{field}: {detail}" for field, ok, detail in rows if not ok]
    assert not failures, f"{stem} ({variant}) field mismatches:\n" + "\n".join(failures)
