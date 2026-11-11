# backend/agents/sql_agent.py
import os
import re
import time
import threading
import requests
from typing import Optional, List, Tuple

# ---------- Provider URLs & Free Model Catalogs ----------

OPENROUTER_API_URL = "https://" + "openrouter.ai/api/v1/chat/completions"
OPENROUTER_FREE_MODELS = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "deepseek/deepseek-r1:free",
    "google/gemma-3-12b-it:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-coder-32b-instruct:free",
]

GROQ_API_URL = "https://" + "api.groq.com/openai/v1/chat/completions"
GROQ_FREE_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen-qwq-32b",
    "deepseek-r1-distill-llama-70b",
    "gemma2-9b-it",
    "llama3-70b-8192",
    "llama3-8b-8192",
]

GEMINI_API_URL = "https://" + "generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_FREE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

MISTRAL_API_URL = "https://" + "api.mistral.ai/v1/chat/completions"
MISTRAL_FREE_MODELS = [
    "open-mistral-nemo",
    "mistral-small-latest",
    "ministral-8b-latest",
    "ministral-8b-2512",
    "ministral-3b-latest",
    "codestral-latest",
]

HF_API_URL = "https://" + "router.huggingface.co/v1/chat/completions"
HF_FREE_MODELS = [
    "Qwen/Qwen2.5-72B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "microsoft/Phi-3.5-mini-instruct",
]

ANTHROPIC_API_URL = "https://" + "api.anthropic.com/v1/messages"
ANTHROPIC_MODELS = [
    "claude-3-5-haiku-latest",
    "claude-3-haiku-20240307",
    "claude-sonnet-4-6",
]

OLLAMA_BASE_URL = "http://" + "127.0.0.1:11434"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"
OLLAMA_FALLBACK_MODELS = [
    "llama3.2:latest",
    "llama3.1:latest",
    "llama3:latest",
    "mistral:latest",
    "qwen2.5:latest",
    "gemma2:latest",
    "phi3:latest",
]

# Circuit-breaker caches so dead keys (401), nonexistent models (404),
# or offline hosts don't stall parallel requests.
_COOLDOWN_UNTIL: dict[str, float] = {}

# Total time one provider-chain call may spend across ALL providers and models. Keep this well below the
# reverse-proxy timeout (nginx: 180s) so a request fails cleanly (and its quota is refunded) instead of
# ending in a gateway error while the backend keeps cascading.
try:
    LLM_TOTAL_BUDGET_SECONDS = float(os.environ.get("LLM_TOTAL_BUDGET_SECONDS", "40"))
except ValueError:
    LLM_TOTAL_BUDGET_SECONDS = 40.0

_BUDGET = threading.local()


def _start_budget() -> None:
    _BUDGET.deadline = time.monotonic() + LLM_TOTAL_BUDGET_SECONDS


def _budget_left() -> float:
    deadline = getattr(_BUDGET, "deadline", None)
    if deadline is None:
        return float("inf")
    return deadline - time.monotonic()


def _is_cooling_down(key: str) -> bool:
    until = _COOLDOWN_UNTIL.get(key)
    if until and time.time() < until:
        return True
    return False


def _set_cooldown(key: str, seconds: int) -> None:
    _COOLDOWN_UNTIL[key] = time.time() + seconds


def _dedupe_models(custom_first: List[str], defaults: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for m in custom_first + defaults:
        m = (m or "").strip()
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return ordered


def _clean_llm_output(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    # Strip <think>...</think> blocks emitted by reasoning models (DeepSeek-R1, QwQ)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    return cleaned or text.strip()


_PII_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PII_SECRET_RE = re.compile(r"(?<![A-Za-z0-9])(?:sk-|pk-|AIza|ghp_|xoxb-|xoxp-|xoxa-)[A-Za-z0-9_\-]{10,}")
_PII_CARD_RE = re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}(?!\d)")
_PII_AADHAAR_RE = re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)")
_PII_PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|91[\s-]?|0)?[6-9]\d{9}(?!\d)")
_PII_PAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Za-z0-9])")


def _redact_pii_for_prompt(text: str) -> str:
    """
    Conservative, deterministic, local masking of obvious personal data and secrets before text is sent
    to an AI provider. Non-string input is returned unchanged. No network, AI or database access.
    """
    if not isinstance(text, str):
        return text
    redacted = _PII_EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    redacted = _PII_SECRET_RE.sub("[REDACTED_SECRET]", redacted)
    redacted = _PII_CARD_RE.sub("[REDACTED_CARD]", redacted)
    redacted = _PII_AADHAAR_RE.sub("[REDACTED_ID]", redacted)
    redacted = _PII_PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _PII_PAN_RE.sub("[REDACTED_PAN]", redacted)
    return redacted


