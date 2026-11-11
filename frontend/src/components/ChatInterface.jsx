// frontend/src/components/ChatInterface.jsx
import { useState, useRef, useEffect } from "react";
import api from "../api";
import { cleanMarkdown, errorDetail } from "../utils";
import { BarChart, Bar, LineChart, Line, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

function downloadRowsAsCsv(rows) {
  const safeRows = Array.isArray(rows)
    ? rows.filter((row) => row && typeof row === "object")
    : [];

  if (safeRows.length === 0) return;

  const headers = Array.from(
    new Set(
      safeRows
        .flatMap((row) => Object.keys(row))
        .filter((key) => typeof key === "string" && key)
    )
  );

  if (headers.length === 0) return;

  const escape = (val) => {
    if (val === null || val === undefined) return "";
    const str = String(val);
    return /[",\n\r]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };

  const lines = [
    headers.map(escape).join(","),
    ...safeRows.map((row) => headers.map((h) => escape(row?.[h])).join(",")),
  ];

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "query_result.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

function copyToClipboard(text, buttonEl) {
  // Capture the label node and original label synchronously: the event target is gone after dispatch.
  const labelNode = buttonEl && buttonEl.firstChild && buttonEl.firstChild.nodeType === 3 ? buttonEl.firstChild : null;
  const originalLabel = labelNode ? labelNode.nodeValue : "";

  const flashCopied = () => {
    if (!labelNode) return;
    labelNode.nodeValue = "Copied!";
    setTimeout(() => {
      labelNode.nodeValue = originalLabel;
    }, 1200);
  };

  const fallbackCopy = () => {
    let textarea = null;
    try {
      textarea = document.createElement("textarea");
      textarea.value = String(text ?? "");
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.top = "-9999px";
      textarea.style.left = "-9999px";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      if (document.execCommand("copy")) flashCopied();
    } catch (err) {
      // Copy denied or unsupported: fail silently.
    } finally {
      if (textarea && textarea.parentNode) textarea.parentNode.removeChild(textarea);
    }
  };

  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(String(text ?? "")).then(flashCopied).catch(fallbackCopy);
    } else {
      fallbackCopy();
    }
  } catch (err) {
    fallbackCopy();
  }
}

function ChatInterface({ datasetId, columns: rawColumns = [], onDatasetCreated }) {
  const columns = Array.isArray(rawColumns)
    ? rawColumns.filter((c) => c && typeof c === "object")
    : [];

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [chatMode, setChatMode] = useState("auto");
  const [savingSql, setSavingSql] = useState(false);
  const [error, setError] = useState(null);

  const quoteIdent = (name) => `"${String(name).replace(/"/g, '""')}"`;

  const namedColumns = columns.filter((c) => typeof c.name === "string" && c.name);

  const isIdLike = (name) =>
    /^(id|code|key|uuid|pk)$/i.test(String(name ?? "")) ||
    /([_\- ](id|code|key|uuid|pk)|[a-z0-9](ID|Id|Code|Key|UUID|PK))$/.test(String(name ?? ""));

  const numCol = namedColumns.find((c) => c.inferred_type === "numeric" && !isIdLike(c.name))?.name;
  const catCol = namedColumns.find((c) => c.inferred_type === "categorical")?.name;

  const applySqlPreset = (preset) => {
    const firstCol = columns[0]?.name ? quoteIdent(columns[0].name) : "*";
    const cat = catCol ? quoteIdent(catCol) : firstCol;
    const num = numCol ? quoteIdent(numCol) : firstCol;
    if (preset === "preview") {
      setInput("SELECT * FROM data LIMIT 25");
    } else if (preset === "group") {
      setInput(
        `SELECT ${cat}, COUNT(*) AS row_count, ROUND(AVG(CAST(${num} AS REAL)), 2) AS avg_val FROM data GROUP BY ${cat} ORDER BY row_count DESC`
      );
    } else if (preset === "top") {
      setInput(`SELECT * FROM data ORDER BY CAST(${num} AS REAL) DESC LIMIT 10`);
    }
  };

  const handleSaveSqlAsDataset = async (sqlText) => {
    const queryToSave = (sqlText || input || "").trim();
    if (!queryToSave) return;
    const customName = window.prompt("Enter a name for the new dataset:", "sql_filtered_view.csv");
    if (customName === null) return;
    setSavingSql(true);
    setError(null);
    try {
      const res = await api.post(`/dataset/${datasetId}/sql/save-as-dataset`, {
        sql: queryToSave,
        new_dataset_name: customName,
      });
      onDatasetCreated?.();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: `Saved query result as new dataset "${res.data.filename}" (${res.data.rows} rows, ${res.data.columns} columns). Open Datasets drawer at the top to switch to it.`,
          action: "insight",
        },
      ]);
    } catch (err) {
      setError(errorDetail(err, "Could not save SQL result as a dataset."));
    } finally {
      setSavingSql(false);
    }
  };
  const messagesEndRef = useRef(null);

  const starterQuestions = [
    "Summarize the key insights in this dataset",
    numCol && catCol ? `What is the average ${numCol} by ${catCol}?` : null,
    numCol ? `Show the top 5 rows by ${numCol}` : null,
    numCol && catCol ? `Plot ${numCol} by ${catCol}` : null,
  ].filter(Boolean).slice(0, 4);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const response = await api.get(`/dataset/${datasetId}/chat/history`);
        const loaded = response.data.history.map((turn) => ({
          role: turn.role,
          text: turn.content,
          action: turn.action,
          result: turn.result,
        }));
        setMessages(loaded);
      } catch (err) {
        // no history yet, or failed to load — start with empty chat
      } finally {
        setHistoryLoaded(true);
      }
    };
    loadHistory();
  }, [datasetId]);

  const formatResult = (action, result) => {
    if (action === "sql") {
      if (!result || typeof result !== "object") return null;

      const rows = Array.isArray(result.rows)
        ? result.rows.filter((row) => row && typeof row === "object")
        : [];

      const generatedSql = typeof result.generated_sql === "string" ? result.generated_sql : null;

      const sqlBlock = generatedSql ? (
        <details className="code-transparency">
          <summary>View generated SQL</summary>
          <pre className="chat-result-pre">{generatedSql}</pre>
          <button
            type="button"
            className="logout-button"
            style={{ fontSize: "12px", padding: "4px 10px" }}
            onClick={(e) => copyToClipboard(generatedSql, e.currentTarget)}
          >
            Copy SQL
          </button>
        </details>
      ) : null;

      if (rows.length === 0) {
        return <>No rows returned.{sqlBlock}</>;
      }

      const headers = Object.keys(rows[0] || {}).filter((key) => typeof key === "string" && key);

      return (
        <>
          <table className="chat-result-table">
            <thead>
              <tr>
                {headers.map((key) => (
                  <th key={key}>{key}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((row, idx) => (
                <tr key={idx}>
                  {headers.map((key) => (
                    <td key={key}>{String(row?.[key] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 200 && (
            <p className="subtitle" style={{ fontSize: "12px", margin: "6px 0 0" }}>
              Showing the first 200 of {rows.length} rows. Use Download CSV for all returned rows.
            </p>
          )}
          <div className="button-group" style={{ marginTop: "8px" }}>
            <button
              type="button"
              className="demo-button"
              style={{ fontSize: "12px", padding: "6px 12px" }}
              onClick={() => downloadRowsAsCsv(rows)}
            >
              Download CSV
            </button>
            {generatedSql && (
              <button
                type="button"
                className="logout-button"
                style={{ fontSize: "12px", padding: "6px 12px" }}
                disabled={savingSql}
                onClick={() => handleSaveSqlAsDataset(generatedSql)}
              >
                Save as New Dataset
              </button>
            )}
          </div>
          {sqlBlock}
        </>
      );
    }

    if (action === "python" && result.value !== undefined) {
      const codeBlock = result.generated_code ? (
        <details className="code-transparency">
          <summary>View generated Python code</summary>
          <pre className="chat-result-pre">{result.generated_code}</pre>
          <button
            type="button"
            className="logout-button"
            style={{ fontSize: "12px", padding: "4px 10px" }}
            onClick={(e) => copyToClipboard(result.generated_code, e.currentTarget)}
          >
            Copy Code
          </button>
        </details>
      ) : null;

      const valueView = typeof result.value === "object"
        ? <pre className="chat-result-pre">{JSON.stringify(result.value, null, 2)}</pre>
        : <strong>{String(result.value)}</strong>;

      return <>{valueView}{codeBlock}</>;
    }

    if (action === "chart") {
      if (!result || typeof result !== "object") return null;

      const chartData = Array.isArray(result.data)
        ? result.data.filter((row) => row && typeof row === "object")
        : [];

      const chartType = typeof result.chart_type === "string" ? result.chart_type : "table";
      const xKey = typeof result.x_column === "string" ? result.x_column : null;
      const yKey = typeof result.y_column === "string" ? result.y_column : null;

      if (chartData.length > 0 && chartType !== "table" && xKey && yKey) {
        return (
          <ResponsiveContainer width="100%" height={240}>
            {chartType === "line" ? (
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={xKey} />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey={yKey} stroke="#4f46e5" />
              </LineChart>
            ) : chartType === "scatter" ? (
              <ScatterChart>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={xKey} />
                <YAxis dataKey={yKey} />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={chartData} fill="#4f46e5" />
              </ScatterChart>
            ) : (
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={xKey} />
                <YAxis />
                <Tooltip />
                <Bar dataKey={yKey} fill="#4f46e5" />
              </BarChart>
            )}
          </ResponsiveContainer>
        );
      }

      return <em>Chart generated ({chartType}) — view it in the Analysis Dashboard above.</em>;
    }

    return null;
  };

  const handleSend = async (overrideText) => {
    const text = typeof overrideText === "string" ? overrideText : input;
    const message = text.trim();
    if (!message || loading) return;

    setMessages((prev) => [...prev, { role: "user", text: message }]);
    setInput("");
    setLoading(true);

    try {
      if (chatMode === "raw_sql") {
        const res = await api.post(`/dataset/${datasetId}/sql`, { sql: message });
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `Executed custom SQL (0 AI quota used) — ${res.data.total_rows} total row(s) matched (showing up to 500).`,
            action: "sql",
            result: { generated_sql: res.data.generated_sql, rows: res.data.results },
          },
        ]);
      } else if (chatMode === "sql") {
        const res = await api.post(`/dataset/${datasetId}/query`, { question: message });
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `Ran a SQL query and found ${res.data.results.length} row(s).`,
            action: "sql",
            result: { generated_sql: res.data.generated_sql, rows: res.data.results },
          },
        ]);
      } else if (chatMode === "python") {
        const res = await api.post(`/dataset/${datasetId}/analyze`, { question: message });
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: "Ran a Python analysis on the data.",
            action: "python",
            result: { generated_code: res.data.generated_code, value: res.data.result },
          },
        ]);
      } else if (chatMode === "insight") {
        const res = await api.post(`/dataset/${datasetId}/insights`, { focus_question: message });
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: res.data.insight, action: "insight" },
        ]);
      } else {
        const response = await api.post(`/dataset/${datasetId}/chat`, { message });
        const { action, reply, result } = response.data;
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: reply, action, result },
        ]);
      }
        } catch (err) {
      const message = errorDetail(err, "Sorry, something went wrong. Please try again.");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: message },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleReset = async () => {
    setError(null);
    try {
      await api.post(`/dataset/${datasetId}/chat/reset`);
      setMessages([]);
    } catch (err) {
      setError(errorDetail(err, "Could not reset chat history."));
    }
  };

  return (
    <div className="chat-card">
      <div className="chat-header">
        <h2>Chat With Your Data</h2>
        <button className="reset-button" onClick={handleReset}>Reset</button>
      </div>

      <div className="chat-messages">
        {historyLoaded && messages.length === 0 && (
          <p className="subtitle">Ask a question about your data, e.g. "Which region had the highest sales?"</p>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} className={`chat-bubble ${msg.role}`}>
            <p>{msg.role === "assistant" ? cleanMarkdown(msg.text) : msg.text}</p>
            {msg.role === "assistant" &&
              msg.text &&
              msg.action !== "quota" &&
              !String(msg.text).trim().toLowerCase().startsWith("0 ai quota used") &&
              (msg.action === "insight" || msg.action === "sql" || msg.action === "python") && (
                <>
                  <p className="subtitle" style={{ fontSize: "11px", margin: "6px 0 0" }}>
                    <span
                      style={{
                        fontSize: "11px",
                        padding: "2px 6px",
                        borderRadius: "999px",
                        background: "rgba(14,124,102,0.12)",
                        color: "#0e7c66",
                        fontWeight: 600,
                        marginRight: "6px",
                      }}
                    >
                      AI-generated
                    </span>
                    Verify important results against the data.
                  </p>
                  <p className="subtitle" style={{ fontSize: "11px", margin: "4px 0 0" }}>
                    AI output may be cached until the dataset changes. Regenerate after cleaning or editing data.
                  </p>
                </>
              )}
            {msg.result && <div className="chat-result">{formatResult(msg.action, msg.result)}</div>}
          </div>
        ))}
        {loading && <div className="chat-bubble assistant"><p>Thinking...</p></div>}
        <div ref={messagesEndRef} />
      </div>

      {columns.length > 0 && (
        <div className="button-group" style={{ flexWrap: "wrap", marginBottom: "12px" }}>
          {starterQuestions.map((q) => (
            <button key={q} className="demo-button" disabled={loading} onClick={() => handleSend(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      {chatMode === "raw_sql" && (
        <div className="history-panel" style={{ marginBottom: "12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px", marginBottom: "8px" }}>
            <strong>SQL Workbench (Table name: <code>data</code> — 0 AI Quota)</strong>
            <div className="button-group">
              <button type="button" className="logout-button" style={{ fontSize: "12px", padding: "4px 10px" }} onClick={() => applySqlPreset("preview")}>
                SELECT * LIMIT 25
              </button>
              <button type="button" className="logout-button" style={{ fontSize: "12px", padding: "4px 10px" }} onClick={() => applySqlPreset("group")}>
                GROUP BY Template
              </button>
              <button type="button" className="logout-button" style={{ fontSize: "12px", padding: "4px 10px" }} onClick={() => applySqlPreset("top")}>
                Top 10 Template
              </button>
            </div>
          </div>
          {namedColumns.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              <span className="subtitle" style={{ fontSize: "12px", alignSelf: "center" }}>Click to insert column:</span>
              {namedColumns.map((c, idx) => {
                const colName = String(c.name ?? "");

                return (
                  <button
                    key={`${colName}-${idx}`}
                    type="button"
                    className="logout-button"
                    style={{ fontSize: "11px", padding: "2px 8px" }}
                    onClick={() =>
                      setInput((prev) => `${prev}${prev && !prev.endsWith(" ") ? " " : ""}${quoteIdent(colName)}`)
                    }
                  >
                    {colName} ({String(c.inferred_type ?? "-")})
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {error && <p className="error-text">{error}</p>}

      <div className="chat-input-row">
        <select
          value={chatMode}
          onChange={(e) => {
            const next = e.target.value;
            setChatMode(next);
            if (next === "raw_sql" && !input.trim()) {
              setInput("SELECT * FROM data LIMIT 25");
            }
          }}
          disabled={loading}
          style={{ padding: "0 12px", border: "1px solid var(--line)", borderRadius: "8px", background: "var(--paper-raised)" }}
        >
          <option value="auto">Auto Route</option>
          <option value="sql">AI SQL Query</option>
          <option value="raw_sql">Custom SQL (0 Quota)</option>
          <option value="python">Python Analysis</option>
          <option value="insight">AI Insight</option>
        </select>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your question..."
          disabled={loading}
        />
        <button onClick={() => handleSend()} disabled={loading}>Send</button>
      </div>
    </div>
  );
}

export default ChatInterface;