-- migrate:up

-- Sources disagree on how they report: FinMind gives single quarters for the income
-- statement, the exchanges' OpenAPI gives year-to-date figures as filed. Each source keeps
-- its own rows (rule 3: never rewritten); the compute layer picks and single-quarterizes.
ALTER TABLE financials
  ADD COLUMN basis text NOT NULL CHECK (basis IN ('quarter', 'ytd', 'instant'));
ALTER TABLE financials DROP CONSTRAINT financials_natural_key;
ALTER TABLE financials ADD CONSTRAINT financials_natural_key
  UNIQUE (stock_id, period_end, statement, item_code, source, revision);
COMMENT ON COLUMN financials.basis IS 'quarter = that quarter alone; ytd = fiscal year-to-date as filed (Q4 = full year); instant = balance at period_end.';
COMMENT ON COLUMN financials.revision IS '0 = first value seen from this source; a later different value from the same source is stored as the next revision.';
COMMENT ON COLUMN financials.publish_date IS 'Date the figure became public (first seen in an official snapshot); NULL when unknown, in which case the statutory deadline applies.';
CREATE INDEX financials_stock_period_idx ON financials (stock_id, period_end);

COMMENT ON COLUMN financial_item_map.is_cumulative IS 'True when the filing reports the item year-to-date (IS, CF); single quarters are derived in the compute layer.';

-- Canonical items for general (non-financial) companies; providers map their own labels here.
INSERT INTO financial_item_map (industry_type, item_code, label_zh, statement, source_label, is_cumulative) VALUES
  ('general', 'Revenue',                  '營業收入',             'IS', 'FinMind Revenue；OpenAPI 營業收入', true),
  ('general', 'CostOfRevenue',            '營業成本',             'IS', 'FinMind CostOfGoodsSold；OpenAPI 營業成本', true),
  ('general', 'GrossProfit',              '營業毛利',             'IS', 'FinMind GrossProfit；OpenAPI 營業毛利（毛損）淨額', true),
  ('general', 'OperatingExpenses',        '營業費用',             'IS', 'FinMind OperatingExpenses；OpenAPI 營業費用', true),
  ('general', 'OperatingIncome',          '營業利益',             'IS', 'FinMind OperatingIncome；OpenAPI 營業利益（損失）', true),
  ('general', 'NonOperatingIncome',       '營業外收入及支出',     'IS', 'FinMind TotalNonoperatingIncomeAndExpense；OpenAPI 營業外收入及支出', true),
  ('general', 'PreTaxIncome',             '稅前淨利',             'IS', 'FinMind PreTaxIncome；OpenAPI 稅前淨利（淨損）', true),
  ('general', 'IncomeTax',                '所得稅費用',           'IS', 'FinMind TAX；OpenAPI 所得稅費用（利益）', true),
  ('general', 'NetIncome',                '本期淨利',             'IS', 'FinMind IncomeAfterTaxes；OpenAPI 本期淨利（淨損）', true),
  ('general', 'NetIncomeParent',          '歸屬母公司淨利',       'IS', 'FinMind EquityAttributableToOwnersOfParent；OpenAPI 淨利（淨損）歸屬於母公司業主', true),
  ('general', 'NetIncomeNCI',             '歸屬非控制權益淨利',   'IS', 'FinMind NoncontrollingInterests；OpenAPI 淨利（淨損）歸屬於非控制權益', true),
  ('general', 'OtherComprehensiveIncome', '其他綜合損益',         'IS', 'FinMind OtherComprehensiveIncome；OpenAPI 其他綜合損益（淨額）', true),
  ('general', 'ComprehensiveIncome',      '綜合損益總額',         'IS', 'FinMind TotalConsolidatedProfitForThePeriod；OpenAPI 本期綜合損益總額', true),
  ('general', 'EPS',                      '基本每股盈餘',         'IS', 'FinMind EPS；OpenAPI 基本每股盈餘（元）', true),
  ('general', 'TotalAssets',              '資產總額',             'BS', 'FinMind TotalAssets；OpenAPI 資產總計', false),
  ('general', 'CurrentAssets',            '流動資產',             'BS', 'FinMind CurrentAssets；OpenAPI 流動資產', false),
  ('general', 'NoncurrentAssets',         '非流動資產',           'BS', 'FinMind NoncurrentAssets；OpenAPI 非流動資產', false),
  ('general', 'Cash',                     '現金及約當現金',       'BS', 'FinMind CashAndCashEquivalents', false),
  ('general', 'AccountsReceivable',       '應收帳款淨額',         'BS', 'FinMind AccountsReceivableNet', false),
  ('general', 'Inventories',              '存貨',                 'BS', 'FinMind Inventories', false),
  ('general', 'PropertyPlantEquipment',   '不動產、廠房及設備',   'BS', 'FinMind PropertyPlantAndEquipment', false),
  ('general', 'TotalLiabilities',         '負債總額',             'BS', 'FinMind Liabilities；OpenAPI 負債總計', false),
  ('general', 'CurrentLiabilities',       '流動負債',             'BS', 'FinMind CurrentLiabilities；OpenAPI 流動負債', false),
  ('general', 'NoncurrentLiabilities',    '非流動負債',           'BS', 'FinMind NoncurrentLiabilities；OpenAPI 非流動負債', false),
  ('general', 'ShortTermBorrowings',      '短期借款',             'BS', 'FinMind ShorttermBorrowings', false),
  ('general', 'LongTermBorrowings',       '長期借款',             'BS', 'FinMind LongtermBorrowings', false),
  ('general', 'BondsPayable',             '應付公司債',           'BS', 'FinMind BondsPayable', false),
  ('general', 'CapitalStock',             '股本',                 'BS', 'FinMind CapitalStock；OpenAPI 股本', false),
  ('general', 'OrdinaryShare',            '普通股股本',           'BS', 'FinMind OrdinaryShare', false),
  ('general', 'RetainedEarnings',         '保留盈餘',             'BS', 'FinMind RetainedEarnings；OpenAPI 保留盈餘', false),
  ('general', 'EquityParent',             '歸屬母公司權益',       'BS', 'FinMind EquityAttributableToOwnersOfParent；OpenAPI 歸屬於母公司業主之權益合計', false),
  ('general', 'EquityNCI',                '非控制權益',           'BS', 'FinMind NoncontrollingInterests；OpenAPI 非控制權益', false),
  ('general', 'TotalEquity',              '權益總額',             'BS', 'FinMind Equity；OpenAPI 權益總計', false),
  ('general', 'BookValuePerShare',        '每股參考淨值',         'BS', 'OpenAPI 每股參考淨值', false),
  ('general', 'OperatingCashFlow',        '營業活動淨現金流',     'CF', 'FinMind CashFlowsFromOperatingActivities', true),
  ('general', 'InvestingCashFlow',        '投資活動淨現金流',     'CF', 'FinMind CashProvidedByInvestingActivities', true),
  ('general', 'FinancingCashFlow',        '籌資活動淨現金流',     'CF', 'FinMind CashFlowsProvidedFromFinancingActivities', true),
  ('general', 'CapitalExpenditure',       '取得不動產、廠房及設備', 'CF', 'FinMind PropertyAndPlantAndEquipment（負數為支出）', true),
  ('general', 'Depreciation',             '折舊費用',             'CF', 'FinMind Depreciation', true),
  ('general', 'Amortization',             '攤銷費用',             'CF', 'FinMind AmortizationExpense', true);

