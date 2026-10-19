-- migrate:up

CREATE TABLE dividend_receipts (
  stock_id    bigint NOT NULL REFERENCES stocks (id),
  ex_date     date NOT NULL,
  action_type text NOT NULL,
  cash        numeric(14, 2) CHECK (cash >= 0),
  shares      bigint CHECK (shares >= 0),
  pay_date    date,
  note        text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, ex_date, action_type),
  CONSTRAINT dividend_receipts_has_amount CHECK (cash IS NOT NULL OR shares IS NOT NULL)
);
COMMENT ON TABLE dividend_receipts IS 'What actually arrived for a corporate action on a holding (entered by hand on /portfolio); replaces the estimate. Sensitive, like the trade ledger.';
COMMENT ON COLUMN dividend_receipts.action_type IS 'Matches the corporate_actions (or preview) row the estimate came from.';
COMMENT ON COLUMN dividend_receipts.cash IS 'Net cash received (after the transfer fee and NHI premium); NULL keeps the cash estimate.';
COMMENT ON COLUMN dividend_receipts.shares IS 'Stock dividend shares received; NULL keeps the share estimate.';
CREATE TRIGGER dividend_receipts_updated_at BEFORE UPDATE ON dividend_receipts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- migrate:down
DROP TABLE dividend_receipts;
