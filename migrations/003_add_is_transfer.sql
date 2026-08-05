-- ============================================================
-- 003_add_is_transfer.sql — flag fund-movement transactions
-- Apply with: psql "$DATABASE_URL" -f migrations/003_add_is_transfer.sql
--
-- Bank/e-wallet notifications include transfers to the user's own other
-- accounts or to third parties that are not a purchase of goods/services
-- (e.g. moving salary into savings). These are not real expenses and must
-- not count toward spend totals, but they're kept visible in the raw
-- transaction list for audit. Kept as a separate boolean rather than a
-- `category` value, since "is this a fund movement" and "what kind of
-- spending is this" are independent axes.
-- ============================================================

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS is_transfer BOOLEAN NOT NULL DEFAULT false;
