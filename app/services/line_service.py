import base64
import hashlib
import hmac
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

from app.config import settings

LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_DATA_API_BASE = "https://api-data.line.me/v2/bot"


def verify_signature(raw_body: bytes, signature: Optional[str]) -> None:
    if not signature:
        raise HTTPException(status_code=401, detail="Missing x-line-signature")

    digest = hmac.new(
        settings.line_channel_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid x-line-signature")


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.line_channel_access_token}",
        "Content-Type": "application/json",
    }


async def send_reply(reply_token: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    body = {"replyToken": reply_token, "messages": messages[:5]}
    async with httpx.AsyncClient(timeout=settings.line_reply_timeout_seconds) as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/reply",
            headers=_auth_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def send_push(user_id: str, messages: List[Dict[str, Any]], retry_key: Optional[str] = None) -> Dict[str, Any]:
    body = {"to": user_id, "messages": messages[:5]}
    headers = _auth_headers()
    if retry_key:
        headers["X-Line-Retry-Key"] = retry_key

    async with httpx.AsyncClient(timeout=settings.line_reply_timeout_seconds) as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def start_loading_animation(chat_id: str, loading_seconds: int = 20) -> None:
    body = {"chatId": chat_id, "loadingSeconds": max(5, min(60, loading_seconds))}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{LINE_API_BASE}/chat/loading/start",
            headers=_auth_headers(),
            json=body,
        )
        # 429 means already shown; ignore
        if resp.status_code not in (200, 429):
            resp.raise_for_status()


async def get_message_content(message_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{LINE_DATA_API_BASE}/message/{message_id}/content",
            headers={"Authorization": f"Bearer {settings.line_channel_access_token}"},
        )
        resp.raise_for_status()
        return resp.content


def build_text_message(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text[:5000]}


def build_error_message() -> Dict[str, Any]:
    return build_text_message("申し訳ありません。現在応答を生成できませんでした。しばらく経ってから再度お試しください。")
