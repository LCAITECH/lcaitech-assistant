"""GeminiProvider with a fake SDK transport (no network, no credentials)."""
import asyncio
from types import SimpleNamespace

import pytest


def _provider(monkeypatch, model="gemini-3.1-flash-lite"):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests-only")
    monkeypatch.setenv("MODEL", model)
    from app.config import load_settings
    from app.llm import GeminiProvider

    return GeminiProvider(load_settings(), "apikey")


def _resp(text="hola", p=6000, c=5500, o=40, t=0):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason="STOP")],
        usage_metadata=SimpleNamespace(prompt_token_count=p, cached_content_token_count=c, candidates_token_count=o, thoughts_token_count=t),
    )


def test_config_minimal_thinking_and_limits(monkeypatch):
    from google.genai import types

    prov = _provider(monkeypatch)
    cfg = prov._config("SYS")
    assert cfg.max_output_tokens == 400
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert cfg.system_instruction == "SYS"
    assert cfg.temperature is None  # Gemini 3: keep the default temperature
    prov25 = _provider(monkeypatch, "gemini-2.5-flash-lite")
    assert prov25._config("S").thinking_config.thinking_budget == 0


def test_generate_usage_and_cost(monkeypatch):
    from app.config import load_settings
    from app.guard import Msg

    prov = _provider(monkeypatch)
    calls = []

    async def fake(model, contents, config):
        calls.append((model, contents))
        return _resp()

    prov.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake)))
    hist = [Msg("user", "hola"), Msg("model", "¡Hola!"), Msg("user", "¿servicios?")]
    res = asyncio.run(prov.generate("SYS", hist))
    assert res.text == "hola" and res.cached_tokens == 5500
    assert [c.role for c in calls[0][1]] == ["user", "model", "user"]
    # 500 uncached * 0.25 + 5500 cached * 0.025 + 40 out * 1.5  (per 1M)
    assert res.cost(load_settings()) == pytest.approx((500 * 0.25 + 5500 * 0.025 + 40 * 1.5) / 1e6)


def test_signature_error_falls_back_to_flattened_history(monkeypatch):
    from google.genai import errors

    from app.guard import Msg

    prov = _provider(monkeypatch)
    calls = []

    async def fake(model, contents, config):
        calls.append(contents)
        if len(calls) == 1:
            raise errors.ClientError(400, {"error": {"code": 400, "message": "Missing thought signature in model turn", "status": "INVALID_ARGUMENT"}})
        return _resp("ok")

    prov.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake)))
    res = asyncio.run(prov.generate("SYS", [Msg("user", "a"), Msg("model", "b"), Msg("user", "c")]))
    assert res.text == "ok" and len(calls) == 2
    flat = calls[1]
    assert len(flat) == 1 and flat[0].role == "user" and "Mensaje actual del usuario:\nc" in flat[0].parts[0].text


def test_other_api_errors_become_llmerror(monkeypatch):
    from google.genai import errors

    from app.guard import Msg
    from app.llm import LLMError

    prov = _provider(monkeypatch)

    async def fake(model, contents, config):
        raise errors.ClientError(403, {"error": {"code": 403, "message": "Permission denied on resource", "status": "PERMISSION_DENIED"}})

    prov.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake)))
    with pytest.raises(LLMError):
        asyncio.run(prov.generate("SYS", [Msg("user", "a")]))
