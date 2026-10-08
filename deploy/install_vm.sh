#!/usr/bin/env bash
# Instala o actualiza el asistente del portfolio de LCA ITECH en una VM Debian/Ubuntu con systemd.
#
#   sudo bash install_vm.sh                # instalar/actualizar (Vertex AI con la cuenta de servicio de la VM)
#   sudo bash install_vm.sh --api-key      # usar una GOOGLE_API_KEY en vez de Vertex/ADC (se pide oculta)
#   sudo bash install_vm.sh --vertex       # volver a Vertex AI (ADC) si antes usaste --api-key
#   sudo bash install_vm.sh --cloudflared  # además instala cloudflared (Cloudflare Tunnel) y pide el token del túnel
#
# Qué hace: git/python3-venv/curl si faltan, usuario de sistema 'assistant', código en /opt/lcaitech-assistant,
# venv, config en /etc/lcaitech-assistant.env (root, 600), servicio systemd 'lcaitech-assistant' escuchando
# SOLO en 127.0.0.1:8080 (MemoryMax=250M), prueba real del modelo y de /health.
# No toca el bot demo (lcaitech-demo-bot / usuario demobot). Los secretos se piden con `read -rs` y nunca se imprimen.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/LCAITECH/lcaitech-assistant.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/lcaitech-assistant}"
ENV_FILE="${ENV_FILE:-/etc/lcaitech-assistant.env}"
SERVICE="lcaitech-assistant"
UNIT_FILE="${UNIT_FILE:-/etc/systemd/system/${SERVICE}.service}"
APP_USER="assistant"
PORT="${PORT:-8080}"
SIMULATE="${SIMULATE:-0}"      # solo para pruebas (permite correr sin root)
SKIP_CHECK="${SKIP_CHECK:-0}"  # solo para pruebas (saltea la llamada real al modelo)
MD="http://metadata.google.internal/computeMetadata/v1"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m⚠\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✖ %s\033[0m\n' "$*" >&2; exit 1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
md() { curl -fsS -m 2 -H 'Metadata-Flavor: Google' "$MD/$1" 2>/dev/null || true; }

USE_API_KEY=0
FORCE_VERTEX=0
WITH_CLOUDFLARED=0
for arg in "$@"; do
  case "$arg" in
    --api-key) USE_API_KEY=1 ;;
    --vertex) FORCE_VERTEX=1 ;;
    --cloudflared) WITH_CLOUDFLARED=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Opción desconocida: $arg (usá --help)" ;;
  esac
done

read_secret() {  # lee sin eco desde la terminal (o stdin si no hay terminal)
  local __v=""
  if { exec 3</dev/tty; } 2>/dev/null; then
    IFS= read -rs __v <&3 || true
    exec 3<&-
  else
    IFS= read -rs __v || true
  fi
  printf '%s' "$__v"
}

# set_env KEY VALUE: escribe/reemplaza una línea en el env file (root:root 600, escritura atómica)
set_env() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  chmod 600 "$tmp"
  if [ -f "$ENV_FILE" ]; then grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true; fi
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  [ "$SIMULATE" = "1" ] || chown root:root "$tmp"
  mv -f "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}
env_has() { [ -f "$ENV_FILE" ] && grep -qE "^$1=.+" "$ENV_FILE"; }
set_default() { env_has "$1" || set_env "$1" "$2"; }

# ---------- 0. chequeos ----------
step "0/8 Chequeos"
if [ "$SIMULATE" != "1" ] && [ "$(id -u)" -ne 0 ]; then
  die "Correlo con sudo: sudo bash $0"
fi
command -v apt-get >/dev/null 2>&1 || die "Este instalador es para Debian/Ubuntu (apt-get)."
command -v systemctl >/dev/null 2>&1 || die "No encontré systemd (systemctl)."
ok "Debian/Ubuntu con systemd"
mem_mb="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
ok "memoria disponible: ${mem_mb} MB (el asistente usa ~80 MB, tope 250 MB)"
if systemctl is-active --quiet lcaitech-demo-bot 2>/dev/null; then
  ok "el bot demo (lcaitech-demo-bot) está corriendo: no se toca"
fi

# ---------- 1. paquetes ----------
step "1/8 Paquetes del sistema (git, python3-venv, curl)"
need=()
command -v git >/dev/null 2>&1 || need+=(git)
command -v curl >/dev/null 2>&1 || need+=(curl)
command -v python3 >/dev/null 2>&1 || need+=(python3)
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import ensurepip, venv' >/dev/null 2>&1; then
  need+=(python3-venv)
