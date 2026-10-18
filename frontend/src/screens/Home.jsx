import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import AppHeader from "../components/AppHeader";
import CameraIcon from "../components/CameraIcon";
import ErrorBox from "../components/ErrorBox";
import IconBadge from "../components/IconBadge";
import { SampleBadge, SampleNote } from "../components/SampleBadge";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { letterTypeLabel, statusLabel, t } from "../strings";
import { fetchLetters, fetchOnQmb, fetchReminders, setOnQmb } from "../api";
import { benefitTone } from "../benefitTone";
import { useScan } from "../context/useScan";
import { useBenefits } from "../hooks/useBenefits";
import { useLoad } from "../hooks/useLoad";

const CATEGORY_TYPES = [
  "ssa_benefit_letter",
  "hra_renewal_notice",
  "medicare_notice",
  "medical_bill",
  "bank_statement",
  "pay_stub",
  "other",
];

// Shown on Home: programs the rules engine has actually decided. Ones it
// can't decide yet stay off Home entirely -- scanning more letters is the
// only way forward, never a typed-in answer.
const SHOWN_STATUSES = new Set(["likely", "possible", "already_enrolled"]);

export default function Home() {
  const { language } = useLanguage();
  const { token, signOut } = useAuth();
  const location = useLocation();
  const pastLettersRef = useRef(null);
  const qmbUserTouchedRef = useRef(false);
  const [onQmb, setOnQmbState] = useState(false);
  const [qmbSaving, setQmbSaving] = useState(false);
  const [qmbError, setQmbError] = useState(false);
  const { startScan, scanning } = useScan();

  const letters = useLoad(() => fetchLetters(token), [token]);
  const reminders = useLoad(() => fetchReminders(token), [token]);
  const benefits = useBenefits(token, language);

  useEffect(() => {
    fetchOnQmb(token)
      .then((data) => {
        // Ignore this if the user already toggled the switch themselves
        // while this request was in flight -- their action is newer truth
        // than whatever the server had when the request was sent.
        if (!qmbUserTouchedRef.current) setOnQmbState(data.on_qmb);
      })
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (location.state?.scrollTo === "past-letters") {
      pastLettersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [location.state]);

  async function handleQmbToggle(event) {
    const next = event.target.checked;
    qmbUserTouchedRef.current = true;
    setOnQmbState(next);
    setQmbSaving(true);
    setQmbError(false);
    try {
      await setOnQmb(token, next);
    } catch {
      setOnQmbState(!next); // revert on failure
      setQmbError(true);
    } finally {
      setQmbSaving(false);
    }
  }

  const shownBenefits = (benefits.data?.results || []).filter((b) => SHOWN_STATUSES.has(b.status));

  return (
    <div className="app-shell">
      <AppHeader />

      <div className="section">
        <button
          type="button"
          className="scan-bar"
          disabled={scanning}
          onClick={startScan}
        >
          <span className="scan-bar-label">
            {scanning ? t(language, "uploading") : t(language, "scanPrompt")}
          </span>
          <span className="scan-bar-icon" aria-hidden="true">
            <CameraIcon size={20} />
          </span>
        </button>
        <Link to="/privacy" className="privacy-link">
          {t(language, "privacyLink")}
        </Link>
      </div>

      <div className="section">
        <h3>{t(language, "frequentLetters")}</h3>
        <div className="category-grid">
          {CATEGORY_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              className="category-card"
              disabled={scanning}
              onClick={startScan}
            >
              <IconBadge kind={type} size={32} />
              {letterTypeLabel(language, type)}
            </button>
          ))}
        </div>
      </div>

      <div className="section">
        <div className="section-head-row">
          <h3>{t(language, "viewBenefits")}</h3>
          <Link className="see-all-link" to="/benefits">
            {t(language, "seeAll")} {"›"}
          </Link>
        </div>
        {benefits.loading && <p className="muted-line">{t(language, "loading")}</p>}
        {benefits.error && (
          <ErrorBox
            title={t(language, benefits.error.timeout ? "errBenefitsTimeout" : "errLoadBenefits")}
            error={benefits.error}
            onRetry={benefits.reload}
          />
        )}
        {benefits.data && (
          <>
            {benefits.data.uses_sample_data && <SampleNote textKey="sampleBenefitsNote" />}
            {shownBenefits.length > 0 ? (
              <div className="benefit-tile-row">
                {shownBenefits.map((b) => (
                  <Link key={b.program} to="/benefits" className={`benefit-tile tone-${benefitTone(b.program)}`}>
                    <div>
                      <div className="benefit-tile-title">{b.program}</div>
                      <div className="benefit-tile-sub">{statusLabel(language, b)}</div>
                    </div>
                    <IconBadge kind={b.program} size={28} />
                  </Link>
                ))}
              </div>
            ) : (
              <div className="ios-list">
                <Link to="/benefits" className="nav-row">
                  {t(language, "viewBenefits")}
                  <span className="nav-row-chevron">{"›"}</span>
                </Link>
              </div>
            )}
          </>
        )}
      </div>

      <div className="section">
        <h3>{t(language, "upcomingDeadlines")}</h3>
        {reminders.loading && <p className="muted-line">{t(language, "loading")}</p>}
        {/* A failed request is an error, never "No upcoming deadlines". */}
        {reminders.error && (
          <ErrorBox title={t(language, "errLoadDeadlines")} error={reminders.error} onRetry={reminders.reload} />
        )}
        {reminders.data && reminders.data.length === 0 && <p>{t(language, "noDeadlines")}</p>}
        {reminders.data && reminders.data.length > 0 && (
          <div className="ios-list">
            {reminders.data.map((r) => (
              <Link key={r.id} to="/application-pack" className="reminder-item">
                <IconBadge kind={r.program} size={36} />
                <span style={{ flex: 1 }}>
                  {r.program}
                  {r.packet && (
                    <>
                      {" "}
                      &middot; {r.packet.satisfied_count}/{r.packet.total_count}{" "}
                      {t(language, "documentsReady")}
                    </>
                  )}
                </span>
                <span>
                  {r.overdue ? t(language, "overdue") : `${r.days_until_deadline} ${t(language, "daysLeft")}`}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <div className="ios-switch-row">
          <span className="ios-switch-label">{t(language, "qmbToggleLabel")}</span>
          <label className="ios-switch">
            <input type="checkbox" checked={onQmb} onChange={handleQmbToggle} disabled={qmbSaving} />
            <span className="ios-switch-track" />
            <span className="ios-switch-thumb" />
          </label>
        </div>
        {qmbError && <p className="form-error">{t(language, "errSave")}</p>}
        <p style={{ color: "var(--color-muted)", fontSize: "var(--font-size-xs)", margin: "6px 0 0 4px" }}>
          {t(language, "qmbToggleHelp")}
        </p>
      </div>

      <div className="section">
        <div className="ios-list">
          <Link to="/apply/status" className="nav-row">
            {t(language, "viewApplication")}
            <span className="nav-row-chevron">{"›"}</span>
          </Link>
          <Link to="/privacy" className="nav-row">
            {t(language, "privacyTitle")}
            <span className="nav-row-chevron">{"›"}</span>
          </Link>
        </div>
      </div>

      <div className="section" ref={pastLettersRef} id="past-letters">
        <h3>{t(language, "pastLetters")}</h3>
        {letters.loading && <p className="muted-line">{t(language, "loading")}</p>}
        {letters.error && (
          <ErrorBox title={t(language, "errLoadLetters")} error={letters.error} onRetry={letters.reload} />
        )}
        {letters.data && letters.data.length === 0 && <p>{t(language, "noLettersYet")}</p>}
        {letters.data && letters.data.length > 0 && (
          <div className="ios-list">
            {letters.data.map((l) => (
              <Link key={l.id} to={`/letters/${l.id}`} className="letter-list-item">
                <IconBadge kind={l.letter_type} size={36} />
                <span style={{ flex: 1 }}>
                  {letterTypeLabel(language, l.letter_type)} {l.is_sample && <SampleBadge />}
                </span>
                <span style={{ color: "var(--color-muted)" }}>{new Date(l.created_at).toLocaleDateString()}</span>
                <span className="nav-row-chevron">{"›"}</span>
              </Link>
            ))}
          </div>
        )}
      </div>

      <button type="button" className="sign-out-row" onClick={signOut}>
        {t(language, "signOut")}
      </button>
    </div>
  );
}
