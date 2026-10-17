# StockHub：台股分析平台

個人自用的台股研究平台：基本面、籌碼、總經、新聞與社群情緒、持股追蹤、選股篩選器與回測。單人使用，全端專案。

- 完整規劃摘要：`docs/PLAN.md`
- 目前任務：`docs/M0.md`（里程碑 M0：地基）
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

## 常用指令（M0 完成後應全部可用）

```
docker compose up -d          # 本機 Postgres
make migrate                  # 套用 db/migrations
make py-test                  # ruff + 型別檢查 + pytest
make web-dev                  # Next.js 開發伺服器
make web-check                # lint + typecheck + test
uv run python -m stockhub.etl run heartbeat   # 執行一個排程任務
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
- Web 讀資料的頁面要在自己的 `<Suspense>` 內先 `await requireUser()`；route handler 用 `requireApiUser()`。layout 與 page 並行渲染，proxy 和 layout 的檢查都不夠（見 DECISIONS D-032）。
