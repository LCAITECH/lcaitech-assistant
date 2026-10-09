"""GeminiTarget with a fake streaming SDK transport (no network, no credentials)."""
import asyncio
from types import SimpleNamespace

import pytest


def _target(monkeypatch, model="gemini-3.8-flash", location="global", **env):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests-only")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import load_settings
    from app.llm import GeminiTarget

    return GeminiTarget(load_settings(), model, location, "apikey")


def _chunk(text, usage=None):
    return SimpleNamespace(text=text, usage_metadata=usage)


def _usage(p=6000, c=5500, o=40, t=12):
    return SimpleNamespace(prompt_token_count=p, cached_content_token_count=c, candidates_token_count=o, thoughts_token_count=t)


def _fake_client(chunks=None, exc=None, calls=None, fail_times=1):
    state = {"n": 0}

    async def gen(cs):
        for ch in cs:
            yield ch

    async def stream(model, contents, config):
        state["n"] += 1
        if calls is not None:
            calls.append((model, contents, config))
        if exc is not None and state["n"] <= fail_times:
            raise exc
        return gen(chunks or [_chunk("Hola "), _chunk("mundo", _usage())])

    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=stream)))


async def _collect(tg, history, lang="es"):
    out = []
    async for t, u in tg.stream("SYS", history, lang):
        out.append((t, u))
    return out


def test_thinking_floor_per_model(monkeypatch):
    from google.genai import types

    assert _target(monkeypatch).config("S", False).thinking_config.thinking_level == types.ThinkingLevel.LOW  # 3.8: no MINIMAL
    assert _target(monkeypatch, "gemini-3.7-flash").config("S", False).thinking_config.thinking_level == types.ThinkingLevel.LOW
    lite = _target(monkeypatch, "gemini-3.1-flash-lite").config("S", False)
    assert lite.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert lite.max_output_tokens == 1024 and lite.system_instruction == "S" and lite.temperature is None
    assert _target(monkeypatch, "gemini-2.5-flash-lite").config("S", False).thinking_config.thinking_budget == 0


def test_history_flattened_with_language_hint(monkeypatch):
    from app.guard import Msg

    tg = _target(monkeypatch)
    one = tg.contents([Msg("user", "hola")], "en")
    assert len(one) == 1 and one[0].parts[0].text == "hola" and "English" in one[0].parts[1].text
    many = tg.contents([Msg("user", "a"), Msg("model", "b"), Msg("user", "c")], "es")
    assert len(many) == 1 and many[0].role == "user"
    assert "Usuario: a" in many[0].parts[0].text and "Asistente: b" in many[0].parts[0].text
    assert many[0].parts[0].text.endswith("Mensaje actual del usuario:\nc") and "español" in many[0].parts[1].text


def test_stream_yields_text_and_usage(monkeypatch):
    from app.guard import Msg

    tg = _target(monkeypatch)
    calls = []
    tg.client = _fake_client(calls=calls)
    out = asyncio.run(_collect(tg, [Msg("user", "hola")]))
    assert "".join(t for t, _ in out) == "Hola mundo"
    assert out[-1][1].cached == 5500 and out[-1][1].thoughts == 12
    assert calls[0][0] == "gemini-3.8-flash"


def test_explicit_cache_used_when_ready(monkeypatch):
    import time

    from app.guard import Msg

    tg = _target(monkeypatch)
    calls = []
    tg.client = _fake_client(calls=calls)
    tg.cache_name, tg.cache_expires = "projects/p/locations/global/cachedContents/123", time.monotonic() + 3600
    asyncio.run(_collect(tg, [Msg("user", "hola")]))
    cfg = calls[0][2]
    assert cfg.cached_content.endswith("/123") and cfg.system_instruction is None
    tg.cache_expires = time.monotonic() + 60  # about to expire: don't use it
    asyncio.run(_collect(tg, [Msg("user", "hola")]))
    assert calls[1][2].cached_content is None and calls[1][2].system_instruction == "SYS"


def test_cache_creation_failure_disables_cache(monkeypatch):
    tg = _target(monkeypatch, EXPLICIT_CACHE="1")
    tg.mode = "vertex"

    async def create(model, config):
        raise RuntimeError("cache not allowed")

    tg.client = SimpleNamespace(aio=SimpleNamespace(caches=SimpleNamespace(create=create)))

    async def go():
        tg.maintain_cache("SYS")
        await tg._cache_task

    asyncio.run(go())
    assert tg.cache_name is None and tg.cache_disabled_until > 0


def test_cache_creation_success_bills_once(monkeypatch):
    tg = _target(monkeypatch, "gemini-3.1-flash-lite")
    tg.mode = "vertex"
    billed = []
    tg.on_cache_cost = billed.append

    async def create(model, config):
        assert config.system_instruction == "SYS" and config.ttl == "3600s"
        return SimpleNamespace(name="caches/1", usage_metadata=SimpleNamespace(total_token_count=6200))

    tg.client = SimpleNamespace(aio=SimpleNamespace(caches=SimpleNamespace(create=create)))

    async def go():
        tg.maintain_cache("SYS")
        await tg._cache_task

    asyncio.run(go())
    assert tg.cache_ready() and billed == [pytest.approx((6200 * 0.25 + 6200 * 1.0) / 1e6)]


def test_api_errors_mapped(monkeypatch):
    from google.genai import errors

    from app.guard import Msg
    from app.llm import AttemptError

    tg = _target(monkeypatch)
    tg.client = _fake_client(exc=errors.ServerError(504, {"error": {"code": 504, "message": "Deadline exceeded", "status": "DEADLINE_EXCEEDED"}}))
    with pytest.raises(AttemptError) as e:
        asyncio.run(_collect(tg, [Msg("user", "a")]))
    assert e.value.code == 504 and e.value.retriable
    tg.client = _fake_client(exc=errors.ClientError(403, {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}}))
    with pytest.raises(AttemptError) as e:
        asyncio.run(_collect(tg, [Msg("user", "a")]))
    assert e.value.code == 403 and not e.value.retriable


def test_thinking_level_rejected_switches_to_low(monkeypatch):
    from google.genai import errors, types

    from app.guard import Msg

    tg = _target(monkeypatch, "gemini-3.6-flash")
    calls = []
    tg.client = _fake_client(exc=errors.ClientError(400, {"error": {"code": 400, "message": "thinking_level MINIMAL is not supported", "status": "INVALID_ARGUMENT"}}), calls=calls)
    out = asyncio.run(_collect(tg, [Msg("user", "a")]))
    assert "".join(t for t, _ in out) == "Hola mundo" and len(calls) == 2
    assert calls[0][2].thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert calls[1][2].thinking_config.thinking_level == types.ThinkingLevel.LOW
