# 決策紀錄

格式：日期、決定、原因、取捨。與 `docs/PLAN.md`、`docs/M0.md` 的偏離都記在這裡。

## 2026-10-18 M0 / T1 工具鏈

### D-001 Python 型別檢查用 mypy（strict）
- 原因：pydantic v2 與 SQLAlchemy 2 對 mypy 支援成熟；`strict = true` 從第一天開啟，避免之後補型別。
- 取捨：比 pyright 慢，但單人專案規模不構成問題。

### D-002 Python 專案採平鋪式結構 `py/stockhub/`，建置後端用 `uv_build`
- 原因：照 `CLAUDE.md` 的目錄結構；`uv_build` 是 uv 原生後端，不另外引入 hatchling。
- 設定：`module-root = ""`。

### D-003 pandas 延後到 M1 才加入
- 原因：M0 不處理任何市場資料，介面也規定回傳 pydantic 模型而非 DataFrame；沒用到的依賴先不加。

### D-004 Next.js 16.4（Turbopack、`cacheComponents: true`）與 `proxy.ts`
- Next.js 16 把 `middleware` 改名為 `proxy`（只跑 Node runtime）；M0.md 的「middleware 保護全站」以 `src/proxy.ts` 實作，意義相同。
- `cacheComponents` 維持 create-next-app 的預設開啟：讀 session 與查資料庫的元件須放在 `<Suspense>` 內。

### D-005 shadcn/ui 採 CLI 預設 `base-nova` 樣式（Base UI 元件），Vitest 不用 `vite-tsconfig-paths`
- shadcn 現行預設即為 Base UI；只在需要時逐一加入元件。
- Vite 已原生支援 `resolve.tsconfigPaths`，少一個依賴。

### D-006 本機開發環境：Windows + Git Bash
- Makefile 指定 `SHELL := bash`，在 Windows（Git Bash 的 make）與 Linux CI 行為一致。
- `.gitattributes` 強制 LF，避免 CRLF 造成 ruff／prettier 差異。

## 2026-10-18 M0 / T2 本機環境

### D-007 本機沒有 Docker 時，改用專案私有的 Postgres 實例（替代方案）
- 現況：開發機（Windows 11）沒有 Docker Desktop 與 WSL；已安裝的 PostgreSQL 17 服務占用 5432，帳密不由本專案管理。
- 決定：`docker-compose.yml`（Postgres 16）照規格提供，是正式的本機方案；另提供 `scripts/local-pg.sh`（`make db-local-init` / `db-local-up`），用已安裝的 Postgres 執行檔在 `.local/pgdata` 起一個獨立實例，帳密與 port 都和 compose 相同，`.env` 不用改。
- 取捨：本機替代實例是 PG 17，正式（Neon）與 CI 用 16。M0 的 SQL 只用 16 就有的功能；版本相容性以 CI（PG 16 service container）為準。
- 待辦：使用者安裝 Docker Desktop 後可直接改用 `make db-up`。

### D-008 本機 Postgres 用 5433 port
- 原因：避開開發機上既有的 5432 服務；compose 可用 `POSTGRES_PORT` 覆寫。

### D-009 遷移工具選 dbmate（v2.36）
- 原因：遷移是純 SQL 檔（符合「SQL 為唯一 schema 來源」），只需要一個執行檔，Python 與 Node 兩邊都不用綁特定 ORM。
- 取捨：放棄 Alembic 的自動比對產生遷移；本專案本來就要求手寫 SQL，影響不大。
- `make migrate` 在還沒有遷移檔時只做連線檢查（dbmate 遇到空目錄會報錯）。

### D-010 單一 `.env` 放在 repo 根目錄，`DATABASE_URL` 用 `postgresql://` 格式
- dbmate、Python、Next.js 共用同一份；Python 端在程式內把 scheme 換成 `postgresql+psycopg://`。
- Auth.js 的變數採 v5 慣例名稱（`AUTH_SECRET`、`AUTH_GOOGLE_ID`、`AUTH_GOOGLE_SECRET`）。
- 測試用獨立的 `TEST_DATABASE_URL`（`stockhub_test`），測試會清空它的資料表。

## 2026-10-18 M0 / T3 資料庫 schema

