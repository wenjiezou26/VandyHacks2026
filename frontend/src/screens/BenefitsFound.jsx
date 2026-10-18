import { Link } from "react-router-dom";
import BigButton from "../components/BigButton";
import CameraIcon from "../components/CameraIcon";
import ErrorBox from "../components/ErrorBox";
import IconBadge from "../components/IconBadge";
import Layout from "../components/Layout";
import MissingInfoQuestions from "../components/MissingInfoQuestions";
import { SampleNote } from "../components/SampleBadge";
import TracePanel from "../components/TracePanel";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { useScan } from "../context/useScan";
import { STATUS_KEY, confidenceLabel, numberLabel, statusLabel, t } from "../strings";
import { formatMoney, formatNumberUsed } from "../format";
import { useBenefits } from "../hooks/useBenefits";
import { benefitTone } from "../benefitTone";
import { speechLang } from "../speech";

const MSP_PROGRAMS = new Set(["QMB", "QI", "MSP"]);

function readAloud(text, lang) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 0.9;
  window.speechSynthesis.speak(utterance);
}

export default function BenefitsFound() {
  const { language } = useLanguage();
  const { token } = useAuth();
  const { startScan } = useScan();
  const { loading, refreshing, data, error, reload } = useBenefits(token, language);
  const benefits = data?.results || [];
  const trace = data?.trace || [];

  const canApplyMsp = benefits.some(
    (b) => MSP_PROGRAMS.has(b.program) && (b.status === "likely" || b.status === "possible"),
  );

  // "already_enrolled" (e.g. SNAP after an HRA recertification notice) is
  // good news, not a rejection -- it belongs with the positive results,
  // not under "not likely right now".
  const POSITIVE = new Set(["likely", "possible", "already_enrolled"]);
  const relevant = benefits.filter((b) => POSITIVE.has(b.status));
  const needInfo = benefits.filter((b) => b.status === "missing_info");
  const notNow = benefits.filter((b) => !POSITIVE.has(b.status) && b.status !== "missing_info");
  const anyPreliminary = benefits.some((b) => b.preliminary);
  const nothingYet = !loading && Boolean(data) && relevant.length === 0 && notNow.length === 0;

  return (
    <Layout title={t(language, "benefitsFoundTitle")} backTo="/home">
      {loading && <p className="spinner-wrap">{t(language, "loading")}</p>}
      {error && (
        <ErrorBox
          title={t(language, error.timeout ? "errBenefitsTimeout" : "errLoadBenefits")}
          error={error}
          onRetry={reload}
        />
      )}
      {data && refreshing && !loading && (
        <p className="muted-line" role="status">
          {t(language, "updatingResults")}
        </p>
      )}
      {data?.uses_sample_data && <SampleNote textKey="sampleBenefitsNote" />}

      {/* Nothing known yet (no letter scanned): one scan prompt, not a
          wall of questions. Once anything is known, show what can be
          said now, then the one question that could change it most. */}
      {nothingYet && (
        <div className="section">
          <div className="card" style={{ textAlign: "center" }}>
            <p>{t(language, "scanPrompt")}</p>
            <BigButton onClick={startScan}>
              <CameraIcon size={18} /> {t(language, "takePhoto")}
            </BigButton>
          </div>
        </div>
      )}

      {data && anyPreliminary && <p className="preliminary-note">{t(language, "preliminaryIntro")}</p>}

      {!loading && relevant.length > 0 && (
        <div className="section">
          <h3>{t(language, "resultsNowTitle")}</h3>
          {relevant.map((b) => (
            <div className="benefit-card2" key={b.program} style={{ marginBottom: 16 }}>
              <div className={`benefit-band tone-${benefitTone(b.program)}`}>
                <IconBadge kind={b.program} size={40} />
                <h2>{b.program}</h2>
                <span className="benefit-badges">
                  <span className={`badge ${b.status}`}>{t(language, STATUS_KEY[b.status])}</span>
                  <span className={`badge ${b.preliminary ? "preliminary" : "no-ai"}`}>
                    {t(language, b.preliminary ? "preliminaryTag" : "confirmedTag")}
                  </span>
                </span>
              </div>

              <div className="benefit-body">
                {b.annual_value > 0 && (
                  <>
                    <p className="benefit-amount">${formatMoney(b.annual_value)}</p>
                    <p className="benefit-amount-sub">
                      {t(language, "annualValue")} &middot; ${formatMoney(b.monthly_value)}{" "}
                      {t(language, "monthlyValue")}
                    </p>
                  </>
                )}

                <p>{b.explanation}</p>

                <button
                  type="button"
                  className="speak-pill"
                  onClick={() => readAloud(b.explanation, speechLang(language))}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M4 9.5v5h4l5 4v-13l-5 4H4z" />
                    <path d="M16.5 9a4 4 0 010 6" />
                  </svg>
                  {t(language, "readAloud")}
                </button>

                {b.warnings?.map((w, i) => (
                  <p key={`w${i}`} className="benefit-note warn">
                    {w}
                  </p>
                ))}

                {b.myth_busting_lines?.map((line, i) => (
                  <p key={`m${i}`} className="benefit-note tip">
                    {line}
                  </p>
                ))}

                <details className="benefit-why">
                  <summary>
                    {t(language, "why")} / {t(language, "numbersUsed")}
                  </summary>
                  <p>{b.rule_applied}</p>
                  <table className="kv-table">
                    <tbody>
                      {Object.entries(b.numbers_used).map(([key, value]) => (
                        <tr key={key}>
                          <td>{numberLabel(language, key)}</td>
                          <td>{formatNumberUsed(value)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p>
                    {t(language, "confidence")}: {confidenceLabel(language, b.confidence)}
                  </p>
                </details>
              </div>
            </div>
          ))}
        </div>
      )}

      {data && !nothingYet && (
        <MissingInfoQuestions
          key={(data.questions || []).join(",")}
          questions={data.questions}
          questionPrograms={data.question_programs}
          onAnswered={reload}
        />
      )}

      {!loading && !nothingYet && needInfo.length > 0 && (
        <div className="section">
          <h3>{t(language, "missingInfoTitle")}</h3>
          <div className="ios-list">
            {needInfo.map((b) => (
              <div key={b.program} className="nav-row-details">
                <div className="nav-row">
                  <IconBadge kind={b.program} size={32} />
                  <span style={{ flex: 1 }}>{b.program}</span>
                  <span className="status-text missing_info">{statusLabel(language, b)}</span>
                </div>
                <div className="nav-row-details-body">
                  <p style={{ margin: 0 }}>{b.explanation}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && notNow.length > 0 && (
        <div className="section">
          <h3>{t(language, "notNowLabel")}</h3>
          <div className="ios-list">
            {notNow.map((b) => (
              <div key={b.program} className="nav-row-details">
                <div className="nav-row">
                  <IconBadge kind={b.program} size={32} />
                  <span style={{ flex: 1 }}>{b.program}</span>
                  <span className="status-text not_now">{statusLabel(language, b)}</span>
                </div>
                <div className="nav-row-details-body">
                  <p style={{ marginTop: 0 }}>{b.explanation}</p>
                  {!b.preliminary && <p className="review-source">{b.rule_applied}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {canApplyMsp && (
        <div className="section">
          <BigButton to="/apply">{t(language, "applyCta")}</BigButton>
          <p className="review-source" style={{ margin: "6px 4px 0" }}>
            {t(language, "applyCtaHelp")}
          </p>
        </div>
      )}

      <div className="ios-list">
        <Link to="/application-pack" className="nav-row">
          {t(language, "seeApplicationPack")}
          <span className="nav-row-chevron">{"›"}</span>
        </Link>
        <Link to="/caseworker-card" className="nav-row">
          {t(language, "seeCaseworkerCard")}
          <span className="nav-row-chevron">{"›"}</span>
        </Link>
      </div>

      {/* Every card carries the same "final decision is made by..." line;
          show each distinct one once instead of repeating it per card. */}
      {[...new Set(relevant.map((b) => b.disclaimer).filter(Boolean))].map((d) => (
        <p key={d} className="benefit-footnote">
          {d}
        </p>
      ))}

      <TracePanel trace={trace} />
    </Layout>
  );
}
