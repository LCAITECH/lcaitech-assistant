# LCA ITECH · Portfolio assistant

Asistente virtual (chat widget) del portfolio de Leandro Buchter / LCA ITECH — **https://portfolio.lcaitech.com**.
Backend liviano en FastAPI que responde **solo** sobre Leandro, sus servicios, proyectos y cómo contratarlo, usando **Gemini en Vertex AI** con límites de uso y de costo duros.

*English version below.*

## Qué hace

- `POST /chat` `{"messages":[{"role":"user","content":"..."}], "lang":"es"|"en"}` → `{"reply":"...","lang":"es"}`
- `GET /health` → `{"status":"ok","provider":"vertex","model":"gemini-3.1-flash-lite","accepting":true}`
- Toda la base de conocimiento (`knowledge/*.md`, datos reales del portfolio) va en el *system prompt* (sin RAG vectorial). El prefijo es idéntico en cada pedido, así que el **caché implícito** de Gemini lo cobra con 90% de descuento cuando hay hits (mínimo 4.096 tokens; el prompt tiene ~6.200).
- Modelo por defecto `gemini-3.1-flash-lite` (GA) con `thinking_level=minimal` y `max_output_tokens=400`. Se cambia por env (`MODEL`, `VERTEX_LOCATION`).
  - `gemini-2.5-flash-lite` se retira el 20/10/2026 en Vertex, por eso no es el default.
  - `gemini-3.1-flash-lite` se sirve desde `global` (o `us`/`eu`), **no** desde `us-central1`: por eso `VERTEX_LOCATION=global`.

### Guardrails
- Alcance cerrado: Leandro, LCA ITECH, servicios, proyectos, experiencia, contratación y conceptos tech/cripto relacionados. Lo demás (fútbol, política, tareas genéricas, código para terceros, consejos de inversión, precios futuros) se rechaza con amabilidad.
- No inventa: si no está en la base, lo dice y ofrece el contacto. Precios solo "desde" por paquete (sin tarifa horaria). Sin teléfono.
- Nunca promete resultados de trading; aviso de "no es asesoramiento financiero"; "nadie de LCA ITECH te va a pedir fondos".
- Anti prompt-injection: filtro previo (ES/EN) que responde sin llamar al modelo, reglas en el system prompt y un *canary* que bloquea respuestas que filtren el prompt.
- Responde en el idioma del usuario (rioplatense con "vos" / inglés).

### Límites y anti-abuso
| Límite | Default | Env |
|---|---|---|
| Por IP (CF-Connecting-IP → X-Forwarded-For → peer) | 10/min y 50/día | `IP_PER_MINUTE`, `IP_PER_DAY` |
| Pedidos globales por día | 1.000 | `GLOBAL_REQUESTS_PER_DAY` |
| Tokens globales por día | 3.000.000 | `GLOBAL_TOKENS_PER_DAY` |
| **Presupuesto diario (USD estimados con `usage_metadata`)** | **0,30** | `GLOBAL_COST_USD_PER_DAY` |
| Largo del mensaje | 800 caracteres | `MAX_MSG_CHARS` |
| Historial enviado al modelo | últimos 10 mensajes | `MAX_HISTORY_MESSAGES` |
| Cuerpo HTTP | 32 KB | `MAX_BODY_BYTES` |

- CORS y chequeo de `Origin`: solo `https://portfolio.lcaitech.com` (+ localhost para desarrollo).
- Las respuestas 429 son amables, con `Retry-After`, y llevan los contactos.
- Estado en **sqlite** (`/var/lib/lcaitech-assistant/assistant.db`): los cupos diarios sobreviven a reinicios. Sin Redis.
- Los headers de IP solo se aceptan si la conexión viene de localhost/red privada (el túnel o el proxy).
- **Privacidad:** los logs no guardan el contenido de los mensajes ni IPs, solo largo, hash de IP con sal, tokens, costo y latencia.

## Costo (precios oficiales de Vertex AI, octubre 2026)
`gemini-3.1-flash-lite`, endpoint global: USD 0,25 / 1M tokens de entrada, USD 1,50 / 1M de salida (el *thinking* se cobra como salida), USD 0,025 / 1M de entrada cacheada. Fuente: https://cloud.google.com/vertex-ai/generative-ai/pricing

Supuesto por mensaje: ~7.000 tokens de entrada (prompt ~6.200 + historial) y ~280 de salida.

| Escenario | Sin caché | Con caché implícito |
|---|---|---|
| Por mensaje | USD 0,0022 | USD 0,0008 |
| 500 mensajes/mes | ~USD 1,10 | ~USD 0,40 |
| 5.000 mensajes/mes | ~USD 10,90 | ~USD 3,90 |
| **Peor caso (tope diario de USD 0,30 todos los días)** | **≤ USD 9,30/mes** | |

Sin el tope en USD, 1.000 pedidos/día con historial completo podrían costar USD 65–95 por mes. Por eso existe `GLOBAL_COST_USD_PER_DAY`. El hosting corre en la VM e2 del free tier y Cloudflare Tunnel es gratis.

## Instalación en la VM (Debian 12, systemd)

