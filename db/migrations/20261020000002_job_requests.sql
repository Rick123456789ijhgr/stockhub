-- migrate:up

CREATE TABLE job_requests (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_name     text NOT NULL CHECK (job_name IN (
                 'daily_prices', 'catch_up_prices', 'refetch_stock_prices',
                 'refresh_stock_fundamentals')),
  params       jsonb NOT NULL DEFAULT '{}'::jsonb,
  status       text NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')),
  requested_by text NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz,
  run_id       bigint REFERENCES job_runs (id),
  message      text,
  CONSTRAINT job_requests_started CHECK ((status = 'queued') = (started_at IS NULL)),
  CONSTRAINT job_requests_finished CHECK ((status IN ('queued', 'running')) = (finished_at IS NULL))
);
COMMENT ON TABLE job_requests IS 'Jobs asked for from the website (e.g. re-fetch a missing day); run in order by `python -m stockhub.etl drain-requests`, started by the site locally or by the next scheduled run.';
COMMENT ON COLUMN job_requests.job_name IS 'Only jobs the site may request; params are validated by the site and again by the job.';
COMMENT ON COLUMN job_requests.run_id IS 'The job_runs row of the execution.';
COMMENT ON COLUMN job_requests.message IS 'Outcome summary or error shown on the site.';
-- A double click (or a second tab) does not queue the same work twice.
CREATE UNIQUE INDEX job_requests_one_pending_idx ON job_requests (job_name, params)
  WHERE status IN ('queued', 'running');
CREATE INDEX job_requests_requested_idx ON job_requests (requested_at DESC);

CREATE FUNCTION stock_missing_days(p_stock_id bigint, p_from date, p_to date)
RETURNS SETOF date LANGUAGE sql STABLE AS $$
  SELECT c.date
  FROM trading_calendar c
  JOIN stocks s ON s.id = p_stock_id
  JOIN (SELECT trade_date FROM prices_daily_coverage GROUP BY trade_date HAVING sum(bars) > 0) v
    ON v.trade_date = c.date
  WHERE c.is_trading_day
    AND c.date BETWEEN greatest(p_from, s.listed_date)
                   AND least(p_to, coalesce(s.delisted_date - 1, p_to))
    AND NOT EXISTS (
      SELECT 1 FROM prices_daily p WHERE p.stock_id = p_stock_id AND p.trade_date = c.date)
  ORDER BY c.date
$$;
COMMENT ON FUNCTION stock_missing_days(bigint, date, date) IS 'Trading days in [p_from, p_to] within the listing on which the market has bars but this stock has none (usually a trading suspension; sometimes a missed row). Shared by the stock page and refetch_stock_prices.';

-- migrate:down
DROP FUNCTION stock_missing_days(bigint, date, date);
DROP TABLE job_requests;
