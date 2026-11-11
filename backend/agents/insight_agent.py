# backend/agents/insight_agent.py
import pandas as pd
from typing import Dict, Any

from backend.agents.sql_agent import SQLAgent, _redact_pii_for_prompt  # reuse the same LLM fallback chain and PII helper
from backend.data.profiler import DataProfiler
from backend.visualization.charts import ChartEngine


def _redact_breakdown(breakdown):
    """Redacts only group value strings in a root cause breakdown; statistics and identifiers are kept."""
    if not isinstance(breakdown, list):
        return breakdown

    redacted = []
    for dim in breakdown:
        if not isinstance(dim, dict):
            redacted.append(dim)
            continue

        item = dict(dim)
        for key in ("highest_group", "lowest_group"):
            group = item.get(key)
            if isinstance(group, dict) and group.get("value") is not None:
                item[key] = {
                    **group,
                    "value": _redact_pii_for_prompt(str(group["value"])),
                }

        redacted.append(item)

    return redacted


class InsightAgent:
    """
    Generates natural language insights from a dataset's statistics,
    instead of just showing raw numbers.
    """

    @staticmethod
    def _build_data_summary(df: pd.DataFrame) -> str:
        """
        Builds a compact text summary of the dataset's key statistics
        to feed into the LLM prompt.
        """
        profile = DataProfiler.profile(df)
        kpis = ChartEngine.kpi_cards(df)

        lines = [
            f"Dataset has {profile['num_rows']} rows and {profile['num_columns']} columns.",
            f"Numeric columns: {', '.join(profile['numeric_columns']) or 'none'}.",
            f"Categorical columns: {', '.join(profile['categorical_columns']) or 'none'}.",
            f"Duplicate rows: {profile['duplicate_rows']}.",
        ]

        if kpis:
            lines.append("Key numeric statistics:")
            for kpi in kpis:
                lines.append(
                    f"- {kpi['column']}: total={kpi['total']}, average={kpi['average']}, "
                    f"min={kpi['min']}, max={kpi['max']}"
                )

        # Add top categories for each categorical column (helps the LLM spot patterns)
        for col in profile["categorical_columns"]:
            top_values = df[col].value_counts().head(5)
            if not top_values.empty:
                # Only the individual value strings are redacted; the column name and counts are left as they are.
                breakdown = ", ".join(
                    f"{_redact_pii_for_prompt(str(idx))} ({count})" for idx, count in top_values.items()
                )
                lines.append(f"Top values in '{col}': {breakdown}")

        return "\n".join(lines)

    @staticmethod
    def build_prompt(data_summary: str, focus_question: str = None) -> str:
        focus_line = f"\nThe user specifically wants insight about: {_redact_pii_for_prompt(focus_question)}\n" if focus_question else ""

        return f"""You are a data analyst. Based on the following dataset statistics, write a short, clear insight summary (3-5 sentences) explaining what the data shows — not just repeating the numbers, but explaining the likely story or pattern behind them.

Dataset statistics:
{data_summary}
{focus_line}
Rules:
- Write in plain, simple language, like explaining to a business person, not a data scientist.
- Point out the most notable pattern, trend, or standout value.
- If something looks like a data quality issue (e.g. duplicates, missing values, extreme outliers), mention it briefly.
- Do NOT invent numbers that aren't in the statistics provided.
- Return ONLY the insight text. No headers, no markdown, no bullet points unless natural.

Insight:"""

    @staticmethod
    def generate_insight(df: pd.DataFrame, focus_question: str = None) -> Dict[str, Any]:
        data_summary = InsightAgent._build_data_summary(df)
        prompt = InsightAgent.build_prompt(data_summary, focus_question)

        # Reuse the same multi-provider fallback chain used by SQLAgent
        providers = SQLAgent.get_provider_chain()

        for provider_fn, name in providers:
            raw_output = provider_fn(prompt)
            if raw_output:
                print(f"[InsightAgent] Insight generated using '{name}' provider.")
                return {
                    "insight": raw_output.strip(),
                    "data_summary": data_summary,
                }

        raise RuntimeError("All LLM providers failed. Check if Ollama is running.")

    # -------------------------------
    # New anomaly explanation methods
    # -------------------------------
    @staticmethod
    def build_anomaly_prompt(anomalies: Dict[str, Any]) -> str:
        outliers = anomalies.get("numeric_outliers", [])
        compact = dict(anomalies)
        # Category group values are free text taken from the data, so they are redacted individually.
        if isinstance(compact.get("category_anomalies"), list):
            redacted_categories = []
            for item in compact["category_anomalies"]:
                if isinstance(item, dict) and item.get("group_value") is not None:
                    item = {
                        **item,
                        "group_value": _redact_pii_for_prompt(str(item["group_value"])),
                    }
                redacted_categories.append(item)
            compact["category_anomalies"] = redacted_categories
        if len(outliers) > 20:
            compact["numeric_outliers"] = outliers[:20]
            compact["numeric_outliers_total"] = len(outliers)
        return f"""You are a data analyst. Below is a list of detected anomalies (unusual patterns) found in a dataset.
Explain them in plain, simple language (3-5 sentences), as if telling a business person what looks unusual and why it might matter.

Detected anomalies (JSON):
{compact}

Rules:
- Mention the most notable anomalies first.
- Do NOT invent numbers that aren't in the data provided.
- If there are no anomalies, say clearly that the data looks normal/consistent.
- Return ONLY the explanation text. No headers, no markdown.

Explanation:"""

    @staticmethod
    def explain_anomalies(anomalies: Dict[str, Any]) -> Dict[str, Any]:
        prompt = InsightAgent.build_anomaly_prompt(anomalies)

        providers = SQLAgent.get_provider_chain()

        for provider_fn, name in providers:
            raw_output = provider_fn(prompt)
            if raw_output:
                print(f"[InsightAgent] Anomaly explanation generated using '{name}' provider.")
                return {"explanation": raw_output.strip()}

        raise RuntimeError("All LLM providers failed. Check if Ollama is running.")

    # -------------------------------
    # New root cause explanation methods
    # -------------------------------
    @staticmethod
    def build_root_cause_prompt(metric_column: str, breakdown: list, question: str = None) -> str:
        breakdown = _redact_breakdown(breakdown)
        question = _redact_pii_for_prompt(question) if question else question
        focus_line = f"\nThe user specifically asked: {question}\n" if question else ""

        return f"""You are a data analyst doing root cause analysis. Below is a breakdown showing how much each dimension (category) explains the variation in the metric '{metric_column}', along with the highest and lowest performing groups within each dimension.

Breakdown (JSON, ordered from most to least impactful dimension):
{breakdown}
{focus_line}
Rules:
- Explain in plain, simple language (3-5 sentences) which dimension seems most responsible for the variation, and which specific group (e.g. a specific region, product, etc.) stands out.
- Suggest this as a "probable cause", not a certainty, since correlation isn't necessarily causation.
- Do NOT invent numbers that aren't in the data provided.
- Return ONLY the explanation text. No headers, no markdown.

Explanation:"""

    @staticmethod
    def explain_root_cause(metric_column: str, breakdown: list, question: str = None) -> Dict[str, Any]:
        prompt = InsightAgent.build_root_cause_prompt(metric_column, breakdown, question)

        providers = SQLAgent.get_provider_chain()

        for provider_fn, name in providers:
            raw_output = provider_fn(prompt)
            if raw_output:
                print(f"[InsightAgent] Root cause explanation generated using '{name}' provider.")
                return {"explanation": raw_output.strip()}

        raise RuntimeError("All LLM providers failed. Check if Ollama is running.")