### D-011 不產生 `db/schema.sql` 快照
- 原因：dbmate 的快照是本機 `pg_dump` 輸出，PG 17 與 16 的輸出不同（例如 `\restrict`、`transaction_timeout`），會在不同機器間不斷產生差異。遷移檔本身就是唯一來源；CI 用「空資料庫完整套用」與 schema 測試把關。

### D-012 列舉值用 `text + CHECK`，不用 PG enum
- 原因：之後新增值只要改 CHECK，不必處理 `ALTER TYPE` 的交易限制；kysely-codegen 產生的型別是 `string`，Web 端再用 zod 或常數收斂。

### D-013 M0.md 未明定、由實作補上的 schema 細節
- 主鍵一律 `bigint GENERATED ALWAYS AS IDENTITY`；有 `updated_at` 的表用共用 trigger `set_updated_at()` 維護。
- `stocks.listed_date` 設為 NOT NULL（唯一鍵的一部分，可為 NULL 就無法去重）；另加部分唯一索引「同一代號只能有一筆未下市」，允許代號在下市後重新使用。
- `prices_daily`：主鍵（`stock_id`, `trade_date`）；OHLC 可為 NULL（無成交日）；價格 `numeric(12,4)`、成交金額 `numeric(20,2)`；檢查正值與 high ≥ low。
- `corporate_actions`：加唯一鍵（`stock_id`, `ex_date`, `action_type`）以滿足冪等寫入；`action_type` 另含 `reverse_split`、`rights_issue`、`other`；加 `raw_object_id` 與 `fetched_at` 方便追溯原始檔。
- `monthly_revenue`：主鍵（`stock_id`, `revenue_month`），月份存當月 1 日；加 `raw_object_id`；金額單位統一為元（來源若是千元，擷取時換算）。
- `financials` 唯一鍵照 M0.md，不含 `period_type`（台股第四季不單獨公告，12/31 只會有年報）。
- `raw_objects.sha256` 是「未壓縮內容」的雜湊；同一內容只存一份，`params` 記第一次擷取時的參數。
- `job_runs`：加部分唯一索引，同一（`job_name`, `params`）同時只能有一筆 running；CHECK 規定 running ⇔ `finished_at IS NULL`。
- `trading_calendar` 的種子範圍是 2005-01-01 到 2027-12-31，週一到週五視為交易日，標記 `seed:weekday-rule`，TODO(M1) 匯入官方休市表。

### D-014 Web 端資料庫型別：Kysely + kysely-codegen（`pg` driver）
- 型別由 `make db-types` 從資料庫產生到 `web/src/lib/db/types.gen.ts` 並進版控；CI 用 `kysely-codegen --verify` 檢查是否過期。
- `date` 欄位產生為 `string`（`YYYY-MM-DD`），執行期同樣把 pg 的 DATE 解析為字串，避免 JS `Date` 造成時區偏移；`numeric` 一律用字串保留精度。

### D-015 測試資料庫
- pytest 連 `TEST_DATABASE_URL`；`make py-test` 會先跑 `migrate-test`。每個測試包在一個最後會回滾的交易裡。

## 2026-10-18 M0 / T4 Python 共用層

### D-016 RawStore 先寫檔、再用自己的連線登錄並立即提交
- 原因：CLAUDE.md 規則 5「解析失敗也要有原始檔可重算」。如果 `raw_objects` 跟著任務交易一起回滾，就會留下沒有登錄的孤兒檔。
- 順序：先算 SHA-256 → 已登錄就直接回傳既有物件 → 寫檔（本機用原子 rename；GCS 用 `if_generation_match=0`）→ `INSERT ... ON CONFLICT (sha256) DO NOTHING`。
- 路徑中的日期採 **UTC** 擷取日（M0.md 沒有指定，時間戳一律 UTC 的慣例）。
- `get()` 讀回時重新驗證雜湊。

### D-017 upsert 以反射取得表定義，回傳實際寫入列數
- 不在 Python 重複定義 schema；`upsert()` 只更新內容有變的列（`IS DISTINCT FROM`），因此重跑時回報 0 列，`job_runs.rows_written` 能反映真實變動。

### D-018 交易日曆遇到缺漏日期就拋 `CalendarGapError`，不回退成週末規則
- 原因：安靜地回退會掩蓋休市表匯入失敗。種子資料涵蓋 2005–2027，超出範圍要先補資料。

