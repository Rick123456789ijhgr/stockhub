# StockHub：台股分析平台

個人自用的台股研究平台：基本面、籌碼、總經、新聞與社群情緒、持股追蹤、選股篩選器與回測。單人使用，全端專案。

- 完整規劃摘要：`docs/PLAN.md`
- 任務檔：`docs/M0.md`（地基）、`docs/M2.md`（持股、費用、配息推算、自選清單）、`docs/M3.md`（基本面與估值、缺漏日線補抓）、`docs/M4.md`（籌碼）、`docs/M5.md`（總經、國際市場、熱力圖、題材）
- 與規劃有偏離時，記錄在 `docs/DECISIONS.md`（日期、原因、取捨），不要默默改。

## 技術棧

| 層級 | 選擇 |
|---|---|
| 前端與一般 API | Next.js（App Router、TypeScript strict）、Tailwind、shadcn/ui、TanStack Query，部署 Vercel |
| 登入 | Auth.js，Google OAuth + 單一 email 白名單 |
| 資料庫 | PostgreSQL（正式環境 Neon；本機 docker compose） |
| 後端批次、特徵、回測 | Python 3.12（uv 管理）、SQLAlchemy 2 + psycopg 3、pydantic v2、pandas |
| 排程 | Cloud Run Jobs + Cloud Scheduler |
| 原始資料 | 物件儲存（正式 GCS；本機檔案系統），透過 `RawStore` 抽象 |
| 快取 | Redis（M2 起，盤中報價） |
| 篩選器與回測 API | FastAPI（M7，Cloud Run），僅接受 Next.js 的服務間請求 |
| CI | GitHub Actions |

## 目錄結構

```
web/                 Next.js 應用
py/                  單一 uv 專案
  stockhub/common/   設定、DB、RawStore、Notifier、交易日曆（共用資料存取層）
  stockhub/etl/      providers/（資料源 adapter）、jobs/（排程任務）
  stockhub/engine/   特徵、篩選、回測（M7）
db/migrations/       SQL 遷移（唯一的 schema 來源）
infra/               Dockerfile、部署腳本與說明
docs/                規劃、任務、決策紀錄
```

註：規劃書原寫 `etl/` 與 `engine/` 兩個目錄，這裡合併為單一 Python 專案 `py/` 以共用資料存取層。

## 常用指令

```
make db-up                    # 本機 Postgres（docker compose，port 5433）
make db-local-up              # 沒有 Docker 時：scripts/local-pg.sh 的本機叢集（同 port、同帳密）
make migrate                  # 套用 db/migrations（dbmate）；新增遷移：make db-new name=xxx
make db-types                 # 遷移後重新產生 web 的 Kysely 型別（CI 會檢查是否過期）
make py-test                  # 先遷移測試庫，再 ruff + mypy + pytest
make web-dev                  # Next.js 開發伺服器（web/scripts/next.mjs 會載入根目錄 .env）
make web-check                # lint + typecheck + test
make etl-daily                # 休市表 + 股票主檔 + 當日日線（date=YYYY-MM-DD 可指定）
make etl-backfill             # 回填日線（start= end=，預設過去一年；可中斷續跑）
make etl-history              # 完整歷史（下市、2004 起日線、除權息、還原因子；約 7～8 小時）
make etl-quotes               # 盤中報價輪詢（自選 + 持股，每 30 秒）
make etl-adjust               # 重算還原因子（在 /admin 確認跳空後）
make etl-dividends            # 證交所權息拆分（start= end=，預設近 30 天）
make etl-etf-delistings       # 從已存的日線表推算下市 ETF（不連網，回填完成後才跑）
make etl-previews             # 除權除息預告表（etl-daily 與 etl-quotes 也會跑）
make notify-test              # 經 NOTIFIER 寄一則測試通知（設定 SMTP 後用；步驟見 README）
make etl-fundamentals         # 財報與月營收歷史（2013 起，FinMind；約 17 小時，可續跑；symbols= refetch=true）
make etl-financials           # 最新一季財報與月營收（官方 OpenAPI），再向 FinMind 補新申報的公司（etl-daily 也會跑）
make etl-compute-fundamentals # 重算 fundamentals_quarterly 與 fundamental_signals（all=true 全部）
make etl-chips                # 籌碼：補近 10 個交易日缺的表、集保本週、摘要、法人警示（date= 重抓某天；21:30 排程）
make etl-chips-history        # 籌碼歷史（2012-05-02 起，約 11 小時，可續跑）
make etl-markets              # 市場與總經：指數、匯率、商品、美債、國發會、美國總經、總經警示（07:30 排程）
make etl-markets-history      # 市場序列歷史（2004 起；series=SPX,TAIEX start= end=，可續跑）
make etl-requests             # 執行網站排入的任務（JOB_RUNNER=local 時網站會自己啟動）
make db-cluster               # 依股票重排大表（CLUSTER，會鎖表；平日 07:00～22:30 跳過，force=true 例外；週六排程）
stockhub.bat                  # 雙擊＝啟動資料庫與網站（正式建置，程式碼有變先 build；只綁 127.0.0.1；背景執行，記錄在 .local/logs/web-*.log）；或 start|stop|restart|status|dev（邏輯在 scripts/stockhub.ps1）
scripts/register-tasks.ps1    # Windows 工作排程（平日 07:30 市場與總經、08:55 報價、18:00 每日、21:30 籌碼、週六 10:00 重排、登入時啟動資料庫）；記錄在 .local/logs
```

