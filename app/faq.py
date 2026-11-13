"""Instant answers (no LLM call) for the suggested questions and the most frequent intents.

Match rules: the normalised message equals a suggested question, or it is short
(<= 12 words) and matches exactly ONE intent. Anything else goes to the model.
All answers come from knowledge/*.md (real data only).
"""
from __future__ import annotations

import re
import unicodedata

PACKAGES_ES = """- **S1–S3 bots chicos** (preguntas frecuentes, alertas de precio, moderación): USD 100–180 c/u (2–6 días); Pack Comunidad S1+S2+S3 USD 250–350
- **P0 Starter** (un bot o una automatización): desde USD 250 (~1 semana)
- **P1 Community Alert Bot**: desde USD 600 (1–2 semanas)
- **P2 Market Data API + Dashboard**: desde USD 2,500 (3–5 semanas)
- **P3 Onboarding & Referral Automation**: desde USD 1,200 (2–3 semanas)
- **P4 AI Support Agent**: desde USD 1,500 (2–4 semanas)
- **P5 Partner técnico part-time**: desde USD 1,500/mes
- **P6 Automatización operativa con IA**: desde USD 800 (1–3 semanas)
- **P7 Asistente IA interno + estrategia de modelos**: desde USD 2,000 (2–4 semanas)"""
PACKAGES_EN = """- **S1–S3 small bots** (FAQ, price alerts, moderation): USD 100–180 each (2–6 days); Community Pack S1+S2+S3 USD 250–350
- **P0 Starter** (one bot or one automation): from USD 250 (~1 week)
- **P1 Community Alert Bot**: from USD 600 (1–2 weeks)
- **P2 Market Data API + Dashboard**: from USD 2,500 (3–5 weeks)
- **P3 Onboarding & Referral Automation**: from USD 1,200 (2–3 weeks)
- **P4 AI Support Agent**: from USD 1,500 (2–4 weeks)
- **P5 Part-time technical partner**: from USD 1,500/month
- **P6 AI operations automation**: from USD 800 (1–3 weeks)
- **P7 Internal AI assistant + model strategy**: from USD 2,000 (2–4 weeks)"""

