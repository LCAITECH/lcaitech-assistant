# Servicios y precios (paquetes con alcance claro)

Precio cerrado por proyecto, acordado por escrito (email o chat). Leandro NO hace llamadas ni videollamadas: todo el contacto, las preguntas y el alcance son por escrito; si hace falta mostrar algo, manda una demo escrita o un video pregrabado. Los precios son un punto de partida ("desde") en USD; el precio final depende del alcance y se cotiza por escrito. Leandro NO publica tarifa por hora; vende paquetes con alcance y precio cerrado.

## Para proyectos cripto

### P0 · Starter: un bot o una automatización — desde USD 250 · ~1 semana
Un bot de alertas básico para Telegram (precios, distancia al ATH, resumen diario) o un proceso repetitivo automatizado de punta a punta. Ideal para empezar a trabajar juntos.

### P1 · Community Alert Bot — desde USD 600 · 1–2 semanas
Bot de Telegram (Discord opcional) para tu comunidad: alertas de precio y porcentaje, distancia al ATH, token unlocks próximos, Fear & Greed, movimientos de ballenas (umbral configurable) y resumen diario automático al canal. Panel admin simple (alta y baja de tokens, umbrales y horarios). Ingeniería de producción: reintentos, deduplicación de alertas, logging, alertas de caída y backups. Deploy en VM Linux con Docker. Entregable: bot en producción, repo con README, guía de admin y 30 días de soporte.

### P2 · Market Data API + Dashboard — desde USD 2,500 · 3–5 semanas
Tu propio pipeline de datos de mercado (APIs públicas y de exchanges, opcionalmente on-chain), base de datos histórica, API REST (con API keys, rate limit y documentación OpenAPI) y dashboard web simple, basado en el motor de ATH Intelligence (marca blanca). Métricas como distancia al ATH, Recovery Score, calendario de unlocks, BTC vs otros activos. Jobs programados, monitoreo y backups. Entregable: API desplegada, base de datos, dashboard, docs y handoff técnico.

### P3 · Onboarding & Referral Automation — desde USD 1,200 · 2–3 semanas
Onboarding en Telegram: verificación anti-bot, bienvenida, links de referido, verificación de UID (cuando la API del exchange lo permite), acceso VIP automático, recordatorios y tracking de conversión (en base de datos o Google Sheets). Opcional: verificación de holders (token/NFT) y roles en Discord.

### P4 · AI Support Agent — desde USD 1,500 · 2–4 semanas
Agente de IA para Telegram/Discord que responde desde tu documentación (docs, FAQ, whitepaper, anuncios) en ES/EN/PT, con protecciones anti-scam (no da consejo financiero, nunca pide seed ni manda DMs de "soporte") y derivación a un humano. Selección de modelo y costo con Model Compass. Logs y métricas de uso y costo. Los costos de la API del LLM los paga el cliente aparte.

### P5 · Partner técnico part-time — desde USD 1,500 / mes
Un bloque mensual de horas para mantener y hacer crecer tus bots, integraciones con exchanges, pipelines de datos e infraestructura (GCP, Docker, monitoreo). Reporte semanal. Disponibilidad acordada en horario UTC-3.

### P8 · Bot de señales de trading con IA — en desarrollo (sin precio publicado)
Señales basadas en reglas y backtesteadas sobre tus activos, con Claude como segundo filtro que revisa contexto y riesgo antes de cada alerta. Alertas por Telegram con entrada, stop, take profit y justificación; cada señal queda registrada y la ejecución la decide el cliente. Estado: en desarrollo, paper trading en curso. No se promete rentabilidad; no es asesoramiento financiero.

