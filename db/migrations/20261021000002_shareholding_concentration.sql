-- migrate:up

-- Weekly big-holder shares from the TDCC brackets; same definition as
-- engine/chips.py holder_ratio (a pytest compares the two).
CREATE VIEW shareholding_concentration AS
SELECT
  stock_id,
  week_date,
  sum(shares) FILTER (WHERE level BETWEEN 12 AND 15)::numeric
    / nullif(max(shares) FILTER (WHERE level = 17), 0) AS big_holder_ratio,
  sum(shares) FILTER (WHERE level = 15)::numeric
    / nullif(max(shares) FILTER (WHERE level = 17), 0) AS whale_ratio,
  sum(holders) FILTER (WHERE level BETWEEN 12 AND 15)::integer AS big_holders,
  max(holders) FILTER (WHERE level = 17) AS holders
FROM shareholding_distribution
GROUP BY stock_id, week_date;
COMMENT ON VIEW shareholding_concentration IS 'Per stock and TDCC week: share of custody held by holders of 400 lots or more (big_holder_ratio, brackets 12-15) and of more than 1000 lots (whale_ratio, bracket 15), as fractions; holders = all holders (level 17).';

-- migrate:down
DROP VIEW shareholding_concentration;
