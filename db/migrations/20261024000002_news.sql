-- migrate:up

-- M6: news, exchange announcements and social posts in one table (D-142), their links to
-- stocks, LLM summaries and sentiment, the free-first LLM service list (D-137), the slang
-- dictionary for social posts, and daily sentiment per stock (D-140).

CREATE TABLE news_sources (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_]+$'),
  name             text NOT NULL CHECK (btrim(name) <> ''),
  kind             text NOT NULL CHECK (kind IN (
                     'rss', 'mops', 'cnyes', 'cmoney_notes', 'ptt', 'cmoney_forum')),
  channel          text NOT NULL CHECK (channel IN ('news', 'announcement', 'social')),
  url              text CHECK (url ~ '^https?://'),
  per_stock        boolean NOT NULL DEFAULT false,
  market           text CHECK (market IN ('twse', 'tpex')),
  enabled          boolean NOT NULL DEFAULT true,
  interval_minutes integer NOT NULL DEFAULT 15 CHECK (interval_minutes BETWEEN 1 AND 1440),
  keywords         text[] NOT NULL DEFAULT '{}',
  use_llm          boolean NOT NULL DEFAULT true,
  last_fetched_at  timestamptz,
  last_success_at  timestamptz,
  last_error       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT news_sources_rss_url CHECK (kind <> 'rss' OR url IS NOT NULL),
  CONSTRAINT news_sources_per_stock_url CHECK (
    NOT per_stock OR (url IS NOT NULL AND url LIKE '%{symbol}%'))
);
COMMENT ON TABLE news_sources IS 'Where sync_news reads news, announcements and social posts (M6). RSS sources can be added on /admin; other kinds need an adapter (D-135).';
COMMENT ON COLUMN news_sources.code IS 'Stable key; also the sentiment_daily scope of social sources.';
COMMENT ON COLUMN news_sources.kind IS 'Adapter that reads it: rss (any RSS/Atom feed), mops (exchange OpenAPI 重大訊息), cnyes, cmoney_notes, ptt, cmoney_forum.';
COMMENT ON COLUMN news_sources.channel IS 'news = media articles; announcement = exchange 重大訊息; social = forum posts.';
COMMENT ON COLUMN news_sources.url IS 'Feed or page URL. With per_stock it is a template: {symbol} = 2330, {market_suffix} = TW (上市) or TWO (上櫃).';
COMMENT ON COLUMN news_sources.per_stock IS 'Fetched once per watched stock (holdings and watchlist) instead of once per round.';
COMMENT ON COLUMN news_sources.market IS 'Market of a per-market source (mops); NULL otherwise.';
COMMENT ON COLUMN news_sources.interval_minutes IS 'Minimum minutes between two fetches during poll_news.';
COMMENT ON COLUMN news_sources.keywords IS 'Keep only items whose title contains one of these; empty = keep all.';
COMMENT ON COLUMN news_sources.use_llm IS 'Whether its items go to the LLM (summary, sentiment, importance).';
COMMENT ON COLUMN news_sources.last_error IS 'Error of the latest failed fetch; cleared by the next success.';
CREATE TRIGGER news_sources_updated_at BEFORE UPDATE ON news_sources
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO news_sources (code, name, kind, channel, url, per_stock, market, interval_minutes, enabled) VALUES
  ('mops_twse',       '重大訊息（上市）',     'mops',         'announcement', 'https://openapi.twse.com.tw/v1/opendata/t187ap04_L',        false, 'twse', 5,  true),
  ('mops_tpex',       '重大訊息（上櫃）',     'mops',         'announcement', 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O',     false, 'tpex', 5,  true),
  ('yahoo_tw_market', 'Yahoo 股市 台股盤勢',  'rss',          'news',         'https://tw.stock.yahoo.com/rss?category=tw-market',         false, NULL,   15, true),
  ('yahoo_stock',     'Yahoo 股市 個股新聞',  'rss',          'news',         'https://tw.stock.yahoo.com/rss?s={symbol}.{market_suffix}', true,  NULL,   30, true),
  ('udn_stock',       '經濟日報 證券',        'rss',          'news',         'https://money.udn.com/rssfeed/news/1001/5590?ch=money',     false, NULL,   15, true),
  ('ctee_stock',      '工商時報 證券',        'rss',          'news',         'https://www.ctee.com.tw/rss_web/livenews/stock',            false, NULL,   15, true),
  ('cnyes_tw_stock',  '鉅亨網 台股新聞',      'cnyes',        'news',         'https://news.cnyes.com/api/v3/news/category/tw_stock',      false, NULL,   15, true),
  ('cmoney_notes',    'CMoney 投資網誌',      'cmoney_notes', 'news',         'https://www.cmoney.tw/notes/',                               false, NULL,   30, false),
  ('ptt_stock',       'PTT 股票板 [標的]',    'ptt',          'social',       'https://www.ptt.cc/bbs/Stock/index.html',                   false, NULL,   30, true),
  ('cmoney_forum',    'CMoney 股市爆料同學會', 'cmoney_forum', 'social',       'https://www.cmoney.tw/forum/stock/{symbol}',                true,  NULL,   30, true);

CREATE TABLE news_items (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id        bigint NOT NULL REFERENCES news_sources (id) ON DELETE CASCADE,
  channel          text NOT NULL CHECK (channel IN ('news', 'announcement', 'social')),
  external_id      text NOT NULL,
  url              text NOT NULL,
  title            text NOT NULL CHECK (btrim(title) <> ''),
  snippet          text CHECK (char_length(snippet) <= 500),
  published_at     timestamptz NOT NULL,
  fetched_at       timestamptz NOT NULL DEFAULT now(),
  meta             jsonb NOT NULL DEFAULT '{}'::jsonb,
  duplicate_of     bigint REFERENCES news_items (id) ON DELETE SET NULL,
  llm_status       text NOT NULL DEFAULT 'pending' CHECK (llm_status IN (
                     'pending', 'done', 'skipped', 'failed', 'duplicate')),
  llm_attempts     smallint NOT NULL DEFAULT 0 CHECK (llm_attempts >= 0),
  summary          text,
  sentiment        numeric(4, 3) CHECK (sentiment BETWEEN -1 AND 1),
  sentiment_source text CHECK (sentiment_source IN ('llm', 'author')),
  event_type       text CHECK (event_type IN (
                     'earnings', 'revenue', 'guidance', 'dividend', 'capital', 'order',
                     'product', 'expansion', 'merger', 'management', 'legal', 'analyst',
                     'institutional', 'macro', 'market', 'rumor', 'other')),
  importance       smallint CHECK (importance BETWEEN 1 AND 5),
  topics           text[] NOT NULL DEFAULT '{}',
  llm_provider     text,
  llm_model        text,
  processed_at     timestamptz,
  raw_object_id    bigint REFERENCES raw_objects (id) ON DELETE SET NULL,
  CONSTRAINT news_items_natural_key UNIQUE (source_id, external_id),
  CONSTRAINT news_items_not_own_duplicate CHECK (duplicate_of IS NULL OR duplicate_of <> id),
  CONSTRAINT news_items_sentiment_source CHECK ((sentiment IS NULL) = (sentiment_source IS NULL))
);
COMMENT ON TABLE news_items IS 'News articles, exchange announcements and social posts (D-142): title, short snippet, link and LLM results; never full text (PLAN.md section 5, D-138).';
COMMENT ON COLUMN news_items.external_id IS 'The source''s own id (RSS guid or normalized URL, MOPS symbol+date+time+seq, PTT article id, forum post id).';
COMMENT ON COLUMN news_items.url IS 'Link to the original (normalized: tracking parameters removed).';
COMMENT ON COLUMN news_items.snippet IS 'The source''s own short description, at most 500 characters; NULL for social posts (their text is only read while processing).';
COMMENT ON COLUMN news_items.published_at IS 'Publication time (UTC); announcements: the exchange''s 發言日期 + 發言時間.';
COMMENT ON COLUMN news_items.meta IS 'Source-specific fields: PTT pushes/boos/arrows, forum author stance (bullish/bearish) and likes, announcement clause and fact date.';
COMMENT ON COLUMN news_items.duplicate_of IS 'The first item of the same event (D-139); duplicates are not sent to the LLM and show its results.';
COMMENT ON COLUMN news_items.llm_status IS 'pending = waiting for the LLM; done; skipped = filtered out by the funnel; failed = gave up after retries; duplicate = see duplicate_of.';
COMMENT ON COLUMN news_items.summary IS 'LLM summary in Traditional Chinese (marked as AI summary on the site).';
COMMENT ON COLUMN news_items.sentiment IS 'Overall tone for the stocks concerned, -1 (very negative) .. 1 (very positive).';
COMMENT ON COLUMN news_items.sentiment_source IS 'llm = scored by the LLM; author = the forum author''s own 看多/看空 tag (+0.8 / -0.8).';
COMMENT ON COLUMN news_items.importance IS 'LLM importance for an investor, 1 (noise) .. 5 (material).';
COMMENT ON COLUMN news_items.topics IS 'Industries or themes the LLM named.';
COMMENT ON COLUMN news_items.llm_provider IS 'llm_providers.code that answered (results of different models may differ in scale).';
CREATE INDEX news_items_published_idx ON news_items (published_at DESC);
CREATE INDEX news_items_pending_idx ON news_items (published_at) WHERE llm_status = 'pending';
CREATE INDEX news_items_url_idx ON news_items (url);
CREATE INDEX news_items_duplicate_idx ON news_items (duplicate_of) WHERE duplicate_of IS NOT NULL;
CREATE INDEX news_items_raw_object_idx ON news_items (raw_object_id);

CREATE TABLE news_item_stocks (
  item_id   bigint NOT NULL REFERENCES news_items (id) ON DELETE CASCADE,
  stock_id  bigint NOT NULL REFERENCES stocks (id),
  relation  text NOT NULL CHECK (relation IN ('direct', 'industry', 'theme')),
  weight    numeric(3, 2) NOT NULL CHECK (weight > 0 AND weight <= 1),
  sentiment numeric(4, 3) CHECK (sentiment BETWEEN -1 AND 1),
  PRIMARY KEY (item_id, stock_id)
);
COMMENT ON TABLE news_item_stocks IS 'Which stocks an item concerns (PLAN.md section 5: direct mention or industry/theme relation, with a weight).';
COMMENT ON COLUMN news_item_stocks.relation IS 'direct = symbol, name or alias in the text; industry / theme = related through stocks.industry or a theme the item names.';
COMMENT ON COLUMN news_item_stocks.weight IS '1 for direct mentions; lower for industry and theme relations.';
COMMENT ON COLUMN news_item_stocks.sentiment IS 'Tone toward this stock when the LLM scored stocks separately; NULL = use the item''s.';
CREATE INDEX news_item_stocks_stock_idx ON news_item_stocks (stock_id, item_id);

CREATE TABLE stock_aliases (
  alias      text PRIMARY KEY CHECK (char_length(btrim(alias)) >= 2),
  stock_id   bigint NOT NULL REFERENCES stocks (id) ON DELETE CASCADE,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE stock_aliases IS 'Other names of a stock found in news and posts (護國神山, 發哥, TSMC), edited on /admin; the symbol and official name are matched without an alias.';
CREATE INDEX stock_aliases_stock_idx ON stock_aliases (stock_id);

INSERT INTO stock_aliases (alias, stock_id, note)
SELECT a.alias, s.id, a.note
FROM (VALUES
  ('台積',     '2330', NULL),
  ('台GG',     '2330', 'PTT 用語'),
  ('護國神山', '2330', NULL),
  ('TSMC',     '2330', NULL),
  ('發哥',     '2454', NULL),
  ('MTK',      '2454', NULL),
  ('海公公',   '2317', NULL),
  ('Foxconn',  '2317', NULL),
  ('UMC',      '2303', NULL)
) AS a (alias, symbol, note)
JOIN stocks s ON s.symbol = a.symbol AND s.delisted_date IS NULL;

CREATE TABLE slang_terms (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  term       text NOT NULL UNIQUE CHECK (btrim(term) <> ''),
  meaning    text NOT NULL CHECK (btrim(meaning) <> ''),
  polarity   smallint CHECK (polarity IN (-1, 0, 1)),
  note       text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE slang_terms IS 'Taiwan stock and PTT slang sent with social posts to the LLM (PLAN.md section 5), maintained on /admin.';
COMMENT ON COLUMN slang_terms.polarity IS 'Usual direction: 1 bullish, -1 bearish, 0 neutral, NULL depends on context.';
CREATE TRIGGER slang_terms_updated_at BEFORE UPDATE ON slang_terms
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO slang_terms (term, meaning, polarity) VALUES
  ('反串',     '故意說與自己真正看法相反的話，多為嘲諷；字面看多可能其實看空', NULL),
  ('丸子',     '「完了」的諧音，表示情況很糟', -1),
  ('畢業',     '賠光本金、離開股市', -1),
  ('公園',     '虧損慘重（戲稱賠到要去公園住）', -1),
  ('歐印',     'all in，把資金全部押上', NULL),
  ('韭菜',     '容易被收割的散戶', NULL),
  ('抬轎',     '在高檔追價買進，替先進場的人拉高價格', NULL),
  ('倒貨',     '主力或大戶在高檔大量賣出', -1),
  ('出貨',     '主力或大戶在高檔賣出持股', -1),
  ('養套殺',   '主力先拉抬吸引散戶、套牢後再殺低', -1),
  ('噴',       '股價大漲', 1),
  ('嘎空',     '軋空：空方被迫回補而推升股價', 1),
  ('鎖漲停',   '漲停且買單排隊未打開', 1),
  ('鎖跌停',   '跌停且賣單排隊未打開', -1),
  ('跳樓',     '股價大跌', -1),
  ('住套房',   '買在高點被套牢', -1),
  ('站崗',     '買在高點後長期套牢', -1),
  ('逃命波',   '下跌途中的反彈，被認為是賣出機會', -1),
  ('接刀',     '在急跌途中買進', NULL),
  ('抄底',     '在認為的低點買進', NULL),
  ('上車',     '買進', NULL),
  ('下車',     '賣出', NULL),
  ('空手',     '目前沒有持股', 0),
  ('開香檳',   '提前慶祝獲利，常帶反諷', NULL),
  ('被巴',     '預測被市場打臉', NULL),
  ('少年股神', '戲稱短期獲利的人，多帶反諷', NULL),
  ('送分題',   '認為穩賺的機會，常是過度自信', 1),
  ('多軍',     '看多的人', NULL),
  ('空軍',     '看空的人', NULL),
  ('航海王',   '貨櫃航運股（長榮、陽明、萬海）', 0),
  ('存股',     '長期持有領股利', 0),
  ('當沖',     '當日沖銷，同日買賣', 0);

CREATE TABLE llm_providers (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code                text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_]+$'),
  name                text NOT NULL CHECK (btrim(name) <> ''),
  base_url            text NOT NULL CHECK (base_url ~ '^https://'),
  model               text NOT NULL CHECK (btrim(model) <> ''),
  api_key_env         text NOT NULL CHECK (api_key_env ~ '^[A-Z][A-Z0-9_]*$'),
  priority            smallint NOT NULL,
  enabled             boolean NOT NULL DEFAULT true,
  paid                boolean NOT NULL DEFAULT false,
  requests_per_minute integer CHECK (requests_per_minute > 0),
  requests_per_day    integer CHECK (requests_per_day > 0),
  json_mode           text NOT NULL DEFAULT 'json_object' CHECK (json_mode IN (
                        'json_schema', 'json_object', 'none')),
  input_usd_per_mtok  numeric(10, 4) CHECK (input_usd_per_mtok >= 0),
  output_usd_per_mtok numeric(10, 4) CHECK (output_usd_per_mtok >= 0),
  cooldown_until      timestamptz,
  last_error          text,
  last_error_at       timestamptz,
  last_success_at     timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT llm_providers_paid_prices CHECK (
    NOT paid OR (input_usd_per_mtok IS NOT NULL AND output_usd_per_mtok IS NOT NULL))
);
COMMENT ON TABLE llm_providers IS 'OpenAI-compatible chat completion services tried in priority order, free first (D-137); edited on /admin. Keys live in the environment, never here (rule 8).';
COMMENT ON COLUMN llm_providers.base_url IS 'Endpoint root; the client posts to {base_url}/chat/completions.';
COMMENT ON COLUMN llm_providers.api_key_env IS 'Name of the environment variable that holds the key (e.g. GROQ_API_KEY); a service without its key is skipped.';
COMMENT ON COLUMN llm_providers.priority IS 'Lower is tried first.';
COMMENT ON COLUMN llm_providers.paid IS 'Charged per token: used only when the LLM daily cost cap allows (settings llm.daily_usd_cap).';
COMMENT ON COLUMN llm_providers.requests_per_minute IS 'Our own pacing below the service''s free limit; NULL = no pacing.';
COMMENT ON COLUMN llm_providers.requests_per_day IS 'Requests per Taipei day before the service rests until tomorrow; NULL = no limit.';
COMMENT ON COLUMN llm_providers.json_mode IS 'How to ask for JSON: json_schema (strict schema), json_object, or none (prompt only). Answers are validated either way.';
COMMENT ON COLUMN llm_providers.cooldown_until IS 'Not tried before this time (set after 429, quota or repeated errors).';
CREATE TRIGGER llm_providers_updated_at BEFORE UPDATE ON llm_providers
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO llm_providers (code, name, base_url, model, api_key_env, priority, requests_per_minute, requests_per_day, json_mode) VALUES
  ('google_ai_studio', 'Google AI Studio', 'https://generativelanguage.googleapis.com/v1beta/openai', 'gemini-flash-latest',                 'GEMINI_API_KEY',     10, 8,  200,  'json_object'),
  ('groq',             'Groq',             'https://api.groq.com/openai/v1',                          'qwen/qwen3-32b',                      'GROQ_API_KEY',       20, 20, 1000, 'json_object'),
  ('openrouter',       'OpenRouter',       'https://openrouter.ai/api/v1',                            'google/gemma-4-31b-it:free',          'OPENROUTER_API_KEY', 30, 15, 50,   'json_object'),
  ('nvidia_nim',       'NVIDIA NIM',       'https://integrate.api.nvidia.com/v1',                     'deepseek-ai/deepseek-v4.1-flash',     'NVIDIA_API_KEY',     40, 30, NULL, 'json_object');

CREATE TABLE llm_usage (
  provider_id   bigint NOT NULL REFERENCES llm_providers (id) ON DELETE CASCADE,
  usage_date    date NOT NULL,
  requests      integer NOT NULL DEFAULT 0 CHECK (requests >= 0),
  failures      integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
  input_tokens  bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
  output_tokens bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  cost_usd      numeric(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  PRIMARY KEY (provider_id, usage_date)
);
COMMENT ON TABLE llm_usage IS 'Requests, tokens and cost per LLM service and Taipei day (daily limits, the cost cap and /admin).';
COMMENT ON COLUMN llm_usage.failures IS 'Requests that failed (HTTP error, timeout or an invalid answer).';
COMMENT ON COLUMN llm_usage.cost_usd IS 'Tokens times the service''s price (0 for free services).';

CREATE TABLE sentiment_daily (
  stock_id    bigint NOT NULL REFERENCES stocks (id),
  trade_date  date NOT NULL,
  scope       text NOT NULL CHECK (scope ~ '^[a-z0-9_]+$'),
  items       integer NOT NULL CHECK (items >= 0),
  scored      integer NOT NULL CHECK (scored >= 0 AND scored <= items),
  sentiment   numeric(4, 3) CHECK (sentiment BETWEEN -1 AND 1),
  bullish     integer NOT NULL DEFAULT 0 CHECK (bullish >= 0),
  bearish     integer NOT NULL DEFAULT 0 CHECK (bearish >= 0),
  pushes      integer NOT NULL DEFAULT 0 CHECK (pushes >= 0),
  boos        integer NOT NULL DEFAULT 0 CHECK (boos >= 0),
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (stock_id, trade_date, scope),
  CONSTRAINT sentiment_daily_scored CHECK ((sentiment IS NULL) = (scored = 0))
);
COMMENT ON TABLE sentiment_daily IS 'Daily sentiment per stock (PLAN.md section 5, D-140), accumulated from the M6 launch on; M7 joins it into stock_features_daily.';
COMMENT ON COLUMN sentiment_daily.trade_date IS 'Trading day whose close (13:30 Taipei) is the first at or after the item''s publication, so a day only counts what was known before it closed.';
COMMENT ON COLUMN sentiment_daily.scope IS 'news, announcement, a social source code (ptt_stock, cmoney_forum), or all.';
COMMENT ON COLUMN sentiment_daily.items IS 'Items linked to the stock (duplicates counted once), weighted links included.';
COMMENT ON COLUMN sentiment_daily.sentiment IS 'Weighted mean sentiment of the scored items (link weight times importance); NULL when none was scored.';
COMMENT ON COLUMN sentiment_daily.bullish IS 'Items with sentiment >= 0.3 (social: includes author tags).';
COMMENT ON COLUMN sentiment_daily.bearish IS 'Items with sentiment <= -0.3.';
COMMENT ON COLUMN sentiment_daily.pushes IS 'PTT 推 on the day''s posts (0 for other scopes).';
COMMENT ON COLUMN sentiment_daily.boos IS 'PTT 噓 on the day''s posts.';
CREATE INDEX sentiment_daily_date_idx ON sentiment_daily (trade_date);
ALTER TABLE sentiment_daily CLUSTER ON sentiment_daily_pkey;

ALTER TABLE alerts ADD COLUMN channels text[] NOT NULL DEFAULT '{}';
COMMENT ON COLUMN alerts.channels IS 'Notification channels that accepted the alert (line, telegram, email, console); empty = shown on the site only or sending failed.';
ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check CHECK (kind IN (
  'holding_move', 'institutional_flow', 'business_signal', 'policy_rate',
  'announcement', 'news_sentiment', 'social_buzz'));
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold; institutional_flow = an institutional group traded a large share of a holding''s volume; business_signal = the 景氣對策信號 light changed colour; policy_rate = the Fed target rate changed; announcement = 重大訊息 of a holding or watched stock (one row per stock and day, later ones appended to detail.items); news_sentiment = extreme news sentiment on a holding or watched stock; social_buzz = social post count far above normal (PLAN.md section 5).';

ALTER TABLE job_requests DROP CONSTRAINT job_requests_job_name_check;
ALTER TABLE job_requests ADD CONSTRAINT job_requests_job_name_check CHECK (job_name IN (
  'daily_prices', 'catch_up_prices', 'refetch_stock_prices', 'refresh_stock_fundamentals',
  'sync_chips', 'sync_markets', 'sync_macro', 'sync_news', 'check_llm_providers'));

-- migrate:down
ALTER TABLE job_requests DROP CONSTRAINT job_requests_job_name_check;
DELETE FROM job_requests WHERE job_name IN ('sync_news', 'check_llm_providers');
ALTER TABLE job_requests ADD CONSTRAINT job_requests_job_name_check CHECK (job_name IN (
  'daily_prices', 'catch_up_prices', 'refetch_stock_prices', 'refresh_stock_fundamentals',
  'sync_chips', 'sync_markets', 'sync_macro'));
DELETE FROM alerts WHERE kind IN ('announcement', 'news_sentiment', 'social_buzz');
ALTER TABLE alerts DROP CONSTRAINT alerts_kind_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_kind_check
  CHECK (kind IN ('holding_move', 'institutional_flow', 'business_signal', 'policy_rate'));
COMMENT ON COLUMN alerts.kind IS 'holding_move = a holding moved beyond its volatility threshold; institutional_flow = an institutional group traded a large share of a holding''s volume; business_signal = the 景氣對策信號 light changed colour; policy_rate = the Fed target rate changed (PLAN.md section 5); M6 adds news.';
ALTER TABLE alerts DROP COLUMN channels;
DROP TABLE sentiment_daily;
DROP TABLE llm_usage;
DROP TABLE llm_providers;
DROP TABLE slang_terms;
DROP TABLE stock_aliases;
DROP TABLE news_item_stocks;
DROP TABLE news_items;
DROP TABLE news_sources;
