"""OpenAI Responses and Google Gemini Developer API adapters."""

import base64
from urllib.parse import quote

from .provider_types import ProviderError

OPENAI = "https://api.openai.com/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta"


def api_headers(account):
    if account["provider"] == "openai_api":
        return {"Authorization": "Bearer " + account["credential"]}
    return {"x-goog-api-key": account["credential"]}


def openai_text_model(model):
    return model.startswith(
        ("gpt-", "chatgpt-", "o1", "o3", "o4", "ft:gpt-")
    ) and not any(
        kind in model
        for kind in (
            "audio",
            "realtime",
            "transcribe",
            "tts",
            "image",
            "instruct",
            "deep-research",
        )
    )


async def discover(client, checked, account):
    headers = api_headers(account)
    models = []
    if account["provider"] == "openai_api":
        data = (
            await checked(client, "GET", OPENAI + "/models", headers=headers)
        ).json()
        models = [
            {"id": slug, "name": slug}
            for item in data.get("data", [])
            if isinstance(slug := item.get("id"), str) and openai_text_model(slug)
        ]
        models.sort(key=lambda item: item["id"])
        default = next(
            (m["id"] for m in models if m["id"] in ("gpt-5-mini", "gpt-4o-mini")),
            None,
        )
    else:
        token = ""
        seen = set()
        while True:
            data = (
                await checked(
                    client,
                    "GET",
                    GEMINI + "/models",
                    headers=headers,
                    params={
                        "pageSize": 1000,
                        **({"pageToken": token} if token else {}),
                    },
                )
            ).json()
            for item in data.get("models", []):
                name = item.get("name", "")
                if (
                    name.startswith("models/gemini-")
                    and "generateContent" in item.get("supportedGenerationMethods", [])
                    and not any(
                        kind in name
                        for kind in ("-image", "-tts", "native-audio", "-live")
                    )
                ):
                    slug = name.removeprefix("models/")
                    models.append({"id": slug, "name": item.get("displayName") or slug})
            token = data.get("nextPageToken")
            if not token:
                break
            if token in seen:
                raise ProviderError("كرر Gemini API صفحة النماذج.")
            seen.add(token)
        default = next(
            (m["id"] for m in models if m["id"] == "gemini-2.5-flash"),
            None,
        )
    if not models:
        raise ProviderError("لم يعرض مفتاح API نماذج دردشة متاحة.")
    return {
        "models": models,
        "default_model": default or models[0]["id"],
        "projects": [],
        "chats": [],
        "capabilities": {"projects": False, "attachments": True, "tools": "emulated"},
    }


def upload(account, name, mime, data):
    images = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if account["provider"] == "gemini_api":
        supported = (images - {"image/gif"}) | {
            "image/heic",
            "image/heif",
            "text/plain",
        }
    else:
        supported = images
    if mime not in supported | {"application/pdf"}:
        raise ProviderError("نوع الملف غير مدعوم لدى مزوّد API المختار.", 400)
    return {
        "name": name,
        "mime": mime,
        "inline_data": base64.b64encode(data).decode("ascii"),
    }


async def send(client, checked, account, prompt, settings, attachments):
    model = settings.get("model") or account.get("catalog", {}).get("default_model")
    if not model:
        raise ProviderError("اربط مفتاح API واختر نموذجًا أولًا.", 400)
    headers = api_headers(account)
    if sum(len(a["inline_data"]) for a in attachments) > 18 * 1024 * 1024:
        raise ProviderError("حجم المرفقات المضمّنة مجتمعة يتجاوز 18 MB.", 413)
    limit = settings.get("max_tokens")
    if not settings.get("_explicit_output_limit") and limit == 16384:
        limit = None
    if account["provider"] == "openai_api":
        parts = [{"type": "input_text", "text": prompt}]
        for a in attachments:
            data_url = "data:" + a["mime"] + ";base64," + a["inline_data"]
            if a["mime"] == "application/pdf":
                parts.append(
                    {"type": "input_file", "filename": a["name"], "file_data": data_url}
                )
            else:
                parts.append({"type": "input_image", "image_url": data_url})
        payload = {
            "model": model,
            "input": [{"role": "user", "content": parts}],
            "store": False,
        }
        if limit is not None:
            payload["max_output_tokens"] = limit
        data = (
            await checked(
                client, "POST", OPENAI + "/responses", headers=headers, json=payload
            )
        ).json()
        if data.get("error") or data.get("status") != "completed":
            raise ProviderError("لم يكتمل رد OpenAI API.")
        text = "".join(
            part.get("text", "")
            for item in data.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    else:
        parts = [{"text": prompt}] + [
            {"inlineData": {"mimeType": a["mime"], "data": a["inline_data"]}}
            for a in attachments
        ]
        generation = {}
        if settings.get("temperature") is not None:
            generation["temperature"] = settings["temperature"]
        if limit is not None:
            generation["maxOutputTokens"] = limit
        data = (
            await checked(
                client,
                "POST",
                GEMINI + "/models/" + quote(model, safe="") + ":generateContent",
                headers=headers,
                json={
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": generation,
                },
            )
        ).json()
        candidates = data.get("candidates") or []
        if not candidates or candidates[0].get("finishReason") != "STOP":
            raise ProviderError("لم يكتمل رد Gemini API أو حُجب من المزوّد.")
        text = "".join(
            part.get("text", "")
            for part in candidates[0].get("content", {}).get("parts", [])
            if not part.get("thought")
        )
    if not text.strip():
        raise ProviderError("أعاد مزوّد API ردًا نصيًا فارغًا.")
    return text
