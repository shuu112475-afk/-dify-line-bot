import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models.database import (
    ChatSession,
    DifyConversationMap,
    LineUser,
    MessageLog,
    WebhookEvent,
    get_db,
)
from app.services import dify_service, line_service, session_service
from app.worker.tasks import process_message_task

logger = logging.getLogger(__name__)
router = APIRouter()


def _source_key(source: Dict[str, Any]) -> tuple[str, str, str]:
    """Returns (line_user_id, channel_type, thread_key)."""
    src_type = source.get("type", "user")
    user_id = source.get("userId", "")
    if src_type == "group":
        thread_key = source.get("groupId", user_id)
    elif src_type == "room":
        thread_key = source.get("roomId", user_id)
    else:
        thread_key = user_id
    return user_id, src_type, thread_key


def _dify_user(src_type: str, thread_key: str) -> str:
    if src_type == "group":
        return f"line:group:{thread_key}"
    if src_type == "room":
        return f"line:room:{thread_key}"
    return f"line:{thread_key}"


def _get_or_create_user(db: Session, line_user_id: str, src_type: str) -> LineUser:
    user = db.get(LineUser, line_user_id)
    if not user:
        user = LineUser(line_user_id=line_user_id, line_source_type=src_type)
        db.add(user)
        db.flush()
    return user


def _get_or_create_session(db: Session, line_user_id: str, src_type: str, thread_key: str) -> ChatSession:
    session = (
        db.query(ChatSession)
        .filter_by(line_user_id=line_user_id, thread_key=thread_key, status="active")
        .first()
    )
    if not session:
        session = ChatSession(
            session_id=str(uuid.uuid4()),
            line_user_id=line_user_id,
            channel_type=src_type,
            thread_key=thread_key,
        )
        db.add(session)
        db.flush()
    session.last_message_at = datetime.now(timezone.utc)
    return session


@router.post("/webhooks/line")
async def line_webhook(request: Request):
    raw_body = await request.body()

    # Signature verification must happen before any processing
    signature = request.headers.get("x-line-signature")
    line_service.verify_signature(raw_body, signature)

    import json
    body = json.loads(raw_body.decode("utf-8"))
    events = body.get("events", [])

    # URL verification POST has no events
    if not events:
        return JSONResponse({"ok": True})

    for event in events:
        webhook_event_id = event.get("webhookEventId", "")
        is_redelivery = event.get("deliveryContext", {}).get("isRedelivery", False)

        # Deduplication: skip already-processed events (idempotency)
        if webhook_event_id and await session_service.is_duplicate_event(webhook_event_id):
            logger.info("duplicate_event_skipped", extra={"webhook_event_id": webhook_event_id})
            continue

        # Ignore standby mode (multi-bot setups)
        if event.get("mode") == "standby":
            continue

        event_type = event.get("type", "")

        # Persist webhook event for audit
        try:
            raw_hash = hashlib.sha256(raw_body).hexdigest()
            db_gen = get_db()
            db: Session = next(db_gen)
            try:
                if webhook_event_id:
                    db.add(WebhookEvent(
                        webhook_event_id=webhook_event_id,
                        is_redelivery=is_redelivery,
                        event_type=event_type,
                        raw_hash=raw_hash,
                    ))
                    db.commit()
            finally:
                db.close()
        except Exception:
            logger.exception("webhook_audit_write_failed")

        # Route by event type
        if event_type == "message":
            await _handle_message_event(event)
        elif event_type == "follow":
            await _handle_follow_event(event)
        elif event_type == "unfollow":
            await _handle_unfollow_event(event)

    # Always return 200 quickly so LINE doesn't retry
    return JSONResponse({"ok": True})


async def _handle_message_event(event: Dict[str, Any]) -> None:
    message = event.get("message", {})
    msg_type = message.get("type", "")
    reply_token = event.get("replyToken", "")
    source = event.get("source", {})

    line_user_id, src_type, thread_key = _source_key(source)
    if not line_user_id or not reply_token:
        return

    dify_user = _dify_user(src_type, thread_key)

    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        _get_or_create_user(db, line_user_id, src_type)
        chat_session = _get_or_create_session(db, line_user_id, src_type, thread_key)
        session_id = chat_session.session_id

        # Log inbound message
        msg_log = MessageLog(
            session_id=session_id,
            direction="inbound",
            line_message_id=message.get("id"),
            content=message.get("text", "") if msg_type == "text" else f"[{msg_type}]",
            metadata_={"msg_type": msg_type, "event_type": "message"},
        )
        db.add(msg_log)
        db.commit()
        message_log_id = msg_log.message_id
    finally:
        db.close()

    if msg_type == "text":
        user_text = message.get("text", "")
        # Enqueue to worker (async processing recommended for production)
        # In this implementation we call directly but mark it as a background task approach
        process_message_task.delay(
            session_id=session_id,
            line_user_id=line_user_id,
            dify_user=dify_user,
            reply_token=reply_token,
            user_text=user_text,
            message_log_id=message_log_id,
        )
    elif msg_type in ("image", "audio", "video", "file"):
        message_id = message.get("id", "")
        process_message_task.delay(
            session_id=session_id,
            line_user_id=line_user_id,
            dify_user=dify_user,
            reply_token=reply_token,
            user_text=f"[{msg_type}ファイルが送信されました]",
            message_log_id=message_log_id,
            line_message_id=message_id,
            msg_type=msg_type,
        )
    else:
        logger.info("unsupported_message_type", extra={"type": msg_type})


async def _handle_follow_event(event: Dict[str, Any]) -> None:
    source = event.get("source", {})
    line_user_id, src_type, thread_key = _source_key(source)
    reply_token = event.get("replyToken", "")

    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        _get_or_create_user(db, line_user_id, src_type)
        _get_or_create_session(db, line_user_id, src_type, thread_key)
        db.commit()
    finally:
        db.close()

    if reply_token:
        try:
            await line_service.send_reply(
                reply_token,
                [line_service.build_text_message("友だち追加ありがとうございます！ご質問はいつでもどうぞ。")],
            )
        except Exception:
            logger.exception("follow_reply_failed")


async def _handle_unfollow_event(event: Dict[str, Any]) -> None:
    source = event.get("source", {})
    line_user_id = source.get("userId", "")
    if not line_user_id:
        return

    db_gen = get_db()
    db: Session = next(db_gen)
    try:
        db.query(ChatSession).filter_by(line_user_id=line_user_id, status="active").update(
            {"status": "closed"}
        )
        db.commit()
    finally:
        db.close()

    await session_service.delete_session(line_user_id)
