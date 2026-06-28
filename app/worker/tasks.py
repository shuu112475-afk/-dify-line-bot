import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models.database import DifyConversationMap, MessageLog, OutboundJob, get_db
from app.services import dify_service, line_service, session_service
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _process_message_async(
    session_id: str,
    line_user_id: str,
    dify_user: str,
    reply_token: str,
    user_text: str,
    message_log_id: str,
    job_id: str,
    line_message_id: Optional[str] = None,
    msg_type: str = "text",
):
    await session_service.set_job_status(job_id, "running")

    # Get persisted conversation_id from Redis (fast path)
    conversation_id = await session_service.get_conversation_id(line_user_id) or ""

    # Fallback to DB if Redis miss
    if not conversation_id:
        db_gen = get_db()
        db = next(db_gen)
        try:
            mapping = db.query(DifyConversationMap).filter_by(session_id=session_id).first()
            if mapping:
                conversation_id = mapping.dify_conversation_id or ""
        finally:
            db.close()

    # Optionally upload file attachment to Dify
    file_id: Optional[str] = None
    if line_message_id and msg_type in ("image", "audio", "video", "file"):
        try:
            content = await line_service.get_message_content(line_message_id)
            mime_map = {
                "image": "image/jpeg",
                "audio": "audio/m4a",
                "video": "video/mp4",
                "file": "application/octet-stream",
            }
            upload_result = await dify_service.upload_file(
                content=content,
                filename=f"{line_message_id}.{msg_type}",
                mime_type=mime_map.get(msg_type, "application/octet-stream"),
                dify_user=dify_user,
            )
            file_id = upload_result.get("id")
        except Exception:
            logger.exception("file_upload_failed")

    # Call Dify
    inputs = {"channel": "line", "locale": "ja-JP"}
    if file_id:
        inputs["file_id"] = file_id

    dify_resp = await dify_service.chat(
        query=user_text,
        dify_user=dify_user,
        conversation_id=conversation_id,
        inputs=inputs,
    )

    answer = dify_resp.get("answer", "")
    new_conv_id = dify_resp.get("conversation_id", "")
    dify_message_id = dify_resp.get("message_id", "")
    usage = dify_resp.get("metadata", {}).get("usage", {})

    # Persist conversation_id
    if new_conv_id:
        await session_service.set_conversation_id(line_user_id, new_conv_id)
        db_gen = get_db()
        db = next(db_gen)
        try:
            mapping = db.query(DifyConversationMap).filter_by(session_id=session_id).first()
            if mapping:
                mapping.dify_conversation_id = new_conv_id
                mapping.updated_at = datetime.now(timezone.utc)
            else:
                db.add(DifyConversationMap(
                    session_id=session_id,
                    dify_user_key=dify_user,
                    dify_conversation_id=new_conv_id,
                ))
            db.commit()
        finally:
            db.close()

    # Update outbound message log
    db_gen = get_db()
    db = next(db_gen)
    try:
        outbound = MessageLog(
            session_id=session_id,
            direction="outbound",
            dify_message_id=dify_message_id,
            content=answer,
            metadata_={"usage": usage, "job_id": job_id},
        )
        db.add(outbound)

        job_rec = OutboundJob(
            job_id=job_id,
            message_id=message_log_id,
            send_mode="reply",
            status="sending",
        )
        db.add(job_rec)
        db.commit()
    finally:
        db.close()

    # Send reply (first attempt uses replyToken)
    reply_text = answer if answer else "申し訳ありません。回答の生成に失敗しました。"
    token_fresh = await session_service.mark_reply_token_used(reply_token)

    send_mode = "reply"
    if token_fresh:
        try:
            await line_service.send_reply(
                reply_token,
                [line_service.build_text_message(reply_text)],
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 403):
                await line_service.send_push(
                    line_user_id,
                    [line_service.build_text_message(reply_text)],
                    retry_key=job_id,
                )
                send_mode = "push"
            else:
                raise
    else:
        await line_service.send_push(
            line_user_id,
            [line_service.build_text_message(reply_text)],
            retry_key=job_id,
        )
        send_mode = "push"

    # Mark job completed
    db_gen = get_db()
    db = next(db_gen)
    try:
        job_rec = db.get(OutboundJob, job_id)
        if job_rec:
            job_rec.status = "completed"
            job_rec.send_mode = send_mode
            db.commit()
    finally:
        db.close()

    await session_service.set_job_status(job_id, "completed")


@celery_app.task(
    bind=True,
    name="process_message",
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(httpx.HTTPStatusError,),
    retry_backoff=True,
)
def process_message_task(
    self,
    session_id: str,
    line_user_id: str,
    dify_user: str,
    reply_token: str,
    user_text: str,
    message_log_id: str,
    line_message_id: Optional[str] = None,
    msg_type: str = "text",
):
    job_id = str(uuid.uuid4())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _process_message_async(
                session_id=session_id,
                line_user_id=line_user_id,
                dify_user=dify_user,
                reply_token=reply_token,
                user_text=user_text,
                message_log_id=message_log_id,
                job_id=job_id,
                line_message_id=line_message_id,
                msg_type=msg_type,
            )
        )
    except Exception as exc:
        logger.exception("process_message_failed", extra={"job_id": job_id, "session_id": session_id})

        async def _fail():
            await session_service.set_job_status(job_id, "failed", {"error": str(exc)})
            try:
                await line_service.send_push(
                    line_user_id,
                    [line_service.build_error_message()],
                )
            except Exception:
                logger.exception("error_push_also_failed")

        loop.run_until_complete(_fail())
        raise
    finally:
        loop.close()
        asyncio.set_event_loop(None)
