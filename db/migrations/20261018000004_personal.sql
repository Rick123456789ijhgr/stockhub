-- migrate:up

CREATE TABLE watchlist (
  stock_id bigint PRIMARY KEY REFERENCES stocks (id),
  added_at timestamptz NOT NULL DEFAULT now(),
  note     text
);
COMMENT ON TABLE watchlist IS 'Personal watchlist, one row per followed stock.';

CREATE TABLE portfolio_transactions (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  stock_id   bigint NOT NULL REFERENCES stocks (id),
  trade_date date NOT NULL,
  side       text NOT NULL CHECK (side IN ('buy', 'sell')),
  quantity   bigint NOT NULL CHECK (quantity > 0),
  price      numeric(12, 4) NOT NULL CHECK (price > 0),
  fee        numeric(12, 2) NOT NULL DEFAULT 0 CHECK (fee >= 0),
  tax        numeric(12, 2) NOT NULL DEFAULT 0 CHECK (tax >= 0),
  note       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE portfolio_transactions IS 'Personal trade ledger (single account). Sensitive; used from M2.';
COMMENT ON COLUMN portfolio_transactions.quantity IS 'Shares (not lots); always positive, direction is given by side.';
COMMENT ON COLUMN portfolio_transactions.price IS 'Execution price per share in TWD.';
CREATE INDEX portfolio_transactions_stock_date_idx ON portfolio_transactions (stock_id, trade_date);
CREATE TRIGGER portfolio_transactions_updated_at BEFORE UPDATE ON portfolio_transactions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- migrate:down
DROP TABLE portfolio_transactions;
DROP TABLE watchlist;
