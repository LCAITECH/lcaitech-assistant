"""scripts/latency.py: selection logic, timeouts and error reporting (no network)."""
import asyncio
import importlib.util
import os

import pytest

from app_testing import SpyTarget

_spec = importlib.util.spec_from_file_location("latency", os.path.join(os.path.dirname(__file__), "..", "scripts", "latency.py"))
latency = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(latency)


def R(model, loc, ttft, tmax=None, ok=3, done=3, slow=False):
    return {"model": model, "loc": loc, "ttft": ttft, "ttft_max": tmax or ttft, "total": ttft + 0.8,
            "ok": ok, "done": done, "errors": [], "slow": slow, "runs": 3}


def test_fallback_is_fastest_clean_flash_lite_not_the_primary():
    res = [R("gemini-3.8-flash", "global", 1.0), R("gemini-3.1-flash-lite", "us", 15.7, slow=True, ok=0),
           R("gemini-3.1-flash-lite", "global", 0.6, 0.9), R("gemini-3.5-flash-lite", "global", 0.55, 3.5),
           R("gemini-3.5-flash-lite", "us", 0.7, ok=2), R("gemini-3.1-flash-lite", "eu", 1.4)]
    fb = latency.pick_fallback(res, ("gemini-3.8-flash", "global"), 8.0)
    assert (fb["model"], fb["loc"]) == ("gemini-3.5-flash-lite", "global")  # 0.55 median, max 3.5 < 12
    fb = latency.pick_fallback(res, ("gemini-3.8-flash", "global"), 2.0)  # stricter: max must be < 3 s
    assert (fb["model"], fb["loc"]) == ("gemini-3.1-flash-lite", "global")
    fb = latency.pick_fallback(res, ("gemini-3.5-flash-lite", "global"), 8.0)  # the primary itself is never the fallback
    assert (fb["model"], fb["loc"]) == ("gemini-3.1-flash-lite", "global")


def test_no_fast_fallback_means_no_change():
    res = [R("gemini-3.1-flash-lite", "us", 15.7, slow=True, ok=0), R("gemini-3.5-flash-lite", "us", 9.0)]
    assert latency.pick_fallback(res, ("gemini-3.8-flash", "global"), 8.0) is None


def test_one_cuts_slow_first_token_and_reports_errors():
    slow = SpyTarget("slow", first_delay_s=5)
    r = asyncio.run(latency.one(slow, "SYS", "hola", "es", ttft_timeout=0.2, total_timeout=5))
    assert not r["ok"] and r["slow"] and "sin primer texto" in r["err"]
    bad = SpyTarget("bad", fail_code=429)
    r = asyncio.run(latency.one(bad, "SYS", "hola", "es", ttft_timeout=1, total_timeout=5))
    assert not r["ok"] and "429" in r["err"]
    good = SpyTarget("good", reply="uno dos tres")
    r = asyncio.run(latency.one(good, "SYS", "hola", "es", ttft_timeout=1, total_timeout=5))
    assert r["ok"] and 0 <= r["ttft"] <= r["total"]


def test_apply_env_keeps_other_keys_and_backs_up(tmp_path):
    p = tmp_path / "env"
    p.write_text("A=1\nFALLBACK_LOCATION=us\n# FALLBACK_MODEL=x\nIP_PER_DAY=40\n")
    os.chmod(p, 0o600)
    latency.apply_env(str(p), {"FALLBACK_MODEL": "gemini-3.1-flash-lite", "FALLBACK_LOCATION": "global"})
    txt = p.read_text()
    assert "FALLBACK_LOCATION=global" in txt and "FALLBACK_MODEL=gemini-3.1-flash-lite" in txt
    assert "IP_PER_DAY=40" in txt and "# FALLBACK_MODEL=x" in txt
    assert (tmp_path / "env.bak-latency").read_text().count("FALLBACK_LOCATION=us") == 1
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("phrase", ["No one from LCA ITECH will ever ask you for funds", "Nadie de LCA ITECH te va a pedir fondos"])
def test_anti_scam_notice_exists_in_both_languages(phrase):
    from app.prompt import RULES

    assert phrase in RULES and "MISMO IDIOMA" in RULES
