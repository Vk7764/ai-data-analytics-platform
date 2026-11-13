# backend/agents/cleaning_agent.py
import logging
import pandas as pd
from typing import Dict, Any

from backend.agents.sql_agent import SQLAgent
from backend.data.profiler import DataProfiler
from backend.data.cleaner import DataCleaner

logger = logging.getLogger("app")


class CleaningAgent:
    """
    Gives a plain-English cleaning recommendation based on the issues
    detected in a dataset, using the shared LLM fallback chain.
    """

    @staticmethod
    def _build_summary(df: pd.DataFrame) -> str:
        profile = DataProfiler.profile(df)
        issues = DataCleaner.detect_issues(df)

        lines = [
            f"Rows: {profile['num_rows']}, columns: {profile['num_columns']}.",
            f"Duplicate rows: {issues['duplicate_rows']['count']}.",
        ]
        for k in issues["key_duplicates"]:
            lines.append(f"Duplicate records by '{k['column']}': {k['extra_row_count']} extra row(s).")
        for m in issues["missing_values"]:
            lines.append(f"Missing in '{m['column']}': {m['missing_count']} ({m['missing_percent']}%).")
        for o in issues["outliers"]:
            lines.append(
                f"Outliers in '{o['column']}': {o['outlier_count']} "
                f"(expected range {o['lower_bound']} to {o['upper_bound']})."
            )
        for n in issues["negative_values"]:
            lines.append(f"Negative values in '{n['column']}': {n['negative_count']}.")
        for inc in issues["inconsistent_values"]:
            lines.append(f"Inconsistent text in '{inc['column']}': {inc['raw_unique_count']} raw variants.")
        for fz in issues["fuzzy_category_issues"]:
            lines.append(f"Possible duplicate categories in '{fz['column']}' (fuzzy match).")
        for d in issues["date_format_issues"]:
            lines.append(f"Mixed date formats in '{d['column']}'.")
        for nf in issues["numeric_format_issues"]:
            lines.append(f"Numbers stored as text in '{nf['column']}'.")
        for e in issues["email_format_issues"]:
            lines.append(f"Email issues in '{e['column']}': {e['invalid_count']} malformed.")

        for col in [o["column"] for o in issues["outliers"]]:
            series = df[col].dropna()
            if pd.api.types.is_numeric_dtype(series) and not series.empty:
                lines.append(
                    f"'{col}' mean {round(float(series.mean()), 2)}, "
                    f"median {round(float(series.median()), 2)}."
                )
        return "\n".join(lines)

    @staticmethod
    def advise(df: pd.DataFrame) -> Dict[str, Any]:
        summary = CleaningAgent._build_summary(df)
        prompt = f"""You are a data quality expert. Based on the data quality summary below, write a concise cleaning recommendation in 3-5 sentences of plain, simple English for a business person.
Highlight the highest-priority issues first. For any column with outliers, say whether the mean or the median is the safer value to fill missing entries with.
Do NOT invent numbers that are not in the summary.
Return ONLY the advice text. No headers, no markdown, no bullet points.

Data quality summary:
{summary}

Advice:"""

        for provider_fn, name in SQLAgent.get_provider_chain():
            raw_output = provider_fn(prompt)
            if raw_output:
                logger.info(f"[CleaningAgent] Advice generated using '{name}' provider.")
                return {"advice": raw_output.strip()}

        raise RuntimeError("All LLM providers failed. Check if Ollama is running.")