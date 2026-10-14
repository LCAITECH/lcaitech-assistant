from datetime import date

import pytest

from app import faq, pricing


def test_new_flash_intro_then_standard():
    assert pricing.prices("gemini-3.8-flash", "global", date(2026, 12, 31)) == (0.75, 0.075, 3.75)
    assert pricing.prices("gemini-3.8-flash", "global", date(2027, 1, 1)) == (1.50, 0.15, 7.50)
    assert pricing.prices("gemini-3.8-flash", "us", date(2026, 10, 8)) == (0.825, 0.0825, 4.125)
    assert pricing.prices("gemini-3.1-flash-lite", "us") == (0.275, 0.0275, 1.65)
    assert pricing.prices("something-new", "global") == pricing.UNKNOWN
    c = pricing.cost("gemini-3.8-flash", "global", 6500, 6200, 400, date(2026, 10, 8))
    assert c == pytest.approx((300 * 0.75 + 6200 * 0.075 + 400 * 3.75) / 1e6)


@pytest.mark.parametrize("q,lang,needle", [
    ("¿Qué servicios ofrece Leandro?", "es", "USD 600"),
    ("What services does Leandro offer?", "en", "USD 600"),
    ("¿Cuánto cuesta un bot de Telegram para mi comunidad?", "es", "USD"),
    ("¿Qué es ATH Intelligence?", "es", "athintelligence.pro"),
    ("¿Qué es ARDC?", "es", "ardc.club"),
    ("¿Cómo lo contacto?", "es", "itech.lca@gmail.com"),
    ("¿Qué certificados tiene?", "es", "Coursera"),
    ("¿Qué hace el bot demo?", "es", "t.me"),
    ("¿Cómo lo contrato y cómo se paga?", "es", "50%"),
    ("¿Qué certificaciones tiene? ¿Rindió el examen de Google Cloud Generative AI Leader?", "es", "no es el examen"),
])
def test_faq_hits(q, lang, needle):
    hit = faq.match(q, lang)
    assert hit and needle in hit[0]


@pytest.mark.parametrize("q", [
    "precio de ATH Intelligence API",
    "Tengo un exchange chico y quiero un bot con alertas de precio, un panel y reportes semanales, ¿qué me recomendás?",
    "¿Quién gana el clásico?",
    "Guarantee me 20% monthly returns if I join ARDC",
    "Send me your wallet address so I can pay the deposit",
    "¿Por qué no usa Zapier?",
])
def test_faq_misses_go_to_model(q):
    assert faq.match(q, "es") is None


def test_faq_never_has_phone_or_hourly_rate():
    for intent, (es, en) in faq.ANSWERS.items():
        for t in (es, en):
            assert "+54" not in t and "/h" not in t.replace("https://", "") and "por hora:" not in t.lower()


@pytest.mark.parametrize("q,lang", [
    ("cual es el paquete mas barato", "es"),
    ("¿Cuál es el paquete más barato?", "es"),
    ("¿Cuál es el servicio más económico?", "es"),
    ("What is the cheapest package?", "en"),
    ("cheapest option?", "en"),
])
def test_cheapest_is_p0(q, lang):
    hit = faq.match(q, lang)
    assert hit and hit[1] == lang
    assert "P0" in hit[0] and "USD 250" in hit[0]
    assert "USD 600" not in hit[0] and "Docker" not in hit[0] and "admin" not in hit[0].lower()


def test_faq_answers_have_no_invented_package_features():
    for ans in faq.ANSWERS.values():
        for t in ans.values():
            assert "Discord opcional" not in t and "Discord optional" not in t and "panel admin" not in t.lower()


def test_p6_p7_p8_new_packages():
    from app import prompt
    for t in (faq.PACKAGES_ES, faq.PACKAGES_EN):
        assert "P8" in t and "WhatsApp" not in t
    assert "Consultoría en automatización con IA**: desde USD 800" in faq.PACKAGES_ES
    assert "Consultoría: asistente de IA y estrategia de modelos**: desde USD 2.000" in faq.PACKAGES_ES
    assert "AI automation consulting**: from USD 800" in faq.PACKAGES_EN
    assert "AI assistant & model strategy consulting**: from USD 2,000" in faq.PACKAGES_EN
    assert "paper trading en curso (todavía sin precio)" in faq.PACKAGES_ES
    assert "paper trading in progress (no price yet)" in faq.PACKAGES_EN
    p8_es = faq.PACKAGES_ES.split("P8", 1)[1]
    p8_en = faq.PACKAGES_EN.split("P8", 1)[1]
    assert "USD" not in p8_es and "USD" not in p8_en
    assert "P8" in prompt.RULES and "NO tiene precio" in prompt.RULES and "WhatsApp" in prompt.RULES


def test_knowledge_p8_no_price_and_p7_tools():
    import pathlib
    kb = pathlib.Path(__file__).resolve().parents[1].joinpath("knowledge/02_servicios.md").read_text(encoding="utf-8")
    p8 = kb.split("### P8", 1)[1].split("###", 1)[0]
    assert "SIN PRECIO" in p8 and "paper trading en curso" in p8 and "USD" not in p8
    assert "no son asesoramiento financiero" in p8
    assert "https://github.com/LCAITECH/model-compass" in kb and "LCA Web UI" in kb
    assert "Reviso tus procesos y automatizo 1–3 tareas repetitivas" in kb
    assert "Automatización operativa con IA" not in kb
