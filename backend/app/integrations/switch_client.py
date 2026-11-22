from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import SECRET_DIR

AGENT_SPECS = [
    ("goip-discovery", "GOIP Discovery Agent", "Finds companies and business signals from permitted public sources and reports original URLs."),
    ("goip-company-research", "GOIP Company Research Agent", "Investigates a company and separates observed facts from inference."),
    ("goip-technical-intelligence", "GOIP Technical Intelligence Agent", "Matches public repositories and technical evidence to a company signal."),
    ("goip-qualification", "GOIP Opportunity Qualification Agent", "Scores whether a signal is a plausible freelance opportunity and explains the score."),
    ("goip-strategy", "GOIP Business Strategy Agent", "Recommends a service and a next step. It does not send outreach."),
    ("goip-quality-assurance", "GOIP Quality Assurance Agent", "Checks that claims are supported by stored source evidence."),
    ("goip-orchestrator", "GOIP Orchestrator", "Assigns work to the specialist agents and consolidates the result for the human operator."),
]

KEYS_PATH = SECRET_DIR / "switch-agents.json"
ROOM_PATH = SECRET_DIR / "switch-room.json"


def load_agent_keys() -> dict:
    if not KEYS_PATH.exists():
        return {}
    return json.loads(KEYS_PATH.read_text(encoding="utf-8"))


def save_agent_keys(payload: dict) -> None:
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    KEYS_PATH.chmod(0o600)


def load_room() -> dict:
    if not ROOM_PATH.exists():
        return {}
    return json.loads(ROOM_PATH.read_text(encoding="utf-8"))


def save_room(payload: dict) -> None:
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    ROOM_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    ROOM_PATH.chmod(0o600)


class SwitchClient:
    def __init__(self, base_url: str, registration_key: str = "", agent_keys: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.registration_key = registration_key
        self.agent_keys = agent_keys or {}

    def _agent_headers(self, name: str, connection_id: str | None = None) -> dict[str, str]:
        record = self.agent_keys[name]
        headers = {"Authorization": f"Bearer {record['api_key']}", "Content-Type": "application/json"}
        if connection_id:
            headers["X-Switch-Connection-Id"] = connection_id
        return headers

    async def health(self, client: httpx.AsyncClient) -> bool:
        response = await client.get(f"{self.base_url}/health", timeout=5)
        return response.status_code == 200 and response.json().get("status") == "ok"

    async def register_all(self, client: httpx.AsyncClient) -> dict:
        if not self.registration_key:
            raise RuntimeError("Switch registration key is not configured")
        headers = {"Authorization": f"Bearer {self.registration_key}", "Content-Type": "application/json"}
        for name, display, description in AGENT_SPECS:
            if name in self.agent_keys and self.agent_keys[name].get("api_key"):
                continue
            body = {
                "name": name,
                "display_name": display,
                "description": description,
                "connector_type": "goip",
                "integration_profile": {
                    "connection_model": "session_addressable",
                    "message_exchange": True,
                    "pre_invocation_mediation": [],
                    "post_invocation_mediation": [],
                    "event_reporting": [],
                },
                "metadata": {"product": "goip"},
                "overwrite": False,
            }
            response = await client.post(f"{self.base_url}/agents", headers=headers, content=json.dumps(body), timeout=30)
            if response.status_code == 409 and name not in self.agent_keys:
                raise RuntimeError(f"{name} already exists in Switch but this machine has no saved API key")
            response.raise_for_status()
            payload = response.json()
            self.agent_keys[name] = {"id": payload["id"], "api_key": payload["api_key"], "display_name": display}
        save_agent_keys(self.agent_keys)
        return self.agent_keys

    async def allow_owner_agents(self, client: httpx.AsyncClient) -> None:
        names = [name for name, _, _ in AGENT_SPECS]
        for name in names:
            editor = next(other for other in names if other != name)
            body = {"agent_id": self.agent_keys[name]["id"], "addressing": "anyone"}
            response = await client.post(
                f"{self.base_url}/agents/{self.agent_keys[editor]['id']}/ops/update_agent_detail",
                headers=self._agent_headers(editor),
                content=json.dumps(body),
                timeout=30,
            )
            response.raise_for_status()

    async def operate(
        self,
        client: httpx.AsyncClient,
        agent_name: str,
        operation: str,
        body: dict,
        connection_id: str | None = None,
    ) -> dict:
        response = await client.post(
            f"{self.base_url}/agents/{self.agent_keys[agent_name]['id']}/ops/{operation}",
            headers=self._agent_headers(agent_name, connection_id),
            content=json.dumps(body),
            timeout=40,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"{operation} failed: {response.status_code} {response.text[:300]}")
        return response.json()

    async def ensure_room(self, client: httpx.AsyncClient, connection_id: str | None = None) -> dict:
        existing = load_room()
        if existing.get("id"):
            return existing
        created = await self.operate(
            client,
            "goip-orchestrator",
            "create_room",
            {
                "name": "GOIP Opportunity Intelligence",
                "description": "Collaborative business-development room where GOIP agents discover, investigate, qualify and discuss freelance opportunities with a human operator.",
                "agent_names": [name for name, _, _ in AGENT_SPECS],
                "channel_type": "channel_public",
                "internal_only": False,
                "instructions": (
                    "GOIP agents separate observed facts, inferences, and recommendations. "
                    "They never send email, LinkedIn, or other external outreach. "
                    "Address @goip-orchestrator to approve, reject, request more research, or ask for a draft."
                ),
            },
            connection_id,
        )
        result = created.get("result") or created
        save_room({"id": result["id"], "name": result.get("name"), "transport_room_id": result.get("transport_room_id")})
        return load_room()

    async def post(self, client: httpx.AsyncClient, agent_name: str, room_id: str, content: str) -> dict:
        response = await client.post(
            f"{self.base_url}/agents/{self.agent_keys[agent_name]['id']}/message",
            headers=self._agent_headers(agent_name),
            content=json.dumps({"room_id": room_id, "content": content, "metadata": {"product": "goip"}}),
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"message failed: {response.status_code} {response.text[:300]}")
        return response.json()
