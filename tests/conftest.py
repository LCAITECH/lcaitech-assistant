import importlib
import sys

import pytest
from fastapi.testclient import TestClient

ORIGIN = "https://portfolio.lcaitech.com"


def make_client(tmp_path, monkeypatch, **env):
    base = {
        "LLM_PROVIDER": "mock",
        "STATE_DB": str(tmp_path / "state.db"),
        "IP_PER_MINUTE": "10",
        "IP_PER_DAY": "50",
        "GLOBAL_REQUESTS_PER_DAY": "1000",
    }
    base.update({k: str(v) for k, v in env.items()})
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "MOCK_FAIL"):
        if k not in env:
            monkeypatch.delenv(k, raising=False)
    for mod in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[mod]
    main = importlib.import_module("app.main")
    return TestClient(main.app, client=("127.0.0.1", 50000)), main


@pytest.fixture
def client(tmp_path, monkeypatch):
    c, _ = make_client(tmp_path, monkeypatch)
    return c


@pytest.fixture
def factory(tmp_path, monkeypatch):
    return lambda **env: make_client(tmp_path, monkeypatch, **env)


def ask(c, text, lang="es", origin=ORIGIN, ip="203.0.113.7", history=None):
    msgs = (history or []) + [{"role": "user", "content": text}]
    headers = {"CF-Connecting-IP": ip}
    if origin:
        headers["Origin"] = origin
    return c.post("/chat", json={"messages": msgs, "lang": lang}, headers=headers)
