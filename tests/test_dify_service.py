"""Unit tests for Dify service client."""
import os
import pytest

os.environ.setdefault("LINE_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("DIFY_API_KEY", "test_dify_key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DIFY_API_BASE_URL", "https://api.dify.ai/v1")

import httpx
import respx

from app.services import dify_service


@respx.mock
@pytest.mark.asyncio
async def test_chat_new_conversation():
    mock_response = {
        "event": "message",
        "task_id": "task-001",
        "id": "b01a39de",
        "message_id": "msg-001",
        "conversation_id": "conv-abc",
        "mode": "chat",
        "answer": "テスト回答です。",
        "metadata": {"usage": {"total_tokens": 100}},
        "created_at": 1705407629,
    }
    respx.post("https://api.dify.ai/v1/chat-messages").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    result = await dify_service.chat(
        query="テスト質問",
        dify_user="line:Uabc123",
        conversation_id="",
    )

    assert result["conversation_id"] == "conv-abc"
    assert result["answer"] == "テスト回答です。"


@respx.mock
@pytest.mark.asyncio
async def test_chat_continues_conversation():
    mock_response = {
        "event": "message",
        "conversation_id": "conv-abc",
        "answer": "続きの回答です。",
        "message_id": "msg-002",
        "metadata": {},
        "created_at": 1705407700,
    }
    route = respx.post("https://api.dify.ai/v1/chat-messages").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    result = await dify_service.chat(
        query="続きの質問",
        dify_user="line:Uabc123",
        conversation_id="conv-abc",
    )

    request_body = route.calls[0].request
    import json
    sent = json.loads(request_body.content)
    assert sent["conversation_id"] == "conv-abc"
    assert result["answer"] == "続きの回答です。"


@respx.mock
@pytest.mark.asyncio
async def test_chat_raises_on_4xx():
    respx.post("https://api.dify.ai/v1/chat-messages").mock(
        return_value=httpx.Response(400, json={"code": "invalid_param", "message": "bad request"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await dify_service.chat(query="test", dify_user="line:U123")
