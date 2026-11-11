// frontend/src/components/LoginForm.jsx
import { useState } from "react";
import axios from "axios";
import { BASE_URL } from "../api";
import { errorDetail } from "../utils";

function LoginForm({ onLoginSuccess, initialMode = "login" }) {
  const [mode, setMode] = useState(initialMode); // "login" | "signup" | "forgot"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [infoMessage, setInfoMessage] = useState(null);

  const resetMessages = () => {
    setError(null);
    setInfoMessage(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    resetMessages();

    if (mode === "signup" && !acceptedTerms) {
      setError("Please accept the Terms of Service and Privacy Policy to create an account.");
      return;
    }

    setLoading(true);

    try {
      if (mode === "forgot") {
        const response = await axios.post(`${BASE_URL}/api/auth/forgot-password`, { email });
        setInfoMessage(response.data.message);
      } else if (mode === "signup") {
        const response = await axios.post(`${BASE_URL}/api/auth/signup`, {
          email,
          password,
          accepted_terms: acceptedTerms,
        });
        localStorage.setItem("access_token", response.data.access_token);
        onLoginSuccess();
      } else {
        const response = await axios.post(`${BASE_URL}/api/auth/login`, { email, password });
        localStorage.setItem("access_token", response.data.access_token);
        onLoginSuccess();
      }
    } catch (err) {
      setError(errorDetail(err, "Something went wrong."));
    } finally {
      setLoading(false);
    }
  };

  const titles = {
    login: "Please log in to continue",
    signup: "Create your account",
    forgot: "Reset your password",
  };

  return (
    <div className="login-container">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>AI Data Analytics Platform</h1>
        <p className="subtitle">{titles[mode]}</p>

        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        {mode !== "forgot" && (
          <input
            type="password"
            placeholder={mode === "signup" ? "Password (min. 8 characters)" : "Password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        )}

        {mode === "signup" && (
          <label className="terms-checkbox">
            <input
              type="checkbox"
              checked={acceptedTerms}
              onChange={(e) => setAcceptedTerms(e.target.checked)}
            />
            <span>
              I agree to the{" "}
              <a href="/terms" target="_blank" rel="noopener noreferrer">Terms of Service</a>{" "}
              and{" "}
              <a href="/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a>
            </span>
          </label>
        )}

        <button type="submit" disabled={loading}>
          {loading ? "Please wait..." : mode === "signup" ? "Sign Up" : mode === "forgot" ? "Send Reset Link" : "Log In"}
        </button>

        {error && <p className="error-text">{error}</p>}
        {infoMessage && <p className="success-text">{infoMessage}</p>}

        <p className="auth-toggle">
          {mode === "login" && (
            <>
              <button type="button" className="link-button" onClick={() => { setMode("forgot"); resetMessages(); }}>
                Forgot password?
              </button>
              {" · "}
              New here?{" "}
              <button type="button" className="link-button" onClick={() => { setMode("signup"); resetMessages(); }}>
                Sign up
              </button>
            </>
          )}
          {mode === "signup" && (
            <>
              Already have an account?{" "}
              <button type="button" className="link-button" onClick={() => { setMode("login"); resetMessages(); }}>
                Log in
              </button>
            </>
          )}
          {mode === "forgot" && (
            <button type="button" className="link-button" onClick={() => { setMode("login"); resetMessages(); }}>
              Back to log in
            </button>
          )}
        </p>
      </form>
    </div>
  );
}

export default LoginForm;