class SQLAgent:
    """
    Converts natural language questions into SQL queries.
    Providers and all of their free models are tried in order via
    get_provider_chain(), which is shared by every agent in the app.
    """

    @staticmethod
    def build_prompt(question: str, schema_info: str) -> str:
        # Only the free-text question is redacted; schema_info holds column names and types, which must stay intact.
        question = _redact_pii_for_prompt(question)
        return f"""You are a SQL expert. Convert the user's question into a single valid SQLite SELECT query.

Table name: data
Schema:
{schema_info}

Rules:
- Only generate SELECT queries. Never INSERT, UPDATE, DELETE, DROP, ALTER.
- If a column that looks numeric (marks, price, age, count, amount, id) is being sorted, filtered, or compared, wrap it with CAST(column AS REAL) to ensure correct numeric comparison, since it might be stored as text.
- Return ONLY the raw SQL query. No explanation. No markdown code fences.

Question: {question}

SQL Query:"""

    @staticmethod
    def _extract_sql(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```sql\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"```$", "", text.strip())
        return text.strip().rstrip(";").strip()

    @staticmethod
    def _try_openai_model_list(
        provider_name: str,
        url: str,
        api_key: str,
        models: List[str],
        prompt: str,
        timeout: int = 18,
    ) -> Optional[str]:
        if not api_key or _is_cooling_down(f"provider:{provider_name}"):
            return None

        for model in models:
            model_key = f"model:{provider_name}:{model}"
            if _is_cooling_down(model_key):
                continue
            if _budget_left() <= 0:
                print(f"[SQLAgent] Time budget exhausted before trying {provider_name} '{model}'.")
                return None

            for attempt in range(2):
                try:
                    resp = requests.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0,
                        },
                        timeout=(5, max(1.0, min(timeout, _budget_left()))),
                    )
                    if resp.status_code in (401, 403):
                        print(f"[SQLAgent] {provider_name} auth error ({resp.status_code}) — skipping provider for 120s.")
                        _set_cooldown(f"provider:{provider_name}", 120)
                        return None
                    if resp.status_code == 404:
                        print(f"[SQLAgent] {provider_name} model '{model}' not found (404) — trying next free model.")
                        _set_cooldown(model_key, 3600)
                        break
                    if resp.status_code == 429:
                        print(f"[SQLAgent] {provider_name} model '{model}' rate-limited (429) — trying next free model.")
                        _set_cooldown(model_key, 45)
                        break
                    if not resp.ok:
                        print(f"[SQLAgent] {provider_name} ({model}) HTTP {resp.status_code}: {resp.text[:160]}")
                        _set_cooldown(model_key, 20)
                        break

                    data = resp.json()
                    content = _clean_llm_output(data.get("choices", [{}])[0].get("message", {}).get("content"))
                    if content:
                        print(f"[SQLAgent] Success with {provider_name} -> '{model}'")
                        return content
                    break

                except requests.exceptions.ConnectionError as e:
                    if attempt == 0:
                        time.sleep(0.4)
                        continue
                    print(f"[SQLAgent] {provider_name} connection/DNS failed: {e}")
                    _set_cooldown(f"provider:{provider_name}", 15)
                    return None
                except requests.exceptions.Timeout:
                    print(f"[SQLAgent] {provider_name} ({model}) timed out — trying next model.")
                    _set_cooldown(model_key, 20)
                    break
                except Exception as e:
                    print(f"[SQLAgent] {provider_name} ({model}) failed: {e}")
                    break

        return None

    @staticmethod
    def _try_openrouter(prompt: str) -> Optional[str]:
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        env_model = (os.environ.get("OPENROUTER_MODEL") or "").strip()
        models = _dedupe_models([env_model], OPENROUTER_FREE_MODELS)
        return SQLAgent._try_openai_model_list("OpenRouter", OPENROUTER_API_URL, api_key, models, prompt, timeout=20)

    @staticmethod
    def _try_groq(prompt: str) -> Optional[str]:
        api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
        primary = (os.environ.get("GROQ_MODEL_PRIMARY") or "").strip()
        fallback = (os.environ.get("GROQ_MODEL_FALLBACK") or "").strip()
        models = _dedupe_models([primary, fallback], GROQ_FREE_MODELS)
        return SQLAgent._try_openai_model_list("Groq", GROQ_API_URL, api_key, models, prompt, timeout=15)

    @staticmethod
    def _try_gemini(prompt: str) -> Optional[str]:
        api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not api_key or _is_cooling_down("provider:Gemini"):
            return None
        env_model = (os.environ.get("GEMINI_MODEL") or "").strip()
        # Filter out known non-existent model typos like gemini-3.8-flash
        custom = [env_model] if env_model and not env_model.startswith("gemini-3.8") else []
        models = _dedupe_models(custom, GEMINI_FREE_MODELS)

        # Try OpenAI-compatible endpoint first across all free Gemini models
        out = SQLAgent._try_openai_model_list("Gemini", GEMINI_API_URL, api_key, models, prompt, timeout=18)
        if out:
            return out

        # Fallback to native Gemini generateContent REST endpoint
        for model in models:
            model_key = f"model:GeminiNative:{model}"
            if _is_cooling_down(model_key):
                continue
            if _budget_left() <= 0:
                return None
            native_url = "https://" + f"generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(
                    native_url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=(5, max(1.0, min(18, _budget_left()))),
                )
                if resp.status_code in (401, 403):
                    _set_cooldown("provider:Gemini", 120)
                    return None
                if resp.status_code == 404:
                    _set_cooldown(model_key, 3600)
                    continue
                if resp.status_code == 429:
                    _set_cooldown(model_key, 45)
                    continue
                if not resp.ok:
                    continue
                candidates = resp.json().get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and parts[0].get("text"):
                        print(f"[SQLAgent] Success with Gemini Native -> '{model}'")
                        return _clean_llm_output(parts[0]["text"])
            except requests.exceptions.ConnectionError:
                _set_cooldown("provider:Gemini", 15)
                return None
            except Exception:
                continue
        return None

    @staticmethod
    def _try_mistral(prompt: str) -> Optional[str]:
        api_key = (os.environ.get("MISTRAL_API_KEY") or "").strip()
        env_model = (os.environ.get("MISTRAL_MODEL") or "").strip()
        models = _dedupe_models([env_model], MISTRAL_FREE_MODELS)
        return SQLAgent._try_openai_model_list("Mistral", MISTRAL_API_URL, api_key, models, prompt, timeout=15)

    @staticmethod
    def _try_huggingface(prompt: str) -> Optional[str]:
        api_key = (
            os.environ.get("HUGGINGFACE_API_KEY")
            or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
            or ""
        ).strip()
        env_model = (os.environ.get("HUGGINGFACE_MODEL") or "").strip()
        models = _dedupe_models([env_model], HF_FREE_MODELS)
        return SQLAgent._try_openai_model_list("HuggingFace", HF_API_URL, api_key, models, prompt, timeout=18)

    @staticmethod
    def _try_anthropic(prompt: str) -> Optional[str]:
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key or _is_cooling_down("provider:Anthropic"):
            return None
        for model in ANTHROPIC_MODELS:
            model_key = f"model:Anthropic:{model}"
            if _is_cooling_down(model_key):
                continue
            if _budget_left() <= 0:
                return None
            try:
                resp = requests.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 500,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=(5, 15),
                )
                if resp.status_code in (401, 403):
                    print(f"[SQLAgent] Anthropic auth error ({resp.status_code}) — skipping provider for 120s.")
                    _set_cooldown("provider:Anthropic", 120)
                    return None
                if resp.status_code == 404:
                    _set_cooldown(model_key, 3600)
                    continue
                if not resp.ok:
                    continue
                text = _clean_llm_output(resp.json().get("content", [{}])[0].get("text"))
                if text:
                    print(f"[SQLAgent] Success with Anthropic -> '{model}'")
                    return text
            except requests.exceptions.ConnectionError:
                _set_cooldown("provider:Anthropic", 15)
                return None
            except Exception:
                continue
        return None

    @staticmethod
    def _try_ollama(prompt: str) -> Optional[str]:
        if _is_cooling_down("provider:Ollama"):
            return None
        env_model = (os.environ.get("OLLAMA_MODEL") or "").strip()
        discovered = []
        try:
            tags_resp = requests.get(OLLAMA_TAGS_URL, timeout=1.5)
            if tags_resp.ok:
                discovered = [m.get("name") for m in tags_resp.json().get("models", []) if m.get("name")]
        except Exception:
            _set_cooldown("provider:Ollama", 30)
            return None

        models = _dedupe_models([env_model] + discovered, OLLAMA_FALLBACK_MODELS)
        for model in models:
            if _budget_left() <= 0:
                return None
            try:
                resp = requests.post(
                    OLLAMA_GENERATE_URL,
                    json={"model": model, "prompt": prompt, "stream": False},
                    timeout=(2, max(1.0, min(45, _budget_left()))),
                )
                if not resp.ok:
                    continue
                out = _clean_llm_output(resp.json().get("response"))
                if out:
                    print(f"[SQLAgent] Success with Ollama -> '{model}'")
                    return out
            except requests.exceptions.ConnectionError:
                _set_cooldown("provider:Ollama", 30)
                return None
            except Exception:
                continue
        return None

    @staticmethod
    def get_provider_chain() -> List[Tuple]:
        """
        Shared fallback order used by every agent in this app.
        Each provider function automatically cascades through all of its
        available free models before moving to the next provider.
        """
        _start_budget()
        return [
            (SQLAgent._try_openrouter, "OpenRouter"),
            (SQLAgent._try_groq, "Groq"),
            (SQLAgent._try_gemini, "Gemini"),
            (SQLAgent._try_mistral, "Mistral"),
            (SQLAgent._try_huggingface, "HuggingFace"),
            (SQLAgent._try_anthropic, "Anthropic"),
            (SQLAgent._try_ollama, "Ollama"),
        ]

    @staticmethod
    def generate_sql(question: str, schema_info: str) -> str:
        prompt = SQLAgent.build_prompt(question, schema_info)

        for provider_fn, name in SQLAgent.get_provider_chain():
            raw_output = provider_fn(prompt)
            if raw_output:
                print(f"[SQLAgent] SQL generated using '{name}' provider.")
                return SQLAgent._extract_sql(raw_output)

        raise RuntimeError("All LLM providers failed. Check your API keys and network connection.")