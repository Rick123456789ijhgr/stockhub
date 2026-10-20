-- migrate:up

-- M4 chips (籌碼). Share counts are shares, never lots: margin tables publish lots and the
-- provider multiplies by 1000, so every table here adds up with prices_daily.volume.

CREATE TABLE institutional_trades_daily (
  stock_id            bigint NOT NULL REFERENCES stocks (id),
  trade_date          date NOT NULL,
  foreign_buy         bigint NOT NULL CHECK (foreign_buy >= 0),
  foreign_sell        bigint NOT NULL CHECK (foreign_sell >= 0),
  foreign_net         bigint NOT NULL,
  foreign_dealer_buy  bigint CHECK (foreign_dealer_buy >= 0),
  foreign_dealer_sell bigint CHECK (foreign_dealer_sell >= 0),
  foreign_dealer_net  bigint,
  trust_buy           bigint NOT NULL CHECK (trust_buy >= 0),
  trust_sell          bigint NOT NULL CHECK (trust_sell >= 0),
  trust_net           bigint NOT NULL,
  dealer_buy          bigint NOT NULL CHECK (dealer_buy >= 0),
  dealer_sell         bigint NOT NULL CHECK (dealer_sell >= 0),
  dealer_net          bigint NOT NULL,
  dealer_self_net     bigint,
  dealer_hedge_net    bigint,
  total_net           bigint NOT NULL,
  source              text NOT NULL,
  fetched_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, trade_date)
);
COMMENT ON TABLE institutional_trades_daily IS 'Shares bought and sold by the three institutional investor groups (三大法人) per stock and trading day, as published by TWSE (T86, from 2012-05-02) and TPEx (from 2014-12-01).';
COMMENT ON COLUMN institutional_trades_daily.foreign_buy IS 'Foreign and mainland investors excluding foreign dealers (外陸資，不含外資自營商); before 2017-12-18 TWSE did not split out foreign dealers.';
COMMENT ON COLUMN institutional_trades_daily.foreign_dealer_net IS 'Foreign dealers (外資自營商); NULL when the source did not publish them separately. Already counted in dealer_* by the exchanges, so not part of total_net.';
COMMENT ON COLUMN institutional_trades_daily.trust_net IS 'Domestic investment trusts (投信).';
COMMENT ON COLUMN institutional_trades_daily.dealer_buy IS 'Securities dealers (自營商): own account plus hedging.';
COMMENT ON COLUMN institutional_trades_daily.dealer_self_net IS 'Dealers trading for their own account (自營商自行買賣); NULL before the 2014-12-01 split.';
COMMENT ON COLUMN institutional_trades_daily.dealer_hedge_net IS 'Dealers hedging warrants and other products (自營商避險); NULL before the 2014-12-01 split.';
COMMENT ON COLUMN institutional_trades_daily.total_net IS 'The exchange''s 三大法人買賣超 = foreign_net + trust_net + dealer_net.';
CREATE INDEX institutional_trades_daily_date_idx ON institutional_trades_daily (trade_date);