CREATE TABLE financials_quarantine (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  stock_id      bigint NOT NULL REFERENCES stocks (id),
  period_end    date NOT NULL,
  statement     text NOT NULL CHECK (statement IN ('IS', 'BS', 'CF')),
  source        text NOT NULL,
  payload       jsonb NOT NULL,
  reasons       text[] NOT NULL CHECK (cardinality(reasons) > 0),
  raw_object_id bigint REFERENCES raw_objects (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz,
  resolution    text CHECK (resolution IN ('accepted', 'rejected', 'superseded')),
  CONSTRAINT financials_quarantine_natural_key UNIQUE (stock_id, period_end, statement, source),
  CONSTRAINT financials_quarantine_resolved CHECK ((resolved_at IS NULL) = (resolution IS NULL))
);
COMMENT ON TABLE financials_quarantine IS 'Whole statements (one stock, period, statement and source) that failed quality checks; kept out of financials until reviewed or re-fetched clean (rule 7).';
COMMENT ON COLUMN financials_quarantine.payload IS 'The parsed items as received: [{item_code, value, basis, publish_date}] with values as strings.';
COMMENT ON COLUMN financials_quarantine.reasons IS 'Failed checks, e.g. unbalanced, ytd_as_quarter, negative_revenue.';
COMMENT ON COLUMN financials_quarantine.resolution IS 'accepted = written to financials by the user; rejected = discarded; superseded = a later fetch passed.';
CREATE INDEX financials_quarantine_pending_idx ON financials_quarantine (created_at)
  WHERE resolved_at IS NULL;
CREATE INDEX financials_quarantine_raw_object_idx ON financials_quarantine (raw_object_id);

CREATE TABLE financial_fetch_state (
  stock_id    bigint NOT NULL REFERENCES stocks (id),
  dataset     text NOT NULL CHECK (dataset IN ('IS', 'BS', 'CF', 'monthly_revenue')),
  source      text NOT NULL,
  fetched_at  timestamptz NOT NULL,
  last_period date,
  PRIMARY KEY (stock_id, dataset, source)
);
COMMENT ON TABLE financial_fetch_state IS 'Last per-stock history fetch of each dataset and source; drives backfill resume and the daily refresh of companies that just filed.';
COMMENT ON COLUMN financial_fetch_state.last_period IS 'Latest period in that response (quarter end, or first day of the revenue month); NULL when the source had nothing.';

ALTER TABLE stocks
  ADD COLUMN par_value numeric(12, 4) CHECK (par_value > 0),
  ADD COLUMN issued_shares bigint CHECK (issued_shares >= 0);
COMMENT ON COLUMN stocks.par_value IS 'Par value per common share in TWD (company profile; usually 10). Shares = common stock / par value.';
COMMENT ON COLUMN stocks.issued_shares IS 'Issued common shares per the latest company profile.';
COMMENT ON COLUMN stocks.industry_code IS 'Exchange industry code from the company profile (e.g. 24 = 半導體業); stocks.industry holds the name.';

CREATE TABLE fundamentals_quarterly (
  stock_id                 bigint NOT NULL REFERENCES stocks (id),
  period_end               date NOT NULL,
  available_date           date NOT NULL,
  publish_date             date,
  revenue                  numeric,
  gross_profit             numeric,
  operating_income         numeric,
  pretax_income            numeric,
  net_income               numeric,
  net_income_parent        numeric,
  eps                      numeric,
  operating_cash_flow      numeric,
  capital_expenditure      numeric,
  free_cash_flow           numeric,
  revenue_ttm              numeric,
  net_income_parent_ttm    numeric,
  eps_ttm                  numeric,
  operating_cash_flow_ttm  numeric,
  free_cash_flow_ttm       numeric,
  total_assets             numeric,
  current_assets           numeric,
  current_liabilities      numeric,
  total_liabilities        numeric,
  equity_parent            numeric,
  inventories              numeric,
  accounts_receivable      numeric,
  shares                   numeric,
  bvps                     numeric,
  gross_margin             numeric,
  operating_margin         numeric,
  net_margin               numeric,
  roe_ttm                  numeric,
  roa_ttm                  numeric,
  dupont_net_margin        numeric,
  dupont_asset_turnover    numeric,
  dupont_equity_multiplier numeric,
  debt_ratio               numeric,
  current_ratio            numeric,
  revenue_yoy              numeric,
  eps_yoy                  numeric,
  sources                  jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at              timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, period_end)
);
COMMENT ON TABLE fundamentals_quarterly IS 'Derived per-quarter fundamentals (engine/fundamentals.py, job compute_fundamentals); rebuilt from financials at any time, never edited by hand.';
COMMENT ON COLUMN fundamentals_quarterly.available_date IS 'First date the quarter may be used (publish_date if known, else the statutory deadline); valuation and backtests align on it.';
COMMENT ON COLUMN fundamentals_quarterly.revenue IS 'Single-quarter amounts in TWD (revenue .. free_cash_flow); EPS in TWD per share.';
COMMENT ON COLUMN fundamentals_quarterly.capital_expenditure IS 'Single-quarter cash paid for property, plant and equipment (positive = spent).';
COMMENT ON COLUMN fundamentals_quarterly.free_cash_flow IS 'Operating cash flow minus capital expenditure, single quarter.';
COMMENT ON COLUMN fundamentals_quarterly.revenue_ttm IS 'Sum of the last four single quarters (NULL unless all four exist).';
COMMENT ON COLUMN fundamentals_quarterly.total_assets IS 'Balance at period_end in TWD.';
COMMENT ON COLUMN fundamentals_quarterly.shares IS 'Common shares at period_end (common stock / par value).';
COMMENT ON COLUMN fundamentals_quarterly.bvps IS 'Equity attributable to owners of the parent per common share (official 每股參考淨值 when published).';
COMMENT ON COLUMN fundamentals_quarterly.gross_margin IS 'Ratios are fractions (0.53 = 53%); margins are single-quarter.';
COMMENT ON COLUMN fundamentals_quarterly.roe_ttm IS 'TTM net income to parent / average parent equity (period_end and four quarters earlier); equals the product of the three DuPont factors.';
COMMENT ON COLUMN fundamentals_quarterly.dupont_net_margin IS 'TTM net income to parent / TTM revenue.';
COMMENT ON COLUMN fundamentals_quarterly.dupont_asset_turnover IS 'TTM revenue / average total assets.';
COMMENT ON COLUMN fundamentals_quarterly.dupont_equity_multiplier IS 'Average total assets / average parent equity.';
COMMENT ON COLUMN fundamentals_quarterly.revenue_yoy IS 'Single-quarter growth against the same quarter a year earlier (fraction).';
COMMENT ON COLUMN fundamentals_quarterly.sources IS 'Which source each statement came from, e.g. {"IS": "twse", "BS": "finmind", "CF": "finmind"}.';
CREATE INDEX fundamentals_quarterly_period_idx ON fundamentals_quarterly (period_end);

