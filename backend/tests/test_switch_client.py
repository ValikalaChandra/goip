import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import httpx
import pytest

import app.integrations.switch_client as sc
from app.integrations.switch_client import AGENT_SPECS, SwitchClient


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch):
    saved = []
    monkeypatch.setattr(sc, "save_agent_keys", lambda keys: saved.append(dict(keys)))
    return saved


def _all_keys():
    return {name: {"id": f"id-{name}", "api_key": f"key-{name}"} for name, _, _ in AGENT_SPECS}


async def test_no_registration_key_is_needed_when_every_agent_is_already_registered():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(500)

    client = SwitchClient("http://switch", registration_key="", agent_keys=_all_keys())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        keys = await client.register_all(http)
    assert len(keys) == len(AGENT_SPECS) and calls == []  # nothing contacted


async def test_a_missing_agent_still_requires_a_registration_key():
    keys = _all_keys()
    keys.pop("goip-strategy")
    client = SwitchClient("http://switch", registration_key="", agent_keys=keys)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        with pytest.raises(RuntimeError, match="1 agent"):
            await client.register_all(http)


async def test_only_the_missing_agent_is_registered():
    keys = _all_keys()
    keys.pop("goip-strategy")
    posted = []

    def handler(request):
        posted.append(request.url.path)
        return httpx.Response(200, json={"id": "new-id", "api_key": "new-key"})

    client = SwitchClient("http://switch", registration_key="reg", agent_keys=keys)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        out = await client.register_all(http)
    assert posted == ["/agents"] and out["goip-strategy"]["api_key"] == "new-key" and out["goip-discovery"]["api_key"] == "key-goip-discovery"
