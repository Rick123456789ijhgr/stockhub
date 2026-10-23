-- migrate:up

-- One sample per polled stock per poll_quotes round (every 30 s), for the day's intraday
-- chart and short-term research. Rolling window: poll_quotes deletes trading days older
-- than QUOTE_INTRADAY_KEEP_DAYS (default 5) when it starts (D-124). The raw stream batches
-- stay in RawStore, so a pruned day can be rebuilt.
CREATE TABLE quotes_intraday (
  stock_id    bigint NOT NULL REFERENCES stocks (id),
  sampled_at  timestamptz NOT NULL,
  trade_date  date NOT NULL,
  quote_time  timestamptz NOT NULL,
  price       numeric(12, 4) NOT NULL CHECK (price > 0),
  volume      bigint NOT NULL CHECK (volume >= 0),
  bid         numeric(12, 4) CHECK (bid > 0),
  ask         numeric(12, 4) CHECK (ask > 0),
  source      text NOT NULL,
  PRIMARY KEY (stock_id, sampled_at)
);
COMMENT ON TABLE quotes_intraday IS 'Intraday samples of polled stocks (watchlist + holdings), one per poll_quotes round; kept for the latest few trading days only (QUOTE_INTRADAY_KEEP_DAYS).';
COMMENT ON COLUMN quotes_intraday.sampled_at IS 'When the round took the sample (UTC): a regular 30 s grid, unlike quote_time.';
COMMENT ON COLUMN quotes_intraday.trade_date IS 'Taipei trading date the sample belongs to; pruning goes by it.';
COMMENT ON COLUMN quotes_intraday.quote_time IS 'Exchange time of the last update in the sample (UTC); repeats while nothing trades.';
COMMENT ON COLUMN quotes_intraday.price IS 'Last trade at sampling time (samples before the first trade of the day are not stored).';
COMMENT ON COLUMN quotes_intraday.volume IS 'Cumulative regular-session volume in shares.';
COMMENT ON COLUMN quotes_intraday.source IS 'Provider of the last update (e.g. twse_mis, shioaji).';
CREATE INDEX quotes_intraday_trade_date_idx ON quotes_intraday (trade_date);
-- Read one stock at a time; `make db-cluster` rewrites it in stock order (D-117).
ALTER TABLE quotes_intraday CLUSTER ON quotes_intraday_pkey;

-- migrate:down

DROP TABLE quotes_intraday;
