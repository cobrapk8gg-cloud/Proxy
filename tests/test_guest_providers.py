"""اختبارات مزوّدي الضيف المضافين: Gemini Web وDeepAI وGigaChat.
كل الطلبات تمر عبر MockTransport دون أي اتصال شبكي حقيقي."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from proxy.app import create_app
from proxy.guest_providers import (
    GEMINI_WEB_BUILD,
    GEMINI_WEB_MODELS,
    GIGA_AGENTS,
    derive_auth_session_id,
)
from proxy.providers import Providers, ProviderError

# صفحة gemini.google.com كما يقرأها البروتوكول المرجعي (توكن الإجراء + f.sid).
GEMINI_PAGE = (
    'null)]}\'\n{"bl":"boq","SID":"x"}\n'
    '{"uS02ke":"action-token-123","FdrFJe":"857-12345"}'
)
# حمولة StreamGenerate بصيغة القائمة كما في البروتوكول الفعلي:
# [1] = [cid, rid] و[4] = [[choice, [text]]].
GEMINI_PAYLOAD = [
    None,
    ["conv-web-1", "resp-web-1"],
    None,
    None,
    [["choice-web-1", ["مرحبا من Gemini Web"]]],
]
GEMINI_STREAM = (
    ")]}'\n\n"
    + json.dumps([["wrb.fr", None, json.dumps(GEMINI_PAYLOAD)]])
    + "\n"
)

GIGA_SSE = (
    'data: {"sessionId": "s-1", "contentDelta": [{"role": "ASSISTANT", "delta": "أهلا"}]}\n'
    "\n"
    'data: {"sessionId": "s-1", "contentDelta": [{"role": "ASSISTANT", "delta": " بك"}]}\n'
    "\n"
    'data: {"sessionId": "s-1", "status": "READY", "message": {"model": "GigaChat-3.5"}}\n'
    "\n"
)


def acct(provider, credential="guest-test123456"):
    return {
        "id": "test-" + provider,
        "provider": provider,
        "credential": credential,
        "settings": {},
        "catalog": {},
    }


def form(request):
    return {
        k: v[0]
        for k, v in parse_qs(request.content.decode("utf-8")).items()
    }


def router(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.host == "gemini.google.com":
        if url.path == "/":
            return httpx.Response(200, text=GEMINI_PAGE)
        if url.path.endswith("StreamGenerate"):
            return httpx.Response(200, text=GEMINI_STREAM)
    if url.host == "api.deepai.org":
        if url.path == "/hacking_is_a_serious_crime":
            return httpx.Response(200, text="رد DeepAI النصي")
        if url.path == "/api/text2img":
            if "api-key" not in request.headers:
                return httpx.Response(401, text="API key required")
            return httpx.Response(
                200, json={"output_url": "https://api.deepai.org/out/img.png"}
            )
    if url.host == "giga.chat":
        if url.path.endswith("/prelogin/login"):
            assert "X-Auth-Session-Id" in request.headers
            assert request.headers["X-Prelogin-User-Id"]
            return httpx.Response(
                200,
                json={"status": "ok"},
                headers=[("set-cookie", "_sd_user_id=user-42; Path=/")],
            )
        if "/sessions/" in url.path and url.path.endswith("/request"):
            return httpx.Response(200, text=GIGA_SSE)
    return httpx.Response(404, text="unmocked " + str(url))


def make_providers():
    return Providers(transport=httpx.MockTransport(router))


# ---------------------------------------------------------------- Gemini Web
@pytest.mark.asyncio
async def test_gemini_web_send_uses_action_token_and_model_header():
    p = make_providers()
    state = {}
    text = await p.send(
        acct("gemini-web"), "مرحبا", state, {"model": "gemini-3.5-flash"}
    )
    assert text == "مرحبا من Gemini Web"
    assert state["conversation_id"] == "conv-web-1"
    assert state["response_id"] == "resp-web-1"
    assert state["choice_id"] == "choice-web-1"


@pytest.mark.asyncio
async def test_gemini_web_request_shape_is_faithful():
    seen = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        if request.url.path.endswith("StreamGenerate"):
            return httpx.Response(200, text=GEMINI_STREAM)
        return httpx.Response(200, text=GEMINI_PAGE)

    p = Providers(transport=httpx.MockTransport(capture))
    state = {}
    await p.send(
        acct("gemini-web"), "مرحبا", state, {"model": "gemini-deep-research"}
    )
    request = seen["request"]
    assert request.headers["x-goog-ext-525001261-jspb"] == GEMINI_WEB_MODELS[1][2]
    assert request.url.params["bl"] == GEMINI_WEB_BUILD
    assert request.url.params["hl"] == "en"
    assert request.url.params["rt"] == "c"
    body = form(request)
    assert body["at"] == "action-token-123"
    inner = json.loads(body["f.req"])
    data = json.loads(inner[1])
    assert data[0][0].startswith("\n \n")
    assert "مرحبا" in data[0][0]
    assert data[1] == ["en"]


@pytest.mark.asyncio
async def test_gemini_web_continuation_sends_context_ids():
    seen = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        if request.url.path.endswith("StreamGenerate"):
            return httpx.Response(200, text=GEMINI_STREAM)
        return httpx.Response(200, text=GEMINI_PAGE)

    p = make_providers()
    p.transport = httpx.MockTransport(capture)
    state = {}
    await p.send(acct("gemini-web"), "أول", state, {})
    await p.send(acct("gemini-web"), "ثاني", state, {})
    body = form(seen["request"])
    data = json.loads(json.loads(body["f.req"])[1])
    assert data[2][0] == "conv-web-1"
    assert data[2][1] == "resp-web-1"
    assert data[2][2] == "choice-web-1"


@pytest.mark.asyncio
async def test_gemini_web_rejects_unknown_model_and_empty_reply():
    p = make_providers()
    with pytest.raises(ProviderError):
        await p.send(acct("gemini-web"), "س", {}, {"model": "not-a-model"})

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=")]}'\n\n[]\n")

    p.transport = httpx.MockTransport(empty)
    p.guest.gemini_web_sessions.clear()
    with pytest.raises(ProviderError):
        await p.send(acct("gemini-web"), "س", {}, {})


# ---------------------------------------------------------------- DeepAI
@pytest.mark.asyncio
async def test_deepai_send_form_fields_and_history_state():
    p = make_providers()
    state = {}
    text = await p.send(
        acct("deepai"), "سؤال أول", state, {"model": "glm-5.3-flash"}
    )
    assert text == "رد DeepAI النصي"
    assert state["session_uuid"]
    await p.send(acct("deepai"), "سؤال ثانٍ", state, {"model": "glm-5.3-flash"})
    assert state["deepai_history"][0]["role"] == "user"
    assert state["deepai_history"][1]["role"] == "assistant"
    assert state["conversation_id"] == state["session_uuid"]


@pytest.mark.asyncio
async def test_deepai_request_shape_is_faithful():
    seen = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, text="تم")

    p = Providers(transport=httpx.MockTransport(capture))
    await p.send(
        acct("deepai", "deepai-pro-key"),
        "سؤال",
        {},
        {"model": "glm-5.3-flash", "thinking_enabled": True, "search_enabled": True},
    )
    request = seen["request"]
    assert request.headers["api-key"] == "deepai-pro-key"
    assert request.headers["user-agent"] == "Mozilla/5.0"
    data = form(request)
    assert data["model"] == "glm-5.3-flash"
    assert data["chat_style"] == "chat"
    assert data["language"] == "en"
    assert data["hacker_is_stinky"] == "very_stinky"
    assert data["tool_activity_support"] == "1"
    assert data["thinking_image_tool_support"] == "1"
    assert data["enabled_tools"] == '["image_generator","image_editor"]'
    assert data["web_access_enabled"] == "true"
    assert data["thinking_support"] == "1"
    history = json.loads(data["chatHistory"])
    assert history == [{"role": "user", "content": "سؤال"}]

    # بلا تفعيل التفكير لا تُرسل thinking_support، والضيف بلا api-key.
    await p.send(acct("deepai"), "سؤال", {}, {"model": "glm-5.3-flash"})
    data = form(seen["request"])
    assert "thinking_support" not in data
    assert data["web_access_enabled"] == "false"
    assert "api-key" not in seen["request"].headers


@pytest.mark.asyncio
async def test_deepai_paid_and_quota_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        data = form(request)
        history = json.loads(data["chatHistory"])
        prompt = history[-1]["content"]
        if "مدفوع" in prompt:
            return httpx.Response(
                402, text="Only paid accounts can use genius models."
            )
        if "الحصة" in prompt:
            return httpx.Response(429, text="try it exceeded the free quota.")
        return httpx.Response(200, text="ok")

    p = Providers(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as paid:
        await p.send(acct("deepai"), "مدفوع", {}, {})
    assert paid.value.status == 402
    with pytest.raises(ProviderError) as quota:
        await p.send(acct("deepai"), "الحصة", {}, {})
    assert quota.value.status == 429


@pytest.mark.asyncio
async def test_deepai_image_needs_key_and_returns_url():
    p = make_providers()
    with pytest.raises(ProviderError):
        await p.image(acct("deepai"), "قطة", "1:1")
    url = await p.image(acct("deepai", "deepai-pro-key"), "قطة", "1:1")
    assert url == "https://api.deepai.org/out/img.png"


# ---------------------------------------------------------------- GigaChat
def test_giga_derive_auth_session_id_checksum():
    device = "cc540466-dc61-403f-8836-ab4c630ad228"
    value = derive_auth_session_id(device)
    assert value.count("-") == 4
    raw = value.replace("-", "")
    r = bytearray(int(raw[i : i + 2], 16) for i in range(0, 32, 2))
    dev = bytearray(
        int(device.replace("-", "")[i : i + 2], 16) for i in range(0, 32, 2)
    )
    i = r[6] & 0x0F
    a = 7 + i
    assert a <= 15
    checksum = (sum(dev) + sum(r) - r[a]) % 256
    assert r[a] == checksum


@pytest.mark.asyncio
async def test_giga_guest_login_then_chat_and_continuation():
    p = make_providers()
    state = {}
    text = await p.send(acct("giga"), "مرحبا", state, {"model": "reasoning"})
    assert text == "أهلا بك"
    assert state["giga_session"] == "s-1"
    assert state["conversation_id"] == "s-1"


@pytest.mark.asyncio
async def test_giga_request_shape_is_faithful():
    seen = []
    state_flags = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/prelogin/login"):
            return httpx.Response(
                200,
                json={"status": "ok"},
                headers=[("set-cookie", "_sd_user_id=user-42; Path=/")],
            )
        if "/sessions/s-1/request" in request.url.path:
            state_flags["continued"] = True
            return httpx.Response(200, text=GIGA_SSE)
        return httpx.Response(200, text=GIGA_SSE)

    p = Providers(transport=httpx.MockTransport(capture))
    state = {}
    await p.send(acct("giga"), "مرحبا", state, {"model": "reasoning"})
    assert state_flags.get("continued") is None
    login, chat = seen[0], seen[1]
    # الطلب الأول تسجيل دخول الضيف، والثاني إنشاء الجلسة.
    assert chat.headers["x-device-id"] == login.headers["X-Prelogin-User-Id"]
    assert chat.headers["X-Application-Name"] == "gigachat-b2c-web-neo"
    assert chat.headers["X-Application-Version"] == "0.15.13"
    assert "_sd_user_id=user-42" in chat.headers.get("cookie", "")
    assert chat.headers["accept"] == "text/event-stream, application/json"
    body = json.loads(chat.content.decode("utf-8"))
    assert body["agent"] == GIGA_AGENTS["reasoning"]["guest"]
    assert body["featureFlags"] == ["REASONING"]
    # المتابعة تستخدم معرّف الجلسة في المسار.
    await p.send(acct("giga"), "متابعة", state, {"model": "reasoning"})
    assert state_flags.get("continued") is True


@pytest.mark.asyncio
async def test_giga_stream_error_and_empty_answer():
    p = make_providers()
    p.guest.giga_sessions["test-giga"] = {
        "device_id": "cc540466-dc61-403f-8836-ab4c630ad228",
        "cookies": {"_sd_user_id": "u"},
        "sd_user_id": "u",
        "authed": False,
        "sm_sess": "",
    }

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='data: {"sessionId": "s-9", "status": "ERROR", "error": "boom"}\n\n',
        )

    p.transport = httpx.MockTransport(failing)
    with pytest.raises(ProviderError):
        await p.send(acct("giga"), "س", {}, {})

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='data: {"sessionId": "s-9"}\n\n')

    p.transport = httpx.MockTransport(empty)
    with pytest.raises(ProviderError):
        await p.send(acct("giga"), "س", {}, {})


@pytest.mark.asyncio
async def test_giga_authed_uses_sm_sess_and_back_web_base():
    seen = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, text=GIGA_SSE)

    p = Providers(transport=httpx.MockTransport(capture))
    state = {}
    await p.send(
        acct("giga", "_sm_sess-value-123"), "مرحبا", state, {"model": "giga"}
    )
    request = seen["request"]
    assert request.url.path.startswith("/api/giga-back-web/")
    assert "_sm_sess=_sm_sess-value-123" in request.headers.get("cookie", "")
    assert "x-device-id" not in request.headers
    body = json.loads(request.content.decode("utf-8"))
    assert body["agent"] == GIGA_AGENTS["giga"]["authed"]


# ------------------------------------------------- الربط الكامل عبر التطبيق
def test_guest_account_registers_connects_and_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password-local")
    upstream = make_providers()
    app = create_app(tmp_path, upstream)
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False)
    assert (
        c.post(
            "/admin/api/login", json={"password": "test-admin-password-local"}
        ).status_code
        == 200
    )
    created = c.post(
        "/admin/api/accounts", json={"provider": "gemini-web", "credential": ""}
    )
    assert created.status_code == 200
    account = created.json()
    assert account["label"] == "Gemini Web"
    assert account["provider"] == "gemini-web"
    assert (
        c.post("/admin/api/accounts/" + account["id"] + "/connect").status_code == 200
    )
    key = c.post("/admin/api/keys", json={"name": "k", "models": ["*"]}).json()["key"]
    headers = {"Authorization": "Bearer " + key}
    models = c.get("/v1/models", headers=headers).json()
    ids = [m["id"] for m in models["data"]]
    assert "gemini-web/gemini-3.5-flash" in ids
    completion = c.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "gemini-web/gemini-3.5-flash",
            "messages": [{"role": "user", "content": "مرحبا"}],
        },
    )
    assert completion.status_code == 200
    assert (
        completion.json()["choices"][0]["message"]["content"]
        == "مرحبا من Gemini Web"
    )
    c.close()
    app.state.store.close()
