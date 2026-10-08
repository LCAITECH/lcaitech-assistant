"""Rate limits and daily budget, persisted in sqlite (no Redis).

- Per IP: sliding 60 s window in memory + daily counter in sqlite.
- Global: daily requests, tokens and estimated USD cost in sqlite, so a restart
  never resets the budget.
IPs are never stored: only a salted SHA-256 prefix.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings


@dataclass
class Verdict:
    ok: bool
    reason: str = ""  # ip_minute | ip_day | global_requests | global_tokens | global_cost
    retry_after: int = 0


class Limiter:
    def __init__(self, settings: Settings):
        self.s = settings
        self.tz = ZoneInfo(settings.day_tz)
        self._lock = threading.Lock()
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        db_dir = os.path.dirname(os.path.abspath(settings.state_db))
        os.makedirs(db_dir, exist_ok=True)
        self.db = sqlite3.connect(settings.state_db, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS daily (day TEXT, key TEXT, requests INTEGER DEFAULT 0,"
            " tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0, PRIMARY KEY (day, key))"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        row = self.db.execute("SELECT v FROM meta WHERE k='salt'").fetchone()
        if row:
            self.salt = row[0]
        else:
            self.salt = secrets.token_hex(16)
            self.db.execute("INSERT INTO meta (k, v) VALUES ('salt', ?)", (self.salt,))
        self._purge()

    # helpers -------------------------------------------------------------
    def ip_hash(self, ip: str) -> str:
        return hashlib.sha256((self.salt + "|" + ip).encode()).hexdigest()[:12]

    def today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def seconds_to_midnight(self) -> int:
        now = datetime.now(self.tz)
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((nxt - now).total_seconds()))

    def _purge(self) -> None:
        cutoff = (datetime.now(self.tz) - timedelta(days=7)).strftime("%Y-%m-%d")
        self.db.execute("DELETE FROM daily WHERE day < ?", (cutoff,))

    def _row(self, day: str, key: str) -> tuple[int, int, float]:
        r = self.db.execute("SELECT requests, tokens, cost FROM daily WHERE day=? AND key=?", (day, key)).fetchone()
        return (r[0], r[1], r[2]) if r else (0, 0, 0.0)

    # api ---------------------------------------------------------------
    def check_and_count(self, ip_h: str) -> Verdict:
        """Check every limit; if all pass, count the request (atomically)."""
        s = self.s
        now = time.monotonic()
        with self._lock:
            day = self.today()
            g_req, g_tok, g_cost = self._row(day, "global")
            if g_req >= s.global_requests_per_day:
                return Verdict(False, "global_requests", self.seconds_to_midnight())
            if g_tok >= s.global_tokens_per_day:
                return Verdict(False, "global_tokens", self.seconds_to_midnight())
            if g_cost >= s.global_cost_usd_per_day:
                return Verdict(False, "global_cost", self.seconds_to_midnight())
            ip_req, _, _ = self._row(day, "ip:" + ip_h)
            if ip_req >= s.ip_per_day:
                return Verdict(False, "ip_day", self.seconds_to_midnight())
            win = self._minute[ip_h]
            while win and now - win[0] >= 60:
                win.popleft()
            if len(win) >= s.ip_per_minute:
                return Verdict(False, "ip_minute", max(1, int(60 - (now - win[0])) + 1))
            win.append(now)
            for key in ("global", "ip:" + ip_h):
                self.db.execute(
                    "INSERT INTO daily (day, key, requests) VALUES (?, ?, 1) "
                    "ON CONFLICT(day, key) DO UPDATE SET requests = requests + 1",
                    (day, key),
                )
            if len(self._minute) > 5000:  # bound memory
                for k in [k for k, v in self._minute.items() if not v or now - v[-1] >= 60]:
                    del self._minute[k]
            return Verdict(True)

    def add_usage(self, ip_h: str, tokens: int, cost: float) -> None:
        with self._lock:
            day = self.today()
            for key in ("global", "ip:" + ip_h):
                self.db.execute(
                    "INSERT INTO daily (day, key, tokens, cost) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(day, key) DO UPDATE SET tokens = tokens + excluded.tokens, cost = cost + excluded.cost",
                    (day, key, int(tokens), float(cost)),
                )

    def global_open(self) -> bool:
        s = self.s
        g_req, g_tok, g_cost = self._row(self.today(), "global")
        return g_req < s.global_requests_per_day and g_tok < s.global_tokens_per_day and g_cost < s.global_cost_usd_per_day

    def usage_today(self) -> dict:
        g_req, g_tok, g_cost = self._row(self.today(), "global")
        return {"requests": g_req, "tokens": g_tok, "cost_usd": round(g_cost, 4)}
