"""Router: fallback, hedging, retries, budget and cost by the model that answered."""
import asyncio
import time

import pytest

from app_testing import SpyTarget


@pytest.fixture
def S(monkeypatch):
    for k, v in {"FIRST_TOKEN_TIMEOUT_S": "0.6", "HEDGE_AFTER_S": "0.25", "TOTAL_BUDGET_S": "1.5",
                 "STREAM_IDLE_TIMEOUT_S": "0.5", "MAX_RETRIES": "2"}.items():
        monkeypatch.setenv(k, v)
    from app.config import load_settings

    return load_settings()


def run(S, *targets):
    from app.guard import Msg
    from app.llm import LLMError, Outcome, Router

    out, events = Outcome(), []

    async def go():
        async for ev in Router(S, list(targets)).run("SYS", [Msg("user", "hola")], "es", out):
            events.append(ev)

    t0 = time.monotonic()
    try:
        asyncio.run(go())
        ok = True
    except LLMError:
        ok = False
    return ok, out, events, time.monotonic() - t0


def test_primary_answers(S):
    p, f = SpyTarget("p", reply="uno dos tres cuatro cinco"), SpyTarget("f")
    ok, out, ev, _ = run(S, p, f)
    assert ok and out.target == "p" and "".join(t for k, t in ev if k == "delta") == "uno dos tres cuatro cinco"
    assert f.calls == 0 and len([e for e in ev if e[0] == "delta"]) >= 2  # really streamed in chunks


@pytest.mark.parametrize("code", [429, 499, 500, 503, 504])
def test_retriable_error_falls_back_immediately(S, code):
    p, f = SpyTarget("p", fail_code=code), SpyTarget("f", reply="ok")
    ok, out, _, dt = run(S, p, f)
    assert ok and out.target == "f" and out.attempts[0][:2] == ("p", code) and dt < 0.2


def test_non_retriable_error_skips_target(S):
    p, f = SpyTarget("p", fail_code=404), SpyTarget("f", reply="ok", fail_code=None)
    ok, out, _, _ = run(S, p, f)
    assert ok and out.target == "f" and p.calls == 1


def test_slow_primary_is_hedged(S):
    p, f = SpyTarget("p", first_delay_s=5), SpyTarget("f", reply="rápido")
    ok, out, _, dt = run(S, p, f)
    assert ok and out.target == "f" and 0.2 <= out.ttft_ms / 1000 < 0.45 and dt < 0.6


def test_hedge_disabled_waits_for_first_token_timeout(S):
    S.hedge_after_s = 0
    p, f = SpyTarget("p", first_delay_s=5), SpyTarget("f", reply="ok")
    ok, out, _, _ = run(S, p, f)
    assert ok and out.target == "f" and out.attempts[0][0] == "p" and out.attempts[0][2] >= 550


def test_retries_are_capped_and_backoff_applies(S):
    p, f = SpyTarget("p", fail_code=503), SpyTarget("f", fail_code=429)
    ok, out, _, dt = run(S, p, f)
    assert not ok and len(out.attempts) == 3  # 1 + MAX_RETRIES
    assert [a[0] for a in out.attempts] == ["p", "f", "p"] and dt >= 0.3  # backoff before reusing p


def test_everything_hangs_ends_within_budget(S):
    ok, out, _, dt = run(S, SpyTarget("p", first_delay_s=10), SpyTarget("f", first_delay_s=10))
    assert not ok and dt < S.total_budget_s + 0.3


def test_single_target_retries_same_target(S):
    class Flaky(SpyTarget):
        async def stream(self, system, history, lang, flatten=False):
            self.fail_code = 503 if self.calls == 0 else None
            async for item in super().stream(system, history, lang, flatten):
                yield item

    t = Flaky("only", reply="ok")
    ok, out, _, _ = run(S, t)
    assert ok and t.calls == 2 and [a[1] for a in out.attempts] == [503, 200]


def test_idle_stream_is_cut(S):
    class Stall(SpyTarget):
        async def stream(self, system, history, lang, flatten=False):
            yield "Primera parte", None
            await asyncio.sleep(5)
            yield "nunca", None

    ok, out, ev, dt = run(S, Stall("p"))
    assert ok and out.truncated and ev[-1] == ("delta", " …") and dt < 1.2


def test_cost_uses_model_that_answered(S):
    from app.llm import MockTarget

    class Priced(MockTarget):
        pass

    lite = Priced("lite", reply="ok", model="gemini-3.1-flash-lite", location="us")
    flash = Priced("flash", fail_code=503, model="gemini-3.8-flash", location="global")
    ok, out, _, _ = run(S, flash, lite)
    assert ok and out.model == "gemini-3.1-flash-lite" and out.location == "us"
    from app import pricing

    assert out.cost == pytest.approx(pricing.cost("gemini-3.1-flash-lite", "us", out.usage.prompt, 0, out.usage.output))


def test_leak_mid_stream_is_replaced(S):
    from app.prompt import CANARY

    ok, out, ev, _ = run(S, SpyTarget("p", reply=f"todo bien hasta acá y ahora {CANARY} filtrado"))
    assert ok and out.leak and ev[-1] == ("replace", "") and all(CANARY not in t for k, t in ev)