```bash
curl -fsSL https://raw.githubusercontent.com/LCAITECH/lcaitech-assistant/main/deploy/install_vm.sh -o install_assistant.sh
sudo bash install_assistant.sh                # Vertex AI con la cuenta de servicio de la VM
# o: sudo bash install_assistant.sh --api-key        (GOOGLE_API_KEY, se pide oculta)
# y: sudo bash install_assistant.sh --cloudflared    (además instala Cloudflare Tunnel)
```

El script es idempotente:
- crea el usuario `assistant`, clona en `/opt/lcaitech-assistant`, arma el venv y escribe `/etc/lcaitech-assistant.env` (root, 600);
- **hace una llamada real mínima al modelo** y, si falla, imprime los comandos `gcloud` exactos para arreglarlo;
- instala el servicio `lcaitech-assistant` (127.0.0.1:8080, `MemoryMax=250M`, endurecido) y prueba `/health` y `/chat`.

No toca otros servicios de la VM.

### Habilitar Vertex AI para la VM (desde Cloud Shell)
```bash
PROJECT=$(gcloud config get-value project)
VM=conectivity-server; ZONE=us-central1-a
SA=$(gcloud compute instances describe $VM --zone $ZONE --format='value(serviceAccounts[0].email)')
gcloud services enable aiplatform.googleapis.com --project $PROJECT
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/aiplatform.user"
# solo si la VM no tiene el scope cloud-platform (requiere apagarla un minuto):
gcloud compute instances describe $VM --zone $ZONE --format='value(serviceAccounts[0].scopes)'
gcloud compute instances stop $VM --zone $ZONE
gcloud compute instances set-service-account $VM --zone $ZONE --service-account $SA --scopes cloud-platform
gcloud compute instances start $VM --zone $ZONE
```

### Publicar con HTTPS: Cloudflare Tunnel (recomendado)
Sin abrir puertos ni tocar el firewall:
1. En Cloudflare: **Networking → Tunnels → Create Tunnel**, ponerle un nombre (por ejemplo `conectivity-server`), elegir Debian 64-bit y copiar el token del comando `cloudflared service install <TOKEN>`.
2. En la VM: `sudo bash /opt/lcaitech-assistant/deploy/install_vm.sh --cloudflared` y pegar el token (o correr el comando que muestra Cloudflare).
3. En el túnel: **Routes → Add route → Published application**, con subdominio `asistente`, dominio `lcaitech.com` y Service URL `http://localhost:8080`. Cloudflare crea el DNS (proxied) solo.
4. Probar: `curl https://asistente.lcaitech.com/health`

### Alternativa: Caddy + puerto 443
1. Instalar Caddy y escribir en `/etc/caddy/Caddyfile`:
   ```
   asistente.lcaitech.com {
       reverse_proxy 127.0.0.1:8080
   }
   ```
2. Abrir los puertos en GCP: `gcloud compute firewall-rules create allow-https --allow tcp:80,tcp:443 --target-tags https-server` y `gcloud compute instances add-tags conectivity-server --zone us-central1-a --tags https-server`.
3. Crear un registro A `asistente` → IP pública de la VM (conviene una IP estática). Si lo dejás *proxied* en Cloudflare, usá SSL "Full (strict)".

Caddy manda `X-Forwarded-For`, que el backend usa para el límite por IP. Con Cloudflare delante, usa `CF-Connecting-IP`.

## Desarrollo y tests
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                                              # modo mock: sin red ni credenciales
LLM_PROVIDER=mock .venv/bin/uvicorn app.main:app --port 8099     # backend falso para probar el widget
python3 scripts/battery.py http://127.0.0.1:8080                 # en la VM: 10 preguntas legítimas + 10 fuera de tema/injection con el modelo real (~USD 0,05)
```

## Licencia
MIT. Ver `LICENSE`.

---

# English

Portfolio chat assistant for Leandro Buchter / LCA ITECH (https://portfolio.lcaitech.com).

**Backend**
- FastAPI + uvicorn, about 80 MB RSS.
- Gemini on Vertex AI through `google-genai` (`vertexai=True`, ADC from the VM service account). `GOOGLE_API_KEY` is supported as an alternative, and a `mock` provider covers tests.
- The full knowledge base (`knowledge/*.md`) is placed in the system prompt, so Gemini implicit caching can bill the repeated prefix at 10% of the price.
- Default model `gemini-3.1-flash-lite` on location `global`, with minimal thinking and 400 max output tokens.

**Guardrails**
- Scope limited to Leandro, his services, projects, experience and how to hire him.
- Polite refusals for off-topic requests, plus a prompt-injection pre-filter and an output canary check.
- No invented facts, no hourly rate, no financial advice, no promises of trading results.

**Limits**
- 10 messages/min and 50/day per IP.
- Global daily caps on requests, tokens and **estimated USD cost** (default USD 0.30/day, so at most about USD 9.30/month).
- 800-character messages and a 10-message history.
- CORS and Origin restricted to the portfolio.
- State in sqlite; logs never contain message text or raw IPs.

**Deploy:** `sudo bash deploy/install_vm.sh [--api-key] [--cloudflared]` (idempotent, systemd, `MemoryMax=250M`, binds to 127.0.0.1:8080). The script checks real model access and prints the exact `gcloud` fix commands. Publish through Cloudflare Tunnel (`asistente.lcaitech.com` → `http://localhost:8080`), or use Caddy on port 443.

**Tests:** `pytest -q` runs fully offline in mock mode.

MIT licensed.