## 不可違反的規則

1. **價格存原始價與還原因子**：`prices_daily` 存未還原的開高低收與 `adj_factor`，不覆蓋原始價。ETF 同樣適用。
2. **時間**：交易日期一律用 `date`（台北交易日）；時間戳用 UTC `timestamptz`；顯示層才轉台灣時間。國際市場以交易所當地日期儲存。
3. **財報用長表**：`financials` 為（股票、期別、報表、科目代碼、數值）長表，保留 `publish_date`（可為空）與 `revision`；財報多為累計數，單季化在計算層做，不改原始資料。
4. **寫入必須冪等**：所有擷取任務可安全重跑（upsert 或以唯一鍵去重）。
5. **先落地原始回應再解析**：每次擷取先存 `RawStore` 並寫 `raw_objects`，解析失敗也要有原始檔可重算。
6. **非官方資料源只能經 provider adapter**：twstock、yfinance、FinMind 與未來券商 API 都實作同一組介面，設主來源與備援；上層不得直接 import 資料源套件。
7. **異常資料不覆蓋正式表**：品質檢查不過的資料先放隔離區待確認。
8. **秘密不進版本庫**：只用環境變數與 `.env.example`；`.env*` 在 `.gitignore`。
9. **所有路由與 API 都檢查 session**：持股與交易紀錄是敏感資料。
10. **台股配色**：紅漲綠跌，設計 token 可切換，不寫死顏色。
11. **前端與 Python 的指標公式必須一致**：用共用的標準測試資料驗證（M1 起）。
12. **爬取要守規矩**：優先官方 OpenAPI，限速，遵守 robots 與使用條款。
13. **一律以中文回答**：與使用者的所有對話、計畫、進度回報與總結都用繁體中文；程式碼、識別名稱與指令照原樣，程式碼註解沿用周圍既有的語言。

## 工作方式

