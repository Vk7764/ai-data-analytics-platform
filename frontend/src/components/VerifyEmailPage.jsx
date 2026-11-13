// frontend/src/components/VerifyEmailPage.jsx
import { useState, useEffect, useRef } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function VerifyEmailPage({ token }) {
  const [status, setStatus] = useState("loading"); // "loading" | "success" | "error"
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    // The token works only once. In development React runs effects twice,
    // and without this guard the second call would turn a success into an error.
    if (started.current) return;
    started.current = true;

    if (!token) {
      setStatus("error");
      setMessage("This verification link is incomplete.");
      return;
    }

    api
      .post("/auth/verify-email", { token })
      .then((res) => {
        setStatus("success");
        setMessage(res.data.message);
      })
      .catch((err) => {
        setStatus("error");
        setMessage(errorDetail(err, "Something went wrong."));
      });
  }, [token]);

  return (
    <div className="login-container">
      <div className="login-card">
        <h1>Email Verification</h1>
        {status === "loading" && <p className="subtitle">Verifying...</p>}
        {status === "success" && <p className="success-text">{message}</p>}
        {status === "error" && <p className="error-text">{message}</p>}
        {status !== "loading" && (
          <a href="/"><button>Go to the app</button></a>
        )}
      </div>
    </div>
  );
}

export default VerifyEmailPage;