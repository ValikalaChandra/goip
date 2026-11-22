import json

import pytest

import app.config as config


@pytest.fixture(autouse=True)
def no_tracing_upload(monkeypatch):
    """Tests must never upload to LangSmith, even when the developer's shell has the tracing variables set.

    LangGraph auto-traces whenever LANGSMITH_TRACING/LANGCHAIN_TRACING_V2 and a key are in the environment,
    which would send test runs to the real project.
    """
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    from app.observability import tracing

    monkeypatch.setattr(tracing, "_enabled", False)


@pytest.fixture(autouse=True)
def no_real_model_and_no_network(monkeypatch):
    """Tests never call the real model and never reach the internet.

    The settings loaded from the developer's .env carry a real OpenRouter key; blank it for the test process, and make any
    non-loopback socket connection fail loudly so a test that would spend money or hit a live site cannot do so quietly.
    """
    import socket

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "openrouter_api_key", "")
    real_connect = socket.socket.connect

    def guarded(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else str(address)
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost", "0.0.0.0") and not host.startswith("/"):
            raise RuntimeError(f"network access is blocked in tests: {host}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def hermetic_runtime(tmp_path, monkeypatch):
    """Every test gets its own copy of config/runtime.json with no sector focus.

    Tests must neither depend on nor modify the operator's real configuration.
    """
    data = json.loads(config.CONFIG_PATH.read_text())
    data["focus"] = {"sector": None}
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(config, "CONFIG_PATH", path)
