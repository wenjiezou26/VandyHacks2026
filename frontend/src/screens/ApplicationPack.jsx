import BigButton from "../components/BigButton";
import CameraIcon from "../components/CameraIcon";
import ErrorBox from "../components/ErrorBox";
import Layout from "../components/Layout";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { useScan } from "../context/useScan";
import { documentText, numberLabel, t } from "../strings";
import { documentLabel } from "../applicationFields";
import { fetchMspChecklist, fetchReminders } from "../api";
import { formatNumberUsed } from "../format";
import { useBenefits } from "../hooks/useBenefits";
import { useLoad } from "../hooks/useLoad";

const MSP_PROGRAMS = new Set(["QMB", "QI", "MSP"]);
const QUALIFIES = new Set(["likely", "possible"]);
const SNAP_APPLY_DOCS = ["snapDocId", "snapDocAddress", "snapDocIncome", "snapDocExpenses", "snapDocMedical"];

// status "have" | "partial" | "missing"; falls back to the done boolean
// (treated as "have"/"missing") for checklists that don't pass a status.
const STATUS_ICON = { have: "✅", partial: "🟡", missing: "⬜" };

function Checklist({ items }) {
  return (
    <ul style={{ listStyle: "none", paddingLeft: 0, margin: 0 }}>
      {items.map(({ key, done, status, label }) => (
        <li key={key} style={{ padding: "4px 0" }}>
          {STATUS_ICON[status] || (done ? "✅" : "⬜")} {label}
        </li>
      ))}
    </ul>
  );
}

// LetterLens can't file SNAP, so say so plainly and give the real next step:
// renew with HRA by the deadline, or apply through ACCESS HRA.
function SnapSection({ snap, renewal }) {
  const { language } = useLanguage();
  const { startScan } = useScan();
  if (!snap && !renewal) return null;

  let body;
  if (renewal) {
    const items = (
      renewal.packet?.items ?? renewal.checklist.map((item) => ({ item, satisfied: false, status: "missing" }))
    ).map((p, i) => ({ key: i, done: p.satisfied, status: p.status, label: documentText(language, p.item) }));
    body = (
      <>
        <p>{t(language, "snapRenewalNext", { date: renewal.deadline })}</p>
        <Checklist items={items} />
      </>
    );
  } else if (QUALIFIES.has(snap.status)) {
    body = (
      <>
        <p>{t(language, "snapApplyNext")}</p>
        <Checklist items={SNAP_APPLY_DOCS.map((key) => ({ key, done: false, label: t(language, key) }))} />
      </>
    );
  } else if (snap.status === "missing_info") {
    body = (
      <>
        <p>{t(language, "snapNeedsInfo")}</p>
        <BigButton onClick={startScan} variant="secondary">
          <CameraIcon size={18} /> {t(language, "takePhoto")}
        </BigButton>
      </>
    );
  } else {
    return null; // "not likely right now" -- nothing to apply for
  }

  return (
    <section>
      <h3>{t(language, "snapTitle")}</h3>
      <div className="card">
        <p className="review-source" style={{ marginTop: 0 }}>
          {t(language, "snapUnsupported")}
        </p>
        {body}
      </div>
    </section>
  );
}

