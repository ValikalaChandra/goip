from __future__ import annotations

import json

import httpx


async def send_message(client: httpx.AsyncClient, token: str, chat_id: str, text: str) -> dict:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        timeout=30,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "telegram_send_failed")
    return payload


async def send_document(client: httpx.AsyncClient, token: str, chat_id: str, filename: str, content: bytes, caption: str) -> dict:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data={"chat_id": chat_id, "caption": caption[:900]},
        files={"document": (filename, content, "text/csv" if filename.endswith(".csv") else "application/json")},
        timeout=60,
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "telegram_document_failed")
    return payload


async def get_me(client: httpx.AsyncClient, token: str) -> dict:
    response = await client.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20)
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("telegram_auth_failed")
    user = payload.get("result") or {}
    return {"id": user.get("id"), "username": user.get("username")}


def authorized(chat_id: str | int, allowed: str) -> bool:
    return str(chat_id) == str(allowed) and bool(allowed)


def authorized_message(message: dict, allowed_chat: str, allowed_users: str = "") -> bool:
    """The chat must match, and the person must be allowed.

    In a private chat the sender is the chat itself. In a group, every member shares the chat id, so a member
    must also be on the allowlist; otherwise anyone who joins the group could approve leads and pull reports.
    """
    chat = message.get("chat") or {}
    if not authorized(chat.get("id", ""), allowed_chat):
        return False
    sender = str((message.get("from") or {}).get("id", ""))
    if not sender:
        return False
    if chat.get("type", "private") == "private":
        return sender == str(chat.get("id"))
    return sender in {u.strip() for u in (allowed_users or "").split(",") if u.strip()}


def parse_command(text: str) -> tuple[str, str]:
    parts = (text or "").strip().split(maxsplit=1)
    if not parts or not parts[0].startswith("/"):
        return "", text or ""
    command = parts[0].split("@", 1)[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument
