-- LINE-Dify Integration Bot: initial schema

CREATE TABLE IF NOT EXISTS line_user (
    line_user_id    TEXT PRIMARY KEY,
    line_source_type TEXT NOT NULL DEFAULT 'user',
    display_name    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_session (
    session_id      TEXT PRIMARY KEY,
    line_user_id    TEXT NOT NULL REFERENCES line_user(line_user_id),
    channel_type    TEXT NOT NULL DEFAULT 'user',
    thread_key      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    last_message_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_session_user_thread ON chat_session(line_user_id, thread_key, status);

CREATE TABLE IF NOT EXISTS message_log (
    message_id      TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES chat_session(session_id),
    direction       TEXT NOT NULL,  -- 'inbound' | 'outbound'
    line_message_id TEXT,
    dify_message_id TEXT,
    content         TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_message_log_session ON message_log(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dify_conversation_map (
    session_id           TEXT PRIMARY KEY REFERENCES chat_session(session_id),
    dify_user_key        TEXT NOT NULL,
    dify_conversation_id TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS webhook_event (
    webhook_event_id TEXT PRIMARY KEY,
    is_redelivery    BOOLEAN NOT NULL DEFAULT FALSE,
    event_type       TEXT NOT NULL,
    raw_hash         TEXT,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS outbound_job (
    job_id       TEXT PRIMARY KEY,
    message_id   TEXT REFERENCES message_log(message_id),
    send_mode    TEXT NOT NULL DEFAULT 'reply',  -- 'reply' | 'push'
    status       TEXT NOT NULL DEFAULT 'pending',
    retry_key    TEXT,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS context_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_session(session_id),
    summary     TEXT,
    variables   JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