export default function ApplicationPack() {
  const { language } = useLanguage();
  const { token } = useAuth();
  const reminders = useLoad(() => fetchReminders(token), [token]);
  const benefits = useBenefits(token, language);
  const { startScan, scanning } = useScan();
  const mspChecklist = useLoad(() => fetchMspChecklist(token), [token]);

  const results = benefits.data?.results || [];
  const likelyPrograms = results.filter((b) => QUALIFIES.has(b.status));
  const mspResult = results.find((b) => MSP_PROGRAMS.has(b.program) && QUALIFIES.has(b.status));
  const mspLikely = Boolean(mspResult);
  const snap = results.find((b) => b.program === "SNAP");
  const snapRenewal = (reminders.data || []).find((r) => r.program === "SNAP");
  const otherReminders = (reminders.data || []).filter((r) => r.program !== "SNAP");
  const loading = reminders.loading || benefits.loading || mspChecklist.loading;
  const failed = benefits.error || reminders.error;
  // Something to apply for or renew. SNAP alone waiting on answers isn't a
  // pack -- that's the empty state below, which covers every program.
  const snapQualifies = Boolean(snapRenewal) || (snap && QUALIFIES.has(snap.status));
  const hasPack = mspLikely || snapQualifies || otherReminders.length > 0 || likelyPrograms.length > 0;
  const notLikely = results.filter((b) => b.status === "not_now");
  const waiting = results.filter((b) => b.status === "missing_info");
  const needsAnswers = (benefits.data?.questions || []).length > 0;

  return (
    <Layout title={t(language, "applicationPackTitle")} backTo="/benefits">
      {loading && <p className="spinner-wrap">{t(language, "loading")}</p>}
      {benefits.error && (
        <ErrorBox
          title={t(language, benefits.error.timeout ? "errBenefitsTimeout" : "errLoadBenefits")}
          error={benefits.error}
          onRetry={benefits.reload}
        />
      )}
      {reminders.error && (
        <ErrorBox title={t(language, "errLoadDeadlines")} error={reminders.error} onRetry={reminders.reload} />
      )}

      {mspLikely && (
        <section>
          <h3>{t(language, "mspChecklistTitle")}</h3>
          {mspChecklist.error && (
            <ErrorBox
              title={t(language, "errLoadChecklist")}
              error={mspChecklist.error}
              onRetry={mspChecklist.reload}
            />
          )}
          {mspResult.preliminary && <p className="preliminary-note">{t(language, "packPreliminaryNote")}</p>}
          {mspChecklist.data && (
            <div className="card">
              <Checklist
                items={mspChecklist.data.items.map((item) => ({
                  key: item.key,
                  done: item.status === "already_have",
                  label: documentLabel(item, language),
                }))}
              />
              <p style={{ color: "var(--color-muted)", fontSize: "var(--font-size-xs)", margin: "10px 0" }}>
                {t(language, "msp45DayNote")}
              </p>
              <BigButton to="/apply">{t(language, "applyCta")}</BigButton>
            </div>
          )}
        </section>
      )}

      {!failed && hasPack && <SnapSection snap={snap} renewal={snapRenewal} />}

      {otherReminders.length > 0 && (
        <section>
          <h3>{t(language, "checklist")}</h3>
          {otherReminders.map((r) => (
            <div key={r.id} className="card" style={{ marginBottom: 12 }}>
              <div className="benefit-card-header">
                <strong>{r.program}</strong>
                {r.packet && (
                  <span className={`badge ${r.packet.all_satisfied ? "likely" : "possible"}`}>
                    {r.packet.satisfied_count}/{r.packet.total_count} {t(language, "documentsReady")}
                  </span>
                )}
              </div>
              <Checklist
                items={(
                  r.packet?.items ?? r.checklist.map((item) => ({ item, satisfied: false, status: "missing" }))
                ).map((p, i) => ({
                  key: i,
                  done: p.satisfied,
                  status: p.status,
                  label: documentText(language, p.item),
                }))}
              />
            </div>
          ))}
        </section>
      )}

      {likelyPrograms.length > 0 && (
        <section>
          <h3>
            {t(language, "english")} / {t(language, "translated")}
          </h3>
          {likelyPrograms.map((b) => (
            <div key={b.program} className="card" style={{ marginBottom: 12 }}>
              <strong>{b.program}</strong>
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
            </div>
          ))}
        </section>
      )}

      {/* Nothing to apply for: say why, per program, and what to do next --
          never just an empty page. */}
      {!loading && !failed && benefits.data && !hasPack && (
        <section className="card">
          <h2 style={{ marginTop: 0 }}>{t(language, "packEmptyTitle")}</h2>
          {needsAnswers && <p>{t(language, "packNeedsAnswers")}</p>}
          {waiting.length > 0 && (
            <ul>
              {waiting.map((b) => (
                <li key={b.program}>
                  <strong>{b.program}</strong>: {b.explanation}
                </li>
              ))}
            </ul>
          )}
          {notLikely.length > 0 && (
            <>
              <p>
                {t(language, "packNotLikely", {
                  programs: notLikely.map((b) => b.program).join(language === "zh" ? "、" : ", "),
                })}
              </p>
              <ul>
                {notLikely.map((b) => (
                  <li key={b.program}>
                    <strong>{b.program}</strong>: {b.explanation}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="review-source">{t(language, "packChangeHint")}</p>
          {needsAnswers ? (
            <BigButton to="/benefits#questions">{t(language, "missingInfoCta")}</BigButton>
          ) : (
            <BigButton to="/benefits">{t(language, "goToBenefits")}</BigButton>
          )}
          <BigButton variant="secondary" onClick={startScan} disabled={scanning}>
            {t(language, "scanLetter")}
          </BigButton>
        </section>
      )}
    </Layout>
  );
}
