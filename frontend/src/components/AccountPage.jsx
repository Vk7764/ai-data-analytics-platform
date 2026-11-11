// frontend/src/components/AccountPage.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function formatDate(value) {
  if (!value) return "—";
  // The server stores UTC times without a timezone marker, so add one before parsing.
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

function Message({ message }) {
  if (!message) return null;
  return (
    <p className={`account-message ${message.type === "ok" ? "success-text" : "error-text"}`}>
      {message.text}
    </p>
  );
}

// One line of the settings list: label, current value, and an action button.
// The edit form (children) is only shown while the row is open.
function SettingsRow({ label, value, actionLabel, open, onToggle, message, children }) {
  return (
    <div className="settings-row">
      <div className="settings-row-main">
        <div className="settings-row-label">{label}</div>
        <div className="settings-row-value">{value}</div>
        <button className="settings-row-action" onClick={onToggle}>
          {open ? "Cancel" : actionLabel}
        </button>
      </div>
      {open && <div className="settings-row-panel">{children}</div>}
      <Message message={message} />
    </div>
  );
}

function AccountPage({ onBack }) {
  const [account, setAccount] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [openRow, setOpenRow] = useState(null); // "profile" | "email" | "password" | "delete" | null
  const [busy, setBusy] = useState(null);
  const [messages, setMessages] = useState({});

  const [fullName, setFullName] = useState("");
  const [organization, setOrganization] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const setMessage = (key, message) => setMessages((prev) => ({ ...prev, [key]: message }));

  const loadAccount = async () => {
    try {
      const res = await api.get("/account");
      setAccount(res.data);
      setFullName(res.data.full_name || "");
      setOrganization(res.data.organization || "");
    } catch (err) {
      setLoadError(errorDetail(err, "Could not load your account details."));
    }
  };

  useEffect(() => {
    loadAccount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Opens a row (closing any other one), or closes it if it is already open.
  // Either way the forms start clean, so nothing typed earlier lingers.
  const toggleRow = (key) => {
    setOpenRow((current) => (current === key ? null : key));
    setNewEmail("");
    setEmailPassword("");
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    if (account) {
      setFullName(account.full_name || "");
      setOrganization(account.organization || "");
    }
    setMessage(key, null);
  };

  // Runs one action. On success the row closes (unless close is false) and the
  // result stays visible under it; on failure the form stays open with the error.
  const run = async (key, action, { close = true, messageKey = key } = {}) => {
    setBusy(key);
    setMessage(messageKey, null);
    try {
      const text = await action();
      setMessage(messageKey, { type: "ok", text });
      if (close) setOpenRow(null);
    } catch (err) {
      setMessage(messageKey, {
        type: "error",
        text: errorDetail(err, "Something went wrong. Please try again."),
      });
    } finally {
      setBusy(null);
    }
  };

  const saveProfile = () =>
    run("profile", async () => {
      await api.put("/account/profile", { full_name: fullName, organization });
      await loadAccount();
      return "Profile saved.";
    });

  const resendVerification = () =>
    run("verify", async () => (await api.post("/auth/resend-verification")).data.message, {
      close: false,
      messageKey: "email",
    });

  const changeEmail = () =>
    run("email", async () => {
      const res = await api.post("/account/change-email", { new_email: newEmail, password: emailPassword });
      setNewEmail("");
      setEmailPassword("");
      await loadAccount();
      return res.data.message;
    });

  const changePassword = () => {
    if (newPassword.length < 8) {
      setMessage("password", { type: "error", text: "New password must be at least 8 characters." });
      return;
    }
    if (newPassword !== confirmPassword) {
      setMessage("password", { type: "error", text: "The new passwords don't match." });
      return;
    }
    run("password", async () => {
      await api.post("/account/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      return "Password changed.";
    });
  };

  const sendDeletionEmail = () =>
    run("delete", async () => (await api.post("/account/delete/request")).data.message, { close: false });

  if (loadError) {
    return <p className="error-text">{loadError}</p>;
  }
  if (!account) {
    return <p className="subtitle">Loading your account...</p>;
  }

  const isPremium = account.plan === "premium";
  const profileSummary = [account.full_name, account.organization].filter(Boolean).join(" · ");

  return (
    <div className="account-page">
      <div className="account-page-header">
        <h2>Your Account</h2>
        <button className="logout-button" onClick={onBack}>← Back to dashboard</button>
      </div>

      <section className="account-section">
        <h3>Overview</h3>
        <div className="account-details">
          <div className="account-detail">
            <span className="account-detail-label">Plan</span>
            <span className={`status-badge ${isPremium ? "status-ok" : ""}`}>
              {isPremium ? "Premium ⭐" : "Free"}
            </span>
          </div>
          <div className="account-detail">
            <span className="account-detail-label">Member since</span>
            <span className="account-detail-value">{formatDate(account.created_at)}</span>
          </div>
          <div className="account-detail">
            <span className="account-detail-label">Datasets</span>
            <span className="account-detail-value">{account.datasets_count}</span>
          </div>
          <div className="account-detail">
            <span className="account-detail-label">AI requests today</span>
            <span className="account-detail-value">
              {account.ai_usage.used} / {account.ai_usage.limit}
            </span>
          </div>
          <div className="account-detail">
            <span className="account-detail-label">Terms accepted on</span>
            <span className="account-detail-value">{formatDate(account.terms_accepted_at)}</span>
          </div>
        </div>
      </section>

      <section className="account-section">
        <h3>Profile</h3>
        <SettingsRow
          label="Name &amp; organization"
          value={profileSummary || <span className="settings-muted">Not set</span>}
          actionLabel="Edit"
          open={openRow === "profile"}
          onToggle={() => toggleRow("profile")}
          message={messages.profile}
        >
          <form className="account-form" onSubmit={(e) => { e.preventDefault(); saveProfile(); }}>
            <label htmlFor="full-name">Full name</label>
            <input id="full-name" type="text" maxLength={100} value={fullName} onChange={(e) => setFullName(e.target.value)} />
            <label htmlFor="organization">Organization / college</label>
            <input id="organization" type="text" maxLength={100} value={organization} onChange={(e) => setOrganization(e.target.value)} />
            <button type="submit" disabled={busy === "profile"}>
              {busy === "profile" ? "Saving..." : "Save"}
            </button>
          </form>
        </SettingsRow>
      </section>

      <section className="account-section">
        <h3>Sign-in &amp; security</h3>

        <SettingsRow
          label="Email"
          value={
            <>
              {account.email}{" "}
              {account.email_verified ? (
                <span className="status-badge status-ok">Verified</span>
              ) : (
                <>
                  <span className="status-badge status-warn">Not verified</span>{" "}
                  <button className="link-button" onClick={resendVerification} disabled={busy === "verify"}>
                    {busy === "verify" ? "Sending..." : "Resend email"}
                  </button>
                </>
              )}
            </>
          }
          actionLabel="Change"
          open={openRow === "email"}
          onToggle={() => toggleRow("email")}
          message={messages.email}
        >
          <p className="subtitle">You'll need to verify the new address before using AI features again.</p>
          <form className="account-form" onSubmit={(e) => { e.preventDefault(); changeEmail(); }}>
            <label htmlFor="new-email">New email</label>
            <input id="new-email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} required />
            <label htmlFor="email-password">Current password</label>
            <input id="email-password" type="password" autoComplete="current-password" value={emailPassword} onChange={(e) => setEmailPassword(e.target.value)} required />
            <button type="submit" disabled={busy === "email"}>
              {busy === "email" ? "Updating..." : "Update email"}
            </button>
          </form>
        </SettingsRow>

        <SettingsRow
          label="Password"
          value="••••••••••"
          actionLabel="Change"
          open={openRow === "password"}
          onToggle={() => toggleRow("password")}
          message={messages.password}
        >
          <form className="account-form" onSubmit={(e) => { e.preventDefault(); changePassword(); }}>
            <label htmlFor="current-password">Current password</label>
            <input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
            <label htmlFor="new-password">New password (min. 8 characters)</label>
            <input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
            <label htmlFor="confirm-password">Confirm new password</label>
            <input id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
            <button type="submit" disabled={busy === "password"}>
              {busy === "password" ? "Updating..." : "Update password"}
            </button>
          </form>
        </SettingsRow>
      </section>

      <section className="account-section danger-zone">
        <h3>Danger zone</h3>
        <SettingsRow
          label="Delete account"
          value="Permanently removes your account and all your data."
          actionLabel="Delete…"
          open={openRow === "delete"}
          onToggle={() => toggleRow("delete")}
          message={messages.delete}
        >
          <p className="subtitle">
            This permanently deletes your datasets, chat history, reports, and settings, and it cannot be undone.
            To keep your account safe, deletion takes two steps:
          </p>
          <ol className="delete-steps">
            <li>We email a confirmation link to <strong>{account.email}</strong>.</li>
            <li>You open that link and enter your password. Only then is the account deleted.</li>
          </ol>
          <button className="danger-button" onClick={sendDeletionEmail} disabled={busy === "delete"}>
            {busy === "delete"
              ? "Sending..."
              : messages.delete?.type === "ok"
              ? "Resend confirmation email"
              : "Send confirmation email"}
          </button>
        </SettingsRow>
      </section>
    </div>
  );
}

export default AccountPage;