-- migrate:up

CREATE TABLE stocks (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  symbol        text NOT NULL,
  market        text NOT NULL CHECK (market IN ('twse', 'tpex')),
  type          text NOT NULL CHECK (type IN ('stock', 'etf')),
  name          text NOT NULL,
  industry_code text,
  listed_date   date NOT NULL,
  delisted_date date,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT stocks_symbol_listed_date_key UNIQUE (symbol, listed_date),
  CONSTRAINT stocks_delisted_after_listed CHECK (delisted_date IS NULL OR delisted_date >= listed_date)
);
COMMENT ON TABLE stocks IS 'Listed securities (TWSE/TPEx stocks and ETFs). Delisted rows are kept to avoid survivorship bias.';
COMMENT ON COLUMN stocks.market IS 'twse = listed (上市), tpex = OTC (上櫃).';
COMMENT ON COLUMN stocks.listed_date IS 'Listing date; with symbol forms the natural key because symbols can be reused after delisting.';
CREATE UNIQUE INDEX stocks_active_symbol_idx ON stocks (symbol) WHERE delisted_date IS NULL;
CREATE TRIGGER stocks_updated_at BEFORE UPDATE ON stocks
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE prices_daily (
  stock_id   bigint NOT NULL REFERENCES stocks (id),
  trade_date date NOT NULL,
  open       numeric(12, 4),
  high       numeric(12, 4),
  low        numeric(12, 4),
  close      numeric(12, 4),
  volume     bigint NOT NULL DEFAULT 0 CHECK (volume >= 0),
  turnover   numeric(20, 2) NOT NULL DEFAULT 0 CHECK (turnover >= 0),
  adj_factor numeric(18, 10) NOT NULL DEFAULT 1 CHECK (adj_factor > 0),
  source     text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, trade_date),
  CONSTRAINT prices_daily_ohlc_positive CHECK (
    (open IS NULL OR open > 0) AND (high IS NULL OR high > 0)
    AND (low IS NULL OR low > 0) AND (close IS NULL OR close > 0)),
  CONSTRAINT prices_daily_high_low CHECK (high IS NULL OR low IS NULL OR high >= low)
);
COMMENT ON TABLE prices_daily IS 'Unadjusted daily OHLCV. Adjusted price = raw price * adj_factor; raw prices are never overwritten.';
COMMENT ON COLUMN prices_daily.open IS 'Raw (unadjusted) price in TWD; OHLC are NULL when no trade occurred.';
COMMENT ON COLUMN prices_daily.volume IS 'Traded volume in shares (not lots).';
COMMENT ON COLUMN prices_daily.turnover IS 'Traded value in TWD.';
COMMENT ON COLUMN prices_daily.adj_factor IS 'Cumulative backward adjustment factor for corporate actions; 1 = no adjustment.';
CREATE INDEX prices_daily_trade_date_idx ON prices_daily (trade_date);

CREATE TABLE corporate_actions (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  stock_id             bigint NOT NULL REFERENCES stocks (id),
  ex_date              date NOT NULL,
  action_type          text NOT NULL CHECK (action_type IN (
                         'cash_dividend', 'stock_dividend', 'capital_reduction',
                         'split', 'reverse_split', 'rights_issue', 'other')),
  cash_dividend        numeric(14, 6) CHECK (cash_dividend >= 0),
  stock_dividend_ratio numeric(14, 8) CHECK (stock_dividend_ratio >= 0),
  ratio                numeric(18, 10) CHECK (ratio > 0),
  pay_date             date,
  source               text NOT NULL,
  raw_object_id        bigint REFERENCES raw_objects (id),
  fetched_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT corporate_actions_natural_key UNIQUE (stock_id, ex_date, action_type)
);
COMMENT ON TABLE corporate_actions IS 'Ex-dividend/ex-rights events, capital reductions and splits; source of prices_daily.adj_factor.';
COMMENT ON COLUMN corporate_actions.cash_dividend IS 'Cash dividend per share in TWD.';
COMMENT ON COLUMN corporate_actions.stock_dividend_ratio IS 'New shares received per existing share (0.05 = 50 shares per 1000).';
COMMENT ON COLUMN corporate_actions.ratio IS 'Shares after / shares before, for capital reductions and splits.';
CREATE INDEX corporate_actions_ex_date_idx ON corporate_actions (ex_date);
CREATE INDEX corporate_actions_raw_object_idx ON corporate_actions (raw_object_id);

CREATE TABLE financial_item_map (
  industry_type text NOT NULL CHECK (industry_type IN ('general', 'bank', 'insurance', 'securities', 'holding')),
  item_code     text NOT NULL,
  label_zh      text NOT NULL,
  statement     text NOT NULL CHECK (statement IN ('IS', 'BS', 'CF')),
  source_label  text,
  is_cumulative boolean NOT NULL,
  PRIMARY KEY (industry_type, item_code)
);
COMMENT ON TABLE financial_item_map IS 'Account code dictionary per industry template (general, bank, insurance, securities, holding).';
COMMENT ON COLUMN financial_item_map.source_label IS 'Label as published by the source, kept for mapping audits.';
COMMENT ON COLUMN financial_item_map.is_cumulative IS 'True when reported year-to-date (IS, CF); single-quarter values are derived in the compute layer.';

CREATE TABLE financials (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  stock_id      bigint NOT NULL REFERENCES stocks (id),
  period_end    date NOT NULL,
  period_type   text NOT NULL CHECK (period_type IN ('Q', 'Y')),
  statement     text NOT NULL CHECK (statement IN ('IS', 'BS', 'CF')),
  item_code     text NOT NULL,
  value         numeric NOT NULL,
  publish_date  date,
  revision      integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
  source        text NOT NULL,
  raw_object_id bigint REFERENCES raw_objects (id),
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT financials_natural_key UNIQUE (stock_id, period_end, statement, item_code, revision)
);
COMMENT ON TABLE financials IS 'Long-format financial statements exactly as reported (mostly year-to-date); never rewritten into single quarters.';
COMMENT ON COLUMN financials.publish_date IS 'Date the figure became public; NULL when unknown (backtests fall back to the statutory deadline).';
COMMENT ON COLUMN financials.revision IS '0 = original filing; restatements get increasing numbers.';
COMMENT ON COLUMN financials.value IS 'Reported value in TWD; per-share and ratio items in their natural unit.';
CREATE INDEX financials_stock_item_idx ON financials (stock_id, item_code, period_end);
CREATE INDEX financials_raw_object_idx ON financials (raw_object_id);

CREATE TABLE monthly_revenue (
  stock_id      bigint NOT NULL REFERENCES stocks (id),
  revenue_month date NOT NULL CHECK (extract(day FROM revenue_month) = 1),
  revenue       numeric(20, 2) NOT NULL,
  publish_date  date,
  source        text NOT NULL,
  raw_object_id bigint REFERENCES raw_objects (id),
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, revenue_month)
);
COMMENT ON TABLE monthly_revenue IS 'Monthly revenue as published on MOPS.';
COMMENT ON COLUMN monthly_revenue.revenue_month IS 'First day of the revenue month.';
COMMENT ON COLUMN monthly_revenue.revenue IS 'Revenue in TWD (sources reporting in thousands are converted on ingest).';
CREATE INDEX monthly_revenue_month_idx ON monthly_revenue (revenue_month);
CREATE INDEX monthly_revenue_raw_object_idx ON monthly_revenue (raw_object_id);

-- migrate:down
DROP TABLE monthly_revenue;
DROP TABLE financials;
DROP TABLE financial_item_map;
DROP TABLE corporate_actions;
DROP TABLE prices_daily;
DROP TABLE stocks;
