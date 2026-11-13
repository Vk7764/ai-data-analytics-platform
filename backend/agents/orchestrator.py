# backend/agents/orchestrator.py
import json
import logging
import re
import sqlite3
import pandas as pd
from typing import Dict, Any, List

from backend.agents.sql_agent import SQLAgent, _redact_pii_for_prompt
from backend.agents.python_agent import PythonAgent
from backend.sandbox.docker_runner import is_sandbox_available
from backend.agents.insight_agent import InsightAgent
from backend.data.profiler import DataProfiler
from backend.visualization.charts import ChartEngine
from backend.database.db_connector import get_connection_with_data, run_query, validate_select_only
from backend.database.dataset_store import DB_PATH, configure_sqlite_connection

logger = logging.getLogger("app")


def _get_connection() -> sqlite3.Connection:
    conn = configure_sqlite_connection(sqlite3.connect(DB_PATH, timeout=30))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for column_definition in ("action TEXT", "result_json TEXT"):
        try:
            conn.execute(f"ALTER TABLE chat_history ADD COLUMN {column_definition}")
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


HISTORY_MAX_ROWS = 50
HISTORY_MAX_MESSAGES = 100  # newest chat messages kept per dataset
HISTORY_MAX_CHART_POINTS = 200
HISTORY_MAX_TEXT_CHARS = 5000
HISTORY_MAX_RESULT_CHARS = 100_000


def _result_to_bounded_json(result: Any) -> Any:
    """
    Serializes a chat result for persistence with bounded size. Large row sets, chart data and Python
    values are cut to a preview with explicit truncation markers. The live API response is not affected.
    """
    if result is None:
        return None
    if not isinstance(result, dict):
        text = json.dumps(result, default=str)
        if len(text) > HISTORY_MAX_RESULT_CHARS:
            return json.dumps({"truncated": True, "note": "Result too large; preview not stored."})
        return text

    bounded = dict(result)

    for text_key in ("generated_sql", "generated_code"):
        value = bounded.get(text_key)
        if isinstance(value, str) and len(value) > HISTORY_MAX_TEXT_CHARS:
            bounded[text_key] = value[:HISTORY_MAX_TEXT_CHARS]

    for list_key, limit in (("rows", HISTORY_MAX_ROWS), ("data", HISTORY_MAX_CHART_POINTS)):
        items = bounded.get(list_key)
        if isinstance(items, list) and len(items) > limit:
            bounded[list_key] = items[:limit]
            bounded[f"{list_key}_truncated"] = True
            bounded[f"{list_key}_total"] = len(items)

    value = bounded.get("value")
    if isinstance(value, list) and len(value) > HISTORY_MAX_ROWS:
        bounded["value"] = value[:HISTORY_MAX_ROWS]
        bounded["value_truncated"] = True
        bounded["value_total"] = len(value)
    elif isinstance(value, dict) and len(value) > HISTORY_MAX_ROWS:
        bounded["value"] = dict(list(value.items())[:HISTORY_MAX_ROWS])
        bounded["value_truncated"] = True
        bounded["value_total"] = len(value)
    elif isinstance(value, str) and len(value) > HISTORY_MAX_TEXT_CHARS:
        bounded["value"] = value[:HISTORY_MAX_TEXT_CHARS]
        bounded["value_truncated"] = True

    text = json.dumps(bounded, default=str)
    if len(text) > HISTORY_MAX_RESULT_CHARS:
        # Still too large (for example very wide rows): keep only the essentials.
        minimal = {"truncated": True, "note": "Result too large; preview not stored."}
        for keep_key in ("generated_sql", "generated_code", "error", "chart_type", "x_column", "y_column"):
            if keep_key in bounded:
                minimal[keep_key] = bounded[keep_key]
        text = json.dumps(minimal, default=str)
    return text