fi
if [ "${#need[@]}" -gt 0 ]; then
  echo "    Instalando: ${need[*]}…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates "${need[@]}" >/dev/null
  ok "Instalado: ${need[*]}"
else
  ok "ya estaban"
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Se necesita Python 3.10+ (hay $(python3 -V 2>&1))."
ok "$(python3 -V)"

# ---------- 2. usuario ----------
step "2/8 Usuario de sistema '$APP_USER'"
if id "$APP_USER" >/dev/null 2>&1; then
  ok "ya existe"
else
  useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$APP_USER"
  ok "creado (sin login, sin home)"
fi

# ---------- 3. código ----------
step "3/8 Código en $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"
  ok "actualizado a $(git -C "$APP_DIR" log -1 --format='%h %s')"
elif [ -e "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
  die "$APP_DIR existe y no es un repo git. Movelo o borralo y volvé a correr el script."
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  ok "clonado $(git -C "$APP_DIR" log -1 --format='%h %s')"
fi

# ---------- 4. venv ----------
step "4/8 Entorno Python (venv + dependencias)"
if [ ! -x "$APP_DIR/.venv/bin/pip" ]; then
  rm -rf "$APP_DIR/.venv"
  if ! python3 -m venv "$APP_DIR/.venv" >/dev/null 2>&1; then
    pyver="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3-venv "python${pyver}-venv" >/dev/null 2>&1 || apt-get install -y -qq python3-venv >/dev/null
    rm -rf "$APP_DIR/.venv"
    python3 -m venv "$APP_DIR/.venv"
  fi
fi
"$APP_DIR/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$APP_DIR/requirements.txt"
ok "dependencias instaladas"

# ---------- 5. configuración ----------
step "5/8 Configuración ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
  ( umask 077; printf '# LCA ITECH assistant (root, 600). Editá y reiniciá: sudo systemctl restart %s\n' "$SERVICE" > "$ENV_FILE" )
  [ "$SIMULATE" = "1" ] || chown root:root "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi
project="$(md project/project-id)"
sa_email="$(md instance/service-accounts/default/email)"
if [ -n "$project" ]; then ok "VM de GCP detectada: proyecto $project · cuenta de servicio ${sa_email:-ninguna}"; fi
if [ -n "$project" ]; then set_default VERTEX_PROJECT "$project"; fi
set_default VERTEX_LOCATION global
set_default MODEL gemini-3.1-flash-lite
set_default THINKING_LEVEL minimal
set_default MAX_OUTPUT_TOKENS 400
set_default ALLOWED_ORIGINS https://portfolio.lcaitech.com
set_default ALLOW_LOCALHOST 1
set_default IP_PER_MINUTE 10
set_default IP_PER_DAY 50
set_default GLOBAL_REQUESTS_PER_DAY 1000
set_default GLOBAL_TOKENS_PER_DAY 3000000
set_default GLOBAL_COST_USD_PER_DAY 0.30
set_default MAX_MSG_CHARS 800
set_default MAX_HISTORY_MESSAGES 10
set_default STATE_DB "/var/lib/${SERVICE}/assistant.db"
if [ "$USE_API_KEY" = "1" ]; then
  echo "    Pegá tu GOOGLE_API_KEY y apretá Enter (no se va a ver nada mientras pegás)."
  printf '    API key: '
  KEY="$(read_secret)"; echo
  KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
  [ -n "$KEY" ] || die "No ingresaste ninguna key."
  set_env GOOGLE_API_KEY "$KEY"
  unset KEY
  set_env LLM_PROVIDER apikey
  ok "API key guardada (no se muestra)"
elif [ "$FORCE_VERTEX" = "1" ]; then
  set_env LLM_PROVIDER vertex
else
  set_default LLM_PROVIDER vertex
fi
ok "config lista (root:root, permisos 600). Proveedor: $(sed -n 's/^LLM_PROVIDER=//p' "$ENV_FILE")"

# ---------- 6. prueba real del modelo ----------
step "6/8 Prueba del modelo (una llamada mínima)"
model_ok=0
if [ "$SKIP_CHECK" = "1" ]; then
  warn "salteada (SKIP_CHECK=1)"
elif (cd "$APP_DIR" && "$APP_DIR/.venv/bin/python" -m app.check --env-file "$ENV_FILE"); then
  model_ok=1
else
  warn "El modelo todavía no responde. Arriba están los comandos exactos para arreglarlo."
  warn "El servicio igual se instala: hasta que lo arregles, el chat muestra los contactos de Leandro."
fi

# ---------- 7. servicio ----------
step "7/8 Servicio systemd '$SERVICE' (127.0.0.1:$PORT)"
if [ "$SIMULATE" != "1" ] && command -v ss >/dev/null 2>&1 \
   && ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q . && ! systemctl is-active --quiet "$SERVICE"; then
  die "El puerto $PORT ya está en uso por otro programa. Corré: PORT=8090 sudo -E bash $0"
fi
cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=LCA ITECH portfolio assistant (FastAPI)
Documentation=https://github.com/LCAITECH/lcaitech-assistant
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/var/lib/$SERVICE
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --workers 1 --no-access-log --no-proxy-headers --timeout-keep-alive 5
Restart=always
RestartSec=5
StateDirectory=$SERVICE
StateDirectoryMode=0700
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryMax=250M
TasksMax=64

[Install]
WantedBy=multi-user.target
UNIT
chmod 644 "$UNIT_FILE"
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl restart "$SERVICE"
ok "habilitado (arranca solo con la VM) y (re)iniciado"

# ---------- 8. verificación ----------
step "8/8 Verificación"
health=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  health="$(curl -fsS -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null || true)"
  [ -n "$health" ] && break
  sleep 1
done
if [ -n "$health" ]; then ok "/health → $health"; else warn "/health no responde. Mirá: sudo journalctl -u $SERVICE -n 50"; fi
if [ -n "$health" ] && [ "$model_ok" = "1" ]; then
  code="$(curl -sS -m 40 -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/chat" \
    -H 'Origin: https://portfolio.lcaitech.com' -H 'Content-Type: application/json' \
    -d '{"lang":"es","messages":[{"role":"user","content":"¿Qué servicios ofrece Leandro?"}]}' || true)"
  if [ "$code" = "200" ]; then ok "POST /chat de prueba → 200"; else warn "POST /chat de prueba → $code (mirá el journal)"; fi
