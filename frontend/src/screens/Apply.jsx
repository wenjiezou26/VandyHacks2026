import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import BigButton from "../components/BigButton";
import Layout from "../components/Layout";
import VoiceButton from "../components/VoiceButton";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { t } from "../strings";
import { answerField, errorText, startApplication } from "../api";
import { question } from "../applicationFields";
import { speechLang } from "../speech";

const EDITABLE = new Set(["draft", "info_requested"]);

function readAloud(text, lang) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 0.9;
  window.speechSynthesis.speak(utterance);
}

export default function Apply() {
  const { language } = useLanguage();
  const { token } = useAuth();
  const navigate = useNavigate();
  const [application, setApplication] = useState(null);
  const [initialMissing, setInitialMissing] = useState(0);
  const [answer, setAnswer] = useState("");
  const [dialect, setDialect] = useState("mandarin");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    startApplication(token)
      .then((app) => {
        if (!EDITABLE.has(app.status)) return navigate("/apply/status", { replace: true });
        if (!app.next_question) return navigate("/apply/review", { replace: true });
        setInitialMissing(app.fields.filter((f) => f.value === null).length);
        setApplication(app);
      })
      .catch((err) => setError(errorText(err, language)));
  }, [token, language, navigate]);

  const current = application?.fields.find((f) => f.key === application.next_question);
  const lang = speechLang(language, dialect);

  async function submitAnswer(value) {
    if (!value.trim()) return;
    setBusy(true);
    setError("");
    try {
      const updated = await answerField(token, application.id, current.key, value);
      if (!updated.next_question) {
        navigate("/apply/review");
        return;
      }
      setApplication(updated);
      setAnswer("");
      inputRef.current?.focus();
    } catch (err) {
      setAnswer(value);
      setError(errorText(err, language));
    } finally {
      setBusy(false);
    }
  }

  if (!current) {
    return (
      <Layout backTo="/benefits">
        <p className="spinner-wrap">{error || t(language, "loading")}</p>
      </Layout>
    );
  }

  const remaining = application.fields.filter((f) => f.value === null).length;
  const filledFromLetters = application.fields.length - initialMissing;

  return (
    <Layout title={t(language, "interviewTitle")} backTo="/benefits">
      {filledFromLetters > 0 && (
        <p className="card notice">
          {"✅"} {t(language, "alreadyFilled", { n: filledFromLetters })}
        </p>
      )}

      <section className="card">
        <h3>{t(language, "questionOf", { n: initialMissing - remaining + 1, total: initialMissing })}</h3>
        <h2>
          {question(current, language)}{" "}
          <button
            type="button"
            className="link-button"
            aria-label={t(language, "readAloud")}
            onClick={() => readAloud(question(current, language), lang)}
          >
            {"\u{1F50A}"}
          </button>
        </h2>

        {language === "zh" && (
          <div className="segmented" role="group">
            {["mandarin", "cantonese"].map((d) => (
              <button
                key={d}
                type="button"
                className={dialect === d ? "active" : ""}
                onClick={() => setDialect(d)}
              >
                {t(language, d)}
              </button>
            ))}
          </div>
        )}

        <VoiceButton key={current.key + lang} lang={lang} onResult={submitAnswer} />

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitAnswer(answer);
          }}
        >
          <input
            ref={inputRef}
            className="text-input"
            placeholder={t(language, "answerPlaceholder")}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            style={{ marginTop: 12 }}
          />
          {error && <p style={{ color: "var(--color-danger)", marginTop: 8 }}>{error}</p>}
          <BigButton type="submit" disabled={busy || !answer.trim()} style={{ marginTop: 12 }}>
            {t(language, "next")}
          </BigButton>
        </form>
      </section>
    </Layout>
  );
}