CREATE TABLE margin_daily (
  stock_id       bigint NOT NULL REFERENCES stocks (id),
  trade_date     date NOT NULL,
  margin_buy     bigint NOT NULL CHECK (margin_buy >= 0),
  margin_sell    bigint NOT NULL CHECK (margin_sell >= 0),
  margin_redeem  bigint NOT NULL CHECK (margin_redeem >= 0),
  margin_balance bigint NOT NULL CHECK (margin_balance >= 0),
  margin_limit   bigint CHECK (margin_limit >= 0),
  short_sell     bigint NOT NULL CHECK (short_sell >= 0),
  short_cover    bigint NOT NULL CHECK (short_cover >= 0),
  short_redeem   bigint NOT NULL CHECK (short_redeem >= 0),
  short_balance  bigint NOT NULL CHECK (short_balance >= 0),
  short_limit    bigint CHECK (short_limit >= 0),
  offset_shares  bigint NOT NULL DEFAULT 0 CHECK (offset_shares >= 0),
  note           text,
  source         text NOT NULL,
  fetched_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, trade_date)
);
COMMENT ON TABLE margin_daily IS 'Margin purchases (融資) and short sales (融券) per stock and trading day, in shares (published in lots of 1000).';
COMMENT ON COLUMN margin_daily.margin_redeem IS 'Margin loans repaid in cash (現金償還).';
COMMENT ON COLUMN margin_daily.margin_balance IS 'Outstanding margin purchases after the day: previous + buy - sell - redeem.';
COMMENT ON COLUMN margin_daily.margin_limit IS 'Margin quota for the next trading day (次一營業日限額 / 資限額); utilization = balance / limit.';
COMMENT ON COLUMN margin_daily.short_sell IS 'Short sales opened (融券賣出).';
COMMENT ON COLUMN margin_daily.short_cover IS 'Short positions bought back (融券買進).';
COMMENT ON COLUMN margin_daily.short_redeem IS 'Short positions returned with stock (現券償還).';
COMMENT ON COLUMN margin_daily.short_balance IS 'Outstanding short sales after the day: previous + sell - cover - redeem.';
COMMENT ON COLUMN margin_daily.offset_shares IS 'Day-trade offsets of margin against short (資券互抵).';
COMMENT ON COLUMN margin_daily.note IS 'Exchange flags for the next day (O 停止融資, X 停止融券, @ 融資分配, % 融券分配, ! 停止買賣), as published.';
CREATE INDEX margin_daily_date_idx ON margin_daily (trade_date);

CREATE TABLE foreign_holdings_daily (
  stock_id        bigint NOT NULL REFERENCES stocks (id),
  trade_date      date NOT NULL,
  issued_shares   bigint NOT NULL CHECK (issued_shares >= 0),
  foreign_shares  bigint NOT NULL CHECK (foreign_shares >= 0),
  foreign_ratio   numeric(9, 6) NOT NULL CHECK (foreign_ratio BETWEEN 0 AND 1),
  limit_ratio     numeric(9, 6) CHECK (limit_ratio BETWEEN 0 AND 1),
  source          text NOT NULL,
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, trade_date)
);
COMMENT ON TABLE foreign_holdings_daily IS 'Shares held by all foreign and mainland investors (外資及陸資持股) after each trading day (TWSE MI_QFIIS, TPEx qfii).';
COMMENT ON COLUMN foreign_holdings_daily.foreign_ratio IS 'Held / issued as published, as a fraction (0.7234 = 72.34%).';
COMMENT ON COLUMN foreign_holdings_daily.limit_ratio IS 'Legal investment ceiling as a fraction (usually 1).';
CREATE INDEX foreign_holdings_daily_date_idx ON foreign_holdings_daily (trade_date);

CREATE TABLE shareholding_distribution (
  stock_id   bigint NOT NULL REFERENCES stocks (id),
  week_date  date NOT NULL,
  level      smallint NOT NULL CHECK (level BETWEEN 1 AND 17),
  holders    integer NOT NULL CHECK (holders >= 0),
  shares     bigint NOT NULL,
  ratio      numeric(9, 6) NOT NULL,
  source     text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, week_date, level)
);
COMMENT ON TABLE shareholding_distribution IS 'TDCC weekly shareholding distribution (集保戶股權分散表). The open data file holds only the latest week, so history accumulates from M4 on.';
COMMENT ON COLUMN shareholding_distribution.week_date IS 'TDCC data date (資料日期), normally the Friday of the week.';
COMMENT ON COLUMN shareholding_distribution.level IS 'TDCC bracket: 1 = 1-999 shares, 2 = 1-5 lots, ..., 11 = 200-400 lots, 12 = 400-600, 13 = 600-800, 14 = 800-1000, 15 = over 1000 lots, 16 = adjustment (差異數調整), 17 = total.';
COMMENT ON COLUMN shareholding_distribution.shares IS 'Shares in the bracket; the level-16 adjustment can be negative.';
COMMENT ON COLUMN shareholding_distribution.ratio IS 'Share of TDCC custody as a fraction (published as a percentage).';
CREATE INDEX shareholding_distribution_week_idx ON shareholding_distribution (week_date);

