"""Register GOIP agents against the local Switch server and create the room.

Prints statuses and identifiers only. It does not print credentials.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.config import SECRET_DIR, get_settings, registration_key
from app.integrations.switch_client import SwitchClient, load_agent_keys


async def _personal_key(client: httpx.AsyncClient, settings) -> str:
    env_path = settings.switch_env_file
    if not env_path:
        return ""
    values = {}
    for line in open(env_path, encoding="utf-8", errors="replace"):
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    email = values.get("GATEWAY_ADMIN_EMAIL", "")
    password = values.get("GATEWAY_ADMIN_PASSWORD", "")
    if not email or not password:
        return ""
    for base in {settings.switch_gateway_url.rstrip("/"), settings.switch_base_url.rstrip("/")}:
        try:
            response = await client.post(f"{base}/auth/login", json={"email": email, "password": password}, timeout=15)
        except httpx.HTTPError as exc:
            print(f"login {base} {exc.__class__.__name__}")
            continue
        print(f"login {base} {response.status_code}")
        if response.status_code != 200:
            continue
        created = await client.post(f"{base}/api-keys", json={"label": "goip-registration"}, timeout=15)
        print(f"api-key {created.status_code}")
        if created.status_code != 200:
            continue
        key = created.json().get("key", "")
        path = SECRET_DIR / "registration.key"
        path.write_text(key, encoding="utf-8")
        path.chmod(0o600)
        return key
    return ""


async def main() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(follow_redirects=False) as http:
        personal = await _personal_key(http, settings)
        key = personal or registration_key(settings)
        print("registration_key_source", "personal" if personal else ("configured" if key else "missing"))
        switch = SwitchClient(settings.switch_base_url, key, load_agent_keys())
        print("health", await switch.health(http))
        if not key:
            return
        await switch.register_all(http)
        print("agents", len(switch.agent_keys))
        try:
            await switch.allow_owner_agents(http)
            print("addressing", "updated")
        except Exception as exc:  # noqa: BLE001
            print("addressing_error", exc.__class__.__name__, str(exc)[:180])
        try:
            listed = await switch.operate(http, "goip-orchestrator", "list_agents", {"name_contains": "goip-"})
            rows = listed.get("result") or listed
            if isinstance(rows, list):
                print("owners", sorted({row.get("owner_name") for row in rows}))
        except Exception as exc:  # noqa: BLE001
            print("list_agents_error", str(exc)[:180])
        try:
            room = await switch.ensure_room(http)
            print("room", room.get("id"), room.get("name"))
        except Exception as exc:  # noqa: BLE001
            print("room_error", str(exc)[:300])
            try:
                created = await switch.operate(
                    http,
                    "goip-orchestrator",
                    "create_room",
                    {
                        "name": "GOIP Opportunity Intelligence",
                        "description": "GOIP research room for a human operator and seven specialist agents.",
                        "agent_names": list(switch.agent_keys),
                        "internal_only": True,
                        "instructions": "Separate facts from inference. Do not send external outreach.",
                    },
                )
                result = created.get("result") or created
                from app.integrations.switch_client import save_room

                save_room({"id": result["id"], "name": result.get("name"), "transport_room_id": result.get("transport_room_id"), "internal_only": True})
                print("room_internal", result.get("id"))
            except Exception as inner:  # noqa: BLE001
                print("room_internal_error", str(inner)[:300])


if __name__ == "__main__":
    asyncio.run(main())