## Bots chicos modulares (S1–S3)
Bots chicos y rápidos para comunidades, con precio en rango (USD) y plazo corto:
- **S1 · Bot de preguntas frecuentes para Telegram** — USD 100–150 · 3–5 días. Responde las preguntas frecuentes de tu comunidad (cómo comprar, links, reglas, guías) en tu grupo o por privado, con tus textos y comandos.
- **S2 · Bot de alertas de precio (cripto)** — USD 100–150 · 2–4 días. Publica alertas en tu grupo o canal de Telegram cuando un activo cruza los niveles que elijas, con la fuente del dato en cada mensaje.
- **S3 · Bot de moderación para Discord o Telegram** — USD 120–180 · 4–6 días. Da la bienvenida a los nuevos, borra spam y mensajes que piden seed phrases o claves privadas, y advierte o silencia al que los manda.
Combos: 2 módulos cualesquiera de S1–S3 tienen 15% de descuento (S1+S2: USD 170–255; S1+S3 o S2+S3: USD 185–280). **Pack Comunidad** S1 + S2 + S3: USD 250–350 (~25% menos que por separado, que serían USD 320–480). Los S1–S3 también requieren 50% de anticipo para empezar.

## Armador de proyectos (en el portfolio, sección #builder)
En el portfolio hay un armador interactivo de 4 pasos para armar el pedido sin llamadas:
1. **Elegí qué querés**: Bot para tu comunidad, Automatizar tu negocio, Asistente con IA o Dashboard cripto.
2. **Armalo por módulos**: prendés módulos (o los arrastrás a la vista previa) y ves cada uno funcionando en una simulación de demo. Comunidad: S1, S2, S3, onboarding y referidos (P3), pagos y accesos VIP. Negocio: Gmail, Google Sheets, reportes, preguntas frecuentes por WhatsApp. Asistente: base de conocimiento (P4), memoria, multicanal, asistente interno con ruteo de modelos (P7). Dashboard: API de datos de mercado + dashboard (P2), wallets, alertas a Telegram (S2), señales con IA (P8, en desarrollo).
3. **Plataforma y cerebro**: Telegram, Discord, WhatsApp o Web, y nivel de inteligencia (respuestas fijas, IA básica o IA avanzada con memoria).
4. **Resumen y pedido**: total estimado con descuentos por combo, días estimados, aviso de 50% de anticipo, y el botón "Pedir este proyecto" que completa el formulario de contacto con toda la selección (el visitante lo revisa y lo envía).
Solo muestran precio los módulos con precio publicado (S1–S3 y los paquetes P0–P8 "desde"); todo lo demás figura como "a cotizar" y Leandro pasa el precio por escrito. Si hay algo a cotizar, el total dice "desde USD X + a cotizar". Las elecciones se guardan solo en el navegador del visitante.

## IA y automatización para empresas

### P6 · Automatización operativa con IA — desde USD 800 · 1–3 semanas
Automatiza 1–3 procesos repetitivos: formularios, mails o mensajes clasificados con IA y enviados a tus planillas o CRM, reportes y alertas. Python + Make + APIs, con reintentos, logging y alertas de error. Entregable: automatizaciones funcionando, diagrama del flujo y video corto de uso.

### P7 · Asistente IA interno + estrategia de modelos — desde USD 2,000 · 2–4 semanas
Un asistente sobre tu documentación interna (soporte, ventas u onboarding), más una comparación de modelos por costo, idioma y volumen (con Model Compass) para bajar el costo por respuesta. Entregable: asistente desplegado, informe de evaluación de modelos y costos, y runbook.

## Condiciones
- Alcance por escrito antes de empezar.
- 50% de anticipo SIEMPRE para empezar, en todos los paquetes (incluidos S1–S3); milestones en proyectos grandes.
- Pago en USDC / USDT o transferencia.
- 30 días de soporte después de la entrega.
- Hosting/mantenimiento mensual: opcional, se cotiza aparte. Costos de APIs de terceros y de LLMs: a cargo del cliente.
- Proyectos a medida fuera de estos paquetes: se cotizan por escrito.
- Contacto siempre por escrito: no hay llamadas ni videollamadas.

## Cómo contratar
1. Escribir a itech.lca@gmail.com (o por LinkedIn), o usar el formulario de contacto o el armador de proyectos del portfolio, contando qué necesitás en 2–3 líneas. Leandro responde por escrito con preguntas o una primera idea.
2. Alcance y precio cerrado por escrito (sin llamadas).
3. 50% de anticipo para empezar (milestones en proyectos grandes) y arranque.
4. Entrega + 30 días de soporte.
