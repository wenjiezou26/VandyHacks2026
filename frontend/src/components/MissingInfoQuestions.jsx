import { useState } from "react";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { t } from "../strings";
import { answerQuestion, errorText } from "../api";

const YES_NO = new Set(["has_medicare", "married"]);
const WHOLE_NUMBER = new Set(["household_size", "age"]);

function Question({ field, programs, onAnswered }) {
  const { language } = useLanguage();
  const { token } = useAuth();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [answered, setAnswered] = useState(false);

  async function save(answer) {
    if (!String(answer).trim()) return;
    setBusy(true);
    setError("");
    try {
      await answerQuestion(token, field, answer);
      setAnswered(true); // hide right away; the re-check refreshes the rest
      onAnswered();
    } catch (err) {
      // The server explains bad answers ("can't be negative"); otherwise generic.
      setError(err.fromServer ? errorText(err, language) : t(language, "errSave"));
      setBusy(false);
    }
  }

  if (answered) return <p className="muted-line">{t(language, "updatingResults")}</p>;

  return (
    <div className="question-row">
      <p className="question-text">{t(language, `pq_${field}`)}</p>
      {programs?.length > 0 && (
        <p className="review-source">{t(language, "questionAffects", { programs: programs.join(", ") })}</p>
      )}
      {YES_NO.has(field) ? (
        <div className="question-buttons">
          <button type="button" className="big-button" disabled={busy} onClick={() => save("yes")}>
            {t(language, "yes")}
          </button>
          <button type="button" className="big-button secondary" disabled={busy} onClick={() => save("no")}>
            {t(language, "no")}
          </button>
        </div>
      ) : (
        <form
          className="question-form"
          onSubmit={(e) => {
            e.preventDefault();
            save(value);
          }}
        >
          <input
            className="text-input"
            inputMode={WHOLE_NUMBER.has(field) ? "numeric" : "decimal"}
            aria-label={t(language, `pq_${field}`)}
            placeholder={WHOLE_NUMBER.has(field) ? "1" : "$0"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button type="submit" className="big-button" disabled={busy || !value.trim()}>
            {t(language, "save")}
          </button>
        </form>
      )}
      {error && <p className="form-error">{error}</p>}
    </div>
  );
}

// Ask only for facts that could change a result, one at a time, most
// useful first (the server ranks them). Each answer re-checks the results
// right away; "Skip" moves on and the results stay marked preliminary.
// Unknown facts are never guessed.
export default function MissingInfoQuestions({ questions, questionPrograms, onAnswered }) {
  const { language } = useLanguage();
  const [skipped, setSkipped] = useState([]);
  const open = (questions || []).filter((q) => !skipped.includes(q));
  if (!open.length) return null;
  const [field, ...rest] = open;
  return (
    <section id="questions" className="card missing-info-card">
      <h2>{t(language, "nextQuestionTitle")}</h2>
      <Question key={field} field={field} programs={questionPrograms?.[field]} onAnswered={onAnswered} />
      <div className="question-footer">
        {rest.length > 0 && <p className="review-source">{t(language, "moreQuestions", { n: rest.length })}</p>}
        <button type="button" className="link-button" onClick={() => setSkipped((prev) => [...prev, field])}>
          {t(language, "skipQuestion")}
        </button>
      </div>
    </section>
  );
}