- 開工前先給計畫，等確認後再大量改動；每個任務小步提交（Conventional Commits）。
- 計算邏輯（指標、單季化、還原價、配息推算、回測引擎）一定要有單元測試。
- 新增依賴要說明理由；優先沿用既有套件。
- 不確定的需求先問，不要自行擴大範圍。M0 的範圍外清單見 `docs/M0.md`。
- 學到值得保留的慣例，更新本檔。
- 新資料源：在 `stockhub/etl/providers/` 實作介面的 `fetch_*`（只做 I/O）與 `parse_*`（純函式），用 `@register_provider` 註冊；擷取一律透過 `ProviderRouter`，由它把原始回應存進 RawStore，任務不要自己呼叫 provider 的 `fetch_*`。
- 新排程任務：繼承 `Job`、用 `@register_job` 註冊，並在 `stockhub/etl/jobs/__init__.py` 匯入；寫入一律用 `upsert()`，長任務用 `ctx.save_checkpoint()`。
- 新 schema：只加遷移檔（`make db-new`），必附 `COMMENT ON`、`down` 段與 pytest schema 測試，再跑 `make db-types`。
- 指標公式：`py/stockhub/engine/indicators.py` 與 `web/src/lib/indicators.ts` 逐式對應；改任一邊都要同步另一邊，並用 `py/scripts/gen_indicator_fixture.py` 重產 `testdata/indicators.json`。
- 持股計算：`py/stockhub/engine/portfolio.py` 與 `web/src/lib/portfolio.ts` 逐式對應（平均成本、手續費、證交稅、配息推算、今日損益），改任一邊都要同步另一邊，並用 `py/scripts/gen_portfolio_fixture.py` 重產 `testdata/portfolio.json`。交易寫入一律經 `applyTransactionChange`（重播檢查賣超、重算自動費用、寫稽核紀錄）。配息推算不入庫，頁面每次重算並標示「估算」；有 `dividend_receipts` 實收時改用實收。讀持股的 Python 程式一律用 `common/portfolio_store.holdings()`（引擎重播），不要自己加總交易股數。
- `corporate_action_previews` 是預告快照，只供推算與當天暫時套用（`with_previews`）；正式紀錄永遠是 `corporate_actions`。
- 警示寫進 `alerts`（唯一鍵 kind + 股票 + 交易日就是冷卻），經 `Notifier` 送出；新種類要擴充 `kind` 的 CHECK。
- 所有手動操作（交易、自選、設定、事件確認）都寫 `audit_log`，`action` 用 `領域.動作`（例如 `portfolio.update`），新動作要在 `components/admin/audit-log.tsx` 加中文標籤。
- 還原價 = 原始價 × `adj_factor`；漲跌一律用還原後的前收（`rebasedPrevClose`），不要直接拿原始前收算。
- 圖表顏色只用 token：漲跌 `--price-up/down`，線 `--series-1..3`（已用 dataviz 驗證，最多三條會交錯的線）；Tailwind v4 會刪掉沒被 utility 用到的變數，新 token 要有對應的 `bg-*` 等用法。
- 手動確認的事件 `corporate_actions.source = 'manual'`；匯入同一天的官方事件時會刪掉它。`action_type` 保留交易所的標示（它是自然鍵的一部分），事件實際內容看 `cash_dividend`、`stock_dividend_ratio`、`rights_ratio`。
- `/status` 這類彙總要讀 `prices_daily_coverage`（由觸發器維護），不要直接掃 `prices_daily`。
- 顯示偏好（主題、漲跌配色）存在 localStorage，由 `lib/appearance.ts` 管理，`<head>` 的內嵌腳本負責第一次繪製；不要另外寫一套。
- 連到頂層頁面（側邊欄、返回連結）用 `components/nav/remembered-link.tsx` 的 `RememberedLink`，會回到該頁上次的分頁與選項（`lib/nav-memory.ts`，D-122）；新的頂層頁面要加進 `REMEMBERED_PAGES`。
- 本機判斷一律用 `lib/auth/mode.ts` 的 `isLocalMachine`（免登入、網站觸發任務都靠它），不要另外檢查 `NODE_ENV`；`STOCKHUB_LOCAL_SERVER` 只由 `stockhub.ps1` 設定，不放 `.env`（D-117）。
- 新的「每檔一段歷史」大表：遷移裡 `ALTER TABLE … CLUSTER ON` 以 `stock_id` 開頭的索引，`cluster_tables` 才會重排它（D-117）。
- Web 讀資料的元件要先 `await requireUser()`；route handler 用 `requireApiUser()`。layout 與 page 並行渲染，proxy 和 layout 的檢查都不夠（見 DECISIONS D-032）。
- 切換頁面不顯示骨架（D-118）：`(app)/layout.tsx` 設了 `instant = false`，頁面裡讀資料的元件不要包 `<Suspense>`（React 的 fallback 至少停 300 ms）；只有真的慢的區塊才包。點擊回饋由 `components/nav/nav-progress.tsx` 負責，選單與分頁的連結裡放 `LinkPending`。寫入之後要 `router.refresh()`（`staleTimes.dynamic` 會保留看過的頁面 30 秒）。
- 財報：`financials` 每個來源各存一份（`source` + `basis`：quarter／ytd／instant），數字改變就存成下一個 `revision`，寫入一律經 `store_statements`（品質檢查、隔離、取代隔離）。單季化、近四季、比率只在 `engine/fundamentals.py`，結果在 `fundamentals_quarterly`，網站只讀這張表；檢查規則改了就跑 `recheck_financials_quarantine`。
- FinMind 只經 `FinMindProvider`（`QuotaGuard` 守每小時額度，token 用標頭送出）；不要另外寫迴圈直接打 FinMind。每日更新先用官方 OpenAPI 快照，再只向 FinMind 補新申報的公司。
- 財報的「可用日」是 `available_date`（已知公布日，否則法定截止日，`common/filings.py`）；估值、篩選、回測都用它對齊，不要直接用 `period_end`。
- 估值公式：`py/stockhub/engine/valuation.py` 與 `web/src/lib/valuation.ts` 逐式對應，改任一邊都要同步另一邊，並用 `py/scripts/gen_valuation_fixture.py` 重產 `testdata/valuation.json`。
- 網站觸發 Python 任務一律排入 `job_requests`（`POST /api/jobs`，可排的任務在 `lib/job-request-input.ts` 與資料表 CHECK 兩處列舉，新增時兩邊都改），不要在 route handler 直接執行任務。
- 版面：頁內分頁用 `components/page-tabs.tsx`（`?tab=`，伺服器只渲染目前分頁；要保留其他參數用 `query`）；分段切換（例如股票／ETF、熱力圖期間）用 `components/segmented-links.tsx`；摺疊用 `components/disclosure.tsx`（原生 `<details>`，巢狀時箭頭用 `DISCLOSURE_CHEVRON`）；長列表、長表格用 `components/show-more.tsx` 先顯示一部分；卡片頂端的長說明收進 `InfoNote`。不要另外引入 tabs 或 accordion 套件。
- 圖表：小型時間序列用 `components/charts/time-chart.tsx`（lightweight-charts，顏色只用 token，數值格式在 `lib/chart-format.ts`）；不要做雙 Y 軸，兩種單位就拆成兩張圖。
- 籌碼：股數一律存「股」（融資融券以張公布，provider 乘 1000）；外資不含外資自營商，舊格式沒拆分的欄位存 NULL 不填 0。每個資料集、市場、日期抓過就寫 `chip_coverage`，補抓、續跑、`/status` 都讀它，不要掃籌碼表；當天未公布不寫涵蓋。衍生指標（連買天數、5／20 日累計、券資比、大戶比）只在 `engine/chips.py`，網站讀 `chip_summary` 與 `shareholding_concentration` 檢視表，不要在 TS 另算。
- 市場與總經：每條線是 `market_series` 的一個序列，值在 `market_series_values`（國際市場存交易所當地日期，月資料存月初）；provider 以 `series_symbols` 宣告服務哪些序列，`PROVIDERS_MARKET_SERIES` 的順序就是主來源與備援，一次只服務一個月的來源設 `series_monthly`。新增序列＝遷移加一列目錄＋在 provider 的 `series_symbols` 加代號。寫入一律經 `jobs/markets.py` 的 `store_observations`（品質檢查、隔離、取代隔離）；沒有 `has_ohlc` 的序列只存收盤值。涵蓋讀 `market_series_status` 檢視表。Yahoo 是非官方來源，只經 `YahooProvider`。
- 熱力圖：只用收盤資料，市值＝收盤價 × `issued_shares`，漲跌用還原價（`adjustedChange`），群組報酬以期初市值加權；計算在 `web/src/lib/heatmap-data.ts`（純函式），版面在 `lib/treemap.ts`；顏色只用 `heatColor`（`--price-up/down` 混入 `--muted`），不要另寫色碼。
- 題材：`themes` + `stock_themes`（起訖日，移出時設 `valid_to` 保留歷史，期間不得重疊），讀「某天的成分股」一律用 `valid_from <= d AND (valid_to IS NULL OR valid_to >= d)`；網站的寫入都經 `lib/themes.ts`（寫稽核紀錄）。
- 總經警示（`business_signal`、`policy_rate`）沒有股票：`alerts.stock_id` 為 NULL，讀警示要用 left join。
