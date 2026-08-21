-- ============================================================
-- 006_transactions_date_no_tz.sql — fix cross-timezone date-shift bug
-- Apply with: psql "$DATABASE_URL" -f migrations/006_transactions_date_no_tz.sql
--
-- transactions.date was TIMESTAMPTZ holding a bare calendar day at
-- midnight. Postgres renders a TIMESTAMPTZ using the reading session's
-- `timezone` setting — local Postgres defaults to Asia/Jakarta, Railway's
-- managed Postgres defaults to Etc/UTC. Same stored instant, different
-- calendar day depending on which server you ask: every transaction
-- appeared one day earlier on production than locally, even though the
-- underlying data was identical.
--
-- DATE has no timezone conversion at all, so this bug class becomes
-- structurally impossible going forward. The USING clause re-derives each
-- row's intended calendar day via Asia/Jakarta wall-clock time — the
-- timezone every date was originally authored under (WIB) — so this also
-- corrects the already-wrong values on whichever database currently has
-- them shifted, not just future rows.
-- ============================================================

ALTER TABLE transactions
    ALTER COLUMN date TYPE DATE
    USING (date AT TIME ZONE 'Asia/Jakarta')::date;
