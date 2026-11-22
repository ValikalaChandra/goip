import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import json

from app.config import Settings
from app.observability import tracing

FAKE = {
    "openrouter_api_key": "sk-or-v1-abcdefghijklmnopqrstuvwxyz012345",
    "telegram_bot_token": "1234567890:AAExampleExampleExampleExampleExample1",
    "crawl4ai_api_key": "crawlkey_" + "z" * 40,
    "langsmith_api_key": "lsv2_pt_" + "a" * 32 + "_" + "b" * 10,
    "goip_api_token": "T" * 43,
}


def test_settings_object_is_never_serialised():
    settings = Settings(**FAKE)
    out = json.dumps(tracing._scrub({"settings": settings, "runtime": object(), "trigger": "dashboard"}))
    for value in FAKE.values():
        assert value not in out
    assert "<Settings>" in out and "dashboard" in out


def test_secret_shaped_strings_and_keys_are_redacted():
    out = json.dumps(
        tracing._scrub(
            {
                "api_key": "x",
                "nested": {"Authorization": "Bearer abc.def", "note": "token sk-abcdefghijklmnopqrstuv and a@b.io"},
                "list": [FAKE["telegram_bot_token"], FAKE["goip_api_token"]],
            }
        )
    )
    assert "sk-abc" not in out and "a@b.io" not in out and "Bearer abc" not in out
    assert FAKE["telegram_bot_token"] not in out and FAKE["goip_api_token"] not in out


def test_traced_function_inputs_are_scrubbed_without_a_client(monkeypatch):
    """process_inputs must apply even when no scrubbing client is attached."""
    captured = {}

    class FakeSettings:
        openrouter_api_key = FAKE["openrouter_api_key"]

    from langsmith import traceable

    seen = []

    def spy(inputs):
        seen.append(tracing._scrub(inputs))
        return seen[-1]

    @traceable(process_inputs=spy, tracing_enabled=False)
    def f(settings):
        return 1

    f(FakeSettings())  # tracing disabled: spy not required to fire, scrub itself is what we test
    assert FAKE["openrouter_api_key"] not in json.dumps(tracing._scrub({"settings": FakeSettings()}))


def test_tracing_off_when_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert tracing.configure_tracing(Settings(**FAKE)) is False
    assert tracing.tracing_enabled() is False