ANSWERS: dict[str, dict[str, str]] = {
    "services": {
        "es": "Leandro construye sistemas completos para proyectos cripto y equipos tech: datos de mercado y APIs, bots de Telegram, agentes de IA, automatizaciones y deploy en la nube. Paquetes (precios \"desde\", USD):\n"
        + PACKAGES_ES + "\nEl precio final se cierra por escrito (sin llamadas). Contale tu proyecto en 2–3 líneas a itech.lca@gmail.com o armalo en https://portfolio.lcaitech.com/#builder.",
        "en": "Leandro builds complete systems for crypto projects and tech teams: market data and APIs, Telegram bots, AI agents, automations and cloud deployment. Packages (\"from\" prices, USD):\n"
        + PACKAGES_EN + "\nThe final price is agreed in writing (no calls). Describe your project in 2–3 lines to itech.lca@gmail.com or build it at https://portfolio.lcaitech.com/#builder.",
    },
    "prices": {
        "es": "Leandro trabaja con paquetes de precio cerrado (no por hora). Precios \"desde\", en USD:\n" + PACKAGES_ES
        + "\nCondiciones: alcance por escrito, 50% de anticipo para empezar en todos los paquetes, incluidos S1–S3 (milestones en proyectos grandes), pago en USDC/USDT o transferencia y 30 días de soporte. Para una cotización, escribile a itech.lca@gmail.com.",
        "en": "Leandro works with fixed-price packages (not hourly). \"From\" prices in USD:\n" + PACKAGES_EN
        + "\nTerms: written scope, 50% upfront to start on every package, S1–S3 included (milestones on larger projects), payment in USDC/USDT or bank transfer, and 30 days of support. For a quote, email itech.lca@gmail.com.",
    },
    "bot_price": {
        "es": "Para una comunidad hay dos caminos:\n- **Bots chicos S1–S3**: S1 preguntas frecuentes para Telegram (USD 100–150, 3–5 días), S2 alertas de precio (USD 100–150, 2–4 días), S3 moderación para Discord o Telegram (USD 120–180, 4–6 días). 2 módulos −15%; **Pack Comunidad** S1+S2+S3: USD 250–350.\n- **P1 Community Alert Bot**: alertas de precio, ATH, unlocks, Fear & Greed, ballenas y resumen diario, **desde USD 600** (1–2 semanas).\n50% de anticipo para empezar. Armalo en https://portfolio.lcaitech.com/#builder o escribile a itech.lca@gmail.com. Bot demo: https://t.me/lcaitech_demo_bot",
        "en": "For a community there are two options:\n- **Small bots S1–S3**: S1 Telegram FAQ (USD 100–150, 3–5 days), S2 price alerts (USD 100–150, 2–4 days), S3 moderation for Discord or Telegram (USD 120–180, 4–6 days). Any 2 modules −15%; **Community Pack** S1+S2+S3: USD 250–350.\n- **P1 Community Alert Bot**: price alerts, ATH, unlocks, Fear & Greed, whales and a daily summary, **from USD 600** (1–2 weeks).\n50% upfront to start. Build it at https://portfolio.lcaitech.com/#builder or email itech.lca@gmail.com. Demo bot: https://t.me/lcaitech_demo_bot",
    },
    "ath": {
        "es": "**ATH Intelligence** (https://athintelligence.pro) es el producto propio de Leandro, online. Responde una pregunta: ¿puede un activo volver de verdad a su máximo histórico (ATH) después del supply que se emitió desde entonces? Guarda el market cap y el supply de cada ATH, puntúa cada activo con un **Recovery Score** determinista (distancia al ATH, inflación del supply y tamaño) y expone todo por una API REST. Hecho con Python, FastAPI, PostgreSQL, Docker y GCP. Es contexto, no consejo financiero.",
        "en": "**ATH Intelligence** (https://athintelligence.pro) is Leandro's own product, live. It answers one question: can an asset really return to its all-time high (ATH) after the supply issued since then? It stores market cap and supply at each ATH, gives each asset a deterministic **Recovery Score** (distance to ATH, supply inflation and size) and exposes everything through a REST API. Built with Python, FastAPI, PostgreSQL, Docker and GCP. It's context, not financial advice.",
    },
    "contact": {
        "es": "Contacto de Leandro:\n- Email: itech.lca@gmail.com (el mejor canal para proyectos)\n- LinkedIn: https://www.linkedin.com/in/leandrobuchter\n- X: https://x.com/LCA_ITECH\n- GitHub: https://github.com/LCAITECH\n- Bot demo: https://t.me/lcaitech_demo_bot\nContale qué necesitás en 2–3 líneas.",
        "en": "Leandro's contact:\n- Email: itech.lca@gmail.com (best channel for projects)\n- LinkedIn: https://www.linkedin.com/in/leandrobuchter\n- X: https://x.com/LCA_ITECH\n- GitHub: https://github.com/LCAITECH\n- Demo bot: https://t.me/lcaitech_demo_bot\nDescribe what you need in 2–3 lines.",
    },
    "hire": {
        "es": "Así se trabaja con Leandro (todo por escrito, sin llamadas):\n- Escribile a itech.lca@gmail.com (o por LinkedIn) contando qué necesitás en 2–3 líneas, o armá el pedido en https://portfolio.lcaitech.com/#builder.\n- Alcance y precio cerrado por escrito.\n- 50% de anticipo para empezar, en todos los paquetes (milestones en proyectos grandes); pago en USDC/USDT o transferencia.\n- Entrega + 30 días de soporte.\nNadie de LCA ITECH te va a pedir fondos por privado: los pagos se acuerdan siempre con alcance por escrito.",
        "en": "How to work with Leandro (all in writing, no calls):\n- Email itech.lca@gmail.com (or LinkedIn) describing what you need in 2–3 lines, or build the request at https://portfolio.lcaitech.com/#builder.\n- Written scope with a fixed price.\n- 50% upfront to start on every package (milestones on larger projects); payment in USDC/USDT or bank transfer.\n- Delivery + 30 days of support.\nNobody from LCA ITECH will DM you asking for funds: payments are always agreed with a written scope.",
    },
    "builder": {
        "es": "El **armador de proyectos** (https://portfolio.lcaitech.com/#builder) arma tu pedido en 4 pasos:\n- 1. Elegí qué querés: bot para tu comunidad, automatizar tu negocio, asistente con IA o dashboard cripto.\n- 2. Prendé módulos y miralos funcionar en una demo simulada.\n- 3. Elegí plataforma (Telegram, Discord, WhatsApp o Web) y nivel de IA.\n- 4. Mirá el total estimado (con descuentos por combo; lo que no tiene precio publicado figura \"a cotizar\") y tocá \"Pedir este proyecto\" para completar el formulario.\n50% de anticipo para empezar.",
        "en": "The **project builder** (https://portfolio.lcaitech.com/#builder) puts your request together in 4 steps:\n- 1. Pick what you want: community bot, business automation, AI assistant or crypto dashboard.\n- 2. Turn modules on and watch them work in a simulated demo.\n- 3. Choose platform (Telegram, Discord, WhatsApp or Web) and AI level.\n- 4. See the estimated total (with combo discounts; anything without a published price shows \"quote\") and tap \"Order this project\" to fill in the form.\n50% upfront to start.",
    },
    "certs": {
        "es": "Certificados verificables (Coursera):\n- **DeFi Specialization**, Duke University (2026)\n- **Google AI Professional Certificate** (2026)\n- **Google Cloud Generative AI Leader Professional Certificate** (programa de 5 cursos en Coursera, 2026; no es el examen de certificación de Google Cloud)\n- **IBM AI Foundations for Everyone** (2020)\n- **Google IT Support Professional Certificate** (2020)\nEn curso: IBM AI Engineering y Machine Learning for Trading. Links de verificación en https://portfolio.lcaitech.com",
        "en": "Verifiable certificates (Coursera):\n- **DeFi Specialization**, Duke University (2026)\n- **Google AI Professional Certificate** (2026)\n- **Google Cloud Generative AI Leader Professional Certificate** (5-course Coursera program, 2026; not the Google Cloud certification exam)\n- **IBM AI Foundations for Everyone** (2020)\n- **Google IT Support Professional Certificate** (2020)\nIn progress: IBM AI Engineering and Machine Learning for Trading. Verification links at https://portfolio.lcaitech.com",
    },
    "demobot": {
        "es": "El **bot demo** (https://t.me/lcaitech_demo_bot) es un bot público de Telegram en castellano e inglés: /precio btc, /ath eth, /feargreed, /whales btc (trades grandes en MEXC), /ask y /servicios. Cada respuesta muestra su fuente de datos. Es open source (https://github.com/LCAITECH/lcaitech-demo-bot) y corre 24/7 en una VM de Google Cloud. Es un demo técnico: no da señales ni consejos de inversión.",
        "en": "The **demo bot** (https://t.me/lcaitech_demo_bot) is a public Telegram bot in Spanish and English: /precio btc, /ath eth, /feargreed, /whales btc (large MEXC trades), /ask and /servicios. Every answer shows its data source. It's open source (https://github.com/LCAITECH/lcaitech-demo-bot) and runs 24/7 on a Google Cloud VM. It's a technical demo: no signals or investment advice.",
    },
}

