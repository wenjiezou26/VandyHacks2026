import BigButton from "../components/BigButton";
import ErrorBox from "../components/ErrorBox";
import Layout from "../components/Layout";
import { useAuth } from "../context/useAuth";
import { useLanguage } from "../context/useLanguage";
import { UI_STRINGS, numberLabel, statusLabel, t } from "../strings";
import { formatNumberUsed } from "../format";
import { useBenefits } from "../hooks/useBenefits";

export default function CaseworkerCard() {
  const { language } = useLanguage();
  const { token } = useAuth();
  const loaded = useBenefits(token, language);
  const benefits = loaded.data?.results || [];

  return (
    <Layout backTo="/benefits">
      <div className="no-print">
        <BigButton onClick={() => window.print()}>{t(language, "print")}</BigButton>
      </div>

      <h1>
        {UI_STRINGS.en.caseworkerCardTitle} / {t(language, "caseworkerCardTitle")}
      </h1>
      {loaded.loading && <p className="spinner-wrap">{t(language, "loading")}</p>}
      {loaded.error && (
        <ErrorBox
          title={t(language, loaded.error.timeout ? "errBenefitsTimeout" : "errLoadBenefits")}
          error={loaded.error}
          onRetry={loaded.reload}
        />
      )}

      {benefits.map((b) => (
        <div key={b.program} className="card" style={{ marginBottom: 12 }}>
          <h2>
            {b.program} &mdash; {statusLabel("en", b)} / {statusLabel(language, b)}
          </h2>
          <p>
            <em>EN:</em> {b.rule_applied_en}
          </p>
          {language && language !== "en" && (
            <p>
              <em>{language.toUpperCase()}:</em> {b.rule_applied}
            </p>
          )}
          <table className="kv-table">
            <tbody>
              {Object.entries(b.numbers_used).map(([key, value]) => (
                <tr key={key}>
                  <td>
                    {numberLabel("en", key)}
                    {language && language !== "en" && ` / ${numberLabel(language, key)}`}
                  </td>
                  <td>{formatNumberUsed(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            <em>{(language || "en").toUpperCase()}:</em> {b.explanation}
          </p>
        </div>
      ))}

      <p className="disclaimer">
        {UI_STRINGS.en.disclaimer} / {t(language, "disclaimer")}
      </p>
    </Layout>
  );
}
