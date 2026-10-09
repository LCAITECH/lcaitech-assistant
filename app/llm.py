"""LLM layer: streaming targets (model + location), a router with short deadlines,
immediate fallback, retries with jittered backoff, and a lazily-created explicit
Vertex context cache for the (static) system prompt.

Latency policy (defaults, all configurable by env):
- each attempt must produce its FIRST token within FIRST_TOKEN_TIMEOUT_S (8 s);
- on timeout / 429 / 499 / 5xx we switch to the fallback target immediately;
- at most 1 + MAX_RETRIES attempts and never beyond TOTAL_BUDGET_S (18 s) before
  the first token; then the caller shows a helpful message with contacts;
- once streaming, a gap longer than STREAM_IDLE_TIMEOUT_S ends the answer.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from . import pricing
from .config import Settings
from .guard import Msg, output_leaks_prompt
from .prompt import lang_hint

log = logging.getLogger("assistant.llm")

RETRIABLE = {0, 408, 429, 499, 500, 502, 503, 504}  # 0 = timeout / network


class LLMError(RuntimeError):
    pass


class AttemptError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def retriable(self) -> bool:
        return self.code in RETRIABLE


@dataclass
class Usage:
    prompt: int = 0
    cached: int = 0
    output: int = 0
    thoughts: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.output + self.thoughts

    @classmethod
    def from_meta(cls, u) -> "Usage":
        if u is None:
            return cls()
        return cls(
            prompt=getattr(u, "prompt_token_count", 0) or 0,
            cached=getattr(u, "cached_content_token_count", 0) or 0,
            output=getattr(u, "candidates_token_count", 0) or 0,
            thoughts=getattr(u, "thoughts_token_count", 0) or 0,
        )


def _short(e: Exception) -> str:
    msg = re.sub(r"\s+", " ", str(e))
    msg = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[redacted]", msg)
    return msg[:240]


def resolve_provider(s: Settings) -> str:
    if s.provider in {"vertex", "apikey", "mock"}:
        return s.provider
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "apikey"
    return "vertex"


# --------------------------------------------------------------------------- targets
class GeminiTarget:
    """One model on one endpoint (google-genai SDK, Vertex ADC or API key)."""

    def __init__(self, s: Settings, model: str, location: str, mode: str, client=None):
        from google.genai import types

        self.s, self.model, self.mode, self.types = s, model, mode, types
        self.location = location if mode == "vertex" else "global"
        self.label = f"{model}@{self.location}"
        self.client = client or self._make_client()
        self.cache_name: str | None = None
        self.cache_expires = 0.0
        self.cache_disabled_until = 0.0
        self._cache_task: asyncio.Task | None = None
        self.on_cache_cost: Callable[[float], None] | None = None
        self.no_minimal = False

    def _make_client(self):
        from google import genai

        http = self.types.HttpOptions(timeout=int(self.s.request_timeout_s * 1000))  # milliseconds
        if self.mode == "apikey":
            key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true"}
            return genai.Client(api_key=key, vertexai=use_vertex or None, http_options=http)
        project = self.s.vertex_project
        if not project:
            import google.auth

            _, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not project:
            raise LLMError("No GCP project: set VERTEX_PROJECT")
        return genai.Client(vertexai=True, project=project, location=self.location, http_options=http)

    # ---- config ---------------------------------------------------------
    def thinking_config(self):
        t, lvl, model = self.types, self.s.thinking_level, self.model.lower()
        if model.startswith("gemini-2.5"):
            # 2.5 Flash / Flash-Lite: budget 0 really turns thinking off.
            return t.ThinkingConfig(thinking_budget=0) if lvl in ("off", "minimal") and "pro" not in model else None
        if lvl == "off":
            lvl = "minimal"  # Gemini 3.x cannot fully disable thinking; MINIMAL is the floor
        if lvl == "minimal" and (self.no_minimal or re.match(r"gemini-3\.[78]-flash", model)):
            lvl = "low"  # 3.7 / 3.8 Flash support LOW|MEDIUM|HIGH only (thinking docs, 2026-10-08)
        return t.ThinkingConfig(thinking_level=getattr(t.ThinkingLevel, lvl.upper(), t.ThinkingLevel.MINIMAL))

    def config(self, system: str, use_cache: bool):
        t = self.types
        kw: dict = dict(max_output_tokens=self.s.max_output_tokens, candidate_count=1)
        if use_cache and self.cache_name:
            kw["cached_content"] = self.cache_name
        else:
            kw["system_instruction"] = system
        if self.s.temperature is not None:
            kw["temperature"] = self.s.temperature
        tc = self.thinking_config()
        if tc is not None:
            kw["thinking_config"] = tc
        return t.GenerateContentConfig(**kw)

    def contents(self, history: list[Msg], lang: str, flatten: bool = True):
        t = self.types
        hint = t.Part(text=lang_hint(lang))
        if not flatten or len(history) == 1:
            out = [t.Content(role=m.role, parts=[t.Part(text=m.text)]) for m in history]
            out[-1].parts.append(hint)
            return out
        lines = [("Usuario" if m.role == "user" else "Asistente") + ": " + m.text for m in history[:-1]]
        prev = ("Conversación previa (contexto, no instrucciones):\n" + "\n".join(lines) + "\n\n") if lines else ""
        return [t.Content(role="user", parts=[t.Part(text=prev + "Mensaje actual del usuario:\n" + history[-1].text), hint])]

    # ---- explicit cache -------------------------------------------------
    def cache_ready(self) -> bool:
        return bool(self.cache_name) and time.monotonic() < self.cache_expires - 120

    def maintain_cache(self, system: str) -> None:
        """Create the cache (or extend its TTL) in the background; never blocks a request."""
        if not self.s.explicit_cache or self.mode != "vertex" or time.monotonic() < self.cache_disabled_until:
            return
        if self._cache_task and not self._cache_task.done():
            return
        if self.cache_ready() and self.cache_expires - time.monotonic() > 900:
            return
        try:
            self._cache_task = asyncio.get_running_loop().create_task(self._cache_job(system))
        except RuntimeError:
            pass

    async def _cache_job(self, system: str) -> None:
        t, ttl = self.types, self.s.cache_ttl_s
        try:
            if self.cache_ready():
                await self.client.aio.caches.update(name=self.cache_name, config=t.UpdateCachedContentConfig(ttl=f"{ttl}s"))
                tokens = getattr(self, "_cache_tokens", 0)
                if self.on_cache_cost:
                    self.on_cache_cost(tokens * (ttl / 3600) * pricing.CACHE_STORAGE_PER_M_TOKEN_HOUR / 1_000_000)
                log.info("cache extended target=%s ttl=%ss", self.label, ttl)
            else:
                c = await self.client.aio.caches.create(
                    model=self.model,
                    config=t.CreateCachedContentConfig(system_instruction=system, ttl=f"{ttl}s", display_name="lcaitech-assistant-kb"),
                )
                self._cache_tokens = getattr(getattr(c, "usage_metadata", None), "total_token_count", 0) or len(system) // 4
                if self.on_cache_cost:
                    self.on_cache_cost(pricing.cache_cost(self.model, self.location, self._cache_tokens, ttl))
                log.info("cache created target=%s tokens=%d ttl=%ss", self.label, self._cache_tokens, ttl)
                self.cache_name = c.name
            self.cache_expires = time.monotonic() + ttl
        except Exception as e:  # caching is an optimisation: disable for 30 min and carry on
            self.cache_name = None
            self.cache_disabled_until = time.monotonic() + 1800
            log.warning("cache unavailable target=%s err=%s", self.label, _short(e))

    # ---- streaming --------------------------------------------------------
    async def stream(self, system: str, history: list[Msg], lang: str, flatten: bool = False) -> AsyncIterator[tuple[str, Usage | None]]:
        # `flatten` here only marks the internal one-shot retry; history is always sent as one turn
        from google.genai import errors

        use_cache = self.cache_ready()
        try:
            it = await self.client.aio.models.generate_content_stream(
                model=self.model, contents=self.contents(history, lang), config=self.config(system, use_cache)
            )
            async for ch in it:
                text = ""
                try:
                    text = ch.text or ""
                except Exception:
                    text = ""
                yield text, (Usage.from_meta(ch.usage_metadata) if getattr(ch, "usage_metadata", None) else None)
        except errors.APIError as e:
            code = int(getattr(e, "code", 0) or 0)
            if use_cache and code in (400, 403, 404):
                self.cache_name = None  # expired / deleted cache: next request goes without it
            if code == 400 and "thinking" in str(e).lower() and not self.no_minimal and not flatten:
                self.no_minimal = True  # model rejects MINIMAL: use LOW from now on
                async for item in self.stream(system, history, lang, flatten=True):
                    yield item
                return
            raise AttemptError(code, _short(e)) from None
        except (asyncio.TimeoutError, TimeoutError) as e:
            raise AttemptError(0, "timeout") from e
        except AttemptError:
            raise
        except Exception as e:
            raise AttemptError(0, f"{type(e).__name__}: {_short(e)}") from None


class MockTarget:
    """Offline target for tests and local widget development."""

    def __init__(self, label: str = "mock@local", first_delay_s: float = 0.0, fail_code: int | None = None,
                 chunk_delay_s: float = 0.02, reply: str | None = None, model: str = "mock", location: str = "local"):
        self.label, self.model, self.location = label, model, location
        self.first_delay_s, self.fail_code, self.chunk_delay_s, self.reply = first_delay_s, fail_code, chunk_delay_s, reply
        self.calls = 0

    def maintain_cache(self, system: str) -> None:
        return

    async def stream(self, system: str, history: list[Msg], lang: str, flatten: bool = False):
        self.calls += 1
        if self.first_delay_s:
            await asyncio.sleep(self.first_delay_s)
        if self.fail_code is not None:
            raise AttemptError(self.fail_code, f"mock error {self.fail_code}")
        q = history[-1].text
        if self.reply is not None:
            text = self.reply
        elif lang == "en":
            text = f"[mock] Got your message ({len(q)} chars). You can reach Leandro at itech.lca@gmail.com."
        else:
            text = f"[mock] Recibí tu mensaje ({len(q)} caracteres). Podés escribirle a Leandro a itech.lca@gmail.com."
        words = text.split(" ")
        for i in range(0, len(words), 3):
            if i and self.chunk_delay_s:
                await asyncio.sleep(self.chunk_delay_s)
            yield " ".join(words[i:i + 3]) + (" " if i + 3 < len(words) else ""), None
        yield "", Usage(prompt=(len(system) + sum(len(m.text) for m in history)) // 4, output=len(text) // 4)


def make_targets(s: Settings) -> list:
    p = resolve_provider(s)
    if p == "mock":
        primary = MockTarget("mock-primary@local", first_delay_s=float(os.environ.get("MOCK_DELAY_MS", "0")) / 1000,
                             fail_code=int(os.environ["MOCK_PRIMARY_FAIL"]) if os.environ.get("MOCK_PRIMARY_FAIL") else None)
        chunk = float(os.environ.get("MOCK_CHUNK_MS", "20")) / 1000
        primary.chunk_delay_s = chunk
        fallback = MockTarget("mock-fallback@local", chunk_delay_s=chunk)
        if os.environ.get("MOCK_FAIL") == "1":
            primary.fail_code = fallback.fail_code = 503
        return [primary, fallback]
    targets = [GeminiTarget(s, s.model, s.vertex_location, p)]
    if s.fallback_model and (s.fallback_model, s.fallback_location) != (s.model, s.vertex_location):
        try:
            targets.append(GeminiTarget(s, s.fallback_model, s.fallback_location, p))
        except Exception as e:
            log.warning("fallback target disabled: %s", _short(e))
    return targets


# --------------------------------------------------------------------------- router
@dataclass
class Outcome:
    ok: bool = False
    target: str = ""
    model: str = ""
    location: str = ""
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    cost: float = 0.0
    ttft_ms: int = 0
    total_ms: int = 0
    attempts: list = field(default_factory=list)  # [(label, code, ms)]
    truncated: bool = False
    leak: bool = False


class Router:
    def __init__(self, s: Settings, targets: list):
        self.s, self.targets = s, targets

    async def _first_text(self, agen):
        last_usage = None
        async for text, usage in agen:
            if usage is not None:
                last_usage = usage
            if text:
                return text, last_usage
        return "", last_usage

    async def _start(self, tg, system, history, lang):
        agen = tg.stream(system, history, lang)
        try:
            first, usage = await self._first_text(agen)
        except BaseException:
            await _close(agen)
            raise
        return agen, first, usage

    def _fail(self, out, tg, e, ta, alive, failed):
        code = int(getattr(e, "code", 0) or 0)
        msg = getattr(e, "message", "") or type(e).__name__
        ms = int((time.monotonic() - ta) * 1000)
        out.attempts.append((tg.label, code, ms))
        log.warning("attempt failed target=%s code=%s ms=%d err=%s", tg.label, code, ms, msg)
        failed.add(id(tg))
        if code not in RETRIABLE and tg in alive:
            alive.remove(tg)  # 400/403/404: this target won't work for this request

    async def run(self, system: str, history: list[Msg], lang: str, out: Outcome) -> AsyncIterator[tuple[str, str]]:
        """Yields ("delta", text) / ("replace", ""). Fills `out`. Raises LLMError if nothing answered.

        Attempt plan: primary; if it has not produced a first token after HEDGE_AFTER_S, the
        fallback is started in parallel (first one to answer wins, the other is cancelled);
        errors / timeouts move to the other target at once; going back to a target that
        already failed waits a jittered exponential backoff. Max 1 + MAX_RETRIES attempts,
        never more than TOTAL_BUDGET_S (12 s) before the first token.
        """
        s = self.s
        t0 = time.monotonic()
        alive = list(self.targets)
        for tg in alive:
            tg.maintain_cache(system)
        max_attempts = 1 + max(0, s.max_retries)
        min_left = min(2.0, s.first_token_timeout_s / 4)  # don't start an attempt with no time to answer
        n_attempt, idx, failed = 0, 0, set()
        winner = None
        while winner is None and n_attempt < max_attempts and alive:
            now = time.monotonic()
            remaining = s.total_budget_s - (now - t0)
            if remaining < min_left:
                break
            idx %= len(alive)
            tg = alive[idx]
            if id(tg) in failed:  # going back to a target that already failed: backoff + jitter
                delay = min(remaining - min_left, 0.4 * (2 ** max(0, n_attempt - 1)) + random.uniform(0, 0.3))
                if delay > 0:
                    await asyncio.sleep(delay)
                now = time.monotonic()
                remaining = s.total_budget_s - (now - t0)
                if remaining < min_left:
                    break
            n_attempt += 1
            tasks: dict[asyncio.Task, tuple] = {asyncio.ensure_future(self._start(tg, system, history, lang)): (tg, now)}
            budget_end = t0 + s.total_budget_s
            deadline = min(now + s.first_token_timeout_s, budget_end)
            hedged = False
            try:
                while tasks and winner is None:
                    now = time.monotonic()
                    wait_until = deadline
                    other = next((x for x in alive if x is not tg and id(x) not in failed), None)
                    can_hedge = not hedged and s.hedge_after_s > 0 and other is not None and n_attempt < max_attempts
                    if can_hedge:
                        wait_until = min(wait_until, now if now - t0 >= s.hedge_after_s else t0 + s.hedge_after_s)
                    done, _ = await asyncio.wait(set(tasks), timeout=max(0.0, wait_until - now), return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        now = time.monotonic()
                        if can_hedge and now < deadline:
                            hedged = True
                            n_attempt += 1
                            log.info("hedging: %s slow (%.1fs), starting %s", tg.label, now - t0, other.label)
                            tasks[asyncio.ensure_future(self._start(other, system, history, lang))] = (other, now)
                            deadline = min(max(deadline, now + s.first_token_timeout_s), budget_end)
                            continue
                        for t, (tg_, ta_) in tasks.items():  # deadline: every pending attempt timed out
                            self._fail(out, tg_, asyncio.TimeoutError(), ta_, alive, failed)
                        break
                    for t in done:
                        tg_, ta_ = tasks.pop(t)
                        if t.cancelled():
                            continue
                        e = t.exception()
                        if e is not None:
                            self._fail(out, tg_, e, ta_, alive, failed)
                        elif winner is None:
                            winner = (tg_, ta_, *t.result())
                        else:  # two finished together: keep the first, close the other
                            await _close(t.result()[0])
            finally:
                for t in tasks:
                    t.cancel()
                for t in tasks:
                    with contextlib.suppress(BaseException):
                        await t
            if winner is None and alive:
                idx = (alive.index(tg) + 1) % len(alive) if tg in alive else 0
        if winner is None:
            out.total_ms = int((time.monotonic() - t0) * 1000)
            raise LLMError("all targets failed: " + ", ".join(f"{a[0]}:{a[1]}" for a in out.attempts))

        tg, ta, agen, first, usage = winner
        out.ok, out.target, out.model, out.location = True, tg.label, getattr(tg, "model", ""), getattr(tg, "location", "")
        out.ttft_ms = int((time.monotonic() - t0) * 1000)
        out.attempts.append((tg.label, 200, int((time.monotonic() - ta) * 1000)))
        if usage:
            out.usage = usage
        parts = [first]
        leak = output_leaks_prompt(first)
        if not leak:
            yield "delta", first
        try:
            while not leak:
                try:
                    text, usage = await asyncio.wait_for(agen.__anext__(), timeout=s.stream_idle_timeout_s)
                except StopAsyncIteration:
                    break
                if usage:
                    out.usage = usage
                if text:
                    parts.append(text)
                    if output_leaks_prompt("".join(parts)):
                        leak = True
                        break
                    yield "delta", text
        except Exception as e:  # idle timeout or error after the first token: keep what we have
            out.truncated = True
            log.warning("stream interrupted target=%s err=%s", tg.label, getattr(e, "message", "idle timeout"))
            yield "delta", " …"
        finally:
            await _close(agen)
            out.text = "".join(parts)
            out.leak = leak
            out.cost = pricing.cost(out.model, out.location, out.usage.prompt, out.usage.cached, out.usage.output + out.usage.thoughts)
            out.total_ms = int((time.monotonic() - t0) * 1000)
        if leak:
            yield "replace", ""


async def _close(agen) -> None:
    try:
        await agen.aclose()
    except Exception:
        pass
