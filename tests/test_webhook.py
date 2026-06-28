"""Unit tests for LINE webhook signature verification and event routing."""
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set required env vars before importing app
import os
os.environ.setdefault("LINE_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("DIFY_API_KEY", "test_dify_key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DIFY_API_BASE_URL", "https://api.dify.ai/v1")

from app.services.line_service import verify_signature


CHANNEL_SECRET = "test_secret"


def _make_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _make_text_event(user_id: str = "Uabc123", text: str = "こんにちは") -> dict:
    return {
        "destination": "Uxxxxxxx",
        "events": [
            {
                "webhookEventId": "test-event-001",
                "type": "message",
                "mode": "active",
                "timestamp": 1700000000000,
                "deliveryContext": {"isRedelivery": False},
                "replyToken": "test-reply-token",
                "source": {"type": "user", "userId": user_id},
                "message": {"id": "msg001", "type": "text", "text": text},
            }
        ],
    }


class TestSignatureVerification:
    def test_valid_signature_passes(self):
        body = b'{"test": true}'
        sig = _make_signature(body, CHANNEL_SECRET)
        # Should not raise
        verify_signature(body, sig)

    def test_missing_signature_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_signature(b"body", None)
        assert exc.value.status_code == 401

    def test_wrong_signature_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            verify_signature(b"body", "wrong_signature")
        assert exc.value.status_code == 401

    def test_tampered_body_raises_401(self):
        from fastapi import HTTPException
        original = b'{"test": true}'
        sig = _make_signature(original, CHANNEL_SECRET)
        tampered = b'{"test": false}'
        with pytest.raises(HTTPException) as exc:
            verify_signature(tampered, sig)
        assert exc.value.status_code == 401


class TestWebhookEndpoint:
    """Integration-level tests using TestClient (no real DB/Redis)."""

    def _make_client(self):
        from app.main import app
        return TestClient(app, raise_server_exceptions=False)

    def _post_webhook(self, client, body_dict: dict, secret: str = CHANNEL_SECRET):
        body = json.dumps(body_dict).encode()
        sig = _make_signature(body, secret)
        return client.post(
            "/webhooks/line",
            content=body,
            headers={"Content-Type": "application/json", "x-line-signature": sig},
        )

    @patch("app.routers.webhook.get_db")
    @patch("app.routers.webhook.session_service.is_duplicate_event", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.webhook.process_message_task")
    def test_empty_events_returns_200(self, mock_task, mock_dedup, mock_db):
        mock_db.return_value = iter([MagicMock()])
        client = self._make_client()
        resp = self._post_webhook(client, {"destination": "U123", "events": []})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_wrong_signature_returns_401(self):
        client = self._make_client()
        body = json.dumps({"destination": "U123", "events": []}).encode()
        resp = client.post(
            "/webhooks/line",
            content=body,
            headers={"Content-Type": "application/json", "x-line-signature": "bad_sig"},
        )
        assert resp.status_code == 401

    def test_missing_signature_returns_401(self):
        client = self._make_client()
        body = json.dumps({"destination": "U123", "events": []}).encode()
        resp = client.post(
            "/webhooks/line",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401


class TestSessionService:
    @pytest.mark.asyncio
    async def test_duplicate_event_detection(self):
        from unittest.mock import AsyncMock, patch

        with patch("app.services.session_service.get_redis") as mock_redis:
            r = AsyncMock()
            mock_redis.return_value = r

            # First call: key does not exist (nx=True succeeds → returns "OK")
            r.set.return_value = "OK"
            r.aclose = AsyncMock()
            from app.services.session_service import is_duplicate_event
            result = await is_duplicate_event("event-001")
            assert result is False  # not duplicate

            # Second call: key exists (nx=True fails → returns None)
            r.set.return_value = None
            result = await is_duplicate_event("event-001")
            assert result is True  # duplicate
