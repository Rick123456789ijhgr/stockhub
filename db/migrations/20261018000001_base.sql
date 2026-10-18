-- migrate:up

-- Shared trigger function: keep updated_at current on every UPDATE.
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;
COMMENT ON FUNCTION set_updated_at() IS 'Trigger: sets updated_at = now() on UPDATE.';

CREATE TABLE trading_calendar (
  date           date PRIMARY KEY,
  is_trading_day boolean NOT NULL,
  note           text,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE trading_calendar IS 'Taipei exchange trading days, one row per calendar date.';
COMMENT ON COLUMN trading_calendar.note IS 'Holiday name, or seed:weekday-rule until the official TWSE holiday import (M1).';
CREATE TRIGGER trading_calendar_updated_at BEFORE UPDATE ON trading_calendar
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- TODO(M1): replace this weekday-only seed with the official TWSE holiday schedule.
INSERT INTO trading_calendar (date, is_trading_day, note)
SELECT d::date, extract(isodow FROM d) < 6, 'seed:weekday-rule'
FROM generate_series(date '2005-01-01', date '2027-12-31', interval '1 day') AS d
ON CONFLICT (date) DO NOTHING;

-- migrate:down
DROP TABLE trading_calendar;
DROP FUNCTION set_updated_at();
