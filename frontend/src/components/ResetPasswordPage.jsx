// frontend/src/components/ResetPasswordPage.jsx
import { useState } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function ResetPasswordPage({ token, onDone }) {
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
        await api.post("/auth/reset-password", {
        token,
        new_password: newPassword,
      });
      setSuccess(true);
    } catch (err) {
      setError(errorDetail(err, "Something went wrong."));
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="login-container">
        <div className="login-card">
          <h1>Password Reset</h1>
          <p className="success-text">Your password has been reset successfully.</p>
          <button onClick={onDone}>Go to Log In</button>
        </div>
      </div>
    );
  }

  return (
    <div className="login-container">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Set a New Password</h1>
        <input
          type="password"
          placeholder="New password (min. 8 characters)"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          required
        />
        <button type="submit" disabled={loading}>
          {loading ? "Please wait..." : "Reset Password"}
        </button>
        {error && <p className="error-text">{error}</p>}
      </form>
    </div>
  );
}

export default ResetPasswordPage;