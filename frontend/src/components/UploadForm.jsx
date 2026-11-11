// frontend/src/components/UploadForm.jsx
import { useState, useEffect, useRef } from "react";

import api from "../api";

// Matches the backend cap (MAX_UPLOAD_SIZE_MB in backend/api/routes.py).
const MAX_UPLOAD_SIZE_MB = 500;
const LARGE_UPLOAD_WARNING_MB = 50;
import { errorDetail } from "../utils";

function UploadForm({ onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [sizeWarning, setSizeWarning] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, []);

  const handleFileChange = (e) => {
    const selected = e.target.files[0] || null;
    setFile(selected);
    setError(null);
    setSizeWarning(null);

    if (!selected) return;

    const sizeMb = selected.size / (1024 * 1024);

    if (sizeMb > MAX_UPLOAD_SIZE_MB) {
      setFile(null);
      setError(
        `This file is ${sizeMb.toFixed(1)} MB, which exceeds the ${MAX_UPLOAD_SIZE_MB} MB upload limit. Please choose a smaller file.`
      );
      e.target.value = "";
      return;
    }

    if (sizeMb > LARGE_UPLOAD_WARNING_MB) {
      setSizeWarning(
        `This file is ${sizeMb.toFixed(1)} MB. Large uploads may take a while to process.`
      );
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError("Please choose a file first.");
      return;
    }

    if (file.size / (1024 * 1024) > MAX_UPLOAD_SIZE_MB) {
      setError(`The file exceeds the ${MAX_UPLOAD_SIZE_MB} MB upload limit. Please choose a smaller file.`);
      return;
    }

    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    const controller = new AbortController();
    abortRef.current = controller;
    setUploadProgress(0);

    try {
      const response = await api.post("/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        signal: controller.signal,
        onUploadProgress: (event) => {
          if (event.total) {
            setUploadProgress(Math.round((event.loaded * 100) / event.total));
          }
        },
      });

      // A cancelled upload is never reported as a success.
      if (controller.signal.aborted) return;

      onUploadSuccess(response.data);
    } catch (err) {
      const cancelled =
        controller.signal.aborted ||
        err?.code === "ERR_CANCELED" ||
        err?.name === "CanceledError";

      if (cancelled) {
        setError("Upload cancelled. No dataset was loaded.");
      } else {
        setError(errorDetail(err, "Upload failed. Please try again."));
      }
    } finally {
      abortRef.current = null;
      setUploadProgress(null);
      setLoading(false);
    }
  };

  const handleCancel = () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  };

  const handleTryDemo = async () => {
    setDemoLoading(true);
    setError(null);
    try {
      const response = await api.post("/demo/load");
      onUploadSuccess(response.data);
    } catch (err) {
      setError("Could not load the sample dataset. Please try again.");
    } finally {
      setDemoLoading(false);
    }
  };

  return (
    <div className="upload-card">
      <h2>Upload a Dataset</h2>
      <p className="subtitle">Supports .csv, .xlsx, .json, and .sql files</p>
      <p className="subtitle" style={{ fontSize: "12px" }}>
        New here? Start with the sample dataset to see the profile, KPIs and insights right away. Then upload your own file.
      </p>

      <input type="file" accept=".csv,.xlsx,.json,.sql" onChange={handleFileChange} />

      {sizeWarning && (
        <p className="subtitle" style={{ color: "var(--amber, #b45309)" }}>
          {sizeWarning}
        </p>
      )}

      <button onClick={handleUpload} disabled={loading || demoLoading}>
        {loading ? "Uploading..." : "Upload"}
      </button>

      {loading && (
        <div style={{ marginTop: "12px" }}>
          <button type="button" className="logout-button" onClick={handleCancel}>
            Cancel upload
          </button>

          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={uploadProgress ?? 0}
            style={{
              marginTop: "10px",
              height: "8px",
              background: "var(--line, #e5e7eb)",
              borderRadius: "4px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${uploadProgress ?? 0}%`,
                height: "100%",
                background: "var(--teal, #0e7c66)",
                transition: "width 0.2s",
              }}
            />
          </div>

          <p className="subtitle" style={{ fontSize: "12px", margin: "6px 0 0" }}>
            {uploadProgress === null || uploadProgress === undefined
              ? "Preparing upload..."
              : uploadProgress < 100
              ? `Uploading... ${uploadProgress}%`
              : "Upload complete. Processing file..."}
          </p>
        </div>
      )}

      <button
        className="demo-button"
        onClick={handleTryDemo}
        disabled={demoLoading || loading}
        style={{ fontWeight: 600 }}
      >
        {demoLoading ? "Loading sample..." : "Try with Sample Data"}
      </button>

      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

export default UploadForm;