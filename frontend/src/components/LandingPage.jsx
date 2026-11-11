// frontend/src/components/LandingPage.jsx
function LandingPage({ onGetStarted, onLogin }) {
  return (
    <div className="landing-page">
      <header className="landing-nav">
        <h1 className="landing-logo">AI Data Analytics Platform</h1>
        <div className="landing-nav-buttons">
          <button className="landing-nav-login" onClick={onLogin}>Log In</button>
          <button onClick={onGetStarted}>Sign Up Free</button>
        </div>
      </header>

      <section className="landing-hero">
        <h2>Clean, analyze, and understand your data — without writing a single line of code.</h2>
        <p>
          Upload a CSV, Excel, JSON, or SQL file. Our AI cleans it, finds anomalies, forecasts trends,
          and lets you chat with your data in plain English — then turns it all into a professional report.
        </p>
        <div className="landing-hero-buttons">
          <button onClick={onGetStarted}>Get Started Free</button>
        </div>
        <p className="subtitle" style={{ marginTop: "16px", marginBottom: 0 }}>
          Three steps: 1) Sign up or log in. 2) Upload your file or try the sample dataset. 3) Review the profile, KPIs and AI insights.
        </p>
      </section>

      <section className="landing-features">
        <h3>Everything you need to go from raw data to insight</h3>
        <div className="feature-grid">
          <div className="feature-item"><strong>Automated Data Cleaning</strong><p>Duplicates, missing values, inconsistent text, mixed date formats — fixed with one click, with full undo history.</p></div>
          <div className="feature-item"><strong>Chat With Your Data</strong><p>Ask questions in plain English and get instant answers, charts, or SQL — with full code transparency.</p></div>
          <div className="feature-item"><strong>Anomaly & Root Cause Detection</strong><p>AI automatically flags unusual patterns and explains what's likely driving them.</p></div>
          <div className="feature-item"><strong>Forecasting</strong><p>Predict future trends from historical data, with honest uncertainty ranges — not false precision.</p></div>
          <div className="feature-item"><strong>Automated Reports</strong><p>One-click PDF, Excel, or PowerPoint reports with AI-generated executive summaries.</p></div>
          <div className="feature-item"><strong>Secure by Design</strong><p>Your data is isolated per account, and AI-generated code runs in an isolated sandbox.</p></div>
        </div>
      </section>

      <section className="landing-pricing">
        <h3>Simple pricing</h3>
        <div className="pricing-grid">
          <div className="pricing-card">
            <h4>Free</h4>
            <p className="pricing-price">₹0</p>
            <ul>
              <li>Full data cleaning & analysis</li>
              <li>Chat with your data</li>
              <li>Anomaly detection & forecasting</li>
              <li>PDF, Excel & PPT reports</li>
            </ul>
            <button onClick={onGetStarted}>Start Free</button>
          </div>
          <div className="pricing-card pricing-card-premium">
            <h4>Premium ⭐</h4>
            <p className="pricing-price">Contact us</p>
            <ul>
              <li>Everything in Free</li>
              <li>High-resolution chart exports (PNG/SVG/PDF)</li>
              <li>Charts embedded in PDF reports</li>
              <li>Custom branding (logo & colors)</li>
              <li>JSON & SQL script exports</li>
              <li>Scheduled automated exports</li>
            </ul>
            <button
              onClick={() => {
                window.location.href =
                  "mailto:vikashkumar47023@gmail.com?subject=Premium%20upgrade";
              }}
            >
              Upgrade to Premium
            </button>
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