from typing import Any, Dict, List, Optional

import httpx

from app.config import settings


def _base_url() -> str:
    return settings.dify_api_base_url.rstrip("/")


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }


async def chat(
    query: str,
    dify_user: str,
    conversation_id: str = "",
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "inputs": inputs or {"channel": "line", "locale": "ja-JP"},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": dify_user,
    }
    async with httpx.AsyncClient(timeout=settings.dify_timeout_seconds) as client:
        resp = await client.post(
            f"{_base_url()}/chat-messages",
            headers=_auth_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def upload_file(content: bytes, filename: str, mime_type: str, dify_user: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{_base_url()}/files/upload",
            headers={"Authorization": f"Bearer {settings.dify_api_key}"},
            files={"file": (filename, content, mime_type)},
            data={"user": dify_user},
        )
        resp.raise_for_status()
        return resp.json()


async def get_app_parameters() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_base_url()}/parameters",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def list_conversations(dify_user: str, limit: int = 20) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_base_url()}/conversations",
            headers=_auth_headers(),
            params={"user": dify_user, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()


async def get_suggested_questions(message_id: str, dify_user: str) -> List[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_base_url()}/messages/{message_id}/suggested",
            headers=_auth_headers(),
            params={"user": dify_user},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
