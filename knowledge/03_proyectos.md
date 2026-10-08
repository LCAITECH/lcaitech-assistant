# Proyectos

## ATH Intelligence — online — https://athintelligence.pro
Producto propio de inteligencia de recuperación cripto. Responde una pregunta: ¿puede un activo volver de verdad a su máximo histórico (ATH) después del supply que se emitió desde entonces? Guarda el market cap y el supply de cada ATH, puntúa cada activo con un Recovery Score determinista y expone todo por una API REST. Hecho de punta a punta por Leandro: recolección de datos, backend, base de datos, API y deploy.
Stack: Python, FastAPI, PostgreSQL, Docker, Google Cloud (GCP).
Secciones y métricas:
- Recovery Score: determinista; combina distancia al ATH, inflación del supply y tamaño.
- ATH honesto (supply-adjusted ATH): market cap del máximo ÷ supply de hoy.
- Recovery tape: ranking de recuperación de más de 1.000 activos líquidos.
- Unlocks: contexto de presión de supply (burns, inflación, vesting) con fuentes primarias.
- xStocks: acciones tokenizadas vs su ATH.
- Bitcoin: épocas de halving y altcoins medidas en BTC.
- Poder adquisitivo: qué compraba BTC año a año (autos, electrónica, inmuebles, commodities).
- Fear & Greed: sentimiento de mercado histórico vs precio.
- Además: Cap lab (precio a otro market cap), docs para desarrolladores con API REST por x-api-key y un asistente para los endpoints de la API.
Es contexto y análisis, no predicción ni consejo financiero.

## Model Compass — open source (MIT) — https://github.com/LCAITECH/model-compass
Motor de decisión open source que ayuda a elegir el modelo de IA correcto según caso de uso, presupuesto, prioridades, idioma y volumen. Recomendaciones explicables y deterministas, no opiniones. Stack: Python 3.11, FastAPI, pytest. Estado: pre-1.0.

## ARDC · Alto Riesgo Degens Club — https://ardc.club
Comunidad de habla hispana de cripto de alto riesgo, enfocada en trading de memecoins, que Leandro co-dirige con un socio. Primero el riesgo: antes de cada entrada se revisan liquidez, holders, permisos del contrato (mint, freeze, honeypot) y liquidez bloqueada. Tiene un analizador de tokens gratuito con análisis de riesgo con IA, un registro público de trades (ganadores y perdedores) y guías anti-scam. Redes: Solana, BNB Chain, Base. Es una comunidad de alto riesgo: no es asesoramiento financiero ni garantiza resultados.

## LCA ITECH / LCA Trading — 2020 → hoy — https://x.com/LCA_ITECH
LCA ITECH es la empresa que Leandro fundó en 2020. LCA Trading es su comunidad de trading y educación cripto (desde 2022) en Telegram, X, Instagram, YouTube y Discord, donde construye y prueba en la vida real: bots de Telegram, dashboards, integraciones con exchanges y sistemas de referidos.

## LCA-GPT — herramienta interna
Interfaz web interna con ruteo de IA: cada consulta va al modelo más adecuado (Gemini, Claude u OpenAI) según la tarea y el costo. No es un producto público.

## Bot demo de Telegram — online — https://t.me/lcaitech_demo_bot (@lcaitech_demo_bot)
Bot público para probar en vivo lo que Leandro construye, en castellano e inglés. Comandos: /precio btc (precio y variación 24 h), /ath eth (distancia al ATH), /feargreed (índice Fear & Greed), /whales btc (trades grandes recientes en MEXC), /ask (agente que responde preguntas frecuentes sobre cripto), /servicios. Cada respuesta muestra su fuente de datos (CoinGecko, MEXC, alternative.me). Código abierto (MIT): https://github.com/LCAITECH/lcaitech-demo-bot. Corre 24/7 en una VM de Google Cloud con systemd. Es un demo técnico: no da señales ni consejos de inversión.

## Este asistente virtual
El chat del portfolio es un asistente con IA (Gemini en Google Cloud Vertex AI) hecho por Leandro, con límites de uso y protecciones. Código abierto: https://github.com/LCAITECH/lcaitech-assistant
