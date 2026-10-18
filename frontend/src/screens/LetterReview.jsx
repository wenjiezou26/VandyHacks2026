import { useState } from "react";
import { useNavigate } from "react-router-dom";
import BigButton from "../components/BigButton";
import ErrorBox from "../components/ErrorBox";
import IconBadge from "../components/IconBadge";
import Layout from "../components/Layout";
import { SampleNote } from "../components/SampleBadge";
import TracePanel from "../components/TracePanel";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { useScan } from "../context/useScan";
import { confirmLetter } from "../api";
import { formatField } from "../letterFields";
import { extractedFieldLabel, letterTypeLabel, t } from "../strings";

function FactInput({ name, kind, value, onChange, language }) {
  const label = extractedFieldLabel(language, name);
  if (kind === "bool") {
    return (
      <div className="fact-row">
        <span className="fact-label">{label}</span>
        <div className="segmented-mini" role="group" aria-label={label}>
          {[true, false].map((option) => (
            <button
              key={String(option)}
              type="button"
              className={value === option ? "active" : ""}
              aria-pressed={value === option}
              onClick={() => onChange(option)}
            >
              {t(language, option ? "yes" : "no")}
            </button>
          ))}
        </div>
      </div>
    );
  }
  if (kind === "list" || kind === "people") {
    // One item per line -- delete a line to remove a wrongly read item.
    // People are edited by name (the server keeps what it read for each).
    const lines = Array.isArray(value)
      ? value.map((item) => (item && typeof item === "object" ? item.name ?? "" : item))
      : null;
    return (
      <label className="fact-row">
        <span className="fact-label">{label}</span>
        <textarea
          className="text-input"
          rows={Math.max(3, (lines ? lines.length : 1) + 1)}
          value={lines ? lines.join("\n") : value ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
  }
  return (
    <label className="fact-row">
      <span className="fact-label">{label}</span>
      <input
        className="text-input"
        inputMode={kind === "money" ? "decimal" : undefined}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

// "Check what we read": nothing is saved until the user taps Save, and then
// only these facts (plus name/address if they tick the box). Keyed by draft
// so a new scan starts with fresh boxes.
export default function LetterReview() {
  const { draft } = useScan();
  return <ReviewDraft key={draft?.draft_token || "none"} />;
}

function ReviewDraft() {
  const { language } = useLanguage();
  const { token } = useAuth();
  const { draft, clearDraft, startScan } = useScan();
  const navigate = useNavigate();
  const [values, setValues] = useState(() => ({ ...(draft?.facts || {}), ...(draft?.identifiers || {}) }));
  const [saveIdentifiers, setSaveIdentifiers] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!draft) {
    return (
      <Layout title={t(language, "reviewTitleLetter")} backTo="/home">
        <p>{t(language, "noDraft")}</p>
        <BigButton onClick={startScan}>{t(language, "takePhoto")}</BigButton>
      </Layout>
    );
  }

  const editable = draft.editable || {};
  const identifierKeys = Object.keys(draft.identifiers || {});
  const set = (key) => (value) => setValues((prev) => ({ ...prev, [key]: value }));

  async function save() {
    setBusy(true);
    setError(null);
    const facts = {};
    for (const key of Object.keys(editable)) {
      if (key in values && (!identifierKeys.includes(key) || saveIdentifiers)) facts[key] = values[key];
    }
    try {
      const saved = await confirmLetter(token, {
        draftToken: draft.draft_token,
        facts,
        saveIdentifiers,
        language: language || "en",
      });
      clearDraft();
      navigate(`/letters/${saved.letter_id}`, { replace: true });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  function discard() {
    clearDraft();
    navigate("/home", { replace: true });
  }

  return (
    <Layout title={t(language, "reviewTitleLetter")} backTo="/home">
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <IconBadge kind={draft.letter_type} size={44} />
        <strong>{letterTypeLabel(language, draft.letter_type)}</strong>
      </div>
      {draft.is_sample && <SampleNote textKey="sampleLetterNote" />}

      <div className="section">
        <h3>{t(language, "explanation")}</h3>
        <div className="card">
          <p style={{ margin: 0 }}>{draft.explanation}</p>
        </div>
      </div>

      {draft.action_items?.length > 0 && (
        <div className="section">
          <h3>{t(language, "actionItems")}</h3>
          <ul>
            {draft.action_items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="section">
        <h3>{t(language, "reviewTitleLetter")}</h3>
        <div className="card">
          <p className="review-source" style={{ marginTop: 0 }}>
            {t(language, "reviewLetterIntro")}
          </p>
          {Object.keys(draft.facts).length === 0 && <p>—</p>}
          {Object.entries(draft.facts).map(([key, original]) =>
            editable[key] ? (
              <FactInput
                key={key}
                name={key}
                kind={editable[key]}
                value={values[key]}
                onChange={set(key)}
                language={language}
              />
            ) : (
              <div key={key} className="fact-row">
                <span className="fact-label">{extractedFieldLabel(language, key)}</span>
                <span>{formatField(key, original, language)}</span>
              </div>
            ),
          )}
        </div>
      </div>

      {identifierKeys.length > 0 && (
        <div className="section">
          <h3>{t(language, "identifiersTitle")}</h3>
          <div className="card">
            {identifierKeys.map((key) => (
              <FactInput
                key={key}
                name={key}
                kind={editable[key] || "text"}
                value={values[key]}
                onChange={set(key)}
                language={language}
              />
            ))}
            <label className="notice-checkbox">
              <input
                type="checkbox"
                checked={saveIdentifiers}
                onChange={(e) => setSaveIdentifiers(e.target.checked)}
              />
              {t(language, "identifiersSave")}
            </label>
            {!saveIdentifiers && <p className="review-source">{t(language, "identifiersNotSaved")}</p>}
          </div>
        </div>
      )}

      <ul className="notice-list small">
        <li>{t(language, "noticeNotVerification")}</li>
        <li>{t(language, "noticeKeepOriginals")}</li>
      </ul>

      {draft.bill_check && (
        <BigButton to="/bill-check" state={{ billCheck: draft.bill_check }} variant="secondary">
          {t(language, "seeBillCheck")}
        </BigButton>
      )}

      {error && <ErrorBox title={t(language, "errConfirm")} error={error} />}
      {error?.status === 410 ? (
        <BigButton onClick={startScan}>{t(language, "takePhoto")}</BigButton>
      ) : (
        <BigButton onClick={save} disabled={busy}>
          {busy ? t(language, "sending") : t(language, "saveFacts")}
        </BigButton>
      )}
      <BigButton variant="secondary" onClick={discard} disabled={busy}>
        {t(language, "discardScan")}
      </BigButton>

      <TracePanel trace={draft.trace} />
    </Layout>
  );
}