class Orchestrator:
    """
    Enables context-aware "Chat With Your Data" conversations.
    Conversation history is persisted to SQLite (per dataset), so it
    survives server restarts, and routes each new message to the right
    capability (SQL, Python analysis, chart, or insight), resolving
    follow-up references (e.g. "compare that to last year") using history.
    """

    @staticmethod
    def reset_conversation(dataset_id: str) -> None:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM chat_history WHERE dataset_id = ?", (dataset_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _get_history(dataset_id: str) -> List[Dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT role, content, action, result_json FROM chat_history WHERE dataset_id = ? ORDER BY id ASC",
                (dataset_id,),
            ).fetchall()
            history = []
            for r in rows:
                result = None
                if r[3]:
                    try:
                        result = json.loads(r[3])
                    except Exception:
                        result = None
                history.append({"role": r[0], "content": r[1], "action": r[2], "result": result})
            return history
        finally:
            conn.close()

    @staticmethod
    def _append_history(dataset_id: str, role: str, content: str, action: str = None, result: Any = None) -> None:
        conn = _get_connection()
        try:
            result_json = _result_to_bounded_json(result)
            conn.execute(
                "INSERT INTO chat_history (dataset_id, role, content, action, result_json) VALUES (?, ?, ?, ?, ?)",
                (dataset_id, role, content, action, result_json),
            )
            conn.execute(
                "DELETE FROM chat_history WHERE dataset_id = ? AND id NOT IN "
                "(SELECT id FROM chat_history WHERE dataset_id = ? ORDER BY id DESC LIMIT ?)",
                (dataset_id, dataset_id, HISTORY_MAX_MESSAGES),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_full_history(dataset_id: str) -> List[Dict[str, str]]:
        """Returns the full chat history for a dataset, for the frontend to render on load."""
        return Orchestrator._get_history(dataset_id)

    @staticmethod
    def _format_history(history: List[Dict[str, str]], max_turns: int = 6) -> str:
        if not history:
            return "(no previous conversation)"
        recent = history[-max_turns:]
        return "\n".join(
            f"{turn['role']}: {_redact_pii_for_prompt(str(turn['content'])) if turn['role'] == 'user' else turn['content']}"
            for turn in recent
        )

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"```$", "", text.strip())
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object found in LLM output")
        return json.loads(text[start:end + 1])

    @staticmethod
    def _route_message(message: str, schema_info: str, history_text: str) -> Dict[str, str]:
        prompt = f"""You are an orchestrator for a data analytics chat assistant.
Given the conversation history and the new user message, do two things:

1. Rewrite the user's new message into a standalone, fully-specified question, resolving
   any references to earlier context (e.g. "compare that to last year", "make a chart of it").
   If there is nothing to resolve, just repeat the message as-is.
2. Classify which capability should handle this standalone question. Choose exactly ONE of:
   - "sql": for direct data lookups, filtering, sorting, counting, or aggregations (sums, averages, top-N, etc.)
   - "python": for more complex analysis (correlations, custom calculations, grouping with multiple steps)
   - "chart": if the user wants a visualization/chart/graph
   - "insight": if the user wants a general explanation, summary, or narrative about the data (not one specific number)

Conversation history:
{history_text}

Dataset schema:
{schema_info}

New user message: {_redact_pii_for_prompt(str(message))}

Return ONLY a JSON object in this exact format, nothing else:
{{"action": "sql", "resolved_question": "..."}}"""

        try:
            providers = SQLAgent.get_provider_chain()
        except RuntimeError:
            return {"action": "insight", "resolved_question": message}

        for provider_fn, name in providers:
            raw_output = provider_fn(prompt)
            if raw_output:
                try:
                    parsed = Orchestrator._extract_json(raw_output)
                    action = parsed.get("action", "insight")
                    resolved_question = parsed.get("resolved_question", message)
                    if action not in ("sql", "python", "chart", "insight"):
                        action = "insight"
                    logger.info(f"[Orchestrator] Routed using '{name}' -> action='{action}'")
                    return {"action": action, "resolved_question": resolved_question}
                except Exception as e:
                    logger.warning(f"[Orchestrator] Failed to parse routing JSON from {name}: {e}")
                    continue

        return {"action": "insight", "resolved_question": message}

    @staticmethod
    def handle_message(dataset_id: str, df: pd.DataFrame, message: str) -> Dict[str, Any]:
        history = Orchestrator._get_history(dataset_id)
        history_text = Orchestrator._format_history(history)

        profile = DataProfiler.profile(df)
        schema_info = "\n".join(
            f"- {col['name']} ({col['inferred_type']})" for col in profile["columns"]
        )

        routing = Orchestrator._route_message(message, schema_info, history_text)
        action = routing["action"]
        # Hosts without a code sandbox (free PaaS) answer through SQL instead of failing.
        if action == "python" and not is_sandbox_available():
            action = "sql"
        resolved_question = routing["resolved_question"]

        result: Any = None
        reply_text = ""

        try:
            if action == "sql":
                sql = SQLAgent.generate_sql(resolved_question, schema_info)
                validate_select_only(sql)
                conn = get_connection_with_data(df)
                try:
                    rows = run_query(conn, sql)
                finally:
                    conn.close()
                result = {"generated_sql": sql, "rows": rows}
                reply_text = f"Ran a SQL query and found {len(rows)} row(s)."

            elif action == "python":
                code = PythonAgent.generate_code(resolved_question, schema_info)
                py_result = PythonAgent.execute_code(code, df)
                result = {"generated_code": code, "value": py_result}
                reply_text = "Ran a Python analysis on the data."

            elif action == "chart":
                lowered_question = resolved_question.lower()
                mentioned = sorted(
                    [c for c in df.columns if str(c).lower() in lowered_question],
                    key=lambda c: len(str(c)),
                    reverse=True,
                )
                x_col = None
                y_col = None
                for col in mentioned:
                    is_numeric = pd.api.types.is_numeric_dtype(df[col])
                    if not is_numeric and x_col is None:
                        x_col = col
                    elif is_numeric and y_col is None:
                        y_col = col
                    elif is_numeric and x_col is None:
                        x_col = col
                chart = ChartEngine.suggest_chart(df, x_column=x_col, y_column=y_col)
                result = chart
                reply_text = f"Generated a {chart['chart_type']} chart."

            else:
                insight = InsightAgent.generate_insight(df, focus_question=resolved_question)
                result = insight
                reply_text = insight["insight"]

        except Exception as e:
            reply_text = f"Sorry, I couldn't complete that: {e}"
            result = {"error": str(e)}

        Orchestrator._append_history(dataset_id, "user", message)
        Orchestrator._append_history(dataset_id, "assistant", reply_text, action=action, result=result)

        return {
            "action": action,
            "resolved_question": resolved_question,
            "reply": reply_text,
            "result": result,
        }