### D-019 新增依賴
- `sqlalchemy`、`pydantic`、`pydantic-settings`：技術棧指定。
- `psycopg[binary]`：技術棧指定的 driver，用 binary wheel 免編譯。
- `google-cloud-storage`：GCS RawStore（套件沒有型別資訊，mypy 對它設 `ignore_missing_imports`）。
- `tzdata`：`zoneinfo("Asia/Taipei")` 在精簡容器與 Windows 上都需要。

### D-020 設定的小慣例
- 逗號分隔的清單（`ALERT_EMAIL_TO`、`PROVIDERS_*`）直接用字串，不要求寫成 JSON。
- 相對路徑的 `RAWSTORE_LOCAL_DIR` 以 repo 根目錄為基準（在 checkout 內時），否則以工作目錄為基準。
- 依後端決定的必要設定（GCS bucket、SMTP）在啟動時一起檢查，錯誤訊息一次列出所有缺少的變數。

## 2026-10-18 M0 / T5 Provider adapter 框架

### D-021 介面拆成 `fetch_*`（I/O，回傳原始回應）與 `parse_*`（純函式）
- 原因：由 `ProviderRouter` 在兩步之間把原始回應存進 RawStore，「先落地再解析」由框架保證，adapter 不必自己記得。
- M0.md 的「依日期區間取日線」：`fetch_daily_prices(start, end, symbols=None)`，`None` 表示全市場（證交所的端點本來就是一次回傳全市場）。

### D-022 錯誤分類與切換規則
- `TransientProviderError` 與未知例外：同一來源重試（預設 3 次，指數退避 1s、2s…，上限 30s，加 10% jitter）。
- `PermanentProviderError` 與解析失敗：不重試，直接切下一個來源；解析失敗時原始檔已經保存。
- 全部失敗時拋 `AllProvidersFailedError`，訊息列出每個來源每次嘗試的錯誤。切換到備援時寫 WARNING log，`Fetched.attempts` 也保留失敗紀錄，供任務寫進 `job_runs`。
- 限速：每個來源各有 `min_interval`（同一個 router 內同名來源共用），時鐘與 sleep 可以注入，測試不用真的等。

### D-023 用測試強制規則 6
- `test_data_source_packages_are_only_imported_by_providers` 掃描 `stockhub/` 的 import：`providers/` 以外不得 import twstock、yfinance、FinMind。

### D-024 mypy 關閉 `type-abstract`
- 原因：router 需要把抽象介面類別當參數做 `isinstance` 檢查；這是 mypy 已知的誤報類型。

## 2026-10-18 M0 / T6 排程任務框架

### D-025 失敗通知由 `run_job` 統一處理，以任務名稱判斷連續失敗
- 失敗時，只有在「同一任務名稱上一次結束的執行」不是失敗時才寄信；連續失敗合併成一封。之後第一次成功寄「恢復」通知（info）。
- 用任務名稱而不是（名稱＋參數）判斷，因為每日任務的 `date` 參數天天不同，跨日的連續失敗仍應視為同一串。
- `freshness_check` 判定落後時讓任務失敗（`JobError`，不記 traceback），自動套用同一套合併規則。這是 M0.md 的「落後則經 Notifier 發 Email」的實作方式。
- 通知寄送失敗只記 log，不改變 `job_runs` 的結果。

### D-026 檢查點與續跑規則
- 同一（任務, 參數）最近一次結束的執行如果是 failed 且有 checkpoint，新的執行就從該 checkpoint 開始；最近一次是成功就從頭跑（靠冪等寫入保證不重複）。
- `ctx.save_checkpoint()` 用獨立交易立即提交；成功結束時清掉 checkpoint。
- 同一（任務, 參數）同時只能有一筆 running（部分唯一索引）。超過任務 `timeout`（預設 1 小時）的 running 紀錄視為行程已死，標記為 failed（`abandoned`）後允許新的執行。CLI 結束碼：0 成功或略過、1 失敗、2 用法或設定錯誤、3 已在執行中。

### D-027 `--date` 預設為台北當天日期並寫進 params
- 讓 `job_runs.params` 永遠是具體日期，冪等與續跑判斷不會因為「預設值」而失準。

