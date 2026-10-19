-- migrate:up

CREATE TABLE prices_daily_coverage (
  trade_date date NOT NULL,
  market     text NOT NULL,
  bars       integer NOT NULL,
  PRIMARY KEY (trade_date, market)
);
COMMENT ON TABLE prices_daily_coverage IS 'Bars per trading date and market, kept by triggers on prices_daily and stocks.market so /status does not scan prices_daily.';
COMMENT ON COLUMN prices_daily_coverage.market IS 'The stock''s current stocks.market (same grouping as the old live query; a transferred stock counts in its new market).';
COMMENT ON COLUMN prices_daily_coverage.bars IS 'Rows in prices_daily for the date and market.';

-- Statement-level triggers: one aggregate per INSERT/DELETE statement, not per row. For
-- INSERT ... ON CONFLICT DO UPDATE the new-rows table holds only the inserted rows.
CREATE FUNCTION prices_daily_coverage_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO prices_daily_coverage (trade_date, market, bars)
  SELECT c.trade_date, s.market, count(*)
  FROM changed c JOIN stocks s ON s.id = c.stock_id
  GROUP BY c.trade_date, s.market
  ON CONFLICT (trade_date, market) DO UPDATE SET bars = prices_daily_coverage.bars + excluded.bars;
  RETURN NULL;
END $$;
COMMENT ON FUNCTION prices_daily_coverage_insert() IS 'Adds inserted prices_daily rows to prices_daily_coverage.';

CREATE FUNCTION prices_daily_coverage_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE prices_daily_coverage v SET bars = v.bars - d.n
  FROM (
    SELECT c.trade_date, s.market, count(*) AS n
    FROM changed c JOIN stocks s ON s.id = c.stock_id
    GROUP BY c.trade_date, s.market
  ) d
  WHERE v.trade_date = d.trade_date AND v.market = d.market;
  DELETE FROM prices_daily_coverage WHERE bars <= 0;
  RETURN NULL;
END $$;
COMMENT ON FUNCTION prices_daily_coverage_delete() IS 'Removes deleted prices_daily rows from prices_daily_coverage.';

CREATE FUNCTION prices_daily_coverage_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  TRUNCATE prices_daily_coverage;
  RETURN NULL;
END $$;
COMMENT ON FUNCTION prices_daily_coverage_truncate() IS 'Empties prices_daily_coverage with prices_daily.';

CREATE FUNCTION prices_daily_coverage_market() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE prices_daily_coverage v SET bars = v.bars - d.n
  FROM (SELECT trade_date, count(*) AS n FROM prices_daily WHERE stock_id = NEW.id GROUP BY 1) d
  WHERE v.trade_date = d.trade_date AND v.market = OLD.market;
  DELETE FROM prices_daily_coverage WHERE bars <= 0;
  INSERT INTO prices_daily_coverage (trade_date, market, bars)
  SELECT trade_date, NEW.market, count(*) FROM prices_daily WHERE stock_id = NEW.id GROUP BY 1
  ON CONFLICT (trade_date, market) DO UPDATE SET bars = prices_daily_coverage.bars + excluded.bars;
  RETURN NULL;
END $$;
COMMENT ON FUNCTION prices_daily_coverage_market() IS 'Moves a stock''s bars to its new market in prices_daily_coverage (e.g. TPEx -> TWSE transfer).';

CREATE TRIGGER prices_daily_coverage_insert AFTER INSERT ON prices_daily
  REFERENCING NEW TABLE AS changed FOR EACH STATEMENT
  EXECUTE FUNCTION prices_daily_coverage_insert();
CREATE TRIGGER prices_daily_coverage_delete AFTER DELETE ON prices_daily
  REFERENCING OLD TABLE AS changed FOR EACH STATEMENT
  EXECUTE FUNCTION prices_daily_coverage_delete();
CREATE TRIGGER prices_daily_coverage_truncate AFTER TRUNCATE ON prices_daily
  FOR EACH STATEMENT EXECUTE FUNCTION prices_daily_coverage_truncate();
CREATE TRIGGER stocks_market_coverage AFTER UPDATE OF market ON stocks
  FOR EACH ROW WHEN (OLD.market IS DISTINCT FROM NEW.market)
  EXECUTE FUNCTION prices_daily_coverage_market();

-- Initial fill. CREATE TRIGGER above locks out concurrent writers until commit, so the
-- snapshot and the triggers line up.
INSERT INTO prices_daily_coverage (trade_date, market, bars)
SELECT p.trade_date, s.market, count(*)
FROM prices_daily p JOIN stocks s ON s.id = p.stock_id
GROUP BY p.trade_date, s.market;

-- migrate:down
DROP TRIGGER stocks_market_coverage ON stocks;
DROP TRIGGER prices_daily_coverage_truncate ON prices_daily;
DROP TRIGGER prices_daily_coverage_delete ON prices_daily;
DROP TRIGGER prices_daily_coverage_insert ON prices_daily;
DROP FUNCTION prices_daily_coverage_market();
DROP FUNCTION prices_daily_coverage_truncate();
DROP FUNCTION prices_daily_coverage_delete();
DROP FUNCTION prices_daily_coverage_insert();
DROP TABLE prices_daily_coverage;
