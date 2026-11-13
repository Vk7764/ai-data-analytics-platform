// frontend/src/components/VerifyEmailBanner.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { useLanguage } from "../i18n";

function VerifyEmailBanner() {
  const { t } = useLanguage();
  // Assume verified until the server says otherwise, so the banner never flashes for verified users.
  const [verified, setVerified] = useState(true);
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    let mounted = true;
    let interval = null;

    const stop = () => {
      if (interval) {
        clearInterval(interval);
        interval = null;
      }
    };

    const check = () =>
      api
        .get("/me")
        .then((res) => {
          if (!mounted) return;

          const isVerified = res?.data?.email_verified !== false;
          setVerified(isVerified);

          if (isVerified) {
            stop();
          }
        })
        .catch(() => {});

    check();
    // Re-check now and then, so the banner disappears soon after the link is clicked in another tab.
    interval = setInterval(check, 15000);

    return () => {
      mounted = false;
      stop();
    };
  }, []);

  const handleResend = async () => {
    setSending(true);
    setMessage(null);
    try {
      const res = await api.post("/auth/resend-verification");
      setMessage(res.data.message);
    } catch (err) {
      setMessage(err.response?.data?.detail || "Could not send the email.");
    } finally {
      setSending(false);
    }
  };

  if (verified) return null;

  return (
    <div className="verify-banner">
      <span>
        {t("verifyBanner")}
        {message && <strong> {message}</strong>}
      </span>
      <button onClick={handleResend} disabled={sending}>
        {sending ? t("sending") : t("resendEmail")}
      </button>
    </div>
  );
}

export default VerifyEmailBanner;