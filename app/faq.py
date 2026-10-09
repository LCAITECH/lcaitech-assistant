"""Instant answers (no LLM call) for the suggested questions and the most frequent intents.

Match rules: the normalised message equals a suggested question, or it is short
(<= 12 words) and matches exactly ONE intent. Anything else goes to the model.
All answers come from knowledge/*.md (real data only).
"""
from __future__ import annotations

import re
import unicodedata

PACKAGES_ES = """- **P1 Community Alert Bot**: desde USD 600 (1–2 semanas)
- **P2 Market Data API + Dashboard**: desde USD 2,500 (3–5 semanas)
- **P3 Onboarding & Referral Automation**: desde USD 1,200 (2–3 semanas)
- **P4 AI Support Agent**: desde USD 1,500 (2–4 semanas)
- **P5 Partner técnico part-time**: desde USD 1,500/mes
- **P6 Automatización operativa con IA**: desde USD 800 (1–3 semanas)
- **P7 Asistente IA interno + estrategia de modelos**: desde USD 2,000 (2–4 semanas)"""
PACKAGES_EN = """- **P1 Community Alert Bot**: from USD 600 (1–2 weeks)
- **P2 Market Data API + Dashboard**: from USD 2,500 (3–5 weeks)
- **P3 Onboarding & Referral Automation**: from USD 1,200 (2–3 weeks)
- **P4 AI Support Agent**: from USD 1,500 (2–4 weeks)
- **P5 Part-time technical partner**: from USD 1,500/month
- **P6 AI operations automation**: from USD 800 (1–3 weeks)
- **P7 Internal AI assistant + model strategy**: from USD 2,000 (2–4 weeks)"""

ANSWERS: dict[str, dict[str, str]] = {
    "services": {
        "es": "Leandro construye sistemas completos para proyectos cripto y equipos tech: datos de mercado y APIs, bots de Telegram, agentes de IA, automatizaciones y deploy en la nube. Paquetes (precios \"desde\", USD):\n"
        + PACKAGES_ES + "\nEl precio final se cierra después de una llamada corta. Contale tu proyecto en 2–3 líneas a itech.lca@gmail.com.",
        "en": "Leandro builds complete systems for crypto projects and tech teams: market data and APIs, Telegram bots, AI agents, automations and cloud deployment. Packages (\"from\" prices, USD):\n"
        + PACKAGES_EN + "\nThe final price is agreed after a short call. Describe your project in 2–3 lines to itech.lca@gmail.com.",
    },
    "prices": {
        "es": "Leandro trabaja con paquetes de precio cerrado (no por hora). Precios \"desde\", en USD:\n" + PACKAGES_ES
        + "\nCondiciones: alcance por escrito, 50% de anticipo (milestones en proyectos grandes), pago en USDC/USDT o transferencia y 30 días de soporte. Para una cotización, escribile a itech.lca@gmail.com.",
        "en": "Leandro works with fixed-price packages (not hourly). \"From\" prices in USD:\n" + PACKAGES_EN
        + "\nTerms: written scope, 50% upfront (milestones on larger projects), payment in USDC/USDT or bank transfer, and 30 days of support. For a quote, email itech.lca@gmail.com.",
    },
    "bot_price": {
        "es": "Para una comunidad, el paquete es **P1 Community Alert Bot**: bot de Telegram (Discord opcional) con alertas de precio, distancia al ATH, token unlocks, Fear & Greed, movimientos de ballenas y resumen diario. **Desde USD 600**, 1–2 semanas, con 30 días de soporte. El precio final se cotiza tras una llamada corta: escribile a itech.lca@gmail.com. Podés probar el bot demo: https://t.me/lcaitech_demo_bot",
        "en": "For a community, the package is **P1 Community Alert Bot**: a Telegram bot (Discord optional) with price alerts, distance to ATH, token unlocks, Fear & Greed, whale moves and a daily summary. **From USD 600**, 1–2 weeks, with 30 days of support. The final price is quoted after a short call: email itech.lca@gmail.com. Try the demo bot: https://t.me/lcaitech_demo_bot",
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
        "es": "Así se trabaja con Leandro:\n- Escribile a itech.lca@gmail.com (o por LinkedIn) contando qué necesitás en 2–3 líneas.\n- Llamada corta y alcance por escrito, con precio cerrado.\n- 50% de anticipo (milestones en proyectos grandes); pago en USDC/USDT o transferencia.\n- Entrega + 30 días de soporte.\nNadie de LCA ITECH te va a pedir fondos por privado: los pagos se acuerdan siempre con alcance por escrito.",
        "en": "How to work with Leandro:\n- Email itech.lca@gmail.com (or LinkedIn) describing what you need in 2–3 lines.\n- Short call and written scope, with a fixed price.\n- 50% upfront (milestones on larger projects); payment in USDC/USDT or bank transfer.\n- Delivery + 30 days of support.\nNobody from LCA ITECH will DM you asking for funds: payments are always agreed with a written scope.",
    },
    "ardc": {
        "es": "**ARDC · Alto Riesgo Degens Club** (https://ardc.club) es una comunidad de habla hispana de cripto de alto riesgo, enfocada en trading de memecoins (Solana, BNB Chain, Base), que Leandro co-dirige con un socio. Primero el riesgo: antes de cada entrada se revisan liquidez, holders, permisos del contrato y liquidez bloqueada. Tiene un analizador de tokens gratuito con IA, un registro público de trades (ganadores y perdedores) y guías anti-scam. Esto no es asesoramiento financiero.",
        "en": "**ARDC · Alto Riesgo Degens Club** (https://ardc.club) is a Spanish-speaking high-risk crypto community focused on memecoin trading (Solana, BNB Chain, Base), co-run by Leandro and a partner. Risk first: liquidity, holders, contract permissions and locked liquidity are checked before each entry. It has a free AI token analyzer, a public trade log (winners and losers) and anti-scam guides. This is not financial advice.",
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
    ("ardc", r"\b(ardc|alto riesgo degens)\b"),
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
    specific = [h for h in hits if h in ("bot_price", "ath", "ardc", "demobot", "certs")]
    if specific and "prices" in hits and specific != ["bot_price"]:
        return None  # e.g. "price of ATH Intelligence API": not a canned topic, let the model answer
    if specific:  # a specific topic beats the generic "services"/"hire" wording
        hits = specific
    if len(hits) != 1:
        return None
    lang = guess_lang(norm, ui_lang)
    return ANSWERS[hits[0]][lang], lang
