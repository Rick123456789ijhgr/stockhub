# StockHub：台股分析平台

個人自用的台股研究平台：基本面、籌碼、總經、新聞與社群情緒、持股追蹤、選股篩選器與回測。單人使用，全端專案。

- 完整規劃摘要：`docs/PLAN.md`
- 任務檔：`docs/M0.md`（地基）、`docs/M2.md`（持股、費用、配息推算、自選清單）
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
stockhub.bat                  # 雙擊開選單；或 start|stop|restart|status：本機資料庫 + 網站（邏輯在 scripts/stockhub.ps1）
scripts/register-tasks.ps1    # Windows 工作排程（平日 08:55 報價、18:00 每日）；記錄在 .local/logs
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
- 持股計算：`py/stockhub/engine/portfolio.py` 與 `web/src/lib/portfolio.ts` 逐式對應（平均成本、手續費、證交稅、配息推算、今日損益），改任一邊都要同步另一邊，並用 `py/scripts/gen_portfolio_fixture.py` 重產 `testdata/portfolio.json`。交易寫入一律經 `applyTransactionChange`（重播檢查賣超、重算自動費用、寫稽核紀錄）。配息推算不入庫，頁面每次重算並標示「估算」。
- 所有手動操作（交易、自選、設定、事件確認）都寫 `audit_log`，`action` 用 `領域.動作`（例如 `portfolio.update`），新動作要在 `components/admin/audit-log.tsx` 加中文標籤。
- 還原價 = 原始價 × `adj_factor`；漲跌一律用還原後的前收（`rebasedPrevClose`），不要直接拿原始前收算。
- 圖表顏色只用 token：漲跌 `--price-up/down`，線 `--series-1..3`（已用 dataviz 驗證，最多三條會交錯的線）；Tailwind v4 會刪掉沒被 utility 用到的變數，新 token 要有對應的 `bg-*` 等用法。
- 手動確認的事件 `corporate_actions.source = 'manual'`；匯入同一天的官方事件時會刪掉它。`action_type` 保留交易所的標示（它是自然鍵的一部分），事件實際內容看 `cash_dividend`、`stock_dividend_ratio`、`rights_ratio`。
- `/status` 這類彙總要讀 `prices_daily_coverage`（由觸發器維護），不要直接掃 `prices_daily`。
- 顯示偏好（主題、漲跌配色）存在 localStorage，由 `lib/appearance.ts` 管理，`<head>` 的內嵌腳本負責第一次繪製；不要另外寫一套。
- Web 讀資料的頁面要在自己的 `<Suspense>` 內先 `await requireUser()`；route handler 用 `requireApiUser()`。layout 與 page 並行渲染，proxy 和 layout 的檢查都不夠（見 DECISIONS D-032）。
