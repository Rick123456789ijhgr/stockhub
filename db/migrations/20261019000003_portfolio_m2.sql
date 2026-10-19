-- migrate:up

ALTER TABLE portfolio_transactions
  ADD COLUMN day_trade  boolean NOT NULL DEFAULT false,
  ADD COLUMN fee_rebate numeric(12, 2) NOT NULL DEFAULT 0 CHECK (fee_rebate >= 0),
  ADD COLUMN fee_manual boolean NOT NULL DEFAULT false,
  ADD COLUMN tax_manual boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN portfolio_transactions.fee IS 'Brokerage fee charged on the trade (TWD); with the rebate discount mode this is the undiscounted fee.';
COMMENT ON COLUMN portfolio_transactions.tax IS 'Securities transaction tax (TWD); sells only.';
COMMENT ON COLUMN portfolio_transactions.day_trade IS 'Same-day round trip (現股當沖); only changes the tax rate.';
COMMENT ON COLUMN portfolio_transactions.fee_rebate IS 'Estimated discount refunded later by the broker (rebate mode), counted as income.';
COMMENT ON COLUMN portfolio_transactions.fee_manual IS 'Fee (and rebate) entered by hand: kept when price or quantity is edited.';
COMMENT ON COLUMN portfolio_transactions.tax_manual IS 'Tax entered by hand: kept when price or quantity is edited.';

ALTER TABLE watchlist ADD COLUMN position integer NOT NULL DEFAULT 0;
COMMENT ON COLUMN watchlist.position IS 'Custom order on /watchlist (ascending; ties by added_at).';
COMMENT ON COLUMN watchlist.note IS 'Free-text note shown on /watchlist.';
UPDATE watchlist w SET position = o.n
FROM (SELECT stock_id, row_number() OVER (ORDER BY added_at, stock_id) AS n FROM watchlist) o
WHERE o.stock_id = w.stock_id;

CREATE INDEX audit_log_action_idx ON audit_log (action, id);

-- migrate:down
DROP INDEX audit_log_action_idx;
COMMENT ON COLUMN watchlist.note IS NULL;
ALTER TABLE watchlist DROP COLUMN position;
COMMENT ON COLUMN portfolio_transactions.fee IS NULL;
COMMENT ON COLUMN portfolio_transactions.tax IS NULL;
ALTER TABLE portfolio_transactions
  DROP COLUMN tax_manual,
  DROP COLUMN fee_manual,
  DROP COLUMN fee_rebate,
  DROP COLUMN day_trade;
