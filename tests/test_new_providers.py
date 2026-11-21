import json

import httpx
import pytest
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.providers import Providers


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "new-providers-test-password")

    def open_dashboard(handler):
        app = create_app(tmp_path, Providers(httpx.MockTransport(handler)))
        client = TestClient(app)
        assert (
            client.post(
                "/admin/api/login", json={"password": "new-providers-test-password"}
            ).status_code
            == 200
        )
        return app.state.store, client

    return open_dashboard


def connect(client, provider, credential=None):
    data = {"provider": provider}
    if credential is not None:
        data["credential"] = credential
    created = client.post("/admin/api/accounts", json=data)
    assert created.status_code == 200
    assert "credential" not in created.json()
    return client.post(f"/admin/api/accounts/{created.json()['id']}/connect")


def app_key(client, allowed):
    key = client.post("/admin/api/keys", json={"models": allowed}).json()["key"]
    return {"Authorization": "Bearer " + key}


def test_openai_api_routes_and_stateless_history(dashboard):
    requests = []

    def upstream(request):
        assert request.url.host == "api.openai.com"
        assert request.headers["authorization"] == "Bearer fake-openai-key"
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "gpt-5-mini"},
                        {"id": "gpt-image-1"},
                        {"id": "text-embedding-3-small"},
                    ]
                },
            )
        assert request.url.path == "/v1/responses"
        args = json.loads(request.content)
        assert args["store"] is False
        assert args["model"] == "gpt-5-mini"
        requests.append(args)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [{"text": "internal"}]},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "answer"}],
                    },
                ],
            },
        )

    store, client = dashboard(upstream)
    with client:
        linked = connect(client, "openai_api", "fake-openai-key")
        assert linked.status_code == 200
        assert [m["id"] for m in linked.json()["models"]] == ["gpt-5-mini"]
        headers = app_key(client, ["openai-api/gpt-5-mini"])
        catalog = client.get("/v1/models", headers=headers).json()["data"]
        assert [model["id"] for model in catalog] == ["openai-api/gpt-5-mini"]
        assert catalog[0]["supports_vision"]
        upload = client.post(
            "/v1/files?model=openai-api/gpt-5-mini",
            headers=headers,
            files={"file": ("example.pdf", b"%PDF-fixture", "application/pdf")},
        )
        assert upload.status_code == 200
        assert (
            "JVBERi" not in store.rows("SELECT attachment FROM files")[0]["attachment"]
        )
        result = client.post(
            "/v1/responses",
            headers=headers,
            json={
                "model": "openai-api/gpt-5-mini",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "first turn"},
                            {"type": "input_file", "file_id": upload.json()["id"]},
                        ],
                    }
                ],
            },
        )
        assert result.status_code == 200
        first = result.json()
        assert first["output"][0]["content"][0]["text"] == "answer"
        assert "max_output_tokens" not in requests[0]
        assert requests[0]["input"][0]["content"][1]["file_data"].startswith(
            "data:application/pdf;base64,"
        )
        result = client.post(
            "/v1/responses",
            headers=headers,
            json={
                "model": "openai-api/gpt-5-mini",
                "input": "second turn",
                "previous_response_id": first["id"],
                "max_output_tokens": 500,
            },
        )
        assert result.status_code == 200
        assert result.json()["conversation_id"] == first["conversation_id"]
        assert requests[1]["max_output_tokens"] == 500
        parts = requests[1]["input"][0]["content"]
        assert all(
            value in parts[0]["text"]
            for value in ("first turn", "answer", "second turn")
        )
        assert (
            parts[1]["file_data"] == requests[0]["input"][0]["content"][1]["file_data"]
        )
        assert "fake-openai-key" not in client.get("/admin/api/state").text
    store.close()


def test_gemini_api_pagination_and_generation(dashboard):
    def upstream(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "fake-gemini-key"
        assert "key" not in request.url.params
        if request.method == "GET":
            if request.url.params.get("pageToken") == "next":
                return httpx.Response(
                    200,
                    json={
                        "models": [
                            {
                                "name": "models/gemini-2.5-flash",
                                "supportedGenerationMethods": ["generateContent"],
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-embedding-001",
                            "supportedGenerationMethods": ["embedContent"],
                        }
                    ],
                    "nextPageToken": "next",
                },
            )
        assert request.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
        body = json.loads(request.content)
        assert body["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 1000}
        assert body["contents"][0]["parts"][1] == {
            "inlineData": {"mimeType": "image/png", "data": "aW1hZ2U="}
        }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"thought": True, "text": "internal"},
                                {"text": "hello"},
                            ]
                        },
                    }
                ]
            },
        )

    store, client = dashboard(upstream)
    with client:
        assert connect(client, "gemini_api", "fake-gemini-key").status_code == 200
        headers = app_key(client, ["gemini-api"])
        response = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "gemini-api",
                "temperature": 0.3,
                "max_completion_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "hello"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                            },
                        ],
                    }
                ],
            },
        )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "hello"
    store.close()


def test_guest_resumes_its_own_cookie_session_and_parent(dashboard):
    turns = []

    def upstream(request):
        assert request.url.host == "android.chat.openai.com"
        assert "authorization" not in request.headers
        if request.url.path.endswith("/chat-requirements"):
            return httpx.Response(
                200,
                json={"token": "fixture-guest-token"},
                headers={
                    "set-cookie": "guest=fixture; Path=/; Secure",
                },
            )
        assert request.url.path == "/backend-anon/f/conversation"
        assert (
            request.headers["openai-sentinel-chat-requirements-token"]
            == "fixture-guest-token"
        )
        assert request.headers["cookie"] == "guest=fixture"
        body = json.loads(request.content)
        turns.append((request.headers["oai-device-id"], body))
        reply = {
            "conversation_id": "remote-guest-chat",
            "message": {
                "id": f"assistant-{len(turns)}",
                "author": {"role": "assistant"},
                "content": {"parts": ["guest answer"]},
            },
        }
        return httpx.Response(
            200, text=f"data: {json.dumps(reply)}\n\ndata: [DONE]\n\n"
        )

    store, client = dashboard(upstream)
    with client:
        assert connect(client, "chatgpt_guest").status_code == 200
        headers = app_key(client, ["gpt-guest"])
        history = [{"role": "user", "content": "hello guest"}]
        first = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "gpt-guest",
                "messages": history,
            },
        )
        assert first.status_code == 200
        history += [
            first.json()["choices"][0]["message"],
            {"role": "user", "content": "follow up"},
        ]
        second = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "gpt-guest",
                "messages": history,
            },
        )
        assert second.status_code == 200
        assert second.json()["conversation_id"] == first.json()["conversation_id"]
        assert turns[0][0] == turns[1][0]
        assert "conversation_id" not in turns[0][1]
        assert turns[1][1]["conversation_id"] == "remote-guest-chat"
        assert turns[1][1]["parent_message_id"] == "assistant-1"
        assert "hello guest" not in turns[1][1]["messages"][0]["content"]["parts"][0]
        assert (
            client.post(
                "/admin/api/accounts",
                json={"provider": "chatgpt_guest", "credential": "unexpected-secret"},
            ).status_code
            == 400
        )
    store.close()


def test_guest_stops_when_upstream_requires_verification(dashboard):
    def upstream(request):
        assert request.url.path.endswith("/chat-requirements")
        return httpx.Response(
            200,
            json={
                "token": "secret",
                "turnstile": {"required": True},
            },
        )

    store, client = dashboard(upstream)
    with client:
        response = connect(client, "chatgpt_guest")
        assert response.status_code == 502
        assert "secret" not in response.text
    store.close()
