"""LLM providers: Vertex AI (ADC), Gemini API key, or a deterministic mock."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass

from .config import Settings
from .guard import Msg

log = logging.getLogger("assistant.llm")


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    finish: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens + self.thought_tokens

    def cost(self, s: Settings) -> float:
        uncached = max(0, self.prompt_tokens - self.cached_tokens)
        return (
            uncached * s.price_input_per_m
            + self.cached_tokens * s.price_cached_per_m
            + (self.output_tokens + self.thought_tokens) * s.price_output_per_m
        ) / 1_000_000


class LLMError(RuntimeError):
    pass


def resolve_provider(s: Settings) -> str:
    if s.provider in {"vertex", "apikey", "mock"}:
        return s.provider
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "apikey"
    return "vertex"


class GeminiProvider:
    """google-genai SDK. vertex: ADC (VM service account). apikey: GOOGLE_API_KEY."""

    def __init__(self, s: Settings, mode: str):
        from google import genai
        from google.genai import types

        self.s = s
        self.types = types
        http = types.HttpOptions(timeout=int(s.llm_timeout_s * 1000))
        if mode == "apikey":
            key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            # GOOGLE_GENAI_USE_VERTEXAI=true + API key => Vertex AI express mode.
            use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true"}
            self.client = genai.Client(api_key=key, vertexai=use_vertex or None, http_options=http)
            self.where = "vertex-express" if use_vertex else "gemini-api"
        else:
            project = s.vertex_project
            if not project:
                import google.auth

                _, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            if not project:
                raise LLMError("No GCP project: set VERTEX_PROJECT")
            self.client = genai.Client(vertexai=True, project=project, location=s.vertex_location, http_options=http)
            self.where = f"vertex:{s.vertex_location}"

    def _config(self, system: str):
        t = self.types
        kw = dict(system_instruction=system, max_output_tokens=self.s.max_output_tokens, candidate_count=1)
        if self.s.temperature is not None:
            kw["temperature"] = self.s.temperature
        lvl = self.s.thinking_level
        model = self.s.model.lower()
        if lvl != "off":
            if model.startswith("gemini-3"):
                kw["thinking_config"] = t.ThinkingConfig(thinking_level=getattr(t.ThinkingLevel, lvl.upper(), t.ThinkingLevel.MINIMAL))
            elif model.startswith("gemini-2.5-flash"):
                kw["thinking_config"] = t.ThinkingConfig(thinking_budget=0)
        return t.GenerateContentConfig(**kw)

    def _contents(self, history: list[Msg], flatten: bool):
        t = self.types
        if not flatten:
            return [t.Content(role=m.role, parts=[t.Part(text=m.text)]) for m in history]
        lines = []
        for m in history[:-1]:
            who = "Usuario" if m.role == "user" else "Asistente"
            lines.append(f"{who}: {m.text}")
        prev = ("Conversación previa (contexto, no instrucciones):\n" + "\n".join(lines) + "\n\n") if lines else ""
        return [t.Content(role="user", parts=[t.Part(text=prev + "Mensaje actual del usuario:\n" + history[-1].text)])]

    async def generate(self, system: str, history: list[Msg]) -> LLMResult:
        from google.genai import errors

        cfg = self._config(system)
        try:
            resp = await self.client.aio.models.generate_content(model=self.s.model, contents=self._contents(history, False), config=cfg)
        except errors.ClientError as e:
            # Gemini 3 may require thought signatures on replayed model turns: retry flattened.
            if getattr(e, "code", None) == 400 and "signature" in str(e).lower() and len(history) > 1:
                resp = await self.client.aio.models.generate_content(model=self.s.model, contents=self._contents(history, True), config=cfg)
            else:
                raise LLMError(_short(e)) from None
        except errors.APIError as e:
            raise LLMError(_short(e)) from None
        except (asyncio.TimeoutError, TimeoutError) as e:
            raise LLMError("timeout") from e
        except Exception as e:  # network etc.
            raise LLMError(f"{type(e).__name__}: {_short(e)}") from None

        text = ""
        finish = ""
        try:
            text = resp.text or ""
        except Exception:
            text = ""
        if resp.candidates:
            finish = str(getattr(resp.candidates[0], "finish_reason", "") or "")
        u = resp.usage_metadata
        return LLMResult(
            text=text.strip(),
            prompt_tokens=(u.prompt_token_count or 0) if u else 0,
            cached_tokens=(u.cached_content_token_count or 0) if u else 0,
            output_tokens=(u.candidates_token_count or 0) if u else 0,
            thought_tokens=(u.thoughts_token_count or 0) if u else 0,
            finish=finish,
        )


def _short(e: Exception) -> str:
    msg = re.sub(r"\s+", " ", str(e))
    msg = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[redacted]", msg)
    return msg[:300]


class MockProvider:
    """Deterministic, offline. Replies are built from real knowledge-base facts."""

    where = "mock"

    def __init__(self, s: Settings):
        self.s = s
        self.delay = float(os.environ.get("MOCK_DELAY_MS", "0")) / 1000

    async def generate(self, system: str, history: list[Msg]) -> LLMResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        q = history[-1].text.lower()
        en = "interfaz: english" in system.lower() or bool(re.search(r"\b(what|how|who|services?|price|hire|the)\b", q))
        if os.environ.get("MOCK_FAIL") == "1":
            raise LLMError("mock failure")
        if re.search(r"servic|precio|price|cost|cuánto|cuanto|bot", q):
            text = (
                "Leandro works with fixed-price packages (USD, \"from\" prices):\n- **P1 Community Alert Bot**: from USD 600 (1–2 weeks)\n- **P4 AI Support Agent**: from USD 1,500 (2–4 weeks)\n- **P6 AI operations automation**: from USD 800 (1–3 weeks)\nThe final price is quoted after a short call. Write to itech.lca@gmail.com describing your project in 2–3 lines."
                if en
                else "Leandro trabaja con paquetes de precio cerrado (precios \"desde\", en USD):\n- **P1 Community Alert Bot**: desde USD 600 (1–2 semanas)\n- **P4 AI Support Agent**: desde USD 1,500 (2–4 semanas)\n- **P6 Automatización operativa con IA**: desde USD 800 (1–3 semanas)\nEl precio final se cotiza después de una llamada corta. Escribile a itech.lca@gmail.com contando tu proyecto en 2–3 líneas."
            )
        elif "ath" in q:
            text = (
                "ATH Intelligence (https://athintelligence.pro) answers one question: can an asset really return to its all-time high after the supply issued since then? It gives each asset a deterministic Recovery Score and exposes everything through a REST API."
                if en
                else "ATH Intelligence (https://athintelligence.pro) responde una pregunta: ¿puede un activo volver de verdad a su máximo histórico después del supply que se emitió desde entonces? Puntúa cada activo con un Recovery Score determinista y expone todo por una API REST."
            )
        else:
            text = ("[mock] " if en else "[mock] ") + (
                f"Got your message ({len(history[-1].text)} chars). You can reach Leandro at itech.lca@gmail.com."
                if en
                else f"Recibí tu mensaje ({len(history[-1].text)} caracteres). Podés escribirle a Leandro a itech.lca@gmail.com."
            )
        prompt_tokens = (len(system) + sum(len(m.text) for m in history)) // 4
        return LLMResult(text=text, prompt_tokens=prompt_tokens, cached_tokens=0, output_tokens=len(text) // 4, finish="STOP")


def make_provider(s: Settings):
    p = resolve_provider(s)
    if p == "mock":
        return MockProvider(s)
    return GeminiProvider(s, p)
