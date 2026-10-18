-- migrate:up

ALTER TABLE corporate_actions
  ADD COLUMN rights_ratio numeric(14, 8) CHECK (rights_ratio >= 0),
  ADD COLUMN subscription_price numeric(12, 4) CHECK (subscription_price > 0),
  ADD COLUMN detail_raw_object_id bigint REFERENCES raw_objects (id);
COMMENT ON COLUMN corporate_actions.rights_ratio IS 'New shares existing holders may subscribe per share (現金增資認購率); NULL when the source does not say.';
COMMENT ON COLUMN corporate_actions.subscription_price IS 'Subscription price per new share (現金增資認購價) for rights_ratio.';
COMMENT ON COLUMN corporate_actions.detail_raw_object_id IS 'Raw per-event detail page the cash / stock / rights parts came from (TWSE TWT49UDetail since 2009); set even when the page had no data, so it is not fetched again.';
COMMENT ON COLUMN corporate_actions.action_type IS 'The exchange''s label: cash_and_stock_dividend = 權息 on one day. What a TWSE 權息 consisted of is in cash_dividend / stock_dividend_ratio / rights_ratio once its detail page is fetched (a 權息 can be cash plus a subscription).';
CREATE INDEX corporate_actions_detail_raw_object_idx ON corporate_actions (detail_raw_object_id);

-- migrate:down
DROP INDEX corporate_actions_detail_raw_object_idx;
COMMENT ON COLUMN corporate_actions.action_type IS 'cash_and_stock_dividend = 權息 on one day (TWSE no longer publishes the split between the two).';
ALTER TABLE corporate_actions
  DROP COLUMN detail_raw_object_id,
  DROP COLUMN subscription_price,
  DROP COLUMN rights_ratio;
