-- ============================================================
-- 007_email_received_at.sql — capture Gmail's own delivery timestamp
-- Apply with: psql "$DATABASE_URL" -f migrations/007_email_received_at.sql
--
-- Two problems, one column:
-- 1. Some transaction emails never state an explicit transaction date in
--    the body (seen in production: a blu/PLN token top-up receipt had no
--    date field at all). Without one, the LLM correctly returns
--    date: null — but a transaction with a NULL date is invisible
--    everywhere in the dashboard (every query filters by date range).
-- 2. transactions.date (migration 006) is a plain DATE, so same-day rows
--    have no time component to sort by — the transaction table's
--    "sort by date" looked unordered within a single day.
--
-- Gmail's `internalDate` (the email's actual delivery time) fixes both:
-- it's always present (100% coverage, unlike an LLM-extracted time that
-- many emails simply don't state), and transaction notifications are sent
-- effectively in real time, so it's a reliable proxy for both the
-- transaction's date (extraction fallback) and its ordering (secondary
-- sort key alongside `date`).
-- ============================================================

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS email_received_at TIMESTAMPTZ;
