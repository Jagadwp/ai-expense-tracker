-- ============================================================
-- 004_add_is_manual.sql — flag manually-entered transactions
-- Apply with: psql "$DATABASE_URL" -f migrations/004_add_is_manual.sql
--
-- Manual transactions (added by hand from the dashboard, not extracted from
-- an email) have no raw_subject/raw_from/raw_body and no real Gmail
-- message_id — the API synthesizes one to satisfy the existing
-- NOT NULL UNIQUE constraint. is_manual lets the dashboard tell the two
-- apart (e.g. to skip the raw-email preview for manual rows) without
-- inferring it from message_id's format.
-- ============================================================

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS is_manual BOOLEAN NOT NULL DEFAULT false;