CREATE TABLE fundamental_signals (
  stock_id    bigint NOT NULL REFERENCES stocks (id),
  code        text NOT NULL,
  period_end  date NOT NULL,
  direction   text NOT NULL CHECK (direction IN ('up', 'down', 'neutral')),
  title       text NOT NULL,
  detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, code, period_end)
);
COMMENT ON TABLE fundamental_signals IS 'Rule-based notable changes (gross margin swing, turn to loss, revenue record, ...); rebuilt per stock by compute_fundamentals.';
COMMENT ON COLUMN fundamental_signals.code IS 'Rule id, e.g. gross_margin_yoy, turn_loss, revenue_record (see engine/fundamentals.py).';
COMMENT ON COLUMN fundamental_signals.period_end IS 'Quarter end, or the first day of the revenue month for monthly rules.';
COMMENT ON COLUMN fundamental_signals.direction IS 'up = improvement, down = deterioration, neutral = informational.';
CREATE INDEX fundamental_signals_period_idx ON fundamental_signals (period_end DESC);

CREATE VIEW monthly_revenue_growth AS
WITH m AS (
  SELECT stock_id, revenue_month, revenue, publish_date,
         sum(revenue) OVER (PARTITION BY stock_id, date_trunc('year', revenue_month)
                            ORDER BY revenue_month) AS ytd_revenue,
         count(*) OVER (PARTITION BY stock_id, date_trunc('year', revenue_month)
                        ORDER BY revenue_month) AS ytd_months
  FROM monthly_revenue
)
SELECT m.stock_id, m.revenue_month, m.revenue, m.publish_date,
       p.revenue AS prev_month_revenue,
       y.revenue AS last_year_revenue,
       m.revenue / nullif(p.revenue, 0) - 1 AS mom,
       m.revenue / nullif(y.revenue, 0) - 1 AS yoy,
       m.ytd_revenue,
       CASE WHEN m.ytd_months = extract(month FROM m.revenue_month)
             AND y.ytd_months = extract(month FROM y.revenue_month)
            THEN m.ytd_revenue / nullif(y.ytd_revenue, 0) - 1 END AS ytd_yoy
