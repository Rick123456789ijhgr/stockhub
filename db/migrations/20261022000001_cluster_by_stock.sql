-- migrate:up

-- Pages read one stock's history at a time, but the daily jobs append every stock for a
-- date together, so one stock's rows end up one per page: a first open of a stock read ~1
-- page per bar from disk (D-117). Marking the stock-first index lets `make db-cluster`
-- (a plain CLUSTER, scheduled weekly) rewrite each table in stock order. Metadata only;
-- the rewrite itself is not part of the migration.
ALTER TABLE prices_daily CLUSTER ON prices_daily_pkey;
ALTER TABLE institutional_trades_daily CLUSTER ON institutional_trades_daily_pkey;
ALTER TABLE margin_daily CLUSTER ON margin_daily_pkey;
ALTER TABLE foreign_holdings_daily CLUSTER ON foreign_holdings_daily_pkey;
ALTER TABLE financials CLUSTER ON financials_natural_key;
ALTER TABLE fundamentals_quarterly CLUSTER ON fundamentals_quarterly_pkey;
ALTER TABLE fundamental_signals CLUSTER ON fundamental_signals_pkey;
ALTER TABLE monthly_revenue CLUSTER ON monthly_revenue_pkey;

-- migrate:down

ALTER TABLE prices_daily SET WITHOUT CLUSTER;
ALTER TABLE institutional_trades_daily SET WITHOUT CLUSTER;
ALTER TABLE margin_daily SET WITHOUT CLUSTER;
ALTER TABLE foreign_holdings_daily SET WITHOUT CLUSTER;
ALTER TABLE financials SET WITHOUT CLUSTER;
ALTER TABLE fundamentals_quarterly SET WITHOUT CLUSTER;
ALTER TABLE fundamental_signals SET WITHOUT CLUSTER;
ALTER TABLE monthly_revenue SET WITHOUT CLUSTER;
