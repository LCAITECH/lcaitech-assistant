# LCA ITECH · Portfolio assistant

Asistente virtual (chat widget) del portfolio de Leandro Buchter / LCA ITECH — **https://portfolio.lcaitech.com**.
Backend liviano en FastAPI que responde **solo** sobre Leandro, sus servicios, proyectos y cómo contratarlo, usando **Gemini en Vertex AI** con límites de uso y de costo duros.

*English version below.*

## Qué hace

- `POST /chat/stream` (mismo cuerpo que `/chat`) → **SSE** (`text/event-stream`): `meta` (fuente y modelo), `delta` (texto a medida que llega), `replace`, `done` (`ttft_ms`, `ms`) o `error` (mensaje con contactos). Lo usa el widget.
- `POST /chat` `{"messages":[{"role":"user","content":"..."}], "lang":"es"|"en"}` → `{"reply","lang","source","model"}` (misma lógica, respuesta entera).
- `GET /health` → proveedor, modelo principal y de respaldo, `accepting`.

### Velocidad (objetivo: primer texto < 2 s, respuesta completa < 5 s)
1. **Respuestas instantáneas sin modelo** (`app/faq.py`): las preguntas sugeridas y las frecuentes (servicios, precios, bot para comunidad, ATH Intelligence, ARDC, certificados, contacto, cómo contratar, bot demo) se responden desde el servidor en milisegundos, con textos tomados de la base de conocimiento. Lo que necesita criterio (garantías, inversiones, pagos, "por qué no…", comparaciones) siempre va al modelo. El filtro anti-injection corre **antes**.
2. **Streaming** de punta a punta: el widget muestra el texto a medida que llega.
3. **Modelo principal + respaldo con corte rápido** (`app/llm.py`):
   - principal `gemini-3.8-flash` en `global` (GA, el Flash más nuevo; *thinking* en `LOW`, el mínimo que admite);
   - respaldo `gemini-3.1-flash-lite` en `us` (otro modelo y otro endpoint);
   - si el principal no dio el primer token en **2,5 s** (`HEDGE_AFTER_S`) se lanza el respaldo en paralelo y gana el primero que responda;
   - cada intento tiene **8 s** para el primer token (`FIRST_TOKEN_TIMEOUT_S`); 429/499/5xx/timeout pasan al otro modelo al instante; volver a un modelo que ya falló espera un *backoff* exponencial con *jitter*; máximo 3 intentos (`MAX_RETRIES=2`) y **12 s** en total (`TOTAL_BUDGET_S`);
   - si todo falla: mensaje con los contactos de Leandro (nunca una espera larga).
4. **Caché explícita** del *system prompt* (~6.200 tokens) en Vertex, creada en segundo plano al arrancar, TTL 1 h renovado mientras haya tráfico (`EXPLICIT_CACHE`, `CACHE_TTL_S`). Si falla, se desactiva 30 min y se sigue sin caché.
5. Historial enviado como un único turno (con el idioma de la interfaz como pista), lo que evita errores de *thought signatures* y reintentos.

`scripts/latency.py` (en la VM) mide primer token y total reales por modelo y región, compara con y sin caché, recomienda principal y respaldo, y con `--apply` los escribe en `/etc/lcaitech-assistant.env` (con backup) y reinicia el servicio.

Toda la base de conocimiento (`knowledge/*.md`, datos reales del portfolio) va en el *system prompt* (sin RAG vectorial).

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
| Tokens globales por día | 8.000.000 | `GLOBAL_TOKENS_PER_DAY` |
| **Presupuesto diario (USD estimados con `usage_metadata` y el precio del modelo que respondió)** | **1,00** | `GLOBAL_COST_USD_PER_DAY` |
| Largo del mensaje | 800 caracteres | `MAX_MSG_CHARS` |
| Historial enviado al modelo | últimos 10 mensajes | `MAX_HISTORY_MESSAGES` |
| Cuerpo HTTP | 32 KB | `MAX_BODY_BYTES` |

- CORS y chequeo de `Origin`: solo `https://portfolio.lcaitech.com` (+ localhost para desarrollo).
- Las respuestas 429 son amables, con `Retry-After`, y llevan los contactos.
- Estado en **sqlite** (`/var/lib/lcaitech-assistant/assistant.db`): los cupos diarios sobreviven a reinicios. Sin Redis.
- Los headers de IP solo se aceptan si la conexión viene de localhost/red privada (el túnel o el proxy).
- **Privacidad:** los logs no guardan el contenido de los mensajes ni IPs, solo largo, hash de IP con sal, tokens, costo y latencia.

## Costo (precios oficiales de Vertex AI, consultados el 8/10/2026)
Fuente: https://cloud.google.com/vertex-ai/generative-ai/pricing (USD por 1M tokens; el *thinking* se cobra como salida).

| Modelo | Entrada | Entrada cacheada | Salida |
|---|---|---|---|
| `gemini-3.8-flash` global, **precio introductorio hasta el 31/12/2026** | 0,75 | 0,075 | 3,75 |
| `gemini-3.8-flash` global, desde el 1/1/2027 | 1,50 | 0,15 | 7,50 |
| `gemini-3.1-flash-lite` en `us` (no global) | 0,275 | 0,0275 | 1,65 |

