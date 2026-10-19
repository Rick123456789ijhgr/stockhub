-- migrate:up

ALTER TABLE corporate_actions DROP CONSTRAINT corporate_actions_action_type_check;
ALTER TABLE corporate_actions ADD CONSTRAINT corporate_actions_action_type_check CHECK (action_type IN (
  'cash_dividend', 'stock_dividend', 'cash_and_stock_dividend', 'capital_reduction',
  'split', 'reverse_split', 'rights_issue', 'other'));
ALTER TABLE corporate_actions
  ADD COLUMN prev_close numeric(12, 4) CHECK (prev_close > 0),
  ADD COLUMN reference_price numeric(12, 4) CHECK (reference_price > 0),
  ADD COLUMN price_factor numeric(18, 10) GENERATED ALWAYS AS (
    CASE
      WHEN prev_close > 0 AND reference_price > 0 THEN round(reference_price / prev_close, 10)
      WHEN ratio > 0 THEN round(1 / ratio, 10)
    END) STORED;
COMMENT ON COLUMN corporate_actions.action_type IS 'cash_and_stock_dividend = 權息 on one day (TWSE no longer publishes the split between the two).';
COMMENT ON COLUMN corporate_actions.ex_date IS 'First trading day at the new basis: the ex-date, or the day trading resumes after a reduction/split.';
COMMENT ON COLUMN corporate_actions.cash_dividend IS 'Cash per share in TWD: the dividend, or the refund of a capital reduction; NULL when the source does not separate it.';
COMMENT ON COLUMN corporate_actions.prev_close IS 'Exchange-published close before the event (除權息前收盤價 / 停止買賣前收盤價).';
COMMENT ON COLUMN corporate_actions.reference_price IS 'Exchange-published reference price on ex_date (除權息參考價 / 恢復買賣參考價).';
COMMENT ON COLUMN corporate_actions.price_factor IS 'Backward adjustment for bars before ex_date: reference_price / prev_close (else 1 / ratio). prices_daily.adj_factor is the product over later events.';
CREATE INDEX corporate_actions_stock_ex_date_idx ON corporate_actions (stock_id, ex_date);

CREATE TABLE corporate_actions_quarantine (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  symbol        text NOT NULL,
  stock_id      bigint REFERENCES stocks (id),
  ex_date       date NOT NULL,
  action_type   text NOT NULL,
  payload       jsonb NOT NULL,
  reasons       text[] NOT NULL CHECK (cardinality(reasons) > 0),
  source        text NOT NULL,
  raw_object_id bigint REFERENCES raw_objects (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at   timestamptz,
  resolution    text,
  CONSTRAINT corporate_actions_quarantine_natural_key UNIQUE (symbol, ex_date, action_type, source)
);
COMMENT ON TABLE corporate_actions_quarantine IS 'Corporate actions that failed checks, and price gaps no recorded action explains (source derived:price-gap); kept out of adj_factor until reviewed (CLAUDE.md rule 7).';
COMMENT ON COLUMN corporate_actions_quarantine.action_type IS 'As parsed; unknown for derived price gaps.';
COMMENT ON COLUMN corporate_actions_quarantine.payload IS 'The parsed action (or, for gaps, the two adjusted closes) as received.';
COMMENT ON COLUMN corporate_actions_quarantine.resolution IS 'accepted, discarded, explained (a later import explains the gap) or NULL while pending.';
CREATE INDEX corporate_actions_quarantine_pending_idx ON corporate_actions_quarantine (ex_date)
  WHERE resolved_at IS NULL;
CREATE INDEX corporate_actions_quarantine_stock_idx ON corporate_actions_quarantine (stock_id);
CREATE INDEX corporate_actions_quarantine_raw_object_idx ON corporate_actions_quarantine (raw_object_id);

-- migrate:down
DROP TABLE corporate_actions_quarantine;
DROP INDEX corporate_actions_stock_ex_date_idx;
ALTER TABLE corporate_actions DROP COLUMN price_factor, DROP COLUMN reference_price, DROP COLUMN prev_close;
DELETE FROM corporate_actions WHERE action_type = 'cash_and_stock_dividend';
ALTER TABLE corporate_actions DROP CONSTRAINT corporate_actions_action_type_check;
ALTER TABLE corporate_actions ADD CONSTRAINT corporate_actions_action_type_check CHECK (action_type IN (
  'cash_dividend', 'stock_dividend', 'capital_reduction', 'split', 'reverse_split',
  'rights_issue', 'other'));
COMMENT ON COLUMN corporate_actions.cash_dividend IS 'Cash dividend per share in TWD.';
