-- ============================================================
-- 002_sender_filters.sql — configurable Gmail sender allowlist (FR-02)
-- Apply with:  psql "$DATABASE_URL" -f migrations/002_sender_filters.sql
--
-- No CRUD API yet — rows are managed by hand via psql until a settings UI
-- exists (planned for the M5 dashboard). Moving this out of .env into the
-- database means new senders can be added/disabled without a deploy.
-- ============================================================

CREATE TABLE IF NOT EXISTS sender_filters (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_address TEXT NOT NULL UNIQUE,
    label         TEXT,                              -- human-readable name, e.g. "BSI", "OVO"
    active        BOOLEAN NOT NULL DEFAULT true,      -- inactive rows are excluded from sync without deleting history
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
