// frontend/src/components/BrandingSettings.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";

function BrandingSettings() {
  const [isPremium, setIsPremium] = useState(false);
  const [hasLogo, setHasLogo] = useState(false);
  const [accentColor, setAccentColor] = useState("#0e7c66");
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);

  const loadInfo = async () => {
    try {
      const [meRes, brandingRes] = await Promise.all([api.get("/me"), api.get("/branding")]);

      setIsPremium(meRes?.data?.plan === "premium");
      setHasLogo(Boolean(brandingRes?.data?.has_logo));

      const accent = brandingRes?.data?.accent_color;
      if (typeof accent === "string" && accent.trim()) {
        setAccentColor(accent.trim());
      }
    } catch (err) {
      // ignore
    }
  };

  useEffect(() => {
    loadInfo();
  }, []);

  if (!isPremium) return null;

  const handleLogoUpload = async () => {
    if (!file) return;
    setLoading(true);
    setMessage(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      await api.post("/branding/logo", formData, { headers: { "Content-Type": "multipart/form-data" } });
      setMessage("Logo uploaded.");
      setHasLogo(true);
    } catch (err) {
      setMessage(errorDetail(err, "Could not upload logo."));
    } finally {
      setLoading(false);
    }
  };

  const handleColorSave = async () => {
    setLoading(true);
    setMessage(null);
    try {
      await api.post("/branding/color", { accent_color: accentColor });
      setMessage("Brand color saved.");
    } catch (err) {
      setMessage(errorDetail(err, "Could not save color."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="upload-card">
      <h2>Report Branding <span className="premium-tag">⭐ Premium</span></h2>
      <p className="subtitle">Add your logo and brand color to PDF reports.</p>

      <div className="branding-row">
        <div>
          <label className="branding-label">Logo {hasLogo && "(currently set)"}</label>
          <input type="file" accept="image/png,image/jpeg" onChange={(e) => setFile(e.target.files[0])} />
          <button onClick={handleLogoUpload} disabled={loading || !file}>Upload Logo</button>
        </div>
      </div>

      <div className="branding-row">
        <div>
          <label className="branding-label">Accent Color</label>
          <input type="color" value={accentColor} onChange={(e) => setAccentColor(e.target.value)} className="color-input" />
          <button onClick={handleColorSave} disabled={loading}>Save Color</button>
        </div>
      </div>

      {message && <p className="success-text">{message}</p>}
    </div>
  );
}

export default BrandingSettings;