"""Vertex AI list prices (USD per 1M tokens), Standard PayGo, checked 2026-10-08 at
https://cloud.google.com/vertex-ai/generative-ai/pricing . Thinking tokens bill as output.
Explicit cache storage: USD 1 per 1M token-hours for every Flash / Flash-Lite model.

Gemini 3.6 / 3.7 / 3.8 Flash have introductory pricing through 2026-12-31
(0.75 / 3.75 global) and standard pricing from 2027-01-01 (1.50 / 7.50 global);
cost() picks the right one by date so the daily cap stays accurate after New Year.
"""
from __future__ import annotations

from datetime import date

# model -> {"global": (input, cached_input, output), "other": (...)}
_FLASH_NEW_INTRO = {"global": (0.75, 0.075, 3.75), "other": (0.825, 0.0825, 4.125)}
_FLASH_NEW_STD = {"global": (1.50, 0.15, 7.50), "other": (1.65, 0.165, 8.25)}
INTRO_UNTIL = date(2026, 12, 31)

PRICES: dict[str, dict[str, tuple[float, float, float]]] = {
    "gemini-3.1-flash-lite": {"global": (0.25, 0.025, 1.50), "other": (0.275, 0.0275, 1.65)},
    "gemini-3.5-flash-lite": {"global": (0.30, 0.03, 2.50), "other": (0.33, 0.033, 2.75)},
    "gemini-3.5-flash": {"global": (1.50, 0.15, 9.00), "other": (1.65, 0.165, 9.90)},
    "gemini-2.5-flash-lite": {"global": (0.10, 0.01, 0.40), "other": (0.10, 0.01, 0.40)},
    "gemini-2.5-flash": {"global": (0.30, 0.03, 2.50), "other": (0.30, 0.03, 2.50)},
}
NEW_FLASH = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash")
UNKNOWN = (1.65, 0.165, 9.90)  # conservative: priced like the most expensive Flash
CACHE_STORAGE_PER_M_TOKEN_HOUR = 1.0


def prices(model: str, location: str, today: date | None = None) -> tuple[float, float, float]:
    key = "global" if location == "global" else "other"
    if model in NEW_FLASH:
        table = _FLASH_NEW_INTRO if (today or date.today()) <= INTRO_UNTIL else _FLASH_NEW_STD
        return table[key]
    table = PRICES.get(model)
    return table[key] if table else UNKNOWN


def cost(model: str, location: str, prompt: int, cached: int, output: int, today: date | None = None) -> float:
    p_in, p_cached, p_out = prices(model, location, today)
    return (max(0, prompt - cached) * p_in + cached * p_cached + output * p_out) / 1_000_000


def cache_cost(model: str, location: str, tokens: int, ttl_s: int) -> float:
    """Creating a cache bills its tokens once as input, plus storage for the TTL."""
    p_in, _, _ = prices(model, location)
    return (tokens * p_in + tokens * (ttl_s / 3600) * CACHE_STORAGE_PER_M_TOKEN_HOUR) / 1_000_000
