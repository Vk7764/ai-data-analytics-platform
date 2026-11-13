// frontend/src/components/HistoryDrawer.jsx
import { useState, useEffect } from "react";
import api from "../api";
import { errorDetail } from "../utils";
import DatasetShareLinks from "./DatasetShareLinks";
import { useLanguage } from "../i18n";

function HistoryDrawer({ onSelectDataset, activeDatasetId, onDeleteDataset }) {
  const { t } = useLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [shareTarget, setShareTarget] = useState(null);

  const term = String(searchTerm || "").trim().toLowerCase();
  const safeDatasets = Array.isArray(datasets)
    ? datasets.filter((d) => d && typeof d === "object")
    : [];
  const visibleDatasets = term
    ? safeDatasets.filter(
        (d) =>
          String(d.filename || "").toLowerCase().includes(term) ||
          String(d.uploaded_at || "").toLowerCase().includes(term)
      )
    : safeDatasets;

  const fetchDatasets = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get("/datasets");
      const list = Array.isArray(response.data?.datasets) ? response.data.datasets : [];
      setDatasets(
        list.filter(
          (d) =>
            d &&
            typeof d === "object" &&
            typeof d.dataset_id === "string" &&
            d.dataset_id
        )
      );
    } catch (err) {
      setError(errorDetail(err, "Could not load dataset history."));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchDatasets();
    }
  }, [isOpen]);

  const handleSelect = async (datasetId) => {
    try {
      const response = await api.get(`/dataset/${datasetId}/profile`);
      onSelectDataset({
        dataset_id: datasetId,
        filename: datasets.find((d) => d.dataset_id === datasetId)?.filename || datasetId,
        profile: response.data.profile,
        preview: response.data.preview,
      });
      setIsOpen(false);
    } catch (err) {
      setError(errorDetail(err, "Could not load this dataset."));
    }
  };

  const handleDelete = async (datasetId, e) => {
    e.stopPropagation();
    if (!window.confirm(t("confirmDeleteDataset"))) return;
    try {
      await api.delete(`/dataset/${datasetId}`);
      onDeleteDataset?.(datasetId);
      fetchDatasets();
    } catch (err) {
      setError(errorDetail(err, "Could not delete this dataset."));
    }
  };

  const handleDuplicate = async (d, e) => {
    e.stopPropagation();
    try {
      await api.post(`/dataset/${d.dataset_id}/duplicate`);
      fetchDatasets();
    } catch (err) {
      setError(errorDetail(err, "Could not duplicate this dataset."));
    }
  };

  const handleRename = async (d, e) => {
    e.stopPropagation();
    const newName = window.prompt(t("renamePrompt"), d.filename);
    if (newName === null) return;
    try {
      await api.patch(`/dataset/${d.dataset_id}`, { filename: newName });
      fetchDatasets();
    } catch (err) {
      setError(errorDetail(err, "Could not rename this dataset."));
    }
  };

  return (
    <>
      <button className="menu-toggle" onClick={() => setIsOpen(true)} aria-label="Open dataset history">
        <span></span>
        <span></span>
        <span></span>
      </button>

      {isOpen && (
        <div className="drawer-overlay" onClick={() => setIsOpen(false)}>
          <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <h2>{t("historyTitle")}</h2>
              <button className="drawer-close" onClick={() => setIsOpen(false)} aria-label="Close">
                &times;
              </button>
            </div>

            {loading && <p className="subtitle">{t("loading")}</p>}
            {error && <p className="error-text">{error}</p>}
            {!loading && datasets.length === 0 && (
              <p className="subtitle">{t("historyEmpty")}</p>
            )}

            <input
              type="text"
              placeholder={t("historySearchPlaceholder")}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ width: "100%", marginBottom: "16px" }}
            />

            {!loading && datasets.length > 0 && visibleDatasets.length === 0 && (
              <p className="subtitle">{t("historyNoMatch")}</p>
            )}

            <ul className="history-list">
              {visibleDatasets.map((d) => (
                <li key={d.dataset_id} className="history-item" onClick={() => handleSelect(d.dataset_id)}>
                  <div>
                    <strong>{d.filename}{activeDatasetId === d.dataset_id ? t("activeTag") : ""}</strong>
                    <p>{d.uploaded_at}</p>
                  </div>
                  <div className="button-group">
                    <button className="logout-button" onClick={(e) => handleDuplicate(d, e)}>
                      {t("duplicate")}
                    </button>
                    <button className="logout-button" onClick={(e) => handleRename(d, e)}>
                      {t("rename")}
                    </button>
                    <button
                      className="logout-button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setShareTarget({ datasetId: d.dataset_id, displayName: d.filename });
                      }}
                    >
                      {t("share")}
                    </button>
                    <button className="delete-button" onClick={(e) => handleDelete(d.dataset_id, e)}>
                      {t("delete")}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {shareTarget && (
        <DatasetShareLinks
          datasetId={shareTarget.datasetId}
          displayName={shareTarget.displayName}
          onClose={() => setShareTarget(null)}
        />
      )}
    </>
  );
}

export default HistoryDrawer;