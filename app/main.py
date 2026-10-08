"""LCA ITECH portfolio assistant: FastAPI app.

POST /chat   {"messages": [{"role": "user"|"assistant", "content": "..."}], "lang": "es"|"en"}
          -> {"reply": "...", "lang": "es"}
GET  /health -> {"status": "ok", ...}
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import load_settings
from .guard import InputError, looks_like_injection, normalise_history, output_leaks_prompt
from .limits import Limiter
from .llm import LLMError, make_provider, resolve_provider
from .prompt import CONTACT_EN, CONTACT_ES, build_system_prompt, canned, load_knowledge


class RedactSecrets(logging.Filter):
    """Never let an API key reach the logs."""

    def __init__(self):
        super().__init__()
        self.secrets = [v for v in (os.environ.get("GOOGLE_API_KEY"), os.environ.get("GEMINI_API_KEY")) if v and len(v) > 8]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[redacted]", msg)
        for sec in self.secrets:
            red = red.replace(sec, "[redacted]")
        if red != msg:
            record.msg, record.args = red, ()
        return True


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for h in logging.getLogger().handlers:
    h.addFilter(RedactSecrets())
for noisy in ("httpx", "httpcore", "google_genai", "google.auth", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("assistant")

S = load_settings()
KNOWLEDGE = load_knowledge(S.knowledge_dir)
SYSTEM = {lang: build_system_prompt(KNOWLEDGE, lang) for lang in ("es", "en")}
LIMITER = Limiter(S)
PROVIDER_NAME = resolve_provider(S)
_provider = None
_provider_error = ""
_sem = asyncio.Semaphore(max(1, S.max_concurrent_llm))

LOCALHOST_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


def get_provider():
    global _provider, _provider_error
    if _provider is None:
        try:
            _provider = make_provider(S)
            _provider_error = ""
        except Exception as e:  # keep serving /health and friendly errors
            _provider_error = f"{type(e).__name__}"
            log.error("provider init failed: %s: %s", type(e).__name__, str(e)[:200])
            raise LLMError("provider init failed") from None
    return _provider


def origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    origin = origin.rstrip("/")
    if origin in S.allowed_origins:
        return True
    return S.allow_localhost and bool(LOCALHOST_RE.match(origin))


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "0.0.0.0"
    if S.trust_proxy_headers:
        try:
            trusted = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
        except ValueError:
            trusted = False
        if trusted:
            cf = request.headers.get("cf-connecting-ip", "").strip()
            if cf:
                return cf
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                return xff.split(",")[0].strip()
    return peer


app = FastAPI(title="LCA ITECH assistant", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=S.allowed_origins,
    allow_origin_regex=LOCALHOST_RE.pattern if S.allow_localhost else None,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
    max_age=600,
)

MSG = {
    "ip_minute": ("Vas muy rápido 🙂 Esperá unos segundos y volvé a intentar.", "You're going a bit fast 🙂 Please wait a few seconds and try again."),
    "ip_day": (
        "Llegaste al límite de mensajes de hoy. Para seguir la charla, " + CONTACT_ES[0].lower() + CONTACT_ES[1:],
        "You've reached today's message limit. To keep talking, " + CONTACT_EN[0].lower() + CONTACT_EN[1:],
    ),
    "global": (
        "El asistente alcanzó su límite diario de uso. Volvé mañana o " + CONTACT_ES[0].lower() + CONTACT_ES[1:],
        "The assistant reached its daily usage limit. Come back tomorrow or " + CONTACT_EN[0].lower() + CONTACT_EN[1:],
    ),
    "busy": ("Hay muchas consultas en este momento. Probá de nuevo en un ratito.", "Lots of questions right now. Please try again in a moment."),
    "llm": ("No pude responder ahora. " + CONTACT_ES, "I couldn't answer right now. " + CONTACT_EN),
    "origin": ("Origen no permitido.", "Origin not allowed."),
    "bad_request": ("No entendí el pedido.", "Invalid request."),
    "too_large": ("El pedido es demasiado grande.", "Request too large."),
}


def _m(key: str, lang: str) -> str:
    es, en = MSG[key]
    return en if lang == "en" else es


def err(status: int, code: str, message: str, retry_after: int | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": code, "message": message}
    headers = {}
    if retry_after:
        body["retry_after"] = retry_after
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(body, status_code=status, headers=headers)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "provider": PROVIDER_NAME,
        "model": S.model,
        "accepting": LIMITER.global_open(),
    }


@app.post("/chat")
async def chat(request: Request):
    t0 = time.monotonic()
    origin = request.headers.get("origin")
    if S.require_origin and not origin_allowed(origin):
        return err(403, "origin_not_allowed", _m("origin", "es"))
    if origin and not origin_allowed(origin):
        return err(403, "origin_not_allowed", _m("origin", "es"))

    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > S.max_body_bytes:
        return err(413, "too_large", _m("too_large", "es"))
    raw = await request.body()
    if len(raw) > S.max_body_bytes:
        return err(413, "too_large", _m("too_large", "es"))
    try:
        import json

        data = json.loads(raw or b"{}")
        assert isinstance(data, dict)
        lang = "en" if str(data.get("lang", "es")).lower().startswith("en") else "es"
        messages = data.get("messages")
        assert isinstance(messages, list) and 0 < len(messages) <= 60
        messages = [m for m in messages if isinstance(m, dict)]
    except Exception:
        return err(400, "bad_request", _m("bad_request", "es"))

    ip_h = LIMITER.ip_hash(client_ip(request))
    try:
        history = normalise_history(messages, S.max_msg_chars, S.max_history_messages, S.max_assistant_chars)
    except InputError as e:
        log.info("chat ip=%s status=400 kind=%s", ip_h, e.code)
        return err(400, e.code, e.message_en if lang == "en" else e.message_es)

    verdict = LIMITER.check_and_count(ip_h)
    if not verdict.ok:
        key = "global" if verdict.reason.startswith("global") else verdict.reason
        log.info("chat ip=%s status=429 reason=%s", ip_h, verdict.reason)
        return err(429, "rate_limited", _m(key, lang), verdict.retry_after)

    user_len = len(history[-1].text)
    if looks_like_injection(history[-1].text):
        log.info("chat ip=%s len=%d msgs=%d lang=%s status=200 kind=injection_blocked", ip_h, user_len, len(history), lang)
        return {"reply": canned("injection", lang), "lang": lang}

    try:
        provider = get_provider()
        try:
            await asyncio.wait_for(_sem.acquire(), timeout=10)
        except asyncio.TimeoutError:
            log.warning("chat ip=%s status=503 kind=busy", ip_h)
            return err(503, "busy", _m("busy", lang), 10)
        try:
            res = await asyncio.wait_for(provider.generate(SYSTEM[lang], history), timeout=S.llm_timeout_s + 5)
        finally:
            _sem.release()
    except (LLMError, asyncio.TimeoutError) as e:
        log.error("chat ip=%s len=%d status=503 kind=llm_error err=%s", ip_h, user_len, str(e)[:300] or "timeout")
        return err(503, "llm_unavailable", _m("llm", lang))

    cost = res.cost(S)
    LIMITER.add_usage(ip_h, res.total_tokens, cost)
    reply = res.text
    kind = "llm"
    if not reply:
        reply, kind = canned("empty", lang), "empty"
    elif output_leaks_prompt(reply):
        reply, kind = canned("blocked_output", lang), "leak_blocked"
    log.info(
        "chat ip=%s len=%d msgs=%d lang=%s status=200 kind=%s in=%d cached=%d out=%d think=%d cost_usd=%.6f finish=%s ms=%d",
        ip_h, user_len, len(history), lang, kind, res.prompt_tokens, res.cached_tokens, res.output_tokens,
        res.thought_tokens, cost, res.finish, int((time.monotonic() - t0) * 1000),
    )
    return {"reply": reply, "lang": lang}