CREATE TABLE market_institutional_daily (
  market      text NOT NULL CHECK (market IN ('twse', 'tpex')),
  trade_date  date NOT NULL,
  investor    text NOT NULL CHECK (investor IN (
                'foreign', 'foreign_dealer', 'trust', 'dealer', 'dealer_self', 'dealer_hedge',
                'total')),
  buy_amount  numeric(20, 0) NOT NULL CHECK (buy_amount >= 0),
  sell_amount numeric(20, 0) NOT NULL CHECK (sell_amount >= 0),
  net_amount  numeric(20, 0) NOT NULL,
  source      text NOT NULL,
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (market, trade_date, investor)
);
COMMENT ON TABLE market_institutional_daily IS 'Whole-market traded value of the institutional groups in TWD (TWSE BFI82U, TPEx insti/summary).';
COMMENT ON COLUMN market_institutional_daily.investor IS 'foreign excludes foreign dealers; dealer is self + hedge (also stored alone before the 2014-12 split); total is the exchange''s sum, which leaves foreign_dealer out.';

CREATE TABLE market_margin_daily (
  market                 text NOT NULL CHECK (market IN ('twse', 'tpex')),
  trade_date             date NOT NULL,
  margin_balance         bigint NOT NULL CHECK (margin_balance >= 0),
  short_balance          bigint NOT NULL CHECK (short_balance >= 0),
  margin_balance_amount  numeric(20, 0) CHECK (margin_balance_amount >= 0),
  source                 text NOT NULL,
  fetched_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (market, trade_date)
);
COMMENT ON TABLE market_margin_daily IS 'Whole-market margin and short balances from the summary rows of the margin tables.';
COMMENT ON COLUMN market_margin_daily.margin_balance IS 'Outstanding margin purchases in shares.';
COMMENT ON COLUMN market_margin_daily.margin_balance_amount IS 'Outstanding margin loans in TWD (融資金額, published in thousands).';

CREATE TABLE chip_coverage (
  dataset    text NOT NULL CHECK (dataset IN (
               'institutional', 'margin', 'foreign_holdings', 'market_institutional',
               'distribution')),
  market     text NOT NULL CHECK (market IN ('twse', 'tpex', 'all')),
  trade_date date NOT NULL,
  rows       integer NOT NULL CHECK (rows >= 0),
  source     text NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (dataset, market, trade_date)
);
COMMENT ON TABLE chip_coverage IS 'One row per dataset, market and date fetched: drives catch-up and backfill resume and the /status summary without scanning the chip tables.';
COMMENT ON COLUMN chip_coverage.market IS 'all for TDCC, which publishes both markets in one file.';
COMMENT ON COLUMN chip_coverage.trade_date IS 'Trading day (TDCC: its data date).';
COMMENT ON COLUMN chip_coverage.rows IS 'Rows the source published (stored or quarantined); 0 = published empty for a past trading day.';

