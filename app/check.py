"""Minimal real call to the configured model + diagnosis with exact fix commands.

    python -m app.check [--env-file /etc/lcaitech-assistant.env]

Streams a tiny answer from the primary and the fallback target and prints time to
first token and total. Exit 0 = at least one answered. Never prints secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import urllib.request

MD = "http://metadata.google.internal/computeMetadata/v1/"


_MD_OK = [True]


def metadata(path: str) -> str:
    """GCE metadata server (only reachable from inside the VM)."""
    if not _MD_OK[0]:
        return ""
    try:
        req = urllib.request.Request(MD + path, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.read().decode().strip()
    except Exception:
        _MD_OK[0] = False
        return ""


def load_env_file(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def diagnose(err: str, provider: str, model: str, location: str) -> str:
    project = os.environ.get("VERTEX_PROJECT") or metadata("project/project-id") or "TU_PROYECTO"
    sa = metadata("instance/service-accounts/default/email") or "SERVICE_ACCOUNT_DE_LA_VM"
    vm = metadata("instance/name") or "conectivity-server"
    zone = (metadata("instance/zone").rsplit("/", 1)[-1]) or "us-central1-a"
    e = err.lower()
    out = []
    if provider == "apikey":
        if "api key not valid" in e or "api_key_invalid" in e:
            out.append("La API key es inválida. Generá una nueva y volvé a correr el instalador con --api-key.")
        elif "not found" in e or "404" in e:
            out.append(f"El modelo '{model}' no está disponible con esta key. Probá MODEL=gemini-3.1-flash-lite o revisá el nombre.")
        else:
            out.append("Revisá la key, la facturación del proyecto de la key y el nombre del modelo.")
        return "\n".join(out)
    if "default credentials" in e or "defaultcredentialserror" in e or "no gcp project" in e:
        out.append("No hay credenciales ADC. En la VM de GCP vienen de la cuenta de servicio adjunta a la VM:")
        out.append("  - Verificá que la VM tenga una cuenta de servicio (Compute Engine > VM > Editar > Identidad y acceso a la API)")
        out.append(f"  - O seteá VERTEX_PROJECT={project} en /etc/lcaitech-assistant.env si falta el proyecto")
    elif "scope" in e:
        out.append("La VM no tiene el scope 'cloud-platform'. Desde Cloud Shell (NO desde la VM; la VM se reinicia):")
        out.append(f"  gcloud compute instances stop {vm} --zone {zone} --project {project}")
        out.append(f"  gcloud compute instances set-service-account {vm} --zone {zone} --project {project} \\\n      --service-account {sa} --scopes cloud-platform")
        out.append(f"  gcloud compute instances start {vm} --zone {zone} --project {project}")
    elif "service_disabled" in e or "has not been used" in e or "is disabled" in e:
        out.append("La API de Vertex AI no está habilitada. Desde Cloud Shell:")
        out.append(f"  gcloud services enable aiplatform.googleapis.com --project {project}")
    elif "permission" in e or "403" in e:
        out.append("La cuenta de servicio de la VM no tiene permiso para Vertex AI. Desde Cloud Shell:")
        out.append(f"  gcloud projects add-iam-policy-binding {project} \\\n      --member=serviceAccount:{sa} --role=roles/aiplatform.user")
        out.append("  (si recién lo agregaste, esperá 1–2 minutos y reintentá)")
    elif "not found" in e or "404" in e:
        out.append(f"El modelo '{model}' no existe en la ubicación '{location}'. Los Gemini 3.x Flash / Flash-Lite GA están en 'global', 'us' y 'eu' (no en us-central1).")
        out.append("  Revisá VERTEX_LOCATION=global y MODEL en /etc/lcaitech-assistant.env")
    elif "billing" in e:
        out.append(f"El proyecto {project} no tiene facturación activa (los créditos necesitan una cuenta de facturación vinculada).")
    elif "resource_exhausted" in e or "429" in e:
        out.append("Cuota/429 temporal de Vertex. Esperá unos minutos y reintentá.")
    else:
        out.append("Error no reconocido. Checklist (desde Cloud Shell):")
        out.append(f"  gcloud services enable aiplatform.googleapis.com --project {project}")
        out.append(f"  gcloud projects add-iam-policy-binding {project} --member=serviceAccount:{sa} --role=roles/aiplatform.user")
        out.append(f"  gcloud compute instances describe {vm} --zone {zone} --project {project} --format='value(serviceAccounts[].scopes)'")
    out.append("Alternativa sin Vertex/ADC: sudo bash /opt/lcaitech-assistant/deploy/install_vm.sh --api-key")
    return "\n".join(out)


async def _probe(tg, system, history) -> tuple[str, float, float, str]:
    """Stream one short answer; returns (status, ttft_s, total_s, text_or_error)."""
    import time

    from .llm import AttemptError

    t0 = time.monotonic()
    ttft, parts = 0.0, []
    try:
        async def consume():
            nonlocal ttft
            async for text, _ in tg.stream(system, history, "es"):
                if text and not ttft:
                    ttft = time.monotonic() - t0
                parts.append(text)

        await asyncio.wait_for(consume(), timeout=30)
    except AttemptError as e:
        return "error", ttft, time.monotonic() - t0, f"{e.code} {e.message}"
    except asyncio.TimeoutError:
        return "error", ttft, time.monotonic() - t0, "timeout 30s"
    return "ok", ttft, time.monotonic() - t0, "".join(parts).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    from .config import load_settings
    from .guard import Msg
    from .llm import make_targets, resolve_provider

    s = load_settings()
    s.max_output_tokens = 256
    s.explicit_cache = False
    provider = resolve_provider(s)
    print(f"Probando el modelo principal y el de respaldo ({provider})…")
    if provider == "vertex":
        scopes = metadata("instance/service-accounts/default/scopes")
        if scopes and "cloud-platform" not in scopes:
            print("✖ La VM no tiene el scope cloud-platform.")
            print(diagnose("scope", provider, s.model, s.vertex_location))
            return 2
    try:
        targets = make_targets(s)
    except Exception as e:
        print(f"✖ Falló la inicialización: {type(e).__name__}: {str(e)[:200]}")
        print(diagnose(str(e), provider, s.model, s.vertex_location))
        return 1
    system = "Respond with the single word OK."
    results = []
    for i, tg in enumerate(targets):
        st, ttft, total, info = asyncio.run(_probe(tg, system, [Msg("user", "ping")]))
        role = "principal" if i == 0 else "respaldo"
        if st == "ok":
            print(f"✔ {role} {tg.label}: primer texto {ttft:.2f} s · total {total:.2f} s · respuesta {info[:20]!r}")
        else:
            print(f"✖ {role} {tg.label}: {info[:300]}")
            print(diagnose(info, provider, getattr(tg, 'model', s.model), getattr(tg, 'location', s.vertex_location)))
        results.append(st == "ok")
    if results and results[0]:
        return 0
    if any(results):
        print("⚠ El principal falló pero el respaldo responde: el asistente funciona, revisá MODEL/VERTEX_LOCATION.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
