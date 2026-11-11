// frontend/src/components/DataProfile.jsx
import { useState, useEffect, useRef } from "react";
import api from "../api";
import { errorDetail } from "../utils";
import DatasetIntelligencePanel from "./DatasetIntelligencePanel";
import QualitySummaryCard from "./QualitySummaryCard";

function DataProfile({ data, onCleaned }) {
  const { profile, preview, dataset_id } = data;

  const [colError, setColError] = useState(null);
  const [colBusy, setColBusy] = useState(false);
  const [renameCol, setRenameCol] = useState("");
  const [newName, setNewName] = useState("");
  const [calcName, setCalcName] = useState("");
  const [calcA, setCalcA] = useState("");
  const [calcOp, setCalcOp] = useState("+");
  const [calcB, setCalcB] = useState("");
  const [filterCol, setFilterCol] = useState("");
  const [filterOp, setFilterOp] = useState("==");
  const [filterVal, setFilterVal] = useState("");
  const [replaceCol, setReplaceCol] = useState("");
  const [findVal, setFindVal] = useState("");
  const [replaceVal, setReplaceVal] = useState("");
  const [editingCell, setEditingCell] = useState(null);
  // True once the active edit was committed or cancelled, so a trailing blur event cannot act on it again.
  const editSettledRef = useRef(false);

  const [permSortCol, setPermSortCol] = useState("");
  const [permSortDir, setPermSortDir] = useState("asc");
  const [sampleSize, setSampleSize] = useState("100");

  const [inspectedCol, setInspectedCol] = useState(null);
  const [colSummary, setColSummary] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);

  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [pageSize, setPageSize] = useState(10);
  const [page, setPage] = useState(0);
  const [pageData, setPageData] = useState(null);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState(null);

  // The search box updates immediately; the rows request uses this value after a short pause in typing.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const term = String(search ?? "").trim();

    // Clearing the search applies at once.
    if (!term) {
      setDebouncedSearch("");
      return undefined;
    }

    const timer = setTimeout(() => setDebouncedSearch(term), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const [pivotGroupBy, setPivotGroupBy] = useState("");
  const [pivotValue, setPivotValue] = useState("");
  const [pivotAgg, setPivotAgg] = useState("sum");
  const [pivotSplit, setPivotSplit] = useState("");
  const [pivotData, setPivotData] = useState(null);
  const [pivotLoading, setPivotLoading] = useState(false);
  const [pivotError, setPivotError] = useState(null);

  useEffect(() => {
    setInspectedCol(null);
    setColSummary(null);
  }, [dataset_id, preview]);

  const runColumnAction = async (payload) => {
    setColBusy(true);
    setColError(null);
    try {
      const res = await api.post(`/dataset/${dataset_id}/clean`, payload);
      onCleaned?.(res.data);
      return true;
    } catch (err) {
      setColError(errorDetail(err, "Column action failed."));
      return false;
    } finally {
      setColBusy(false);
    }
  };

  const handlePermanentSort = async () => {
    if (!permSortCol) {
      setColError("Pick a column to sort by.");
      return;
    }
    await runColumnAction({ action: "sort_dataset", column: permSortCol, operator: permSortDir });
  };

  const handleSampleRows = async () => {
    const n = Number(sampleSize);
    if (!Number.isInteger(n) || n < 1) {
      setColError("Enter a whole number of rows to sample.");
      return;
    }
    await runColumnAction({ action: "sample_rows", sample_count: n });
  };

  const handleInspectColumn = async (colName) => {
    if (!colName) return;

    if (typeof inspectedCol !== "undefined" && inspectedCol === colName) {
      if (typeof setInspectedCol === "function") setInspectedCol(null);
      if (typeof setColSummary === "function") setColSummary(null);
      return;
    }

    if (typeof setInspectLoading === "function") setInspectLoading(true);
    if (typeof setColError === "function") setColError(null);

    try {
      const res = await api.get(`/dataset/${dataset_id}/column/${encodeURIComponent(colName)}/summary`);

      if (typeof setInspectedCol === "function") setInspectedCol(colName);
      if (typeof setColSummary === "function") {
        setColSummary(res?.data && typeof res.data === "object" ? res.data : null);
      }
    } catch (err) {
      if (typeof setInspectedCol === "function") setInspectedCol(null);
      if (typeof setColSummary === "function") setColSummary(null);
      if (typeof setColError === "function") {
        setColError(errorDetail(err, "Could not inspect this column."));
      }
    } finally {
      if (typeof setInspectLoading === "function") setInspectLoading(false);
    }
  };

  const handleFilterRows = async () => {
    if (!filterCol || !filterVal.trim()) {
      setColError("Pick a column and enter a filter value.");
      return;
    }
    const ok = await runColumnAction({
      action: "filter_rows",
      column: filterCol,
      operator: filterOp,
      filter_value: filterVal.trim(),
    });
    if (ok) setFilterVal("");
  };

  const handleFindReplace = async () => {
    if (!replaceCol || !findVal.trim()) {
      setColError("Pick a column and enter a value to find.");
      return;
    }
    const ok = await runColumnAction({
      action: "find_and_replace",
      column: replaceCol,
      filter_value: findVal,
      replace_value: replaceVal,
    });
    if (ok) {
      setFindVal("");
      setReplaceVal("");
    }
  };

  const commitCellEdit = async () => {
    if (!editingCell || typeof editingCell !== "object" || editSettledRef.current) return;
    editSettledRef.current = true;
    const { rowId, col, value, oldValue } = editingCell;
    setEditingCell(null);

    const rowIndex = Number(rowId);
    if (!Number.isInteger(rowIndex) || rowIndex < 0) return;
    if (typeof col !== "string" || !col) return;
    if (String(value ?? "") === String(oldValue ?? "")) return;

    await runColumnAction({
      action: "update_cell",
      column: col,
      row_index: rowIndex,
      replace_value: String(value ?? ""),
      expected_old_value: String(oldValue ?? ""),
    });
  };

  const safeProfileColumns = Array.isArray(profile?.columns)
    ? profile.columns.filter((c) => c && typeof c === "object")
    : [];

  const allColNames = safeProfileColumns
    .map((c) => String(c.name ?? ""))
    .filter(Boolean);

  const numericCols = safeProfileColumns
    .filter((c) => c.inferred_type === "numeric")
    .map((c) => String(c.name ?? ""))
    .filter(Boolean);

  const handleRename = async () => {
    if (!renameCol || !newName.trim()) {
      setColError("Pick a column and enter a new name.");
      return;
    }
    const ok = await runColumnAction({ action: "rename_column", column: renameCol, new_name: newName.trim() });
    if (ok) {
      setRenameCol("");
      setNewName("");
    }
  };

  const handleDrop = async () => {
    if (!renameCol) {
      setColError("Pick a column to drop.");
      return;
    }
    if (!window.confirm(`Drop column "${renameCol}"?`)) return;
    const ok = await runColumnAction({ action: "drop_column", column: renameCol });
    if (ok) setRenameCol("");
  };

  const handleAddCalc = async () => {
    if (!calcName.trim() || !calcA || !calcB) {
      setColError("Enter a name and pick both columns.");
      return;
    }
    const ok = await runColumnAction({
      action: "add_calculated_column",
      new_name: calcName.trim(),
      column: calcA,
      operator: calcOp,
      second_column: calcB,
    });
    if (ok) setCalcName("");
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const safePage = Number.isFinite(Number(page)) && Number(page) >= 0 ? Number(page) : 0;
      const safePageSize = Number.isFinite(Number(pageSize)) && Number(pageSize) > 0 ? Number(pageSize) : 10;

      setRowsLoading(true);
      try {
        const res = await api.get(`/dataset/${dataset_id}/rows`, {
          params: {
            offset: safePage * safePageSize,
            limit: safePageSize,
            search: debouncedSearch.trim() || undefined,
            sort_by: sortBy || undefined,
            sort_dir: sortDir,
          },
        });
        if (!cancelled) {
          setPageData(res.data);
          setRowsError(null);
          const returnedTotal = Number(res.data.total_rows) || 0;
          const lastValidPage = Math.max(0, Math.ceil(returnedTotal / safePageSize) - 1);
          if (safePage > lastValidPage) setPage(lastValidPage);
        }
      } catch (err) {
        if (!cancelled) {
          setPageData(null);
          setRowsError(errorDetail(err, "Could not load rows."));
        }
      } finally {
        if (!cancelled) setRowsLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [dataset_id, debouncedSearch, sortBy, sortDir, page, pageSize, preview]);

  const runPivot = async () => {
    const currentDatasetId = dataset_id;

    if (!currentDatasetId) {
      setPivotError("Dataset id is unavailable.");
      return;
    }

    if (!pivotGroupBy || !pivotValue) {
      setPivotError("Choose a group-by column and a value column.");
      return;
    }

    if (pivotGroupBy === pivotValue) {
      setPivotError("Group By and Value must be different columns.");
      return;
    }

    setPivotLoading(true);
    setPivotError(null);

    try {
      const res = await api.get(`/dataset/${currentDatasetId}/pivot`, {
        params: {
          group_by: pivotGroupBy,
          value_column: pivotValue,
          agg: pivotAgg,
          split_by: pivotSplit || undefined,
        },
      });
      setPivotData(res.data);
    } catch (err) {
      setPivotData(null);
      setPivotError(errorDetail(err, "Could not build this pivot table."));
    } finally {
      setPivotLoading(false);
    }
  };

  const handleSearch = (value) => {
    setSearch(value);
    setPage(0);
  };

  const toggleSort = (name) => {
    if (typeof rowsLoading !== "undefined" && rowsLoading) return;
    if (sortBy === name) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortBy(name);
      setSortDir("asc");
    }
    setPage(0);
  };

  const rawRows = pageData ? pageData.rows : preview;
  const rows = Array.isArray(rawRows) ? rawRows : [];
  const rawTotal = pageData ? pageData.total_rows : (Array.isArray(preview) ? preview.length : 0);
  const total = Number.isFinite(Number(rawTotal)) ? Math.max(0, Number(rawTotal)) : rows.length;
  const safePage = Number.isFinite(Number(page)) && Number(page) >= 0 ? Number(page) : 0;
  const safePageSize = Number.isFinite(Number(pageSize)) && Number(pageSize) > 0 ? Number(pageSize) : 10;
  const lastPage = Math.max(0, Math.ceil(total / safePageSize) - 1);
  const from = total === 0 ? 0 : safePage * safePageSize + 1;
  const to = safePage * safePageSize + rows.length;

  return (
    <div className="profile-card">
      <h2>Dataset Overview</h2>
      <p className="dataset-id">Dataset ID: {dataset_id}</p>

      <div className="stats-row">
        <div className="stat-box">
          <span className="stat-value">{profile.num_rows}</span>
          <span className="stat-label">Rows</span>
        </div>
        <div className="stat-box">
          <span className="stat-value">{profile.num_columns}</span>
          <span className="stat-label">Columns</span>
        </div>
        <div className="stat-box">
          <span className="stat-value">{profile.duplicate_rows}</span>
          <span className="stat-label">Duplicate Rows</span>
        </div>
        <div className="stat-box">
          <span className="stat-value">{profile.health_score ?? 100}%</span>
          <span className="stat-label">Health Score</span>
        </div>
      </div>

      <h3>Column Tools and Feature Builder</h3>
      <div className="forecast-controls">
        <select value={renameCol} onChange={(e) => setRenameCol(e.target.value)}>
          <option value="">Select column</option>
          {allColNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="New column name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button onClick={handleRename} disabled={colBusy}>Rename</button>
        <button
          className="danger-button"
          onClick={handleDrop}
          disabled={colBusy || profile.columns.length <= 1}
        >
          Drop Column
        </button>
      </div>

      <div className="forecast-controls">
        <input
          type="text"
          placeholder="New column (e.g. Profit)"
          value={calcName}
          onChange={(e) => setCalcName(e.target.value)}
        />
        <select value={calcA} onChange={(e) => setCalcA(e.target.value)}>
          <option value="">Column A</option>
          {numericCols.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <select value={calcOp} onChange={(e) => setCalcOp(e.target.value)}>
          <option value="+">+</option>
          <option value="-">-</option>
          <option value="*">*</option>
          <option value="/">/</option>
        </select>
        <select value={calcB} onChange={(e) => setCalcB(e.target.value)}>
          <option value="">Column B</option>
          {numericCols.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <button onClick={handleAddCalc} disabled={colBusy}>Add Column</button>
      </div>

      <div className="forecast-controls">
        <select value={filterCol} onChange={(e) => setFilterCol(e.target.value)}>
          <option value="">Filter column</option>
          {allColNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <select value={filterOp} onChange={(e) => setFilterOp(e.target.value)}>
          <option value="==">==</option>
          <option value="!=">!=</option>
          <option value=">">&gt;</option>
          <option value="<">&lt;</option>
          <option value=">=">&gt;=</option>
          <option value="<=">&lt;=</option>
          <option value="contains">contains</option>
        </select>
        <input
          type="text"
          placeholder="Filter value..."
          value={filterVal}
          onChange={(e) => setFilterVal(e.target.value)}
        />
        <button onClick={handleFilterRows} disabled={colBusy}>Apply Filter</button>
      </div>

      <div className="forecast-controls">
        <select value={replaceCol} onChange={(e) => setReplaceCol(e.target.value)}>
          <option value="">Find &amp; Replace column</option>
          {allColNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Find value..."
          value={findVal}
          onChange={(e) => setFindVal(e.target.value)}
        />
        <input
          type="text"
          placeholder="Replace with (empty = NaN)..."
          value={replaceVal}
          onChange={(e) => setReplaceVal(e.target.value)}
        />
        <button onClick={handleFindReplace} disabled={colBusy}>Replace All</button>
      </div>

      <div className="forecast-controls">
        <select value={permSortCol} onChange={(e) => setPermSortCol(e.target.value)}>
          <option value="">Sort by column</option>
          {allColNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <select value={permSortDir} onChange={(e) => setPermSortDir(e.target.value)}>
          <option value="asc">Ascending (A→Z / 0→9)</option>
          <option value="desc">Descending (Z→A / 9→0)</option>
        </select>
        <button onClick={handlePermanentSort} disabled={colBusy}>Sort Dataset</button>
        <input
          type="number"
          min="1"
          value={sampleSize}
          onChange={(e) => setSampleSize(e.target.value)}
          className="periods-input"
        />
        <button onClick={handleSampleRows} disabled={colBusy}>Sample N Rows</button>
      </div>

      {colError && <p className="error-text">{colError}</p>}

      {typeof allColNames !== "undefined" && Array.isArray(allColNames) && allColNames.length > 0 && (
        <>
          <h3>Column Summary</h3>

          <div className="forecast-controls" style={{ marginBottom: "10px" }}>
            <select
              value={typeof inspectedCol !== "undefined" ? inspectedCol || "" : ""}
              disabled={typeof inspectLoading !== "undefined" && inspectLoading}
              onChange={(e) => {
                if (typeof handleInspectColumn === "function") {
                  handleInspectColumn(e.target.value);
                }
              }}
            >
              <option value="">Choose a column</option>
              {allColNames.map((name, i) => (
                <option key={`${name}-${i}`} value={name}>
                  {name}
                </option>
              ))}
            </select>

            {typeof inspectLoading !== "undefined" && inspectLoading && (
              <span className="subtitle" style={{ fontSize: "12px" }}>Loading summary...</span>
            )}
          </div>

          {typeof colSummary !== "undefined" && colSummary && typeof colSummary === "object" && (
            <div className="history-panel" style={{ marginBottom: "12px" }}>
              <strong>
                {String(colSummary.column || inspectedCol || "Column summary")}
              </strong>

              <p className="subtitle" style={{ fontSize: "12px", margin: "4px 0 8px" }}>
                {String(colSummary.kind || "") === "numeric"
                  ? "Numeric summary: count/mean/std/min/quartiles/median/max. Missing values are excluded."
                  : String(colSummary.kind || "") === "categorical"
                  ? "Categorical summary: most frequent non-missing values and their share of all rows."
                  : "Column summary."}
              </p>

              <ul className="audit-log">
                {Object.entries(colSummary)
                  .filter(([key, value]) => {
                    if (key === "column" || key === "kind" || key === "top_values") return false;
                    if (value === null || value === undefined || value === "") return false;
                    if (Array.isArray(value) && value.length === 0) return false;
                    return true;
                  })
                  .slice(0, 12)
                  .map(([key, value]) => (
                    <li key={key}>
                      <span className="audit-detail">
                        <strong>{String(key).replace(/_/g, " ")}</strong>:{" "}
                        {Array.isArray(value)
                          ? value
                              .slice(0, 10)
                              .map((item) =>
                                item && typeof item === "object"
                                  ? Object.entries(item)
                                      .map(([k, v]) => {
                                        const safeValue =
                                          v === null || v === undefined ? "-" : String(v);
                                        return `${String(k).replace(/_/g, " ")}=${safeValue}`;
                                      })
                                      .join(", ")
                                  : String(item)
                              )
                              .join(" | ")
                          : typeof value === "object"
                          ? JSON.stringify(value)
                          : String(value)}
                      </span>
                    </li>
                  ))}
              </ul>

              {Array.isArray(colSummary.top_values) && colSummary.top_values.length > 0 && (
                <>
                  <p className="subtitle" style={{ fontSize: "12px", margin: "8px 0 4px" }}>
                    Top values
                  </p>
                  <ul className="audit-log">
                    {colSummary.top_values.slice(0, 10).map((tv, i) => (
                      <li key={i}>
                        <span className="audit-detail">
                          {tv && typeof tv === "object"
                            ? `${String(tv.value ?? "-")} (${String(tv.count ?? "-")}${
                                tv.percent !== undefined && tv.percent !== null
                                  ? `, ${String(tv.percent)}%`
                                  : ""
                              })`
                            : String(tv)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </>
      )}

      <h3>Columns</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Missing</th>
            <th>Unique</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {safeProfileColumns.map((col, colIndex) => {
            const colName = String(col.name ?? `column_${colIndex}`);

            return (
              <tr key={`${colName}-${colIndex}`}>
                <td>{colName}</td>
                <td>{String(col.inferred_type ?? "-")}</td>
                <td>
                  {col.missing_values ?? 0} ({col.missing_percent ?? 0}%)
                </td>
                <td>{col.unique_values ?? 0}</td>
                <td>
                  <button
                    className="logout-button"
                    style={{ padding: "4px 10px", fontSize: "12px" }}
                    onClick={() => handleInspectColumn(colName)}
                  >
                    {inspectedCol === colName ? "Hide" : "Inspect"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>



      {Array.isArray(allColNames) && allColNames.length > 0 && (
        <>
          <h3>Pivot / Group-By Summary</h3>

          <div className="forecast-controls" style={{ marginBottom: "10px" }}>
            <select
              value={pivotGroupBy}
              disabled={pivotLoading}
              onChange={(e) => {
                setPivotGroupBy(e.target.value);
                setPivotData(null);
              }}
            >
              <option value="">Group by</option>
              {allColNames.map((name, i) => (
                <option key={`${name}-${i}`} value={name}>
                  {name}
                </option>
              ))}
            </select>

            <select
              value={pivotValue}
              disabled={pivotLoading}
              onChange={(e) => {
                setPivotValue(e.target.value);
                setPivotData(null);
              }}
            >
              <option value="">Value column</option>
              {(Array.isArray(numericCols) && numericCols.length > 0 ? numericCols : allColNames).map(
                (name, i) => (
                  <option key={`${name}-${i}`} value={name}>
                    {name}
                  </option>
                )
              )}
            </select>

            <select
              value={pivotAgg}
              disabled={pivotLoading}
              onChange={(e) => {
                setPivotAgg(e.target.value);
                setPivotData(null);
              }}
            >
              <option value="sum">Sum</option>
              <option value="mean">Average</option>
              <option value="median">Median</option>
              <option value="count">Count</option>
              <option value="min">Min</option>
              <option value="max">Max</option>
            </select>

            <select
              value={pivotSplit}
              disabled={pivotLoading}
              onChange={(e) => {
                setPivotSplit(e.target.value);
                setPivotData(null);
              }}
            >
              <option value="">No split</option>
              {allColNames.map((name, i) => (
                <option key={`${name}-${i}`} value={name}>
                  {name}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={runPivot}
              disabled={pivotLoading || !pivotGroupBy || !pivotValue}
            >
              {pivotLoading ? "Building..." : "Build Pivot"}
            </button>
          </div>

          {pivotError && (
            <p className="error-text" style={{ marginBottom: "8px" }}>
              {String(pivotError)}
            </p>
          )}

          {pivotData && !pivotError && (
            (() => {
              const safePivotSource =
                Array.isArray(pivotData)
                  ? pivotData
                  : pivotData && typeof pivotData === "object"
                  ? Array.isArray(pivotData.rows)
                    ? pivotData.rows
                    : Array.isArray(pivotData.data)
                    ? pivotData.data
                    : []
                  : [];

              const rowsSource = safePivotSource.filter(
                (row) => row && typeof row === "object"
              );

              const rawColumns =
                pivotData &&
                typeof pivotData === "object" &&
                Array.isArray(pivotData.columns) &&
                pivotData.columns.length > 0
                  ? pivotData.columns
                  : Object.keys(rowsSource[0] || {});

              const columns = Array.from(
                new Set(rawColumns.map((c) => String(c ?? "")).filter(Boolean))
              );

              const rows = rowsSource.slice(0, 100);

              const displayPivotValue = (value) => {
                if (value === null || value === undefined) return "-";

                if (typeof value === "object") {
                  try {
                    return JSON.stringify(value);
                  } catch {
                    return "[unreadable]";
                  }
                }

                return String(value);
              };

              if (!rows.length || !columns.length) {
                return (
                  <p className="subtitle" style={{ marginBottom: "8px" }}>
                    No data to show for this pivot.
                  </p>
                );
              }

              return (
                <div className="table-scroll" style={{ marginBottom: "16px" }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        {columns.map((c, ci) => (
                          <th key={`${c}-${ci}`}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, i) => (
                        <tr key={i}>
                          {columns.map((c, ci) => {
                            const value =
                              row && typeof row === "object" ? row[c] : undefined;

                            return (
                              <td key={`${c}-${ci}`}>
                                {displayPivotValue(value)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {safePivotSource.length > rows.length && (
                    <p className="subtitle" style={{ fontSize: "12px", marginTop: "6px" }}>
                      Showing first 100 pivot rows.
                    </p>
                  )}
                </div>
              );
            })()
          )}
        </>
      )}

      <h3>Rows</h3>
      {typeof allColNames !== "undefined" &&
        typeof sortBy !== "undefined" &&
        typeof sortDir !== "undefined" &&
        typeof setSortBy === "function" &&
        typeof setSortDir === "function" &&
        typeof rowsLoading !== "undefined" &&
        typeof setPage === "function" && (
          <div className="forecast-controls" style={{ marginBottom: "10px" }}>
            <select
              value={sortBy || ""}
              disabled={rowsLoading}
              onChange={(e) => {
                const next = e.target.value || null;
                setSortBy(next);
                setPage(0);
              }}
            >
              <option value="">Sort: none (original order)</option>
              {allColNames.map((name, i) => (
                <option key={`${name}-${i}`} value={name}>
                  {name}
                </option>
              ))}
            </select>

            <button
              type="button"
              className="logout-button"
              style={{ fontSize: "12px", padding: "4px 10px", marginLeft: 0 }}
              disabled={rowsLoading || !sortBy}
              onClick={() => {
                setSortDir((d) => (d === "asc" ? "desc" : "asc"));
                setPage(0);
              }}
            >
              {sortDir === "asc" ? "Ascending ▲" : "Descending ▼"}
            </button>
          </div>
        )}
      <p className="subtitle" style={{ marginBottom: "10px" }}>
        Tip: Double-click any cell to edit its value directly (press Enter to save, Esc to cancel — supports 5-step Undo).
      </p>
      <div className="forecast-controls">
        <input
          type="text"
          placeholder="Search rows..."
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
        />
        {search !== "" && (
          <button
            type="button"
            className="logout-button"
            style={{ fontSize: "12px", padding: "4px 10px", marginLeft: 0 }}
            onClick={() => handleSearch("")}
          >
            Clear
          </button>
        )}
        <select
          value={pageSize}
          disabled={rowsLoading}
          onChange={(e) => {
            const next = Number(e.target.value);
            setPage(0);
            setPageSize(Number.isFinite(next) && next > 0 ? next : 25);
          }}
          aria-label="Rows per page"
        >
          <option value={10}>10 rows</option>
          <option value={20}>20 rows</option>
          <option value={25}>25 rows</option>
          <option value={50}>50 rows</option>
          <option value={100}>100 rows</option>
        </select>
      </div>
      {rowsError && (
        <p className="error-text" style={{ marginBottom: "8px" }}>
          {String(rowsError)} Showing the initial preview only.
        </p>
      )}

      {!rowsError && pageData && Number(total) === 0 && (
        <p className="subtitle" style={{ marginBottom: "8px" }}>
          No rows match the current search.
        </p>
      )}

      {rowsLoading && (
        <p className="subtitle" style={{ color: "var(--teal)", fontSize: "12px", margin: "0 0 8px" }}>
          Loading rows...
        </p>
      )}
      <QualitySummaryCard
        datasetId={dataset_id}
        currentDataVersion={typeof dataVersion !== "undefined" ? dataVersion : null}
      />

      <DatasetIntelligencePanel
        datasetId={dataset_id}
        currentDataVersion={typeof dataVersion !== "undefined" ? dataVersion : null}
      />

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {safeProfileColumns.map((col, colIndex) => {
                const colName = String(col.name ?? `column_${colIndex}`);

                return (
                  <th
                    key={`${colName}-${colIndex}`}
                    onClick={() => toggleSort(colName)}
                    style={{ cursor: "pointer" }}
                  >
                    {colName}{sortBy === colName ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => {
              const safeRow = row && typeof row === "object" ? row : {};
              const rawRowId = safeRow._row_id;
              const rowId =
                Number.isInteger(Number(rawRowId)) && Number(rawRowId) >= 0
                  ? Number(rawRowId)
                  : safePage * safePageSize + idx;

              return (
                <tr key={`${rowId}-${idx}`}>
                  {safeProfileColumns.map((col, colIndex) => {
                    const colName = String(col.name ?? `column_${colIndex}`);
                    const rawVal = safeRow[colName];
                    const strVal = rawVal === null || rawVal === undefined ? "" : String(rawVal);
                    const isEditing =
                      editingCell && editingCell.rowId === rowId && editingCell.col === colName;

                    return (
                      <td
                        key={`${colName}-${colIndex}`}
                        onDoubleClick={() => {
                          if (colBusy) return;
                          editSettledRef.current = false;
                          setEditingCell({
                            rowId,
                            col: colName,
                            value: strVal,
                            oldValue: strVal,
                          });
                        }}
                        style={{ cursor: "pointer" }}
                        title="Double-click to edit"
                      >
                        {isEditing ? (
                          <input
                            type="text"
                            autoFocus
                            value={editingCell.value}
                            onChange={(e) =>
                              setEditingCell((prev) => ({ ...prev, value: e.target.value }))
                            }
                            onBlur={commitCellEdit}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitCellEdit();
                              if (e.key === "Escape") {
                                editSettledRef.current = true;
                                setEditingCell(null);
                              }
                            }}
                            style={{
                              width: "100%",
                              minWidth: "80px",
                              padding: "4px 6px",
                              border: "1px solid var(--teal)",
                              borderRadius: "4px",
                            }}
                          />
                        ) : (
                          String(rawVal ?? "-")
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="forecast-controls">
        <button onClick={() => setPage(Math.max(0, safePage - 1))} disabled={rowsLoading || safePage <= 0}>Prev</button>
        <span className="subtitle">
          {rowsLoading ? "Loading rows..." : `Showing ${from}–${to} of ${total} rows`}
        </span>
        <button onClick={() => setPage(Math.min(lastPage, safePage + 1))} disabled={rowsLoading || safePage >= lastPage}>Next</button>
      </div>
    </div>
  );
}

export default DataProfile;