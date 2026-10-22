-- migrate:up

-- M5: Taiwan and international market series, macro indicators, themes and the macro event
-- calendar. A series is one line on a chart (an index, a rate, a monthly indicator); its
-- provider symbols live in the adapters (series_symbols), this catalog drives what is fetched
-- and how it is shown.

CREATE TABLE market_series (
  code           text PRIMARY KEY,
  name           text NOT NULL,
  category       text NOT NULL CHECK (category IN (
                   'tw_index', 'intl_index', 'fx', 'rate', 'commodity', 'volatility', 'macro')),
  unit           text NOT NULL,
  frequency      text NOT NULL CHECK (frequency IN ('daily', 'monthly')),
  timezone       text NOT NULL,
  has_ohlc       boolean NOT NULL DEFAULT false,
  positive       boolean NOT NULL DEFAULT true,
  max_daily_move numeric(6, 4) CHECK (max_daily_move > 0),
  history_start  date NOT NULL DEFAULT '2004-01-01',
  sort_order     smallint NOT NULL,
  enabled        boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE market_series IS 'Catalog of market and macro series (M5): what sync_markets / sync_macro fetch and how /market shows them.';
COMMENT ON COLUMN market_series.code IS 'Our series code (TAIEX, SPX, UST10Y, TW_SIGNAL, ...); providers map it to their own symbol.';
COMMENT ON COLUMN market_series.unit IS 'Display unit: point, index, percent, score, TWD, USD, USD/oz, USD/bbl.';
COMMENT ON COLUMN market_series.frequency IS 'daily = one value per trading day of its exchange; monthly = obs_date is the first day of the month.';
COMMENT ON COLUMN market_series.timezone IS 'IANA zone of the exchange; obs_date is the local trading date there (rule 2).';
COMMENT ON COLUMN market_series.has_ohlc IS 'Whether the primary source publishes open/high/low (otherwise only value).';
COMMENT ON COLUMN market_series.positive IS 'Values must be > 0 (false for oil futures, which settled negative in 2020, and for rates).';
COMMENT ON COLUMN market_series.max_daily_move IS 'Quality check: a change against the previous value beyond this fraction is quarantined; NULL = no check.';
COMMENT ON COLUMN market_series.history_start IS 'Default start of backfill_markets for the series.';

INSERT INTO market_series
  (code, name, category, unit, frequency, timezone, has_ohlc, positive, max_daily_move, history_start, sort_order)
VALUES
  ('TAIEX',       '加權指數',             'tw_index',   'point',   'daily',   'Asia/Taipei',      true,  true,  0.15, '2004-01-01', 10),
  ('TPEX',        '櫃買指數',             'tw_index',   'point',   'daily',   'Asia/Taipei',      true,  true,  0.15, '2004-01-01', 20),
  ('SPX',         'S&P 500',              'intl_index', 'point',   'daily',   'America/New_York', true,  true,  0.20, '2004-01-01', 30),
  ('NASDAQ',      'Nasdaq 綜合',          'intl_index', 'point',   'daily',   'America/New_York', true,  true,  0.20, '2004-01-01', 40),
  ('SOX',         '費城半導體',           'intl_index', 'point',   'daily',   'America/New_York', true,  true,  0.25, '2004-01-01', 50),
  ('N225',        '日經 225',             'intl_index', 'point',   'daily',   'Asia/Tokyo',       true,  true,  0.20, '2004-01-01', 60),
  ('KOSPI',       'KOSPI',                'intl_index', 'point',   'daily',   'Asia/Seoul',       true,  true,  0.20, '2004-01-01', 70),
  ('USDTWD',      '美元兌台幣',           'fx',         'TWD',     'daily',   'Europe/London',    false, true,  0.10, '2004-01-01', 80),
  ('DXY',         '美元指數',             'fx',         'index',   'daily',   'America/New_York', false, true,  0.10, '2004-01-01', 90),
  ('UST2Y',       '美國 2 年期公債殖利率', 'rate',      'percent', 'daily',   'America/New_York', false, false, NULL, '2004-01-01', 100),
  ('UST10Y',      '美國 10 年期公債殖利率','rate',      'percent', 'daily',   'America/New_York', false, false, NULL, '2004-01-01', 110),
  ('FED_UPPER',   'Fed 利率目標上限',     'rate',       'percent', 'daily',   'America/New_York', false, false, NULL, '2008-12-16', 120),
  ('VIX',         'VIX 波動率指數',       'volatility', 'point',   'daily',   'America/Chicago',  false, true,  NULL, '2004-01-01', 130),
  ('GOLD',        '黃金期貨',             'commodity',  'USD/oz',  'daily',   'America/New_York', false, true,  0.15, '2004-01-01', 140),
  ('WTI',         'WTI 原油期貨',         'commodity',  'USD/bbl', 'daily',   'America/New_York', false, false, NULL, '2004-01-01', 150),
  ('TW_SIGNAL',   '景氣對策信號分數',     'macro',      'score',   'monthly', 'Asia/Taipei',      false, true,  NULL, '1984-01-01', 200),
  ('TW_LEADING',  '領先指標不含趨勢指數', 'macro',      'index',   'monthly', 'Asia/Taipei',      false, true,  NULL, '1984-01-01', 210),
  ('TW_COINCIDENT','同時指標不含趨勢指數','macro',      'index',   'monthly', 'Asia/Taipei',      false, true,  NULL, '1984-01-01', 220),
  ('US_CPI',      '美國 CPI',             'macro',      'index',   'monthly', 'America/New_York', false, true,  NULL, '2000-01-01', 230),
  ('US_UNRATE',   '美國失業率',           'macro',      'percent', 'monthly', 'America/New_York', false, true,  NULL, '2000-01-01', 240);

CREATE TABLE market_series_values (
  series_code   text NOT NULL REFERENCES market_series (code),
  obs_date      date NOT NULL,
  open          numeric(20, 6),
  high          numeric(20, 6),
  low           numeric(20, 6),
  value         numeric(20, 6) NOT NULL,
  label         text,
  source        text NOT NULL,
  raw_object_id bigint REFERENCES raw_objects (id),
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (series_code, obs_date),
  CONSTRAINT market_series_values_range CHECK (
    high IS NULL OR low IS NULL OR high >= low)
);
COMMENT ON TABLE market_series_values IS 'Observations of market_series: daily closes (with OHLC when published) and monthly indicators. Revised macro values overwrite the old ones; the raw responses stay in RawStore.';
COMMENT ON COLUMN market_series_values.obs_date IS 'Local trading date of the series'' exchange; first day of the month for monthly series.';
COMMENT ON COLUMN market_series_values.value IS 'Close (daily) or the indicator value (monthly).';
COMMENT ON COLUMN market_series_values.label IS 'Published category with the value, e.g. the 景氣對策信號 light (紅燈, 黃紅燈, 綠燈, 黃藍燈, 藍燈).';
COMMENT ON COLUMN market_series_values.source IS 'Provider that served the value (fallbacks are used only when the primary failed).';
CREATE INDEX market_series_values_raw_object_idx ON market_series_values (raw_object_id);

CREATE VIEW market_series_status AS
SELECT
  s.code,
  s.name,
  s.category,
  s.frequency,
  s.enabled,
  v.first_date,
  v.last_date,
  v.observations,
  v.last_fetched_at
FROM market_series s
LEFT JOIN LATERAL (
  SELECT min(obs_date) AS first_date, max(obs_date) AS last_date, count(*)::integer AS observations,
         max(fetched_at) AS last_fetched_at
  FROM market_series_values WHERE series_code = s.code
) v ON true;
COMMENT ON VIEW market_series_status IS 'Per series: first and last observation, count and last fetch (for /status and the catch-up of sync_markets).';

CREATE TABLE market_series_quarantine (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  series_code   text NOT NULL REFERENCES market_series (code),
  obs_date      date NOT NULL,
  source        text NOT NULL,
  payload       jsonb NOT NULL,
  reasons       text[] NOT NULL CHECK (cardinality(reasons) > 0),
  raw_object_id bigint REFERENCES raw_objects (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz,
  resolution    text CHECK (resolution IN ('accepted', 'rejected', 'superseded')),
  CONSTRAINT market_series_quarantine_natural_key UNIQUE (series_code, obs_date, source),
  CONSTRAINT market_series_quarantine_resolved CHECK ((resolved_at IS NULL) = (resolution IS NULL))
);
COMMENT ON TABLE market_series_quarantine IS 'Series observations that failed quality checks (rule 7), kept out of market_series_values until reviewed on /admin or re-fetched clean.';
COMMENT ON COLUMN market_series_quarantine.payload IS 'The parsed observation as received (model_dump, numbers as JSON).';
COMMENT ON COLUMN market_series_quarantine.reasons IS 'Failed checks: ohlc_inconsistent, not_positive, move_too_large.';
COMMENT ON COLUMN market_series_quarantine.resolution IS 'accepted = written by the user; rejected = discarded; superseded = a later fetch passed.';
CREATE INDEX market_series_quarantine_pending_idx ON market_series_quarantine (created_at) WHERE resolved_at IS NULL;
CREATE INDEX market_series_quarantine_raw_object_idx ON market_series_quarantine (raw_object_id);

CREATE TABLE themes (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL UNIQUE CHECK (btrim(name) <> ''),
  description text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE themes IS 'Investment themes (題材) curated by the user on /admin; members in stock_themes.';
CREATE TRIGGER themes_updated_at BEFORE UPDATE ON themes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE stock_themes (
  theme_id   bigint NOT NULL REFERENCES themes (id) ON DELETE CASCADE,
  stock_id   bigint NOT NULL REFERENCES stocks (id),
  valid_from date NOT NULL,
  valid_to   date,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (theme_id, stock_id, valid_from),
  CONSTRAINT stock_themes_period CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
COMMENT ON TABLE stock_themes IS 'Theme membership over time (many-to-many); backtests (M7) use the period to avoid look-ahead.';
COMMENT ON COLUMN stock_themes.valid_from IS 'First Taipei date the stock counts as a member.';
COMMENT ON COLUMN stock_themes.valid_to IS 'Last date it counts; NULL = still a member. Periods of one stock and theme do not overlap (checked by the site).';
CREATE INDEX stock_themes_stock_idx ON stock_themes (stock_id);

CREATE TABLE macro_events (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_date date NOT NULL,
  kind       text NOT NULL CHECK (kind IN ('fomc', 'cbc', 'ndc_signal', 'other')),
  title      text NOT NULL CHECK (btrim(title) <> ''),
  note       text,
  source     text NOT NULL CHECK (source IN ('seed', 'manual', 'auto')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT macro_events_natural_key UNIQUE (kind, event_date, title)
);
COMMENT ON TABLE macro_events IS 'Macro event calendar on /market: rate decisions and indicator releases, seeded, entered on /admin or recorded by sync_macro.';
COMMENT ON COLUMN macro_events.event_date IS 'Local date of the event (FOMC: the decision day in Washington).';
COMMENT ON COLUMN macro_events.kind IS 'fomc = Fed rate decision; cbc = 中央銀行理監事會; ndc_signal = 國發會景氣燈號發布; other = anything else.';
COMMENT ON COLUMN macro_events.source IS 'seed = this migration (FOMC 2026 from federalreserve.gov); manual = /admin; auto = recorded by sync_macro when a new month appeared.';
CREATE TRIGGER macro_events_updated_at BEFORE UPDATE ON macro_events
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO macro_events (event_date, kind, title, source) VALUES
  ('2026-01-28', 'fomc', 'FOMC 利率決策', 'seed'),
  ('2026-03-18', 'fomc', 'FOMC 利率決策（含經濟預測）', 'seed'),
  ('2026-04-29', 'fomc', 'FOMC 利率決策', 'seed'),
  ('2026-06-17', 'fomc', 'FOMC 利率決策（含經濟預測）', 'seed'),
  ('2026-07-29', 'fomc', 'FOMC 利率決策', 'seed'),
  ('2026-09-16', 'fomc', 'FOMC 利率決策（含經濟預測）', 'seed'),
  ('2026-10-28', 'fomc', 'FOMC 利率決策', 'seed'),
  ('2026-12-09', 'fomc', 'FOMC 利率決策（含經濟預測）', 'seed');

-- Macro alerts concern no stock: stock_id becomes optional and NULLs share one cooldown slot.
ALTER TABLE alerts ALTER COLUMN stock_id DROP NOT NULL;
ALTER TABLE alerts DROP CONSTRAINT alerts_once_per_day;
ALTER TABLE alerts ADD CONSTRAINT alerts_once_per_day UNIQUE NULLS NOT DISTINCT (kind, stock_id, trade_date);
ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check
  CHECK (kind IN ('holding_move', 'institutional_flow', 'business_signal', 'policy_rate'));
ALTER TABLE alerts ADD CONSTRAINT alerts_stock_kind CHECK (
  (stock_id IS NULL) = (kind IN ('business_signal', 'policy_rate')));
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold; institutional_flow = an institutional group traded a large share of a holding''s volume; business_signal = the 景氣對策信號 light changed colour; policy_rate = the Fed target rate changed (PLAN.md section 5); M6 adds news.';
COMMENT ON COLUMN alerts.stock_id IS 'The stock concerned; NULL exactly for the macro kinds (business_signal, policy_rate).';
COMMENT ON COLUMN alerts.trade_date IS 'Taipei trading date the alert is about (macro kinds: the observation date of the series).';

ALTER TABLE job_requests DROP CONSTRAINT job_requests_job_name_check;
ALTER TABLE job_requests ADD CONSTRAINT job_requests_job_name_check CHECK (job_name IN (
  'daily_prices', 'catch_up_prices', 'refetch_stock_prices', 'refresh_stock_fundamentals',
  'sync_chips', 'sync_markets', 'sync_macro'));

-- migrate:down
ALTER TABLE job_requests DROP CONSTRAINT job_requests_job_name_check;
DELETE FROM job_requests WHERE job_name IN ('sync_markets', 'sync_macro');
ALTER TABLE job_requests ADD CONSTRAINT job_requests_job_name_check CHECK (job_name IN (
  'daily_prices', 'catch_up_prices', 'refetch_stock_prices', 'refresh_stock_fundamentals',
  'sync_chips'));
DELETE FROM alerts WHERE kind IN ('business_signal', 'policy_rate');
ALTER TABLE alerts DROP CONSTRAINT alerts_stock_kind;
ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check
  CHECK (kind IN ('holding_move', 'institutional_flow'));
ALTER TABLE alerts DROP CONSTRAINT alerts_once_per_day;
ALTER TABLE alerts ADD CONSTRAINT alerts_once_per_day UNIQUE (kind, stock_id, trade_date);
ALTER TABLE alerts ALTER COLUMN stock_id SET NOT NULL;
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold; institutional_flow = an institutional group traded a large share of a holding''s volume (PLAN.md section 5); M6 adds news and macro.';
COMMENT ON COLUMN alerts.stock_id IS NULL;
COMMENT ON COLUMN alerts.trade_date IS 'Taipei trading date the alert is about.';
DROP TABLE macro_events;
DROP TABLE stock_themes;
DROP TABLE themes;
DROP TABLE market_series_quarantine;
DROP VIEW market_series_status;
DROP TABLE market_series_values;
DROP TABLE market_series;
