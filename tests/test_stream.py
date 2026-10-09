"""/chat/stream SSE contract."""
import time

from conftest import sse, set_targets

from app_testing import SpyTarget


def test_faq_is_instant_over_sse(client):
    t0 = time.monotonic()
    r, ev = sse(client, "¿Qué servicios ofrece Leandro?")
    dt = time.monotonic() - t0
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert [e for e, _ in ev] == ["meta", "delta", "done"]
    assert ev[0][1]["source"] == "faq" and "USD 600" in ev[1][1]["t"] and dt < 0.5


def test_llm_streams_meta_deltas_done(factory):
    c, main = factory()
    set_targets(main, SpyTarget("m@x", reply="una respuesta con varias palabras para partir en chunks"))
    r, ev = sse(c, "Contame de su experiencia con exchanges")
    kinds = [e for e, _ in ev]
    assert kinds[0] == "meta" and kinds[-1] == "done" and kinds.count("delta") >= 3
    assert ev[0][1] == {"source": "llm", "model": "m@x"}
    assert "".join(d["t"] for e, d in ev if e == "delta") == "una respuesta con varias palabras para partir en chunks"
    assert ev[-1][1]["ttft_ms"] <= ev[-1][1]["ms"]


def test_all_targets_fail_gives_contacts_fast(factory):
    c, main = factory(FIRST_TOKEN_TIMEOUT_S="0.4", HEDGE_AFTER_S="0.2", TOTAL_BUDGET_S="1.0")
    set_targets(main, SpyTarget("p", first_delay_s=9), SpyTarget("f", fail_code=503))
    t0 = time.monotonic()
    r, ev = sse(c, "Contame de su experiencia con exchanges")
    assert time.monotonic() - t0 < 1.5
    assert ev[-1][0] == "error" and "itech.lca@gmail.com" in ev[-1][1]["message"]


def test_language_hint_and_single_system_prompt(factory):
    c, main = factory()
    spy = set_targets(main, SpyTarget("s", reply="ok")).targets[0]
    sse(c, "Tell me about his experience with exchanges", lang="en")
    sse(c, "Contame de su experiencia con exchanges", lang="es", ip="203.0.113.9")
    assert spy.langs == ["en", "es"] and spy.systems[0] == spy.systems[1]


def test_stream_validation_errors_are_json(client):
    r, _ = sse(client, "a" * 801)
    assert r.status_code == 400 and r.json()["error"] == "message_too_long"
    r, _ = sse(client, "hola", origin="https://evil.example")
    assert r.status_code == 403
