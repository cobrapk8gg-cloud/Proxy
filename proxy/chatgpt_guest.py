"""Guest chat protocol adapted from gpt-t6lnn.py by @t5lnn."""

import json
import uuid

import httpx

from .provider_types import ProviderError

BASE = "https://android.chat.openai.com"


def session_headers(state):
    return {
        "User-Agent": "ChatGPT/1.2026.293 (Android 12; sdk_gphone64_x86_64; build 2629319)",
        "oai-package-name": "com.openai.chatgpt",
        "oai-client-type": "android",
        "oai-device-id": state.setdefault("guest_device_id", str(uuid.uuid4())),
        "oai-client-session": state.setdefault(
            "guest_client_session", str(uuid.uuid4())
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }


async def handshake(client, checked, headers):
    data = (
        await checked(
            client,
            "POST",
            BASE + "/backend-anon/sentinel/chat-requirements",
            headers={**headers, "Accept": "application/json"},
            json={},
        )
    ).json()
    for challenge in ("arkose", "turnstile", "proofofwork"):
        requirement = data.get(challenge)
        if requirement is True or (
            isinstance(requirement, dict) and requirement.get("required")
        ):
            raise ProviderError("تطلب خدمة ChatGPT Guest تحققًا إضافيًا لهذه الجلسة.")
    token = data.get("token")
    if not isinstance(token, str) or not token:
        raise ProviderError("لم تصدر خدمة ChatGPT Guest رمز جلسة صالحًا.")
    return token


async def discover(client, checked):
    await handshake(client, checked, session_headers({}))
    return {
        "models": [{"id": "auto", "name": "Auto · ChatGPT Guest"}],
        "default_model": "auto",
        "projects": [],
        "chats": [],
        "capabilities": {"projects": False, "attachments": False, "tools": "emulated"},
    }


async def send(client, checked, prompt, state):
    headers = session_headers(state)
    for cookie in state.get("guest_cookies", []):
        client.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie["domain"],
            path=cookie["path"],
        )
    token = await handshake(client, checked, headers)
    cid = state.get("conversation_id")
    payload = {
        "action": "next",
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [prompt]},
            }
        ],
        "parent_message_id": state.get("parent_message_id") or str(uuid.uuid4()),
        "model": "auto",
        "timezone_offset_min": 180,
        "history_and_training_disabled": True,
        "conversation_mode": {"kind": "primary_assistant"},
        **({"conversation_id": cid} if cid else {}),
    }
    messages = {}
    finished = False
    parent = None
    try:
        async with client.stream(
            "POST",
            BASE + "/backend-anon/f/conversation",
            json=payload,
            headers={
                **headers,
                "Accept": "text/event-stream",
                "openai-sentinel-chat-requirements-token": token,
            },
        ) as response:
            if response.status_code >= 400:
                raise ProviderError(
                    f"رفض ChatGPT Guest الطلب (HTTP {response.status_code}).",
                    429 if response.status_code == 429 else 502,
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    finished = True
                    break
                try:
                    event = json.loads(value)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                item = event.get("v")
                item = item if isinstance(item, dict) else {}
                if event.get("error") or item.get("error"):
                    raise ProviderError("أبلغ ChatGPT Guest عن فشل التوليد.")
                incoming = event.get("conversation_id") or item.get("conversation_id")
                if incoming and cid and incoming != cid:
                    raise ProviderError(
                        "أعاد ChatGPT Guest محادثة أخرى بدل متابعة الجلسة."
                    )
                cid = incoming or cid
                message = event.get("message") or item.get("message") or {}
                if (
                    message.get("author", {}).get("role") != "assistant"
                    or message.get("channel", "final") != "final"
                ):
                    continue
                text = "".join(
                    p
                    for p in message.get("content", {}).get("parts", [])
                    if isinstance(p, str)
                )
                if text.strip():
                    mid = message.get("id")
                    if mid:
                        parent = mid
                    messages[mid or "assistant"] = text
                finished |= (
                    message.get("status") == "finished_successfully"
                    or message.get("end_turn") is True
                )
    except httpx.HTTPError:
        raise ProviderError("انقطع تدفق ChatGPT Guest.") from None
    if not messages or not finished:
        raise ProviderError("لم يكتمل رد ChatGPT Guest.")
    if cid and parent:
        state["conversation_id"] = cid
        state["parent_message_id"] = parent
    state["guest_cookies"] = [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
        for c in client.cookies.jar
    ]
    return "".join(dict.fromkeys(messages.values()))
