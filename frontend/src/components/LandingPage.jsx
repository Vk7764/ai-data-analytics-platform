// frontend/src/components/LandingPage.jsx
import { useLanguage } from "../i18n";

function LandingPage({ onGetStarted, onLogin }) {
  const { t, lang, setLanguage } = useLanguage();
  return (
    <div className="landing-page">
      <header className="landing-nav">
        <h1 className="landing-logo">AI Data Analytics Platform</h1>
        <div className="landing-nav-buttons">
          <button className="landing-nav-login" onClick={() => setLanguage(lang === "hi" ? "en" : "hi")}>
            {lang === "hi" ? "English" : "हिंदी"}
          </button>
          <button className="landing-nav-login" onClick={onLogin}>{t("logIn")}</button>
          <button onClick={onGetStarted}>{t("navSignUpFree")}</button>
        </div>
      </header>

      <section className="landing-hero">
        <h2>{t("heroTitle")}</h2>
        <p>{t("heroText")}</p>
        <div className="landing-hero-buttons">
          <button onClick={onGetStarted}>{t("getStartedFree")}</button>
        </div>
        <p className="subtitle" style={{ marginTop: "16px", marginBottom: 0 }}>
          {t("heroSteps")}
        </p>
      </section>

      <section className="landing-features">
        <h3>{t("featuresTitle")}</h3>
        <div className="feature-grid">
          <div className="feature-item"><strong>{t("featureCleaningTitle")}</strong><p>{t("featureCleaningText")}</p></div>
          <div className="feature-item"><strong>{t("featureChatTitle")}</strong><p>{t("featureChatText")}</p></div>
          <div className="feature-item"><strong>{t("featureAnomalyTitle")}</strong><p>{t("featureAnomalyText")}</p></div>
          <div className="feature-item"><strong>{t("featureForecastTitle")}</strong><p>{t("featureForecastText")}</p></div>
          <div className="feature-item"><strong>{t("featureReportsTitle")}</strong><p>{t("featureReportsText")}</p></div>
          <div className="feature-item"><strong>{t("featureSecureTitle")}</strong><p>{t("featureSecureText")}</p></div>
        </div>
      </section>

      <section className="landing-pricing">
        <h3>{t("pricingTitle")}</h3>
        <div className="pricing-grid">
          <div className="pricing-card">
            <h4>{t("freePlan")}</h4>
            <p className="pricing-price">₹0</p>
            <ul>
              <li>{t("freeItem1")}</li>
              <li>{t("freeItem2")}</li>
              <li>{t("freeItem3")}</li>
              <li>{t("freeItem4")}</li>
            </ul>
            <button onClick={onGetStarted}>{t("startFree")}</button>
          </div>
          <div className="pricing-card pricing-card-premium">
            <h4>{t("premiumPlanTitle")}</h4>
            <p className="pricing-price">₹499</p>
            <p className="subtitle" style={{ fontSize: "12px", marginBottom: "12px" }}>
              {t("premiumSelfServe")}
            </p>
            <ul>
              <li>{t("premiumItem1")}</li>
              <li>{t("premiumItem2")}</li>
              <li>{t("premiumItem3")}</li>
              <li>{t("premiumItem4")}</li>
              <li>{t("premiumItem5")}</li>
              <li>{t("premiumItem6")}</li>
            </ul>
            <button onClick={onGetStarted}>{t("upgradePremium")}</button>
          </div>
        </div>
      </section>

            <footer className="landing-footer">
        <p>
          © {new Date().getFullYear()} AI Data Analytics Platform ·{" "}
          <a href="/terms">Terms of Service</a> · <a href="/privacy">Privacy Policy</a>
        </p>
      </footer>
    </div>
  );
}

export default LandingPage