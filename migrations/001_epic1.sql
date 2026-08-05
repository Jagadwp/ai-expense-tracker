-- ============================================================
-- 001_epic1.sql — Epic 1 schema: Email Ingestion
-- Apply with:  make migrate
-- gen_random_uuid() is built into PostgreSQL 13+ (no extension required).
-- ============================================================

-- ------------------------------------------------------------
-- transactions: the final result of extracting an email into a transaction
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      TEXT NOT NULL UNIQUE,          -- Gmail message ID; unique so one email cannot become two transactions
    raw_subject     TEXT,
    raw_from        TEXT,
    raw_body        TEXT,                           -- original email, kept for audit/debugging
    date            TIMESTAMPTZ,                    -- transaction date (extracted)
    merchant        TEXT,
    amount          NUMERIC(15,2),                  -- NUMERIC, not float — money must not suffer binary rounding
    currency        TEXT NOT NULL DEFAULT 'IDR',
    category        TEXT,
    payment_method  TEXT,
    confidence      NUMERIC(4,3),                   -- 0.000 .. 1.000
    extracted_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transactions_date     ON transactions (date DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions (category);

-- ------------------------------------------------------------
-- processed_emails: deduplication ledger ("has this email been handled?")
-- Kept separate from transactions: an email may be processed without
-- producing a transaction.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id   TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- flagged_emails: error bucket (one failed email must not stop the pipeline)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flagged_emails (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id     TEXT NOT NULL,
    raw_body       TEXT,
    error_message  TEXT,                            -- technical error, e.g. "LLM timeout"
    flagged_reason TEXT,                            -- category, e.g. "low_confidence" / "parse_error"
    flagged_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flagged_emails_message_id ON flagged_emails (message_id);

-- ------------------------------------------------------------
-- oauth_tokens: Gmail credentials, encrypted with AES-256-GCM
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL DEFAULT 'default', -- single-user MVP
    encrypted_token BYTEA NOT NULL,                  -- encrypted OAuth token (raw bytes)
    gmail_email     TEXT,
    connected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at  TIMESTAMPTZ,
    UNIQUE (user_id)                                 -- one token per user
);

-- ------------------------------------------------------------
-- sync_logs: history and observability for each sync run
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger         TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled', 'imap_idle')),
    status          TEXT NOT NULL CHECK (status  IN ('running', 'success', 'failed')),
    emails_fetched  INT NOT NULL DEFAULT 0,
    emails_new      INT NOT NULL DEFAULT 0,
    emails_skipped  INT NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sync_logs_started_at ON sync_logs (started_at DESC);
