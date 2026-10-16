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
    for p in ["USD 250", "USD 600", "USD 2.500", "USD 1.200", "USD 1.500", "USD 800", "USD 2.000"]:
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


def test_packages_match_site_no_invented_features():
    svc = open("knowledge/02_servicios.md", encoding="utf-8").read()
    assert "P0 · ~1 semana · Starter: un bot o una automatización · desde USD 250" in svc
    assert "El paquete más barato es **P0" in svc
    pkgs = svc.split("## Para proyectos cripto")[1].split("## Paquete más barato")[0]
    for bad in ["Panel admin", "Docker", "Discord opcional", "VM Linux"]:
        assert bad not in pkgs


def test_prompt_cheapest_rule():
    from app import prompt
    src = open(prompt.__file__, encoding="utf-8").read()
    assert "MÁS BARATO es P0 Starter, desde USD 250" in src


def test_clients_section_facts_no_testimonial():
    clients = open("knowledge/08_clientes.md", encoding="utf-8").read()
    assert "https://portfolio.lcaitech.com/#clients" in clients
    assert "Ingeniería Gabriel Gomez SRL" in clients
    assert "PENDIENTE" in clients
    assert "NUNCA digas que existe un testimonio" in clients
    assert "4K" in clients and "MercadoLibre" in clients
    assert "NO** es uno de los paquetes" in clients
    from app.prompt import RULES
    assert "#clients" in RULES and "PENDIENTE" in RULES
    assert "NUNCA digas que existe un testimonio" in RULES
    assert "NO es un paquete P0–P8" in RULES