### D-028 `freshness_check` 的比較基準照 M0.md（上一個交易日）
- 所以排程放在平日早上。傍晚檢查「當日」日線的需求（PLAN.md 第 5 節）留到 M1，依實際入庫時間再加。

### D-029 RawStore 本機預設目錄改為 `.local/rawstore`
- 物件 key 本來就以 `raw/` 開頭，避免出現 `.local/raw/raw/...`。路徑日期採 UTC（D-016），所以台北凌晨的執行會落在 UTC 的前一天目錄。

### D-030 ETL 映像
- 多階段建置，uv 0.13.1 只在 build stage；runtime 是 `python:3.12-slim-bookworm`，以 uid 10001 非 root 執行。
- 映像不含 dbmate 和遷移檔；正式環境的遷移在部署前由本機或 CI 執行。
- 開發機沒有 Docker，映像的建置驗證交給 CI（T8）。

## 2026-10-18 M0 / T7 Web 外殼

### D-031 Auth.js v5（`next-auth@5.0.0-beta.32`）
- v4 不支援 App Router 的 `auth()` 用法；v5 雖然還標示 beta，但已宣告支援 Next 16，也是官方文件主推的版本。版本鎖死，升級時要看 changelog。
- JWT session（14 天），不建 session 表。登入條件：Google 回傳 `email_verified` 且 email 在 `ALLOWED_EMAIL` 內。
- 每次請求都**重新比對白名單**（proxy 與 `getCurrentUser()` 都會），從 `ALLOWED_EMAIL` 移除的帳號，已發出的 session 也會立刻失效。

### D-032 三層保護：proxy、頁面、API
- `src/proxy.ts`（Next 16 的 middleware）：除 `/login`、`/api/auth/*` 與靜態檔外全部攔截；頁面導向 `/login?callbackUrl=...`，API 回 401 JSON。
- **App Router 的 layout 與 page 是並行渲染的**，layout 裡的檢查擋不住 page 讀資料（production build 時實際踩到）。所以凡是讀資料的頁面，都要在自己的 `<Suspense>` 內先 `await requireUser()`；route handler 用 `requireApiUser()`。這條已加入 CLAUDE.md 的慣例。
- `callbackUrl` 只接受站內相對路徑，避免 open redirect。

### D-033 漲跌色 token
- `--color-up` / `--color-down` / `--color-flat` 是語意 token（Tailwind 的 `text-up` 等）；`<html data-price-colors="tw|intl">` 切換紅漲綠跌或綠漲紅跌，M0 固定為 `tw`，M2 的個人設定再接上切換。
- `PriceChange` 元件另外加上 ▲▼ 符號，不只靠顏色表達方向。
- 任務失敗等「狀態」用 shadcn 的 destructive 色，與價格的漲跌 token 分開。

### D-034 手機版導覽
- 底部列放 4 個主要項目（首頁、持股、個股、市場），再加「更多」頁收篩選器、回測、狀態、設定；桌機版側邊欄列出全部 8 項。這樣做不需要 client 端的抽屜選單。

### D-035 環境變數載入改用 `web/scripts/next.mjs`
- 用 `process.loadEnvFile` 讀 repo 根目錄的 `.env` 後，再啟動 `next` 子行程。原因有兩個：在 next.config 裡呼叫 `@next/env` 時，Next 的 build worker 會把環境變數還原成啟動時的快照；`node --env-file` 則會被 Next 轉進 `NODE_OPTIONS` 而被拒絕。
- 在 Vercel 上檔案不存在，直接使用專案設定的環境變數。

### D-036 其他
- shadcn CLI 產生的元件 import `cn` 套件（shadcn 官方維護，取代 clsx + tailwind-merge），保留。
- 新增 `server-only`，避免 DB 與 session 模組被打包進 client。
- 新增 `/api/status`（JSON，需要 session），之後給 TanStack Query 做 client 端刷新用。
- `admin` 頁的稽核紀錄讀取函式放在 `src/lib/audit.ts`（M0.md 要求預留）。
- 驗收方式：本機沒有 Google OAuth 憑證，所以用 Auth.js 的 `encode` 和本機 `AUTH_SECRET` 簽出測試 session，實測三種情況（未登入、非白名單、白名單）的頁面與 API 回應，並用 headless Chrome 在 375px 與 1280px 檢查畫面（無水平捲動）。真正的 Google 登入要等使用者提供 OAuth 憑證。
