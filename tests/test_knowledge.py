import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = "\n".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(ROOT, "knowledge", "*.md"))))


def test_no_phone_numbers():
    assert not re.search(r"\+\s?54|\b\d{2,4}[\s-]\d{4}[\s-]\d{4}\b|whatsapp\.com|wa\.me", KB, re.I)


def test_only_public_email():
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", KB))
    assert emails == {"itech.lca@gmail.com"}


def test_no_hourly_rate():
    low = KB.lower()
    assert not re.search(r"usd\s*\d+\s*/\s*h\b|por hora:|/hora|per hour", low)


def test_from_prices_present():
    for p in ["USD 600", "USD 2,500", "USD 1,200", "USD 1,500", "USD 800", "USD 2,000"]:
        assert p in KB


def test_in_progress_and_gen_ai_leader_wording():
    assert re.search(r"En curso.*Machine Learning for Trading.*IBM AI Engineering", KB, re.S)
    assert "NO es la certificación/examen oficial" in KB


def test_prompt_is_big_enough_for_implicit_cache():
    from app.prompt import RULES

    # Gemini 3 implicit caching needs >= 4096 tokens; ~4 chars/token is conservative for ES text.
    assert (len(RULES) + len(KB)) / 4 > 4096


def test_founding_year_is_2022():
    from app.prompt import RULES

    assert "fundada por Leandro en 2022" in KB and "fundó en 2022" in KB
    assert not re.search(r"(fund\w+|founded)( por Leandro)? en 2020|en 2020 fund|2020 · \w+ \w+: deja la empresa|LCA ITECH / LCA Trading — 2020", KB + RULES, re.I)
    assert "2022" in RULES
    assert "cripto desde 2020" in KB


def test_links_are_full_https_urls():
    import app.faq as faq

    src = KB + open(faq.__file__, encoding="utf-8").read()
    assert not re.search(r"\]\(", KB), "no markdown links in the knowledge base"
    assert not re.search(r"(?<!https://)(?<![/\w])t\.me/", src), "t.me links must be full https:// URLs"
    assert "https://t.me/lcaitech_demo_bot" in KB
