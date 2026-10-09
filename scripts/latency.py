"""Measure real Vertex latency per model/location FROM THE VM and pick primary + fallback.

    cd /opt/lcaitech-assistant
    sudo .venv/bin/python scripts/latency.py --env-file /etc/lcaitech-assistant.env          # measure only
    sudo .venv/bin/python scripts/latency.py --env-file /etc/lcaitech-assistant.env --apply  # + write env, restart

Uses the real system prompt (knowledge base) and a realistic question, streaming, with the
same thinking settings as the service. For each candidate: 1 warm-up + N measured runs;
reports median time-to-first-token (TTFT), median total, tokens and cost per answer.

Choice: primary = the most capable GA model (3.8 Flash > 3.5 Flash > 3.5 Flash-Lite >
3.1 Flash-Lite) whose median TTFT < 2 s AND median total < 5 s with no failures;
fallback = the fastest Flash-Lite, preferring a different endpoint than the primary.
Pro models are not candidates (3.1 Pro is preview and adds > 3 s of thinking).
Never prints credentials. --apply backs up the env file before changing 4 keys.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

CANDIDATES = [  # (model, location, capability rank: higher = better)
    ("gemini-3.8-flash", "global", 4), ("gemini-3.8-flash", "us", 4),
    ("gemini-3.5-flash", "global", 3), ("gemini-3.5-flash", "us", 3),
    ("gemini-3.5-flash-lite", "global", 2), ("gemini-3.5-flash-lite", "us", 2),
    ("gemini-3.1-flash-lite", "global", 1), ("gemini-3.1-flash-lite", "us", 1),
]
QUESTIONS = {
    "es": "Tengo un exchange chico y quiero un bot de Telegram con alertas de precio y un panel para mi comunidad. ¿Qué me recomendás y cómo seguimos?",
    "en": "I run a small crypto community and want a Telegram bot with price alerts. What would you suggest and how do we start?",
}
TTFT_TARGET, TOTAL_TARGET = 2.0, 5.0


async def one(tg, system, q, lang):
    from app.guard import Msg
    from app.llm import AttemptError

    t0 = time.monotonic()
    ttft, usage, n = 0.0, None, 0
    try:
        async def go():
            nonlocal ttft, usage, n
            async for text, u in tg.stream(system, [Msg("user", q)], lang):
                if text and not ttft:
                    ttft = time.monotonic() - t0
                n += len(text)
                if u:
                    usage = u
        await asyncio.wait_for(go(), timeout=30)
    except AttemptError as e:
        return {"ok": False, "err": f"{e.code} {e.message[:120]}"}
    except asyncio.TimeoutError:
        return {"ok": False, "err": "timeout 30 s"}
    return {"ok": True, "ttft": ttft, "total": time.monotonic() - t0, "chars": n, "usage": usage}


async def measure(s, model, loc, system, runs, cache):
    from app import pricing
    from app.llm import GeminiTarget, resolve_provider

    s.explicit_cache = cache
    try:
        tg = GeminiTarget(s, model, loc, resolve_provider(s))
    except Exception as e:
        return {"model": model, "loc": loc, "err": f"init: {type(e).__name__}"}
    if cache:
        tg.maintain_cache(system)
        if tg._cache_task:
            await tg._cache_task
        if not tg.cache_ready():
            return {"model": model, "loc": loc, "err": "cache create failed"}
    res = []
    for i in range(runs + 1):
        lang = "es" if i % 2 == 0 else "en"
        r = await one(tg, system, QUESTIONS[lang], lang)
        if i > 0:  # first run = warm-up (TLS, token)
            res.append(r)
        await asyncio.sleep(0.5)
    if cache and tg.cache_name:
        try:
            await tg.client.aio.caches.delete(name=tg.cache_name)
        except Exception:
            pass
    ok = [r for r in res if r["ok"]]
    out = {"model": model, "loc": loc, "cache": cache, "ok": len(ok), "runs": runs,
           "errors": [r["err"] for r in res if not r["ok"]]}
    if ok:
        out["ttft"] = statistics.median(r["ttft"] for r in ok)
        out["total"] = statistics.median(r["total"] for r in ok)
        out["ttft_max"] = max(r["ttft"] for r in ok)
        us = [r["usage"] for r in ok if r["usage"]]
        if us:
            u = us[-1]
            out["tokens"] = (u.prompt, u.cached, u.output, u.thoughts)
            out["cost"] = pricing.cost(model, loc, u.prompt, u.cached, u.output + u.thoughts)
    return out


def fmt(r):
    if "err" in r:
        return f"  {r['model']:24s} {r['loc']:7s} ✖ {r['err']}"
    if not r["ok"]:
        return f"  {r['model']:24s} {r['loc']:7s} ✖ 0/{r['runs']} ok: {r['errors'][:1]}"
    tk = r.get("tokens")
    toks = f"in={tk[0]} cached={tk[1]} out={tk[2]} think={tk[3]}" if tk else ""
    cost = f"US$ {r['cost']:.5f}/resp" if "cost" in r else ""
    flag = "✔" if r["ttft"] < TTFT_TARGET and r["total"] < TOTAL_TARGET and r["ok"] == r["runs"] else "·"
    return (f"  {flag} {r['model']:24s} {r['loc']:7s} {'cache' if r['cache'] else '     '} "
            f"TTFT med {r['ttft']:.2f}s (máx {r['ttft_max']:.2f}s) · total med {r['total']:.2f}s · {r['ok']}/{r['runs']} ok · {toks} · {cost}")


def apply_env(path, kv):
    shutil.copy2(path, path + ".bak-latency")
    lines = open(path, encoding="utf-8").read().splitlines()
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in kv and not line.lstrip().startswith("#"):
            lines[i] = f"{k}={kv[k]}"
            seen.add(k)
    lines += [f"{k}={v}" for k, v in kv.items() if k not in seen]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default="/etc/lcaitech-assistant.env")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--no-cache-test", action="store_true", help="skip the explicit-cache comparison")
    ap.add_argument("--only", help="comma list of model names to test")
    ap.add_argument("--apply", action="store_true", help="write MODEL/VERTEX_LOCATION/FALLBACK_* and restart")
    ap.add_argument("--service", default="lcaitech-assistant")
    a = ap.parse_args()
    from app.check import load_env_file

    if os.path.exists(a.env_file):
        load_env_file(a.env_file)
    from app.config import load_settings
    from app.prompt import build_system_prompt, load_knowledge

    s = load_settings()
    s.max_output_tokens = max(s.max_output_tokens, 1024)
    system = build_system_prompt(load_knowledge(s.knowledge_dir))
    cands = [c for c in CANDIDATES if not a.only or c[0] in a.only.split(",")]
    print(f"Midiendo {len(cands)} combinaciones × {a.runs} corridas (+1 de calentamiento), prompt real ~{len(system)//4} tokens…")
    print(f"Objetivo: primer texto < {TTFT_TARGET:.0f} s y respuesta completa < {TOTAL_TARGET:.0f} s.\n")

    async def run_all():
        rs = []
        for m, loc, _ in cands:
            r = await measure(s, m, loc, system, a.runs, cache=False)
            print(fmt(r), flush=True)
            rs.append(r)
        return rs
    results = asyncio.run(run_all())
    rank = {(m, l): k for m, l, k in cands}
    good = [r for r in results if r.get("ok") == r.get("runs") and r.get("ttft", 99) < TTFT_TARGET and r.get("total", 99) < TOTAL_TARGET]
    if not good:
        good = [r for r in results if r.get("ok")]
        print("\n⚠ Ninguna combinación cumplió el objetivo; elijo la de menor tiempo total.")
        good.sort(key=lambda r: r["total"])
        primary = good[0] if good else None
    else:
        primary = sorted(good, key=lambda r: (-rank[(r["model"], r["loc"])], r["total"]))[0]
    if not primary:
        print("\n✖ Ningún modelo respondió. Corré: sudo .venv/bin/python -m app.check --env-file " + a.env_file)
        return 1
    lites = [r for r in results if r.get("ok") and "lite" in r["model"] and r is not primary]
    lites.sort(key=lambda r: (r["loc"] == primary["loc"], r["total"]))  # different endpoint first, then fastest
    fallback = lites[0] if lites else None

    if not a.no_cache_test:
        print("\nComparación con caché explícita del prompt de sistema (principal):")
        rc = asyncio.run(measure(s, primary["model"], primary["loc"], system, a.runs, cache=True))
        print(fmt(rc))
        if rc.get("ok") and "ttft" in rc:
            print(f"  → diferencia TTFT: {rc['ttft'] - primary['ttft']:+.2f} s · costo/resp: "
                  f"{rc.get('cost', 0):.5f} vs {primary.get('cost', 0):.5f} US$ (más US$ 1 por 1M tokens·hora de almacenamiento)")

    print(f"\nRecomendación: principal {primary['model']}@{primary['loc']} "
          f"(TTFT {primary['ttft']:.2f}s, total {primary['total']:.2f}s)"
          + (f"; respaldo {fallback['model']}@{fallback['loc']} (TTFT {fallback['ttft']:.2f}s, total {fallback['total']:.2f}s)" if fallback else ""))
    if a.apply:
        kv = {"MODEL": primary["model"], "VERTEX_LOCATION": primary["loc"]}
        if fallback:
            kv.update(FALLBACK_MODEL=fallback["model"], FALLBACK_LOCATION=fallback["loc"])
        apply_env(a.env_file, kv)
        print(f"Escrito en {a.env_file} (backup: {a.env_file}.bak-latency): " + ", ".join(f"{k}={v}" for k, v in kv.items()))
        subprocess.run(["systemctl", "restart", a.service], check=False)
        print(f"Servicio {a.service} reiniciado.")
    else:
        print("Para aplicarlo: agregá --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
