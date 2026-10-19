-- migrate:up

ALTER TABLE stocks ADD COLUMN industry text;
COMMENT ON COLUMN stocks.industry IS 'Industry name as listed on the exchange ISIN page (e.g. 半導體業); industry_code is filled once an official code mapping is imported.';

CREATE TABLE prices_daily_quarantine (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  stock_id      bigint NOT NULL REFERENCES stocks (id),
  trade_date    date NOT NULL,
  payload       jsonb NOT NULL,
  reasons       text[] NOT NULL CHECK (cardinality(reasons) > 0),
  source        text NOT NULL,
  raw_object_id bigint REFERENCES raw_objects (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz,
  resolution    text,
  CONSTRAINT prices_daily_quarantine_natural_key UNIQUE (stock_id, trade_date, source)
);
COMMENT ON TABLE prices_daily_quarantine IS 'Daily bars that failed quality checks; kept out of prices_daily until reviewed (CLAUDE.md rule 7).';
COMMENT ON COLUMN prices_daily_quarantine.payload IS 'The parsed bar as received (prices as strings).';
COMMENT ON COLUMN prices_daily_quarantine.reasons IS 'Failed checks, e.g. high_below_low, partial_ohlc.';
COMMENT ON COLUMN prices_daily_quarantine.resolution IS 'How it was resolved (accepted, discarded, refetched); NULL while pending.';
CREATE INDEX prices_daily_quarantine_pending_idx ON prices_daily_quarantine (trade_date)
  WHERE resolved_at IS NULL;
CREATE INDEX prices_daily_quarantine_raw_object_idx ON prices_daily_quarantine (raw_object_id);

-- migrate:down
DROP TABLE prices_daily_quarantine;
ALTER TABLE stocks DROP COLUMN industry;