CREATE TABLE chip_quarantine (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset       text NOT NULL CHECK (dataset IN (
                  'institutional', 'margin', 'foreign_holdings', 'distribution')),
  stock_id      bigint NOT NULL REFERENCES stocks (id),
  trade_date    date NOT NULL,
  source        text NOT NULL,
  payload       jsonb NOT NULL,
  reasons       text[] NOT NULL CHECK (cardinality(reasons) > 0),
  raw_object_id bigint REFERENCES raw_objects (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz,
  resolution    text CHECK (resolution IN ('accepted', 'rejected', 'superseded')),
  CONSTRAINT chip_quarantine_natural_key UNIQUE (dataset, stock_id, trade_date, source),
  CONSTRAINT chip_quarantine_resolved CHECK ((resolved_at IS NULL) = (resolution IS NULL))
);
COMMENT ON TABLE chip_quarantine IS 'Chip rows that failed quality checks (rule 7), kept out of the chip tables until reviewed on /admin or re-fetched clean.';
COMMENT ON COLUMN chip_quarantine.payload IS 'The parsed row as received (model_dump, numbers as JSON).';
COMMENT ON COLUMN chip_quarantine.reasons IS 'Failed checks, e.g. total_mismatch, margin_balance_mismatch, ratio_out_of_range.';
COMMENT ON COLUMN chip_quarantine.resolution IS 'accepted = written to its table by the user; rejected = discarded; superseded = a later fetch passed.';
CREATE INDEX chip_quarantine_pending_idx ON chip_quarantine (created_at) WHERE resolved_at IS NULL;
CREATE INDEX chip_quarantine_raw_object_idx ON chip_quarantine (raw_object_id);

CREATE TABLE chip_summary (
  stock_id              bigint PRIMARY KEY REFERENCES stocks (id),
  trade_date            date NOT NULL,
  foreign_streak        integer NOT NULL,
  trust_streak          integer NOT NULL,
  dealer_streak         integer NOT NULL,
  foreign_net_5d        bigint NOT NULL,
  foreign_net_20d       bigint NOT NULL,
  trust_net_5d          bigint NOT NULL,
  trust_net_20d         bigint NOT NULL,
  dealer_net_5d         bigint NOT NULL,
  dealer_net_20d        bigint NOT NULL,
  total_net_5d          bigint NOT NULL,
  total_net_20d         bigint NOT NULL,
  total_volume_ratio_5d numeric,
  margin_utilization    numeric,
  short_margin_ratio    numeric,
  margin_change_5d      bigint,
  short_change_5d       bigint,
  foreign_ratio         numeric,
  foreign_ratio_change_20d numeric,
  big_holder_week       date,
  big_holder_ratio      numeric,
  big_holder_change_1w  numeric,
  whale_ratio           numeric,
  whale_change_1w       numeric,
  computed_at           timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE chip_summary IS 'Latest chip metrics per stock, rebuilt by compute_chip_summary with engine/chips.py (the site reads only this for summaries).';
COMMENT ON COLUMN chip_summary.trade_date IS 'Latest trading day with institutional data for the stock.';
COMMENT ON COLUMN chip_summary.foreign_streak IS 'Consecutive trading days of net buying (> 0) or selling (< 0, negative count) up to trade_date; 0 when the last day was flat.';
COMMENT ON COLUMN chip_summary.foreign_net_5d IS 'Sum of net shares over the last 5 trading days with data.';
COMMENT ON COLUMN chip_summary.total_volume_ratio_5d IS '5-day institutional net shares / 5-day traded volume (fraction).';
COMMENT ON COLUMN chip_summary.margin_utilization IS 'Margin balance / margin limit on the latest margin day (fraction).';
COMMENT ON COLUMN chip_summary.short_margin_ratio IS 'Short balance / margin balance (券資比, fraction).';
COMMENT ON COLUMN chip_summary.foreign_ratio_change_20d IS 'Change of foreign_ratio over the last 20 holding days (fraction points).';
COMMENT ON COLUMN chip_summary.big_holder_ratio IS 'TDCC share of holders with 400 lots or more (levels 12-15), fraction.';
COMMENT ON COLUMN chip_summary.whale_ratio IS 'TDCC share of holders with more than 1000 lots (level 15), fraction.';

ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check
  CHECK (kind IN ('holding_move', 'institutional_flow'));
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold; institutional_flow = an institutional group traded a large share of a holding''s volume (PLAN.md section 5); M6 adds news and macro.';

ALTER TABLE job_requests DROP CONSTRAINT job_requests_job_name_check;
ALTER TABLE job_requests ADD CONSTRAINT job_requests_job_name_check CHECK (job_name IN (
  'daily_prices', 'catch_up_prices', 'refetch_stock_prices', 'refresh_stock_fundamentals',
  'sync_chips'));

-- migrate:down
ALTER TABLE job_requests DROP CONSTRAINT job_requests_job_name_check;
DELETE FROM job_requests WHERE job_name = 'sync_chips';
ALTER TABLE job_requests ADD CONSTRAINT job_requests_job_name_check CHECK (job_name IN (
  'daily_prices', 'catch_up_prices', 'refetch_stock_prices', 'refresh_stock_fundamentals'));
ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check;
DELETE FROM alerts WHERE kind = 'institutional_flow';
ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check CHECK (kind IN ('holding_move'));
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold (PLAN.md section 5); M6 adds news, institutional flows, macro.';
DROP TABLE chip_summary;
DROP TABLE chip_quarantine;
DROP TABLE chip_coverage;
DROP TABLE market_margin_daily;
DROP TABLE market_institutional_daily;
DROP TABLE shareholding_distribution;
DROP TABLE foreign_holdings_daily;
DROP TABLE margin_daily;
DROP TABLE institutional_trades_daily;
