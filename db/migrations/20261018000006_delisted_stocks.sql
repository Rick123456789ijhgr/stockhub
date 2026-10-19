-- migrate:up

ALTER TABLE stocks
  ADD COLUMN listed_date_estimated boolean NOT NULL DEFAULT false,
  ADD COLUMN delisting_reason text;
COMMENT ON COLUMN stocks.listed_date_estimated IS 'True when listed_date is a lower bound, not the official date: delisting lists carry no listing date, so it is the first stored trading day (or the previous same-symbol delisting / 1962-02-09 before any price is stored).';
COMMENT ON COLUMN stocks.delisting_reason IS 'Reason published with the delisting (TPEx only; TWSE publishes none).';
COMMENT ON COLUMN stocks.delisted_date IS 'First day no longer listed (終止上市／上櫃日); the last trading day is the trading day before. NULL = active.';
-- Symbol + date -> stock lookups during price ingest pick the incarnation alive on that date.
CREATE INDEX stocks_symbol_delisted_idx ON stocks (symbol, delisted_date);

-- TWSE daily quotes start on 2004-02-11; seed 2004 with the weekday rule like later years.
INSERT INTO trading_calendar (date, is_trading_day, note)
SELECT d::date, extract(isodow FROM d) < 6, 'seed:weekday-rule'
FROM generate_series(date '2004-01-01', date '2004-12-31', interval '1 day') AS d
ON CONFLICT (date) DO NOTHING;

-- migrate:down
DELETE FROM trading_calendar WHERE date < '2005-01-01';
DROP INDEX stocks_symbol_delisted_idx;
ALTER TABLE stocks DROP COLUMN delisting_reason, DROP COLUMN listed_date_estimated;
