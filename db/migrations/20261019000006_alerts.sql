-- migrate:up

CREATE TABLE alerts (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind        text NOT NULL CHECK (kind IN ('holding_move')),
  stock_id    bigint NOT NULL REFERENCES stocks (id),
  trade_date  date NOT NULL,
  severity    text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
  title       text NOT NULL,
  detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  notified_at timestamptz,
  CONSTRAINT alerts_once_per_day UNIQUE (kind, stock_id, trade_date)
);
COMMENT ON TABLE alerts IS 'Alerts shown on the site and sent through the Notifier; one per kind, stock and trading day (the cooldown).';
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold (PLAN.md section 5); M6 adds news, institutional flows, macro.';
COMMENT ON COLUMN alerts.trade_date IS 'Taipei trading date the alert is about.';
COMMENT ON COLUMN alerts.detail IS 'Inputs of the decision (price, reference, change, threshold, shares, source).';
COMMENT ON COLUMN alerts.notified_at IS 'When the Notifier accepted it; NULL if sending failed.';
CREATE INDEX alerts_created_idx ON alerts (created_at DESC);
CREATE INDEX alerts_stock_idx ON alerts (stock_id);

-- migrate:down
DROP TABLE alerts;
