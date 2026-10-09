"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip().rstrip("/") for x in os.environ.get(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    # LLM
    provider: str = ""  # vertex | apikey | mock ("" = auto)
    model: str = "gemini-3.8-flash"
    vertex_project: str = ""
    vertex_location: str = "global"
    thinking_level: str = "minimal"  # lowest the model supports is used (3.7/3.8 Flash: low); 2.5: off => budget 0
    max_output_tokens: int = 1024  # thinking tokens count against this limit
    temperature: float | None = None
    max_concurrent_llm: int = 4
    # Fallback target (different model and/or endpoint). Empty FALLBACK_MODEL disables it.
    fallback_model: str = "gemini-3.1-flash-lite"
    fallback_location: str = "us"
    # Latency budget: time to FIRST token per attempt, gap between chunks, whole pre-first-token budget.
    first_token_timeout_s: float = 8.0
    stream_idle_timeout_s: float = 8.0
    total_budget_s: float = 12.0
    hedge_after_s: float = 2.5  # start the fallback in parallel if no first token yet (0 = off)
    max_retries: int = 2  # extra attempts after the first one (fallback counts as one)
    request_timeout_s: float = 30.0  # hard HTTP cap for a full streamed answer
    # Explicit Vertex context cache for the system prompt (created lazily, TTL refreshed while there is traffic)
    explicit_cache: bool = True
    cache_ttl_s: int = 3600
    # Server-side instant answers for suggested / frequent questions
    faq_enabled: bool = True

    # Input limits
    max_msg_chars: int = 800
    max_history_messages: int = 10
    max_assistant_chars: int = 1500
    max_body_bytes: int = 32_000

    # Rate limits / budget
    ip_per_minute: int = 10
    ip_per_day: int = 50
    global_requests_per_day: int = 1000
    global_tokens_per_day: int = 8_000_000
    global_cost_usd_per_day: float = 1.00
    day_tz: str = "America/Argentina/Buenos_Aires"

    # HTTP
    allowed_origins: list[str] = field(default_factory=list)
    allow_localhost: bool = True
    require_origin: bool = True
    trust_proxy_headers: bool = True

    # Storage
    state_db: str = "./state/assistant.db"
    knowledge_dir: str = ""


def load_settings() -> Settings:
    temp = os.environ.get("TEMPERATURE", "").strip()
    here = os.path.dirname(os.path.abspath(__file__))
    return Settings(
        provider=os.environ.get("LLM_PROVIDER", "").strip().lower(),
        model=os.environ.get("MODEL", "gemini-3.8-flash").strip(),
        vertex_project=(os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip(),
        vertex_location=os.environ.get("VERTEX_LOCATION", "global").strip(),
        thinking_level=os.environ.get("THINKING_LEVEL", "minimal").strip().lower(),
        max_output_tokens=_int("MAX_OUTPUT_TOKENS", 1024),
        temperature=float(temp) if temp else None,
        max_concurrent_llm=_int("MAX_CONCURRENT_LLM", 4),
        fallback_model=os.environ.get("FALLBACK_MODEL", "gemini-3.1-flash-lite").strip(),
        fallback_location=os.environ.get("FALLBACK_LOCATION", "us").strip(),
        first_token_timeout_s=_float("FIRST_TOKEN_TIMEOUT_S", 8.0),
        stream_idle_timeout_s=_float("STREAM_IDLE_TIMEOUT_S", 8.0),
        total_budget_s=_float("TOTAL_BUDGET_S", 12.0),
        hedge_after_s=_float("HEDGE_AFTER_S", 2.5),
        max_retries=_int("MAX_RETRIES", 2),
        request_timeout_s=_float("REQUEST_TIMEOUT_S", 30.0),
        explicit_cache=_bool("EXPLICIT_CACHE", True),
        cache_ttl_s=_int("CACHE_TTL_S", 3600),
        faq_enabled=_bool("FAQ_ENABLED", True),
        max_msg_chars=_int("MAX_MSG_CHARS", 800),
        max_history_messages=_int("MAX_HISTORY_MESSAGES", 10),
        max_assistant_chars=_int("MAX_ASSISTANT_CHARS", 1500),
        max_body_bytes=_int("MAX_BODY_BYTES", 32_000),
        ip_per_minute=_int("IP_PER_MINUTE", 10),
        ip_per_day=_int("IP_PER_DAY", 50),
        global_requests_per_day=_int("GLOBAL_REQUESTS_PER_DAY", 1000),
        global_tokens_per_day=_int("GLOBAL_TOKENS_PER_DAY", 8_000_000),
        global_cost_usd_per_day=_float("GLOBAL_COST_USD_PER_DAY", 1.00),
        day_tz=os.environ.get("DAY_TZ", "America/Argentina/Buenos_Aires"),
        allowed_origins=_list("ALLOWED_ORIGINS", "https://portfolio.lcaitech.com"),
        allow_localhost=_bool("ALLOW_LOCALHOST", True),
        require_origin=_bool("REQUIRE_ORIGIN", True),
        trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", True),
        state_db=os.environ.get("STATE_DB", "./state/assistant.db"),
        knowledge_dir=os.environ.get("KNOWLEDGE_DIR", os.path.join(os.path.dirname(here), "knowledge")),
    )