FROM m
LEFT JOIN m p ON p.stock_id = m.stock_id AND p.revenue_month = m.revenue_month - interval '1 month'
LEFT JOIN m y ON y.stock_id = m.stock_id AND y.revenue_month = m.revenue_month - interval '1 year';
COMMENT ON VIEW monthly_revenue_growth IS 'Monthly revenue with month-over-month, year-over-year and year-to-date growth (fractions); ytd_yoy only when both years have every month so far.';

-- migrate:down
DROP VIEW monthly_revenue_growth;
DROP TABLE fundamental_signals;
DROP TABLE fundamentals_quarterly;
ALTER TABLE stocks DROP COLUMN issued_shares, DROP COLUMN par_value;
COMMENT ON COLUMN stocks.industry_code IS NULL;
DROP TABLE financial_fetch_state;
DROP TABLE financials_quarantine;
DELETE FROM financial_item_map WHERE industry_type = 'general';
COMMENT ON COLUMN financial_item_map.is_cumulative IS 'True when reported year-to-date (IS, CF); single-quarter values are derived in the compute layer.';
DROP INDEX financials_stock_period_idx;
ALTER TABLE financials DROP CONSTRAINT financials_natural_key;
ALTER TABLE financials ADD CONSTRAINT financials_natural_key
  UNIQUE (stock_id, period_end, statement, item_code, revision);
ALTER TABLE financials DROP COLUMN basis;
COMMENT ON COLUMN financials.revision IS '0 = original filing; restatements get increasing numbers.';
COMMENT ON COLUMN financials.publish_date IS 'Date the figure became public; NULL when unknown (backtests fall back to the statutory deadline).';
