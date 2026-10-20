-- migrate:up

-- Same columns and figures as before, without the CTE: a CTE referenced three times is
-- materialized, so `WHERE stock_id = …` could not reach monthly_revenue and every lookup
-- scanned the whole table (D-095). Previous month and same month last year now come from
-- RANGE windows over one subquery; a filter on stock_id (a column of every PARTITION BY)
-- is pushed down to the primary-key index.
DROP VIEW monthly_revenue_growth;
CREATE VIEW monthly_revenue_growth AS
SELECT stock_id, revenue_month, revenue, publish_date,
       prev_month_revenue,
       last_year_revenue,
       revenue / nullif(prev_month_revenue, 0) - 1 AS mom,
       revenue / nullif(last_year_revenue, 0) - 1 AS yoy,
       ytd_revenue,
       CASE WHEN ytd_months = extract(month FROM revenue_month)
             AND last_year_ytd_months = extract(month FROM revenue_month)
            THEN ytd_revenue / nullif(last_year_ytd_revenue, 0) - 1 END AS ytd_yoy
FROM (
  SELECT t.*,
         max(revenue) OVER prev_month AS prev_month_revenue,
         max(revenue) OVER prev_year AS last_year_revenue,
         max(ytd_revenue) OVER prev_year AS last_year_ytd_revenue,
         max(ytd_months) OVER prev_year AS last_year_ytd_months
  FROM (
    SELECT stock_id, revenue_month, revenue, publish_date,
           sum(revenue) OVER (PARTITION BY stock_id, date_trunc('year', revenue_month)
                              ORDER BY revenue_month) AS ytd_revenue,
           count(*) OVER (PARTITION BY stock_id, date_trunc('year', revenue_month)
                          ORDER BY revenue_month) AS ytd_months
    FROM monthly_revenue
  ) t
  -- revenue_month is always the 1st, so these frames hold exactly that one month or nothing.
  WINDOW prev_month AS (PARTITION BY stock_id ORDER BY revenue_month
                        RANGE BETWEEN interval '1 month' PRECEDING AND interval '1 month' PRECEDING),
         prev_year AS (PARTITION BY stock_id ORDER BY revenue_month
                       RANGE BETWEEN interval '1 year' PRECEDING AND interval '1 year' PRECEDING)
) g;
COMMENT ON VIEW monthly_revenue_growth IS 'Monthly revenue with month-over-month, year-over-year and year-to-date growth (fractions); ytd_yoy only when both years have every month so far. Filter by stock_id: it is pushed down to the index.';

-- migrate:down

DROP VIEW monthly_revenue_growth;
CREATE VIEW monthly_revenue_growth AS
WITH m AS (
  SELECT stock_id, revenue_month, revenue, publish_date,
         sum(revenue) OVER (PARTITION BY stock_id, date_trunc('year', revenue_month)
                            ORDER BY revenue_month) AS ytd_revenue,
         count(*) OVER (PARTITION BY stock_id, date_trunc('year', revenue_month)
                        ORDER BY revenue_month) AS ytd_months
  FROM monthly_revenue
)
SELECT m.stock_id, m.revenue_month, m.revenue, m.publish_date,
       p.revenue AS prev_month_revenue,
       y.revenue AS last_year_revenue,
       m.revenue / nullif(p.revenue, 0) - 1 AS mom,
       m.revenue / nullif(y.revenue, 0) - 1 AS yoy,
       m.ytd_revenue,
       CASE WHEN m.ytd_months = extract(month FROM m.revenue_month)
             AND y.ytd_months = extract(month FROM y.revenue_month)
            THEN m.ytd_revenue / nullif(y.ytd_revenue, 0) - 1 END AS ytd_yoy
FROM m
LEFT JOIN m p ON p.stock_id = m.stock_id AND p.revenue_month = m.revenue_month - interval '1 month'
LEFT JOIN m y ON y.stock_id = m.stock_id AND y.revenue_month = m.revenue_month - interval '1 year';
COMMENT ON VIEW monthly_revenue_growth IS 'Monthly revenue with month-over-month, year-over-year and year-to-date growth (fractions); ytd_yoy only when both years have every month so far.';