fi
if [ -f "$ENV_FILE" ] && grep -q '^GOOGLE_API_KEY=.' "$ENV_FILE" 2>/dev/null; then
  if journalctl -u "$SERVICE" -n 300 --no-pager -o cat 2>/dev/null | grep -qF -f <(sed -n 's/^GOOGLE_API_KEY=//p' "$ENV_FILE"); then
    warn "¡La API key aparece en el log! Rotala en Google Cloud."
  else
    ok "la API key no aparece en el log"
  fi
fi

# ---------- cloudflared (opcional) ----------
if [ "$WITH_CLOUDFLARED" = "1" ]; then
  step "Extra: Cloudflare Tunnel (cloudflared)"
  if ! command -v cloudflared >/dev/null 2>&1; then
    install -d -m 0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
      > /etc/apt/sources.list.d/cloudflared.list
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq cloudflared >/dev/null
    ok "cloudflared instalado ($(cloudflared --version 2>/dev/null | head -1))"
  else
    ok "cloudflared ya estaba ($(cloudflared --version 2>/dev/null | head -1))"
  fi
  if systemctl is-active --quiet cloudflared 2>/dev/null; then
    ok "el servicio cloudflared ya está corriendo (túnel configurado). Nada que hacer."
  else
    echo "    Pegá el TOKEN del túnel (Cloudflare Zero Trust > Networks > Tunnels > tu túnel > Debian:"
    echo "    es el texto largo que aparece después de 'cloudflared service install'). Enter vacío = saltear."
    printf '    Token del túnel: '
    CF="$(read_secret)"; echo
    CF="$(printf '%s' "$CF" | tr -d '[:space:]')"
    if [ -n "$CF" ]; then
      if cloudflared service install "$CF" >/dev/null 2>&1; then
        ok "túnel instalado como servicio 'cloudflared'"
      else
        warn "cloudflared service install falló: mirá 'sudo journalctl -u cloudflared -n 30'"
      fi
      unset CF
    else
      warn "salteado. Cuando tengas el token: sudo cloudflared service install <TOKEN>"
    fi
  fi
fi

cat <<HELP

Listo. El asistente escucha SOLO en 127.0.0.1:$PORT (no queda expuesto a Internet).
Para publicarlo en https://asistente.lcaitech.com usá Cloudflare Tunnel (ver README, "Publicar con HTTPS").

Comandos útiles:
  Log en vivo:       sudo journalctl -u $SERVICE -f
  Estado:            systemctl status $SERVICE
  Salud:             curl -s http://127.0.0.1:$PORT/health
  Probar el modelo:  cd $APP_DIR && sudo .venv/bin/python -m app.check --env-file $ENV_FILE
  Editar límites:    sudo nano $ENV_FILE && sudo systemctl restart $SERVICE
  Actualizar:        sudo bash $APP_DIR/deploy/install_vm.sh
  Apagar el chat:    sudo systemctl stop $SERVICE   (el widget muestra los contactos)
HELP
