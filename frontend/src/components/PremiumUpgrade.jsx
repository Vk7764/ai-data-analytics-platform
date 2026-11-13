// frontend/src/components/PremiumUpgrade.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function loadRazorpayScript() {
  return new Promise((resolve) => {
    if (window.Razorpay) {
      resolve(true);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

function PremiumUpgrade({ isPremium, onUpgraded }) {
  const [status, setStatus] = useState(null); // {enabled, public_key, price_inr}
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    api
      .get("/payments/status")
      .then((res) => setStatus(res.data))
      .catch(() => setStatus({ enabled: false }));
  }, []);

  if (isPremium || !status || !status.enabled) return null;

  const handleUpgrade = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const orderRes = await api.post("/payments/create-order");
      if (orderRes.data.already_premium) {
        setMessage({ type: "ok", text: "Your account is already Premium." });
        return;
      }
      const ok = await loadRazorpayScript();
      if (!ok) {
        setMessage({ type: "error", text: "Could not load the payment window. Check your internet connection and try again." });
        return;
      }
      const options = {
        key: orderRes.data.key_id,
        amount: orderRes.data.amount,
        currency: orderRes.data.currency,
        name: "AI Data Analytics Platform",
        description: "Premium plan upgrade",
        order_id: orderRes.data.order_id,
        theme: { color: "#0e7c66" },
        handler: async (response) => {
          try {
            const verifyRes = await api.post("/payments/verify", {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            setMessage({ type: "ok", text: verifyRes.data.message });
            onUpgraded();
          } catch (err) {
            setMessage({ type: "error", text: errorDetail(err, "Payment verification failed.") });
          }
        },
        modal: {
          ondismiss: () => {
            setBusy(false);
            setMessage({ type: "error", text: "Payment window closed before completion." });
          },
        },
      };
      const rzp = new window.Razorpay(options);
      rzp.on("payment.failed", () => {
        setMessage({ type: "error", text: "The payment failed at the bank's end. No plan change was made. You can try again." });
        setBusy(false);
      });
      rzp.open();
    } catch (err) {
      setMessage({ type: "error", text: errorDetail(err, "Could not start the payment.") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="account-section">
      <h3>Upgrade</h3>
      <p className="subtitle">
        Premium unlocks a higher daily AI limit, high-resolution chart exports, charts in PDF
        reports, custom branding, JSON and SQL exports, and scheduled automated exports.
      </p>
      <button onClick={handleUpgrade} disabled={busy}>
        {busy ? "Opening payment..." : `Upgrade to Premium (₹${status.price_inr})`}
      </button>
      {message && (
        <p className={message.type === "ok" ? "success-text" : "error-text"}>{message.text}</p>
      )}
    </section>
  );
}

export default PremiumUpgrade;