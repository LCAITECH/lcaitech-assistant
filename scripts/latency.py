"""Measure real Vertex latency per model/location FROM THE VM and pick primary + fallback.

    cd /opt/lcaitech-assistant
    sudo .venv/bin/python scripts/latency.py                       # measure everything, recommend
    sudo .venv/bin/python scripts/latency.py --apply               # + write MODEL/VERTEX_LOCATION/FALLBACK_* and restart
    sudo .venv/bin/python scripts/latency.py --fallback-only --apply   # keep the primary, pick the fastest Flash-Lite fallback

Uses the real system prompt and a realistic question, streaming, same thinking settings as
the service. Per candidate: 1 warm-up + N measured runs. Each run is cut if there is no first
text within --ttft-timeout s (a fallback that slow is useless: the service budget is 12 s);
after 2 consecutive failures the candidate is skipped. Progress is printed line by line.

Primary = most capable GA model (3.8 Flash > 3.5 Flash > 3.5 Flash-Lite > 3.1 Flash-Lite)
with median TTFT < 2 s and median total < 5 s. Fallback = fastest Flash-Lite (median TTFT,
then worst TTFT), excluding the primary, that never exceeded the cut; if none is fast enough
the fallback is left unchanged. --apply backs up the env file before changing it.
Never prints credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PRIMARY_CANDIDATES = [  # (model, location, capability rank)
    ("gemini-3.8-flash", "global", 4), ("gemini-3.8-flash", "us", 4),
    ("gemini-3.5-flash", "global", 3), ("gemini-3.5-flash", "us", 3),
]
LITE_CANDIDATES = [
    ("gemini-3.1-flash-lite", "global", 1), ("gemini-3.5-flash-lite", "global", 2),
    ("gemini-3.1-flash-lite", "us", 1), ("gemini-3.5-flash-lite", "us", 2),
    ("gemini-3.1-flash-lite", "eu", 1), ("gemini-3.5-flash-lite", "eu", 2),
]
QUESTIONS = {
    "es": "Tengo un exchange chico y quiero un bot de Telegram con alertas de precio y un panel para mi comunidad. ¿Qué me recomendás y cómo seguimos?",
    "en": "I run a small crypto community and want a Telegram bot with price alerts. What would you suggest and how do we start?",
}
TTFT_TARGET, TOTAL_TARGET = 2.0, 5.0
RESULTS: list[dict] = []  # filled as we go, so an interruption can still print a table


def say(*a) -> None:
    print(*a, flush=True)


class Interrupted(Exception):
    pass


def _on_signal(signum, _frame):
    raise Interrupted(signal.Signals(signum).name)


async def one(tg, system, q, lang, ttft_timeout, total_timeout):
    """One streamed answer. Never raises: returns ok/err dict."""
    from app.guard import Msg

    t0 = time.monotonic()
    st = {"ttft": 0.0, "usage": None, "chars": 0}
    first = asyncio.Event()

    async def go():
        async for text, u in tg.stream(system, [Msg("user", q)], lang):
            if text and not st["ttft"]:
                st["ttft"] = time.monotonic() - t0
                first.set()
            st["chars"] += len(text)
            if u:
                st["usage"] = u

    task = asyncio.ensure_future(go())
    waiter = asyncio.ensure_future(first.wait())
    try:
        await asyncio.wait({task, waiter}, timeout=ttft_timeout, return_when=asyncio.FIRST_COMPLETED)
        if not first.is_set() and not task.done():
            task.cancel()
            return {"ok": False, "slow": True, "err": f"sin primer texto en {ttft_timeout:.0f} s"}
        await asyncio.wait_for(task, timeout=max(0.1, total_timeout - (time.monotonic() - t0)))
    except asyncio.TimeoutError:
        return {"ok": False, "slow": True, "err": f"respuesta incompleta a los {total_timeout:.0f} s"}
    except Exception as e:  # AttemptError (code/message) or anything else: report it, don't hide it
        code = getattr(e, "code", "")
        msg = getattr(e, "message", "") or str(e)
        return {"ok": False, "err": f"{type(e).__name__} {code} {msg}".strip()[:200]}
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()
    if not st["ttft"]:
        return {"ok": False, "err": "respuesta vacía"}
    return {"ok": True, "ttft": st["ttft"], "total": time.monotonic() - t0, "usage": st["usage"]}


async def measure(s, model, loc, system, runs, cache, ttft_timeout, total_timeout):
    from app import pricing
    from app.llm import GeminiTarget, resolve_provider

    r = {"model": model, "loc": loc, "cache": cache, "runs": runs, "ok": 0, "errors": [], "done": 0}
    s.explicit_cache = cache
    try:
        tg = GeminiTarget(s, model, loc, resolve_provider(s))
    except Exception as e:
        r["err"] = f"init {type(e).__name__}: {str(e)[:160]}"
        return r
    if cache:
        tg.maintain_cache(system)
        if tg._cache_task:
            await tg._cache_task
        if not tg.cache_ready():
            r["err"] = "no se pudo crear la caché explícita"
            return r
    oks, fails_in_row = [], 0
    for i in range(runs + 1):
        lang = "es" if i % 2 == 0 else "en"
        res = await one(tg, system, QUESTIONS[lang], lang, ttft_timeout, total_timeout)
        tag = "calentamiento" if i == 0 else f"corrida {i}"
        if res["ok"]:
            say(f"      {tag}: primer texto {res['ttft']:.2f} s · total {res['total']:.2f} s")
            fails_in_row = 0
        else:
            say(f"      {tag}: ✖ {res['err']}")
            fails_in_row += 1
            if res.get("slow"):
                r["slow"] = True
        if i > 0:
            r["done"] += 1
            if res["ok"]:
                oks.append(res)
            else:
                r["errors"].append(res["err"])
        if fails_in_row >= 2:
            say("      (2 fallas seguidas: salteo el resto de las corridas)")
            break
        await asyncio.sleep(0.4)
    if cache and tg.cache_name:
        try:
            await tg.client.aio.caches.delete(name=tg.cache_name)
        except Exception:
            pass
    r["ok"] = len(oks)
    if oks:
        r["ttft"] = statistics.median(x["ttft"] for x in oks)
        r["total"] = statistics.median(x["total"] for x in oks)
        r["ttft_max"] = max(x["ttft"] for x in oks)
        us = [x["usage"] for x in oks if x["usage"]]
        if us:
            u = us[-1]
            r["tokens"] = (u.prompt, u.cached, u.output, u.thoughts)
            r["cost"] = pricing.cost(model, loc, u.prompt, u.cached, u.output + u.thoughts)
    return r


def clean(r) -> bool:
    """Answered every measured run, never slow."""
    return "err" not in r and r.get("ok", 0) > 0 and r["ok"] == r["done"] and not r.get("slow")


def fmt(r) -> str:
    name = f"{r['model']:22s} {r['loc']:6s}{' +caché' if r.get('cache') else '       '}"
    if "err" in r:
        return f"  ✖ {name} {r['err']}"
    if not r.get("ok"):
        return f"  ✖ {name} 0/{r['done']} ok · {(r['errors'] or ['?'])[0]}"
    flag = "✔" if clean(r) and r["ttft"] < TTFT_TARGET and r["total"] < TOTAL_TARGET else "·"
    tk = r.get("tokens")
    toks = f" · in={tk[0]} cached={tk[1]} out={tk[2]} think={tk[3]}" if tk else ""
    cost = f" · US$ {r['cost']:.5f}/resp" if "cost" in r else ""
    errs = f" · {r['done'] - r['ok']} fallas" if r["ok"] < r["done"] else ""
    return (f"  {flag} {name} primer texto med {r['ttft']:.2f} s (máx {r['ttft_max']:.2f}) · "
            f"total med {r['total']:.2f} s · {r['ok']}/{r['done']} ok{errs}{toks}{cost}")


def table(results) -> None:
    say("\nResultados (✔ = cumple primer texto < 2 s y total < 5 s en todas las corridas):")
    for r in results:
        say(fmt(r))


def pick_fallback(results, primary_key, max_ttft):
    lites = [r for r in results if "lite" in r["model"] and (r["model"], r["loc"]) != primary_key and clean(r)
             and r["ttft"] < max_ttft and r["ttft_max"] < max_ttft * 1.5]
    lites.sort(key=lambda r: (r["ttft"], r["ttft_max"], r["total"]))
    return lites[0] if lites else None


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


def run(a) -> int:
    from app.check import load_env_file

    if os.path.exists(a.env_file):
        load_env_file(a.env_file)
    else:
        say(f"⚠ No existe {a.env_file}: uso solo variables de entorno.")
    from app.config import load_settings
    from app.prompt import build_system_prompt, load_knowledge

    s = load_settings()
    from app.llm import resolve_provider

    if resolve_provider(s) == "mock":
        say("Proveedor mock: no hay modelos reales para medir.")
        return 0
    s.max_output_tokens = max(s.max_output_tokens, 1024)
    system = build_system_prompt(load_knowledge(s.knowledge_dir))
    cands = ([] if a.fallback_only else PRIMARY_CANDIDATES) + LITE_CANDIDATES
    if a.only:
        cands = [c for c in cands if c[0] in a.only.split(",")]
    current = (s.model, s.vertex_location)
    say(f"Midiendo {len(cands)} combinaciones × {a.runs} corridas (+1 de calentamiento), prompt real ~{len(system)//4} tokens.")
    say(f"Objetivo: primer texto < {TTFT_TARGET:.0f} s y respuesta completa < {TOTAL_TARGET:.0f} s. "
        f"Corte por corrida: {a.ttft_timeout:.0f} s sin primer texto. Config actual: principal {current[0]}@{current[1]}, "
        f"respaldo {s.fallback_model}@{s.fallback_location}.")

    async def run_all():
        for i, (m, loc, _) in enumerate(cands, 1):
            say(f"\n[{i}/{len(cands)}] {m}@{loc}")
            r = await measure(s, m, loc, system, a.runs, False, a.ttft_timeout, a.total_timeout)
            RESULTS.append(r)
            say(fmt(r))
    asyncio.run(run_all())
    table(RESULTS)

    rank = {(m, l): k for m, l, k in PRIMARY_CANDIDATES + LITE_CANDIDATES}
    if a.fallback_only:
        primary = {"model": current[0], "loc": current[1]}
    else:
        good = [r for r in RESULTS if clean(r) and r["ttft"] < TTFT_TARGET and r["total"] < TOTAL_TARGET]
        if good:
            primary = sorted(good, key=lambda r: (-rank[(r["model"], r["loc"])], r["total"]))[0]
        else:
            ok = sorted([r for r in RESULTS if r.get("ok")], key=lambda r: r["total"])
            if not ok:
                say("\n✖ Ningún modelo respondió. Corré: sudo .venv/bin/python -m app.check --env-file " + a.env_file)
                return 1
            primary = ok[0]
            say("\n⚠ Ninguna combinación cumplió el objetivo; elijo la de menor tiempo total.")
    fallback = pick_fallback(RESULTS, (primary["model"], primary["loc"]), min(s.first_token_timeout_s, a.ttft_timeout))

    if not a.fallback_only and not a.no_cache_test and "ttft" in primary:
        say(f"\nComparación con caché explícita del prompt (principal {primary['model']}@{primary['loc']}):")
        rc = asyncio.run(measure(s, primary["model"], primary["loc"], system, a.runs, True, a.ttft_timeout, a.total_timeout))
        say(fmt(rc))
        if rc.get("ok"):
            say(f"  → primer texto {rc['ttft'] - primary['ttft']:+.2f} s · costo/resp {rc.get('cost', 0):.5f} vs "
                f"{primary.get('cost', 0):.5f} US$ (+ US$ 1 por 1M tokens·hora de almacenamiento)")

    p_txt = f"{primary['model']}@{primary['loc']}" + (f" (primer texto {primary['ttft']:.2f} s, total {primary['total']:.2f} s)" if "ttft" in primary else " (actual, sin cambios)")
    if fallback:
        f_txt = f"{fallback['model']}@{fallback['loc']} (primer texto {fallback['ttft']:.2f} s, máx {fallback['ttft_max']:.2f} s)"
    else:
        f_txt = f"sin cambios ({s.fallback_model}@{s.fallback_location}): ningún Flash-Lite respondió rápido y estable"
    say(f"\nRecomendación: principal {p_txt}; respaldo {f_txt}")
    if not a.apply:
        say("Para aplicarlo: agregá --apply")
        return 0
    kv = {} if a.fallback_only else {"MODEL": primary["model"], "VERTEX_LOCATION": primary["loc"]}
    if fallback:
        kv.update(FALLBACK_MODEL=fallback["model"], FALLBACK_LOCATION=fallback["loc"])
    if not kv:
        say("Nada para aplicar.")
        return 0
    apply_env(a.env_file, kv)
    say(f"Escrito en {a.env_file} (backup: {a.env_file}.bak-latency): " + ", ".join(f"{k}={v}" for k, v in kv.items()))
    if not a.no_restart:
        rc = subprocess.run(["systemctl", "restart", a.service], check=False).returncode
        say(f"Servicio {a.service} reiniciado." if rc == 0 else f"⚠ systemctl restart devolvió {rc}")
    return 0


def main() -> int:
    try:  # line-buffered even when piped (ssh --command, nohup, | tee)
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    faulthandler.enable(all_threads=True)  # a hard crash prints a stack instead of dying silently
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Mide latencia real de Vertex por modelo y región")
    ap.add_argument("--env-file", default="/etc/lcaitech-assistant.env")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--ttft-timeout", type=float, default=8.0, help="corte por corrida sin primer texto (s)")
    ap.add_argument("--total-timeout", type=float, default=20.0, help="corte por corrida para la respuesta completa (s)")
    ap.add_argument("--fallback-only", action="store_true", help="medir solo Flash-Lite y elegir el respaldo")
    ap.add_argument("--no-cache-test", action="store_true", help="no comparar con caché explícita")
    ap.add_argument("--only", help="lista de modelos separada por comas")
    ap.add_argument("--apply", action="store_true", help="escribir la elección en el env file")
    ap.add_argument("--no-restart", action="store_true", help="con --apply, no reiniciar el servicio")
    ap.add_argument("--service", default="lcaitech-assistant")
    a = ap.parse_args()
    t0 = time.monotonic()
    try:
        return run(a)
    except (Interrupted, KeyboardInterrupt) as e:
        say(f"\n✖ Interrumpido ({e or 'Ctrl+C'}) a los {time.monotonic() - t0:.0f} s. Resultados parciales:")
        table(RESULTS)
        return 130
    except SystemExit as e:
        say(f"\n✖ Salida anticipada (SystemExit {e.code}) a los {time.monotonic() - t0:.0f} s.")
        traceback.print_exc(file=sys.stdout)
        table(RESULTS)
        return e.code if isinstance(e.code, int) and e.code else 1  # an early exit is never "success"
    except BaseException:
        say(f"\n✖ Error inesperado a los {time.monotonic() - t0:.0f} s:")
        traceback.print_exc(file=sys.stdout)
        table(RESULTS)
        return 2
    finally:
        say(f"(latency.py terminó en {time.monotonic() - t0:.0f} s)")


if __name__ == "__main__":
    sys.exit(main())
