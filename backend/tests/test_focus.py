import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import json
from types import SimpleNamespace

import pytest

from app.agents import chat
from app.discovery.focus import clean_term, feed_sector_for, matches_focus, parse_focus_term
from app.discovery.gather import Gatherer
from app.discovery.extract import RawItem
from tests.support import ScriptedLLM


@pytest.mark.parametrize(
    "message, term",
    [
        ("FOCUS ON BANKING", "banking"),
        ("focus on banking", "banking"),
        ("@goip-orchestrator focus only on climate-tech startups", "climate-tech startups"),
        ("focus on banking and then run", "banking"),
        ("focus on AI agents please", "AI agents"),
        ("only healthcare", "healthcare"),
        ("concentrate on supply chain software", "supply chain software"),
        ("narrow down to payments, lending", "payments, lending"),
        ("specialise in insurance", "insurance"),
    ],
)
def test_focus_is_the_operators_own_words(message, term):
    assert parse_focus_term(message, explicit_only=True) == (term, False)


@pytest.mark.parametrize("message", ["focus", "focus on", "focus on ../../etc/passwd", "focus on <script>alert(1)</script>", "show me only high priority leads please", "what is fintech", "focus on jobs", "focus on freelance work", "focus on " + "x" * 90])
def test_things_that_are_not_a_usable_focus_are_not_one(message):
    term, clear = parse_focus_term(message, explicit_only=True)
    assert term is None and not clear


def test_clear_is_recognised_and_beats_a_term():
    assert parse_focus_term("clear focus") == (None, True)
    assert parse_focus_term("reset the filter") == (None, True)


def test_a_bare_sector_word_in_a_request_is_kept_as_the_operators_word():
    assert parse_focus_term("run and find me banking leads") == ("banking", False)  # not "fintech"
    assert parse_focus_term("find freelance healthtech jobs") == ("healthtech", False)


@pytest.mark.parametrize(
    "focus, text, expected",
    [
        ("banking", "Challenger bank raises $50M", True),
        ("banking", "Banks warn of new fraud wave", True),
        ("banking", "Retail banking app adds budgeting", True),
        ("banking", "Acme files for bankruptcy protection", False),     # a look-alike, not the topic
        ("banking", "Game studio ships a new console", False),
        ("banking", "Payments startup raises Series A", False),         # related, but not what was asked for
        ("fintech", "Payments startup raises Series A", True),          # a named sector keeps its broader vocabulary
        ("fintech", "Game studio ships a new console", False),
        ("AI agents", "Startup builds AI agents for support", True),
        ("AI agents", "Startup builds AI tooling", False),               # both words are required
        ("AI agents", "Paid parking agents strike", False),              # 'ai' must be a whole word
        ("banking and insurance", "Insurance carrier modernises claims", True),  # either topic
        ("banking and insurance", "Bank opens a branch", True),
        ("banking and insurance", "Game studio ships a console", False),
        ("freelance banking jobs", "Bank hiring a contractor", True),   # generic words never have to appear
        (None, "anything at all", True),
        ("", "anything at all", True),
    ],
)
def test_matching_is_about_the_topic_not_a_wider_category(focus, text, expected):
    assert matches_focus(focus, text) is expected


def test_a_related_trade_feed_is_an_extra_source_never_a_wider_filter():
    assert feed_sector_for("banking") == "fintech" and feed_sector_for("healthcare") == "healthtech"
    assert feed_sector_for("gardening") is None and feed_sector_for(None) is None


def test_setting_a_focus_saves_the_word_and_says_so(tmp_path, monkeypatch):
    import app.config as config

    path = tmp_path / "runtime.json"
    path.write_text(config.CONFIG_PATH.read_text())
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    card = chat.set_focus("banking")
    saved = json.loads(path.read_text())["focus"]
    assert saved == {"term": "banking", "sector": "fintech"} and chat.current_focus() == "banking"
    assert "Focus set · banking" in card and "only postings and stories about **banking**" in card
    assert "fintech trade feeds are read as an extra source" in card and "Focus set · fintech" not in card
    unrelated = chat.set_focus("gardening")
    assert "trade feeds" not in unrelated and json.loads(path.read_text())["focus"] == {"term": "gardening", "sector": None}


def test_a_saved_focus_from_before_this_change_still_works(tmp_path, monkeypatch):
    import app.config as config

    path = tmp_path / "runtime.json"
    data = json.loads(config.CONFIG_PATH.read_text())
    data["focus"] = {"sector": "fintech"}  # the old shape
    path.write_text(json.dumps(data))
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    assert chat.current_focus() == "fintech"
    config.validate_runtime(config.load_runtime())


@pytest.mark.parametrize("focus", [{"term": "a/b"}, {"term": "x" * 61}, {"term": "<b>"}, {"term": 5}, {"term": "ok", "sector": "astrology"}, {"topic": "x"}])
def test_the_saved_focus_is_validated(focus, tmp_path, monkeypatch):
    import app.config as config

    path = tmp_path / "runtime.json"
    path.write_text(config.CONFIG_PATH.read_text())
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    with pytest.raises(ValueError):
        config.save_runtime({"focus": focus})


def _gatherer(term, feeds_called=None):
    g = object.__new__(Gatherer)
    g.sector = term
    g.feed_sector = feed_sector_for(term)
    return g


def test_the_gatherer_only_adds_trade_feeds_for_a_related_focus_and_filters_them():
    banking, garden = _gatherer("banking"), _gatherer("gardening")
    assert "sector_feeds" in banking.available() and "sector_feeds" not in garden.available()
    items = [RawItem("S", "https://x.example/1", "Challenger bank raises $50M"), RawItem("S", "https://x.example/2", "Payments startup raises Series A")]
    assert [i.title for i in banking._focus(items)] == ["Challenger bank raises $50M"]  # the payments story is related, not about banking


async def test_the_orchestrator_plans_with_the_operators_word_not_a_category():
    from app.agents.orchestrator import plan_run

    t = SimpleNamespace(llm=ScriptedLLM([{"focus": "banking", "sources_to_prefer": ["hn_hiring"], "notes": "banking first"}]), session=None)
    t.session = type("S", (), {"scalars": lambda *a, **k: type("R", (), {"all": lambda s: []})(), "execute": lambda *a, **k: type("R", (), {"all": lambda s: []})()})()
    plan = await plan_run(t, "find freelance banking jobs")
    assert plan.mode == "llm" and plan.focus == "banking"
    t.llm = ScriptedLLM([None])
    fallback = await plan_run(t, "find freelance banking jobs")
    assert fallback.mode == "fallback" and fallback.focus == "banking"
    t.llm = ScriptedLLM([{"focus": "../../etc", "notes": "x"}])
    assert (await plan_run(t, "find freelance banking jobs")).focus == "banking"  # an unsafe model value falls back to the request


async def test_focus_on_banking_in_the_room_saves_banking_not_fintech(tmp_path, monkeypatch):
    import app.config as config
    from tests.test_chat import _runtime, factory  # noqa: F401  (reuse the room fixtures)

    path = tmp_path / "runtime.json"
    path.write_text(config.CONFIG_PATH.read_text())
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base

    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    rt = _runtime(sessionmaker(bind=engine, expire_on_commit=False, autoflush=False))
    await rt._handle_message("goip-orchestrator", {"addressed": True, "sender_name": "user", "sender_kind": "user", "body": "@goip-orchestrator FOCUS ON BANKING"})
    assert json.loads(path.read_text())["focus"]["term"] == "banking"
    assert rt.posts[-1][1].startswith("#### Focus set · banking") and "fintech" not in rt.posts[-1][1].split("\n\n")[0]
