-- migrate:up

CREATE TABLE corporate_action_previews (
  stock_id             bigint NOT NULL REFERENCES stocks (id),
  ex_date              date NOT NULL,
  source               text NOT NULL,
  label                text NOT NULL CHECK (label IN ('息', '權', '權息')),
  action_type          text NOT NULL CHECK (action_type IN (
                         'cash_dividend', 'stock_dividend', 'cash_and_stock_dividend', 'rights_issue')),
  cash_dividend        numeric(14, 8) CHECK (cash_dividend >= 0),
  stock_dividend_ratio numeric(14, 8) NOT NULL DEFAULT 0 CHECK (stock_dividend_ratio >= 0),
  rights_ratio         numeric(14, 8) NOT NULL DEFAULT 0 CHECK (rights_ratio >= 0),
  subscription_price   numeric(12, 4) CHECK (subscription_price > 0),
  raw_object_id        bigint REFERENCES raw_objects (id),
  fetched_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, ex_date, source)
);
COMMENT ON TABLE corporate_action_previews IS 'Announced upcoming ex-rights / ex-dividend events (除權除息預告表), replaced by each snapshot; corporate_actions stays the record of what happened.';
COMMENT ON COLUMN corporate_action_previews.label IS 'The exchange''s label without the 除 prefix.';
COMMENT ON COLUMN corporate_action_previews.action_type IS 'Classified from the parts, same vocabulary as corporate_actions.';
COMMENT ON COLUMN corporate_action_previews.cash_dividend IS 'Cash per share in TWD; NULL while not announced (ETFs often publish late).';
COMMENT ON COLUMN corporate_action_previews.stock_dividend_ratio IS 'Free new shares per existing share.';
COMMENT ON COLUMN corporate_action_previews.rights_ratio IS 'All new shares of the cash offering per existing share (as corporate_actions.rights_ratio).';
COMMENT ON COLUMN corporate_action_previews.fetched_at IS 'First snapshot that listed the event (raw_object_id too); later snapshots only update the parts.';
CREATE INDEX corporate_action_previews_ex_date_idx ON corporate_action_previews (ex_date);
CREATE INDEX corporate_action_previews_raw_object_idx ON corporate_action_previews (raw_object_id);

-- migrate:down
DROP TABLE corporate_action_previews;
