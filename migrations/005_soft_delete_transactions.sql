-- ============================================================
-- 005_soft_delete_transactions.sql — soft-delete transactions
-- Apply with: psql "$DATABASE_URL" -f migrations/005_soft_delete_transactions.sql
--
-- Deleting a transaction from the dashboard sets deleted_at instead of
-- removing the row: a hard DELETE on an email-derived row is unrecoverable
-- (processed_emails still marks the underlying email as processed, so a
-- re-sync never brings it back). Every read path must add
-- "deleted_at IS NULL" going forward.
-- ============================================================

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