SUGGESTED = {
    "que servicios ofrece leandro": ("services", "es"),
    "cuanto cuesta un bot de telegram para mi comunidad": ("bot_price", "es"),
    "que es ath intelligence": ("ath", "es"),
    "como lo contrato": ("hire", "es"),
    "what services does leandro offer": ("services", "en"),
    "how much is a telegram bot for my community": ("bot_price", "en"),
    "what is ath intelligence": ("ath", "en"),
    "how do i hire him": ("hire", "en"),
}

_PRICE = r"\b(precios?|cuanto (cuesta|sale|cobra\w*|vale)|tarifas?|presupuesto|cotiza\w*|costo|price|prices|pricing|how much|cost|costs|rates?|quote)\b"
INTENTS: list[tuple[str, str]] = [
    ("bot_price", r"\bbot\b.*" + _PRICE + "|" + _PRICE + r".*\bbot\b"),
    ("prices", _PRICE),
    ("services", r"\b(servicios?|services?|que (hace|ofrece|ofreces)|what (does|do) (he|you|leandro) (do|offer)|paquetes|packages)\b"),
    ("ath", r"\b(ath intelligence|athintelligence|recovery score)\b"),
    ("contact", r"\b(contacto|contactar\w*|contactarlo|mail|email|e mail|correo|linkedin|contact|reach (him|you|leandro))\b"),
    ("hire", r"\b(contrat\w*|trabajar con (el|vos|leandro)|como se paga|formas? de pago|hire|hiring|work with (him|you|leandro)|payment terms?)\b"),
    ("builder", r"\b(armador|configurador|armar (mi|el|un) (bot|proyecto)|builder|build (my|a) (bot|project))\b"),
    ("certs", r"\b(certificad\w*|certificacion\w*|certifications?|certificates?|certified)\b"),
    ("demobot", r"\b(bot demo|demo bot|lcaitech demo bot|bot de prueba)\b"),
]
_INTENT_RE = [(name, re.compile(rx)) for name, rx in INTENTS]
_EN_WORDS = re.compile(r"\b(what|how|does|do|is|the|his|him|he|much|who|which|where|can|services?|hire|price|prices)\b")
_ES_WORDS = re.compile(r"\b(que|como|cuanto|cuesta|sale|el|la|los|las|de|lo|tiene|ofrece|servicios|precio|precios|contrato|quien)\b")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9@ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def guess_lang(norm: str, default: str) -> str:
    en, es = len(_EN_WORDS.findall(norm)), len(_ES_WORDS.findall(norm))
    if en > es:
        return "en"
    if es > en:
        return "es"
    return default


