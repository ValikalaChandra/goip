import os

import tempfile

_DB = os.path.join(tempfile.mkdtemp(), "api-test.db")
os.environ["GOIP_DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["GOIP_API_TOKEN"] = "unit-test-token-" + "x" * 30
os.environ["GOIP_SWITCH_ENABLED"] = "false"
os.environ["GOIP_SCHEDULER_ENABLED"] = "false"
os.environ["GOIP_TELEGRAM_POLLING"] = "false"

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app import config
from app.db import Base, Company, Opportunity, PipelineRun, utcnow

TOKEN = os.environ["GOIP_API_TOKEN"]
JSON = {"Content-Type": "application/json"}
AUTH = {**JSON, "Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    Base.metadata.create_all(api.engine)
    api._login_throttle.__init__()
    api._SESSIONS.clear()
    c = TestClient(api.app, base_url="http://127.0.0.1:8001")
    yield c


def test_login_issues_a_random_session_not_the_token(client):
    r = client.post("/api/login", json={"token": TOKEN}, headers=JSON)
    assert r.status_code == 200
    cookie = r.cookies.get("goip_session")
    assert cookie and cookie != TOKEN and TOKEN not in r.headers.get("set-cookie", "")
    assert "samesite=strict" in r.headers["set-cookie"].lower() and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/overview").status_code == 200
    client.post("/api/logout", headers=JSON)
    client.cookies.clear()
    client.cookies.set("goip_session", cookie)
    assert client.get("/api/overview").status_code == 401  # logout really invalidated it server-side


def test_the_raw_token_is_not_accepted_as_a_cookie(client):
    client.cookies.set("goip_session", TOKEN)
    assert client.get("/api/overview").status_code == 401


def test_login_is_throttled_and_a_good_login_is_still_locked_out_meanwhile(client):
    for _ in range(5):
        assert client.post("/api/login", json={"token": "wrong"}, headers=JSON).status_code == 401
    r = client.post("/api/login", json={"token": TOKEN}, headers=JSON)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_throttle_unlocks_and_backs_off():
    now = [0.0]
    t = api.LoginThrottle(limit=2, base_lock=10, clock=lambda: now[0])
    t.failure("a"); t.failure("a")
    assert t.retry_after("a") == 10
    now[0] = 11
    assert t.retry_after("a") == 0
    t.failure("a"); t.failure("a")
    assert t.retry_after("a") == 20  # doubled


def test_unexpected_host_is_refused_dns_rebinding(client):
    r = client.get("/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 400


def test_cross_origin_and_non_json_writes_are_refused(client):
    assert client.post("/api/runs", headers={**AUTH, "Origin": "http://evil.example.com"}, json={}).status_code == 403
    assert client.post("/api/runs", headers={**AUTH, "Origin": "http://127.0.0.1:9999"}, json={}).status_code == 403
    assert client.post("/api/runs", headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/plain"}, content="{}").status_code == 415
    assert client.post("/api/login", headers={"Origin": "null", **JSON}, json={"token": TOKEN}).status_code == 403


def test_unknown_run_export_is_404_and_writes_nothing(client, tmp_path, monkeypatch):
    import app.exports as exports

    out = tmp_path / "exports"
    out.mkdir()
    monkeypatch.setattr(exports, "EXPORT_DIR", out)
    r = client.get("/api/runs/does-not-exist/export.csv", headers=AUTH)
    assert r.status_code == 404 and list(out.iterdir()) == []


def test_illegal_decision_returns_409(client):
    with api.SessionFactory() as s:
        s.add(PipelineRun(id="rx", status="completed", counts={}, started_at=utcnow()))
        s.add(Company(id="cx", identity_key="name:x", name="X", normalized_name="x", created_at=utcnow()))
        s.add(Opportunity(id="ox", public_id="GCCCC3333", run_id="rx", company_id="cx", status="screening"))
        s.commit()
    r = client.post("/api/opportunities/GCCCC3333/decision", headers=AUTH, json={"action": "approve"})
    assert r.status_code == 409


# ---- settings validation (audit: one authenticated write could brick the app or burn money)
@pytest.fixture
def runtime_file(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text(config.CONFIG_PATH.read_text())
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


@pytest.mark.parametrize(
    "values",
    [
        {"schedule": {"hour": 18, "minute": 0, "timezone": "Not/AZone"}},
        {"schedule": {"hour": 99, "minute": 0, "timezone": "Asia/Kolkata"}},
        {"fetch_caps": {"hn_hits": 10**9}},
        {"targets": "everything"},
        {"targets": {"discovered": -5, "screened": 1, "researched": 1, "priority": 1}},
        {"models": {"research": "openai/gpt-4.1-mini; rm -rf /"}},
        {"weights": {"a": 150, "b": -50}},
        {"focus": {"sector": "../../etc/passwd"}},
    ],
)
def test_bad_settings_are_rejected_and_the_file_is_untouched(runtime_file, values):
    before = runtime_file.read_text()
    with pytest.raises(ValueError):
        config.save_runtime(values)
    assert runtime_file.read_text() == before


def test_good_settings_persist_atomically(runtime_file):
    config.save_runtime({"focus": {"sector": "fintech"}})
    assert json.loads(runtime_file.read_text())["focus"]["sector"] == "fintech"
    assert not [p for p in runtime_file.parent.iterdir() if p.name.startswith(".runtime-")]


def test_reconciliation_lists_reasoning_and_the_inspect_endpoint_classifies_the_rest(client):
    from app.db import Signal

    with api.SessionFactory() as s:
        s.add(PipelineRun(id="rr", status="completed", counts={}, started_at=utcnow()))
        s.add(Company(id="cm", identity_key="name:meta", name="Meta", normalized_name="meta", industry="Technology", created_at=utcnow()))
        s.add(Signal(id="sg1", company_id=None, run_id="rr", identity_hint="h1", source_name="HN", source_url="https://news.example.org/a", category="news", title="Former Meta Security Chief Calls Password Access Insane", evidence="Former Meta chief", signal_type="other", discovered_at=utcnow()))
        s.add(Signal(id="sg2", company_id=None, run_id="rr", identity_hint="h2", source_name="HN", source_url="https://news.example.org/b", category="news", title="Markets move on rate news", evidence="rates", signal_type="other", discovered_at=utcnow()))
        s.commit()
    before = client.get("/api/reconciliation", headers=AUTH).json()
    assert before["unclassified"] >= 2
    created = client.post("/api/reconciliation/inspect", headers=AUTH, json={}).json()
    assert created["created"] >= 2
    after = client.get("/api/reconciliation", headers=AUTH).json()
    assert after["unclassified"] == 0
    meta = next(r for r in after["signals"] if r["signal_id"] == "sg1")
    assert meta["classification"] == "ambiguous_match" and meta["candidate_company"] == "Meta"
    reasoning = meta["reasoning"]
    assert reasoning["candidate"]["name"] == "Meta" and reasoning["candidate"]["basis"] == "name"
    assert reasoning["checks"] and reasoning["why_not_higher"] and reasoning["to_confirm"]
    other = next(r for r in after["signals"] if r["signal_id"] == "sg2")
    assert other["classification"] == "unmatched" and other["reasoning"]["candidate"] is None


def test_pages_and_assets_must_revalidate_but_api_responses_are_untouched(client):
    for path in ("/", "/app", "/app.js", "/styles.css", "/theme.css"):
        assert client.get(path).headers.get("cache-control") == "no-cache", path
    assert "cache-control" not in client.get("/api/overview", headers=AUTH).headers


def test_local_assets_are_versioned_so_an_old_cached_copy_cannot_be_reused():
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    for page in ("app.html", "index.html"):
        html = (root / page).read_text()
        local = re.findall(r'(?:href|src)="(/[^"/][^"]*\.(?:css|js))(\?[^"]*)?"', html)
        unversioned = [u for u, q in local if not u.startswith("/vendor/") and not q]
        assert not unversioned, f"{page}: {unversioned}"


def test_lead_detail_carries_the_evidence_trail(client):
    from app.db import Signal

    with api.SessionFactory() as s:
        s.add(PipelineRun(id="re", status="completed", counts={}, started_at=utcnow()))
        s.add(Company(id="ce", identity_key="name:fuck", name="Captchaco", normalized_name="captchaco", created_at=utcnow()))
        s.add(Opportunity(id="oe", public_id="GEEEE5555", run_id="re", company_id="ce", status="needs_review"))
        s.add(Signal(id="se1", company_id="ce", run_id="re", identity_hint="h", source_name="Hacker News front page", source_url="https://github.com/acme/captchaco",
                     parent_domain="github.com", category="community", title="Show HN: Captchaco &#8211; a field guide",
                     evidence='<a href="https://news.ycombinator.com/item?id=50415078">Comments</a>', signal_type="product", discovered_at=utcnow()))
        s.add(Signal(id="se2", company_id="ce", run_id="re", identity_hint="h2", source_name="Hacker News: Who is hiring", source_url="https://news.ycombinator.com/item?id=111",
                     parent_domain="news.ycombinator.com", category="hiring", title="Captchaco | Contract", evidence="Captchaco | Contract see https://news.ycombinator.com/item?id=111", signal_type="hiring", discovered_at=utcnow()))
        s.commit()
    detail = client.get("/api/opportunities/GEEEE5555", headers=AUTH).json()
    by_id = {x["id"]: x for x in detail["signals"]}
    story = by_id["se1"]
    assert story["title"] == "Show HN: Captchaco – a field guide"  # entities decoded
    assert story["source_url"] == "https://github.com/acme/captchaco" and story["parent_domain"] == "github.com"
    assert story["discussion_url"] == "https://news.ycombinator.com/item?id=50415078"
    assert by_id["se2"]["discussion_url"] is None  # the permalink IS the source, so no separate discussion link
    listing = client.get("/api/opportunities?q=Captchaco", headers=AUTH).json()["opportunities"][0]
    assert listing["headline"] == "Show HN: Captchaco – a field guide" or listing["headline"].startswith("Captchaco")
    assert listing["source_name"] and listing["source_url"]


def test_opportunities_are_paginated_and_filtered_in_the_database(client):
    with api.SessionFactory() as s:
        s.add(PipelineRun(id="rp", status="completed", counts={}, started_at=utcnow()))
        for i in range(7):
            s.add(Company(id=f"cp{i}", identity_key=f"name:pg{i}", name=f"PageCo{i}", normalized_name=f"pageco{i}", created_at=utcnow()))
            s.add(Opportunity(id=f"op{i}", public_id=f"GAAAA000{i}", run_id="rp", company_id=f"cp{i}", status="needs_review" if i % 2 else "approved", score=i))
        s.commit()
    first = client.get("/api/opportunities?q=PageCo&limit=3", headers=AUTH).json()
    assert first["total"] == 7 and len(first["opportunities"]) == 3 and first["limit"] == 3 and first["offset"] == 0
    second = client.get("/api/opportunities?q=PageCo&limit=3&offset=3", headers=AUTH).json()
    third = client.get("/api/opportunities?q=PageCo&limit=3&offset=6", headers=AUTH).json()
    ids = [o["id"] for o in first["opportunities"] + second["opportunities"] + third["opportunities"]]
    assert len(ids) == 7 and len(set(ids)) == 7  # pages tile exactly, no overlap, no gap
    approved = client.get("/api/opportunities?q=PageCo&status=approved", headers=AUTH).json()
    assert approved["total"] == 4 and all(o["status"] == "approved" for o in approved["opportunities"])
    assert client.get("/api/opportunities?limit=0", headers=AUTH).status_code == 422
    assert client.get("/api/opportunities?limit=501", headers=AUTH).status_code == 422
    assert client.get("/api/opportunities?offset=-1", headers=AUTH).status_code == 422


def test_a_run_can_carry_the_operators_goal_and_the_trace_is_readable(client, monkeypatch):
    from app.agents import memory
    from app.agents.runtime import Step

    seen = {}

    async def fake_local(session, goal=""):
        seen["goal"] = goal
        return "r-goal"

    monkeypatch.setattr(api, "_local_run", fake_local)
    monkeypatch.setattr(api, "get_runtime", lambda: None)
    assert client.post("/api/runs", headers=AUTH, json={"goal": "  find  freelance   fintech jobs "}).json()["run_id"] == "r-goal"
    assert seen["goal"] == "find freelance fintech jobs"  # whitespace normalised
    assert client.post("/api/runs", headers=AUTH, json={}).status_code == 200 and seen["goal"] == ""
    assert client.post("/api/runs", headers=AUTH, json={"goal": "x" * 301}).status_code == 422

    with api.SessionFactory() as s:
        s.add(PipelineRun(id="rt", status="completed", counts={"agent_modes": {"discover": "llm"}, "sources": ["hn_hiring"], "judged": 3}, started_at=utcnow()))
        s.commit()
        memory.record_steps(s, "rt", "goip-discovery", "discover", [Step(1, "Demand sources first.", "fetch_source", {"source": "hn_hiring"}, "fetched 2")], "llm")
    body = client.get("/api/runs/rt/trace", headers=AUTH).json()
    assert body["modes"] == {"discover": "llm"} and body["sources"] == ["hn_hiring"] and body["trace"][0]["tool"] == "fetch_source"
    assert client.get("/api/runs/latest/trace", headers=AUTH).status_code == 200
    assert client.get("/api/runs/nope/trace", headers=AUTH).status_code == 404
    assert client.get("/api/runs/rt/trace").status_code == 401
