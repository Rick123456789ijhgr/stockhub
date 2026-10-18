-- migrate:up

CREATE TABLE quotes_latest (
  stock_id      bigint PRIMARY KEY REFERENCES stocks (id),
  trade_date    date NOT NULL,
  quote_time    timestamptz NOT NULL,
  price         numeric(12, 4) CHECK (price > 0),
  open          numeric(12, 4) CHECK (open > 0),
  high          numeric(12, 4) CHECK (high > 0),
  low           numeric(12, 4) CHECK (low > 0),
  prev_close    numeric(12, 4) CHECK (prev_close > 0),
  volume        bigint NOT NULL DEFAULT 0 CHECK (volume >= 0),
  bid           numeric(12, 4) CHECK (bid > 0),
  ask           numeric(12, 4) CHECK (ask > 0),
  source        text NOT NULL,
  raw_object_id bigint REFERENCES raw_objects (id),
  fetched_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE quotes_latest IS 'Latest intraday snapshot per polled stock (watchlist + holdings); overwritten every poll. Stands in for the Redis cache until it exists.';
COMMENT ON COLUMN quotes_latest.trade_date IS 'Taipei trading date of the snapshot; older than today means no quote yet today.';
COMMENT ON COLUMN quotes_latest.quote_time IS 'Exchange time of the snapshot (UTC).';
COMMENT ON COLUMN quotes_latest.price IS 'Last trade; kept from the previous poll of the same day when a tick carries none.';
COMMENT ON COLUMN quotes_latest.prev_close IS 'Reference price the exchange measures the day''s change against.';
COMMENT ON COLUMN quotes_latest.volume IS 'Cumulative regular-session volume in shares.';
CREATE INDEX quotes_latest_raw_object_idx ON quotes_latest (raw_object_id);

-- migrate:down
DROP TABLE quotes_latest;
