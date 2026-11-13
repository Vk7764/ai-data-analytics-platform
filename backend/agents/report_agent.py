# backend/agents/report_agent.py
import logging
import pandas as pd
from typing import Dict, Any

from backend.agents.sql_agent import SQLAgent
from backend.agents.insight_agent import InsightAgent

logger = logging.getLogger("app")


class ReportAgent:
    """
    Produces short, practical business recommendations to include in reports.
    """

    @staticmethod
    def generate_recommendations(df: pd.DataFrame) -> Dict[str, Any]:
        summary = InsightAgent._build_data_summary(df)
        prompt = f"""You are a business analyst. Based on the dataset statistics below, give 3 short, practical business recommendations.
Write in plain, simple language for a business person. Use 3-4 sentences in total.
Do NOT invent numbers that are not in the statistics.
Return ONLY the recommendations as plain text. No headers, no markdown, no numbered lists.

Dataset statistics:
{summary}

Recommendations:"""

        for provider_fn, name in SQLAgent.get_provider_chain():
            raw_output = provider_fn(prompt)
            if raw_output:
                logger.info(f"[ReportAgent] Recommendations generated using '{name}' provider.")
                return {"recommendations": raw_output.strip(), "ai_generated": True}

        raise RuntimeError("All LLM providers failed. Check if Ollama is running.")