Almacenamiento de la caché explícita: USD 1 por 1M tokens·hora (~USD 0,006 por hora con tráfico). `app/pricing.py` aplica el precio correcto según la fecha y el modelo que respondió.

Supuesto por respuesta del modelo (estimado, a confirmar con `scripts/latency.py`): ~6.500 tokens de entrada (6.200 del prompt) y ~500 de salida + *thinking*.

| Por respuesta | Sin caché | Con caché explícita |
|---|---|---|
| 3.8 Flash (hasta 31/12/2026) | USD 0,0068 | USD 0,0026 |
| 3.8 Flash (desde 2027) | USD 0,0135 | USD 0,0051 |
| 3.1 Flash-Lite `us` (respaldo) | USD 0,0026 | USD 0,0011 |

Las respuestas instantáneas (FAQ) y los bloqueos anti-injection cuestan USD 0. Con el tope de **USD 1/día** el peor caso es **USD 30–31 por mes** (≈ 390 respuestas del modelo por día con caché, ≈ 150 sin caché). El hosting corre en la VM e2 del free tier y Cloudflare Tunnel es gratis.

## Instalación en la VM (Debian 12, systemd)

```bash
curl -fsSL https://raw.githubusercontent.com/LCAITECH/lcaitech-assistant/main/deploy/install_vm.sh -o install_assistant.sh
sudo bash install_assistant.sh                # Vertex AI con la cuenta de servicio de la VM
# o: sudo bash install_assistant.sh --api-key        (GOOGLE_API_KEY, se pide oculta)
# y: sudo bash install_assistant.sh --cloudflared    (además instala Cloudflare Tunnel)
```

El script es idempotente:
- crea el usuario `assistant`, clona en `/opt/lcaitech-assistant`, arma el venv y escribe `/etc/lcaitech-assistant.env` (root, 600);
- **prueba el modelo principal y el de respaldo con streaming** (muestra el tiempo al primer texto) y, si falla, imprime los comandos `gcloud` exactos para arreglarlo;
- al actualizar **no pisa** `/etc/lcaitech-assistant.env`: solo agrega variables nuevas con su default y migra 4 valores (`MODEL`, `MAX_OUTPUT_TOKENS`, `GLOBAL_COST_USD_PER_DAY`, `GLOBAL_TOKENS_PER_DAY`) **solo si siguen exactamente con el default viejo**, con backup previo (`--keep-config` lo evita);
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
python3 scripts/battery.py http://127.0.0.1:8080                 # en la VM: 10 legítimas + 10 fuera de tema/injection por SSE, con fuente, modelo, primer texto y total
sudo .venv/bin/python scripts/latency.py --env-file /etc/lcaitech-assistant.env [--apply]   # en la VM: latencia real por modelo/región
```

## Licencia
MIT. Ver `LICENSE`.

---

# English

Portfolio chat assistant for Leandro Buchter / LCA ITECH (https://portfolio.lcaitech.com).

**Backend**
- FastAPI + uvicorn, about 80 MB RSS.
- Gemini on Vertex AI through `google-genai` (`vertexai=True`, ADC from the VM service account). `GOOGLE_API_KEY` is supported as an alternative, and a `mock` provider covers tests.
- The full knowledge base (`knowledge/*.md`) is placed in the system prompt, cached explicitly on Vertex (1 h TTL, refreshed while there is traffic).
- **Speed:** SSE streaming (`POST /chat/stream`); instant server-side answers for the suggested and frequent questions (no model call); primary `gemini-3.8-flash` (global, thinking LOW) with fallback `gemini-3.1-flash-lite` (us); the fallback is started in parallel if the primary has no first token after 2.5 s; 8 s per attempt, 12 s total budget, then a helpful message with contacts.
- `scripts/latency.py` measures real time-to-first-token and total per model/region on the VM and can apply the fastest compliant choice.

**Guardrails**
- Scope limited to Leandro, his services, projects, experience and how to hire him.
- Polite refusals for off-topic requests, plus a prompt-injection pre-filter and an output canary check.
- No invented facts, no hourly rate, no financial advice, no promises of trading results.

**Limits**
- 10 messages/min and 50/day per IP.
- Global daily caps on requests, tokens and **estimated USD cost** (default USD 1/day, priced with the model that actually answered, so at most about USD 31/month).
- 800-character messages and a 10-message history.
- CORS and Origin restricted to the portfolio.
- State in sqlite; logs never contain message text or raw IPs.

**Deploy:** `sudo bash deploy/install_vm.sh [--api-key] [--cloudflared]` (idempotent, systemd, `MemoryMax=250M`, binds to 127.0.0.1:8080). The script checks real model access and prints the exact `gcloud` fix commands. Publish through Cloudflare Tunnel (`asistente.lcaitech.com` → `http://localhost:8080`), or use Caddy on port 443.

**Tests:** `pytest -q` runs fully offline in mock mode.

MIT licensed.
