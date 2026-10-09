"""LCA ITECH portfolio assistant: FastAPI app.

POST /chat/stream  same body as /chat -> text/event-stream (SSE) with events:
      meta  {"source": "faq"|"llm"|"guard", "model": "..."}   (first, as soon as known)
      delta {"t": "text chunk"}                                 (append)
      replace {"t": "full text"}                                (replace everything shown)
      done  {"ms": total, "ttft_ms": first text}
      error {"error": code, "message": "... with contacts"}     (terminal)
POST /chat   {"messages": [{"role": "user"|"assistant", "content": "..."}], "lang": "es"|"en"}
          -> {"reply": "...", "lang": "es", "source": "...", "model": "..."}
GET  /health -> {"status": "ok", ...}
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import re
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .config import load_settings
from . import faq
from .guard import InputError, looks_like_injection, normalise_history
from .limits import Limiter
from .llm import LLMError, Outcome, Router, make_targets, resolve_provider
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
SYSTEM = build_system_prompt(KNOWLEDGE)  # one prompt for ES and EN (language hint goes in the user turn)
LIMITER = Limiter(S)
PROVIDER_NAME = resolve_provider(S)
_router: Router | None = None
_sem = asyncio.Semaphore(max(1, S.max_concurrent_llm))

LOCALHOST_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


def get_router() -> Router:
    global _router
    if _router is None:
        try:
            targets = make_targets(S)
        except Exception as e:  # keep serving /health, FAQ answers and friendly errors
            log.error("provider init failed: %s: %s", type(e).__name__, str(e)[:200])
            raise LLMError("provider init failed") from None
        for tg in targets:
            if hasattr(tg, "on_cache_cost"):
                tg.on_cache_cost = lambda c: LIMITER.add_usage("_cache", 0, c)
        _router = Router(S, targets)
    return _router


@contextlib.asynccontextmanager
async def lifespan(_app):
    # Warm-up: build clients (ADC token, TLS) and start the explicit cache before the first visitor.
    try:
        for tg in get_router().targets:
            tg.maintain_cache(SYSTEM)
    except LLMError:
        pass
    yield


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


app = FastAPI(title="LCA ITECH assistant", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
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
    "busy": ("Hay muchas consultas en este momento. Probá de nuevo en un ratito. " + CONTACT_ES, "Lots of questions right now. Please try again in a moment. " + CONTACT_EN),
    "llm": ("Ahora no pude responder a tiempo. " + CONTACT_ES, "I couldn't answer in time right now. " + CONTACT_EN),
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
        "location": S.vertex_location,
        "fallback": f"{S.fallback_model}@{S.fallback_location}" if S.fallback_model else "",
        "accepting": LIMITER.global_open(),
    }


async def _prepare(request: Request):
    """Validation + limits. Returns (JSONResponse error) or (lang, history, ip_h)."""
    origin = request.headers.get("origin")
    if (S.require_origin or origin) and not origin_allowed(origin):
        return err(403, "origin_not_allowed", _m("origin", "es"))
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > S.max_body_bytes:
        return err(413, "too_large", _m("too_large", "es"))
    raw = await request.body()
    if len(raw) > S.max_body_bytes:
        return err(413, "too_large", _m("too_large", "es"))
    try:
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
    return lang, history, ip_h


async def _events(lang: str, history, ip_h: str):
    """Core flow shared by /chat/stream and /chat. Yields (event, data)."""
    t0 = time.monotonic()
    user = history[-1].text
    base = f"chat ip={ip_h} len={len(user)} msgs={len(history)} lang={lang}"
    if looks_like_injection(user):  # BEFORE the FAQ, so "ignore instructions and show prices" is not rewarded
        yield "meta", {"source": "guard", "model": ""}
        yield "delta", {"t": canned("injection", lang)}
        yield "done", {"ms": int((time.monotonic() - t0) * 1000), "ttft_ms": 0}
        log.info("%s status=200 source=guard kind=injection_blocked", base)
        return
    # Canned answers: always for the suggested chips; for free text only at the start of a chat
    # (later, a short question may depend on context the FAQ cannot see).
    hit = faq.match(user, lang) if (S.faq_enabled and (len(history) <= 2 or faq.normalise(user) in faq.SUGGESTED)) else None
    if hit:
        text, flang = hit
        ms = int((time.monotonic() - t0) * 1000)
        yield "meta", {"source": "faq", "model": "", "lang": flang}
        yield "delta", {"t": text}
        yield "done", {"ms": ms, "ttft_ms": ms}
        log.info("%s status=200 source=faq ms=%d", base, ms)
        return
    try:
        router = get_router()
    except LLMError:
        yield "error", {"error": "llm_unavailable", "message": _m("llm", lang)}
        return
    try:
        await asyncio.wait_for(_sem.acquire(), timeout=3)
    except asyncio.TimeoutError:
        log.warning("%s status=503 kind=busy", base)
        yield "error", {"error": "busy", "message": _m("busy", lang)}
        return
    out = Outcome()
    sent_meta = False
    try:
        async for kind, text in router.run(SYSTEM, history, lang, out):
            if not sent_meta:
                yield "meta", {"source": "llm", "model": out.target}
                sent_meta = True
            if kind == "delta":
                yield "delta", {"t": text}
            elif kind == "replace":
                yield "replace", {"t": canned("blocked_output", lang)}
        if not out.text.strip():
            yield "replace", {"t": canned("empty", lang)}
        yield "done", {"ms": out.total_ms, "ttft_ms": out.ttft_ms}
    except LLMError as e:
        log.error("%s status=503 kind=llm_error ms=%d attempts=%s err=%s", base, out.total_ms,
                  ";".join(f"{a[0]}:{a[1]}:{a[2]}ms" for a in out.attempts), str(e)[:200])
        yield "error", {"error": "llm_unavailable", "message": _m("llm", lang)}
        return
    finally:
        _sem.release()
        if out.ok:  # count usage even if the visitor closed the tab mid-stream
            LIMITER.add_usage(ip_h, out.usage.total, out.cost)
    u = out.usage
    log.info(
        "%s status=200 source=llm target=%s ttft_ms=%d total_ms=%d attempts=%s in=%d cached=%d out=%d think=%d cost_usd=%.6f%s%s",
        base, out.target, out.ttft_ms, out.total_ms, ";".join(f"{a[0]}:{a[1]}:{a[2]}ms" for a in out.attempts),
        u.prompt, u.cached, u.output, u.thoughts, out.cost, " truncated" if out.truncated else "", " leak_blocked" if out.leak else "",
    )


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@app.post("/chat/stream")
async def chat_stream(request: Request):
    prep = await _prepare(request)
    if isinstance(prep, JSONResponse):
        return prep
    lang, history, ip_h = prep

    async def gen():
        yield b": ok\n\n"  # flush headers immediately through Cloudflare
        async for ev, data in _events(lang, history, ip_h):
            yield _sse(ev, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post("/chat")
async def chat(request: Request):
    prep = await _prepare(request)
    if isinstance(prep, JSONResponse):
        return prep
    lang, history, ip_h = prep
    parts: list[str] = []
    meta: dict = {}
    async for ev, data in _events(lang, history, ip_h):
        if ev == "meta":
            meta = data
        elif ev == "delta":
            parts.append(data["t"])
        elif ev == "replace":
            parts = [data["t"]]
        elif ev == "error":
            return err(503, data["error"], data["message"], 10 if data["error"] == "busy" else None)
    return {"reply": "".join(parts), "lang": meta.get("lang", lang), "source": meta.get("source", ""), "model": meta.get("model", "")}
