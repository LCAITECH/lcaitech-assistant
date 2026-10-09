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
            assert "bybit" not in t.lower() and "bitget" not in t.lower()