# Free-text questions that mention any of these need judgement (refusals, advice, money moves,
# comparisons, negations): never answer them with a canned text, let the model handle them.
_NEEDS_MODEL = re.compile(
    r"\b(garantiz\w*|guarante\w*|rendimient\w*|retorno\w*|returns?|profit\w*|ganancia\w*|invert\w*|inver(sion|tir)\w*|invest\w*"
    r"|compr[oa]r?|vend[oe]r?|buy|sell|wallet|billetera|deposit\w*|deposit[oa]|transfer\w*|send|mand[aá]\w*"
    r"|predic\w*|precio de (btc|eth|sol|bitcoin)|senal\w*|signals?|vs|versus|mejor que|better than|no |not |sin |without|why|por que)\b"
)


def match(text: str, ui_lang: str) -> tuple[str, str] | None:
    """Return (answer, lang) or None."""
    norm = normalise(text)
    if not norm:
        return None
    if norm in SUGGESTED:
        intent, lang = SUGGESTED[norm]
        return ANSWERS[intent][lang], lang
    if len(norm.split()) > 12 or _NEEDS_MODEL.search(norm + " "):
        return None
    hits = [name for name, rx in _INTENT_RE if rx.search(norm)]
    if "bot_price" in hits:
        hits = [h for h in hits if h not in ("prices", "demobot")]
    specific = [h for h in hits if h in ("bot_price", "ath", "builder", "demobot", "certs")]
    if specific and "prices" in hits and specific != ["bot_price"]:
        return None  # e.g. "price of ATH Intelligence API": not a canned topic, let the model answer
    if specific:  # a specific topic beats the generic "services"/"hire" wording
        hits = specific
    if len(hits) != 1:
        return None
    lang = guess_lang(norm, ui_lang)
    return ANSWERS[hits[0]][lang], lang
