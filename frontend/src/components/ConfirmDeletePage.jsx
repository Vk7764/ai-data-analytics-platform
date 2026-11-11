// frontend/src/components/ConfirmDeletePage.jsx
import { useState } from "react";
import axios from "axios";
import { BASE_URL } from "../api";
import { errorDetail } from "../utils";

function ConfirmDeletePage({ token }) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(
    token ? null : "This confirmation link is incomplete. Please request a new one from your Account page."
  );
  const [blocked, setBlocked] = useState(!token); // true once the link can't be used any more
  const [done, setDone] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await axios.post(`${BASE_URL}/api/account/delete/confirm`, { token, password });
      localStorage.removeItem("access_token");
      setDone(true);
    } catch (err) {
      const status = err.response?.status;
      setError(errorDetail(err, "Something went wrong. Please try again."));
      setPassword("");
      // 403 means a wrong password, so the user can try again.
      // Any other server answer means this link is no longer usable.
      if (status && status !== 403) setBlocked(true);
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="login-container">
        <div className="login-card">
          <h1>Account deleted</h1>
          <p className="success-text">Your account and all its data have been permanently deleted.</p>
          <a href="/"><button>Back to home</button></a>
        </div>
      </div>
    );
  }

  return (
    <div className="login-container">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Confirm account deletion</h1>

        {!blocked && (
          <>
            <p className="subtitle">
              This permanently deletes your account and all your data, and it cannot be undone.
              Enter your password to confirm.
            </p>
            <input
              type="password"
              placeholder="Your password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button type="submit" className="danger-button" disabled={loading || !password}>
              {loading ? "Deleting..." : "Permanently delete my account"}
            </button>
          </>
        )}

        {error && <p className="error-text">{error}</p>}

        {blocked ? (
          <a href="/"><button type="button">Back to home</button></a>
        ) : (
          <p className="auth-toggle"><a href="/">No, keep my account</a></p>
        )}
      </form>
    </div>
  );
}

export default ConfirmDeletePage;