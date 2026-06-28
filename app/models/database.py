import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_db_url = settings.database_url
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(_db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class LineUser(Base):
    __tablename__ = "line_user"

    line_user_id = Column(String, primary_key=True)
    line_source_type = Column(String, nullable=False, default="user")
    display_name = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_session"

    session_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    line_user_id = Column(String, ForeignKey("line_user.line_user_id"), nullable=False)
    channel_type = Column(String, nullable=False, default="user")
    thread_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    last_message_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)


class MessageLog(Base):
    __tablename__ = "message_log"

    message_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_session.session_id"), nullable=False)
    direction = Column(String, nullable=False)  # "inbound" | "outbound"
    line_message_id = Column(String)
    dify_message_id = Column(String)
    content = Column(Text)
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class DifyConversationMap(Base):
    __tablename__ = "dify_conversation_map"

    session_id = Column(String, ForeignKey("chat_session.session_id"), primary_key=True)
    dify_user_key = Column(String, nullable=False)
    dify_conversation_id = Column(String)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookEvent(Base):
    __tablename__ = "webhook_event"

    webhook_event_id = Column(String, primary_key=True)
    is_redelivery = Column(Boolean, nullable=False, default=False)
    event_type = Column(String, nullable=False)
    raw_hash = Column(String)
    received_at = Column(DateTime(timezone=True), default=utcnow)
    processed_at = Column(DateTime(timezone=True))


class OutboundJob(Base):
    __tablename__ = "outbound_job"

    job_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String, ForeignKey("message_log.message_id"))
    send_mode = Column(String, nullable=False, default="reply")  # "reply" | "push"
    status = Column(String, nullable=False, default="pending")
    retry_key = Column(String)
    scheduled_at = Column(DateTime(timezone=True), default=utcnow)


class ContextSnapshot(Base):
    __tablename__ = "context_snapshot"

    snapshot_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_session.session_id"), nullable=False)
    summary = Column(Text)
    variables = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=utcnow)
