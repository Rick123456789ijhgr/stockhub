-- migrate:up

-- /status reads the latest official quarter and how many companies filed it; without this
-- both scan all of financials, which grows to millions of rows with the FinMind history.
CREATE INDEX financials_official_period_idx ON financials (period_end DESC, stock_id)
  WHERE source IN ('twse', 'tpex');
COMMENT ON INDEX financials_official_period_idx IS 'Latest official (TWSE/TPEx OpenAPI) quarter and its companies, for /status.';

-- migrate:down

DROP INDEX financials_official_period_idx;
