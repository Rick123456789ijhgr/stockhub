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

## 2026-10-18 M0 / T8 CI

### D-037 CI 結構
- `CI` workflow 每個 PR 都跑三項（web、py、migrations），不設路徑過濾，確保「開 PR 時三項檢查都會跑」。
- web 另外跑 `next build`，因為 Cache Components 的 prerender 錯誤只有 build 時才會出現。
- migrations：空資料庫套用 → 逐一回滾到零張表 → 重新套用 → `kysely-codegen --verify`。這同時驗證 down 段、可重複執行，以及 PG 16 相容性（本機是 17，見 D-007）。
- `ETL image`：PR 只建置並做冒煙測試（列出任務、確認以 uid 10001 執行）；推送到 Artifact Registry 用 `workflow_dispatch` 加 `push=true` 觸發，而且只有在設定了 GCP repository variables 後才會執行。驗證方式採 Workload Identity Federation，不存服務帳號金鑰。
- Action 版本：setup-uv 沒有主版本標籤，要寫完整版本（`v10.3.0`）。

### D-038 時間格式化不依賴 ICU 的 zh-TW 輸出
- CI 的 Node 在 `zh-TW` 格式中會插入不可見字元，和 Windows 的輸出不同。`formatTaipeiDateTime` 改用 `formatToParts` 自己組字串。

### D-039 GitHub 儲存庫
- 依使用者「照建議實作」的指示，建立 **private** repo `Rick123456789ijhgr/stockhub`；`main` 只有規劃文件，M0 在 `m0` 分支，以 PR #1 合併。

## 2026-10-18 M0 / T9 文件

### D-040 文件分工
- `README.md`：給使用者的快速開始、環境變數、部署、CI、備份計畫。
- `infra/README.md`：GCP 指令細節。
- `CLAUDE.md`：開發慣例（新增 provider、任務、schema、頁面時的規則）。
- 本檔：所有選擇與偏離。

## 待使用者提供或確認（M0 結束時）

| 項目 | 現況 | 影響 |
|---|---|---|
| Google OAuth Client ID／Secret | 未提供 | 無法實際用 Google 登入；登入流程以簽發測試 session 驗證（D-036） |
| `ALLOWED_EMAIL` | 本機 `.env` 暫填 `me@example.com` | 請換成自己的 Google 帳號 |
| Neon 專案 | 未提供 | 用本機 Postgres（D-007）；照 README 建立後套用遷移即可 |
| GCP 專案、bucket、Cloud Run／Scheduler 權限 | 未提供 | 只有文件與指令（infra/README.md）；CI 推送映像先停用 |
| SMTP 或 Email API | 未提供 | 用 `ConsoleNotifier`；`EmailNotifier`（SMTP）已實作並有測試 |
| Docker Desktop | 開發機沒有 | 用 `scripts/local-pg.sh`；compose 檔已備妥，CI 用 PG 16 驗證 |
| Vercel 專案 | 未建立 | README 有步驟（Root Directory = `web`） |
| `freshness_check` 傍晚同日檢查 | 依 M0.md 只比上一個交易日 | M1 依實際入庫時間補（D-028） |
| 官方休市表 | 用週末規則當種子 | M1 匯入（D-013、D-018） |

## 2026-10-18 範圍簡化（使用者指示）：先讓系統跑起來、取得資料

### D-041 本機免登入開關 `AUTH_DISABLED`（暫時偏離規則 9）
- 使用者指示：登入與通知先忽略。登入程式與測試保留；`AUTH_DISABLED=true` 時 proxy 全部放行，`getCurrentUser()` 回傳固定的本機使用者。
- 安全前提：只有在**不是 Vercel、也不是 production 模式**（`next start`／正式 build）時才會生效，所以就算變數誤設到部署環境也無效。
- 取捨：本機的 `make web-dev` 沒有任何保護，只適合在自己的電腦上用。要部署或開放給區網時，必須改回 `false` 並設定 Google OAuth。

### D-042 這一輪的範圍（取代原本 M1 的一部分）
- 做：官方休市表、股票主檔（上市與上櫃的股票、創新板、ETF）、上市與上櫃日線（原始價）、可續跑的回填、網頁的股票清單與個股日線表、`make etl-daily`。
- 延後：還原因子與除權息（`adj_factor` 暫時固定為 1）、已下市股票（存活者偏差）、財報、籌碼、K 線圖、通知、所有雲端部署。
- 通知維持 `ConsoleNotifier`，不需要設定。

### D-043 日線介面改為「單日、單一市場」
- `PriceProvider.fetch_daily_prices(trade_date, market)`，取代 M0 的 `(start, end, symbols)`。官方來源（證交所 MI_INDEX、櫃買 afterTrading/otc）都是一天一次請求就回傳全市場；以後的 FinMind 也有「依日期取全市場」的 API。
- provider 宣告 `markets`（日線）與 `security_markets`（主檔），router 只挑支援該市場的來源；同名來源共用限速器。
- 新增 `CalendarProvider`（休市表）與 `SecurityListProvider`（主檔）兩種資料類型，設定為 `PROVIDERS_CALENDAR`、`PROVIDERS_SECURITIES`。
- 新增依賴 `httpx`：逾時與錯誤分類清楚、可用 `MockTransport` 做離線測試。5xx、429、網路錯誤、非 JSON 回應（被限流的 HTML 頁）視為可重試；其他 4xx 視為永久錯誤。
- 回應的日期必須等於請求的日期，否則視為解析失敗（避免 API 回傳最新一天時把資料存錯日子）。

### D-044 交易日曆的來源
- 證交所休市表只回溯到 2021 年；2027 年尚未公布。已公布的年份整年改寫：平日預設為交易日，公告日期以公告為準（名稱含「開始交易」或「最後交易」的是交易日，其餘包括「市場無交易，僅辦理結算交割作業」都是休市）。
- 沒有公告的年份保留週末規則的種子資料；回填時，過去的某個平日證交所沒有資料，就改標為休市（`derived:no-twse-data`）。這也涵蓋颱風等臨時停市。
- 例外：公告明確列為交易日卻沒有資料，任務會失敗而不是改日曆；當天或未來的日期沒有資料，視為「尚未公布」，任務失敗，不改日曆。

### D-045 股票主檔來源：證交所 ISIN 清單（上市 strMode=2、上櫃 strMode=4）
- 原因：同時有上市日（`stocks` 唯一鍵的一部分）、產業名稱與分區（股票、創新板、ETF）。上市公司 OpenAPI 沒有 ETF，日線資料沒有上市日。
- 只收「股票」「創新板」「ETF」；權證、ETN、TDR、特別股、REITs 不收，它們在日線中會被當成「非主檔代號」略過。
- 同代號的現役資料直接更新（包括上市日修正）。下市的判定還沒有來源，先記 TODO（存活者偏差）。
- 產業存中文名稱到新欄位 `stocks.industry`；`industry_code` 留到匯入官方代碼對照時再填。

### D-046 日線品質檢查與隔離表
- `prices_daily_quarantine`：部分開高低收缺漏、價格 ≤ 0、最高 < 最低、開盤或收盤超出高低區間、有價格卻成交量為 0，這些都會隔離，不寫入正式表。
- 開高低收全空但有成交量是正常情形（盤後或鉅額交易，例如 2026-10-16 的 2321），照存，價格為 NULL。
- `prices_daily.fetched_at` 只在新增時寫入，所以內容沒變的重跑不會算成寫入。

### D-047 網頁先顯示資料，不畫圖
- `/stocks`：代號前綴或名稱子字串搜尋，最多 100 筆。手機版是卡片、桌機版是表格；每檔顯示最新收盤與漲跌幅（lateral join 取最新一筆與前一個收盤價）。
- `/stocks/[symbol]`：最新一日摘要與近 120 日表格。手機版表格在自己的框內左右捲動，日期欄固定，頁面本身不會橫向捲動。成交量以「張」顯示，成交金額以「億」顯示。
- 漲跌是未還原的收盤對收盤，除權息日會偏大，頁面上有註明；`adj_factor` 完成後改用還原價。

### D-048 `/status` 的資料進度視覺化
- 總覽數字、回填進度（進度條、預估剩餘時間）、每年完成度長條、單一年份的「月 × 日」涵蓋格子圖、需要注意的日期清單（表格替代視圖）。
- 有回填或任務執行中時每 5 秒自動刷新（`router.refresh()`），其他時候每 60 秒。
- 格子狀態：兩市場都有、只有一個市場、⚠ 缺漏（已抓範圍內的交易日沒資料）、尚未回填、休市、未來。正在回填但還沒輪到的日子算「尚未回填」，不算缺漏。
- 顏色：有序藍色兩階（經 dataviz 驗證腳本以 `--ordinal` 檢查，亮、暗兩種模式都通過），缺漏用狀態警示黃並搭配 ⚠ 圖示與文字，休市用中性灰；刻意不使用漲跌色。
- 每次請求都會彙總整張 `prices_daily`。目前約 60 萬筆，查詢很快；回填 15 年後若變慢，改成預先計算。
- 免登入模式下 `getCurrentUser()` 會呼叫 `connection()`，讓頁面和真正讀取 session 時一樣依請求渲染（否則 `new Date()` 會在預先渲染時報錯）。

## 2026-10-18 M1 續：下市股票、還原價、K 線、盤中報價、完整歷史

使用者指示依序做：除權息與還原價、K 線圖、盤中報價、補下市股票、回填 2004 年起的歷史。實際順序改為「下市股票 → 啟動長回填 → 其他」，因為回填要 5 到 6 小時，而且必須先有下市股票的主檔，回填時才收得到它們的日線。

### D-049 下市股票的來源與建檔規則
- 來源：證交所 `company/suspendListing?date=YYYY0101`（2001 年起，每年一次請求）、櫃買 `company/deListed?date=YYYY`。新增 `DelistingProvider` 介面與 `PROVIDERS_DELISTINGS`（預設 `twse,tpex`），任務 `sync_delistings`（`start_year`、`end_year`，預設今年；`make etl-daily` 每天跑今年）。
- 只收四碼數字代號（排除特別股），證交所另排除 91xx（TDR）。ETF 下市不在這兩份清單裡，**暫不處理**（ETF 存活者偏差留待之後）。
- 下市清單沒有上市日，`stocks.listed_date` 先填下限（同代號前一次下市日，否則 1962-02-09），並標 `listed_date_estimated = true`；之後每次執行都會改成第一筆日線的日期。
- 「轉市場」不是下市：上櫃轉上市（以及少數「下市改列上櫃」）會出現在下市清單裡。判定規則：
  - 同代號在另一個市場仍是現役，且上市日在下市日的前 7 天到後 30 天內 → 略過（例：8908 欣雄 2026-10-16 轉上市）；
  - 同代號在另一個市場有更早或更晚的下市紀錄 → 合併成同一列（`market` 取最後所在市場），不另開新的 id（例：3454 晶睿 2011 年前在櫃買、之後在證交所直到 2026 年下市）。
  - 取捨：跨市場且代號被不同公司重複使用的情形會被誤合併；目前資料裡沒有看到這種情形，同市場的重複使用（例：2432）會正確分成兩列。
- 實際匯入：2001～2026 年共 362 筆下市公司、98 筆轉市場。

### D-050 日線代號對應改為「依日期」並忽略市場
- `store_daily_bars` 改用 `stock_ids_on(day)`：每個代號對應到「當天還在、而且最早結束」的那一列。代號重複使用時，舊公司拿到下市前的日線，新公司拿到之後的。
- 不再以市場篩選：轉上市的股票在櫃買時期的日線會歸到同一個 id，歷史不中斷。所以「`stocks.market` = 目前（或最後）所在市場」，`listed_date` 是在該市場的上市日，日線可能早於 `listed_date`。

### D-051 歷史起點與 2004 年日曆
- 證交所 MI_INDEX 從 2004-02-11 起有資料；**櫃買日線從 2007-07-02 起才有**（官網更早的日期回空表），除權息表從 2007 年底起。2004～2007 年中的上櫃資料官方來源拿不到，`/status` 會顯示「只有一個市場」，這是預期的。
- 新遷移補上 2004 年的週末規則種子；回填時沒有資料的平日會照 D-044 改標為休市。
- `make etl-history`：先匯入 2001 年起的下市清單，再從 2004-02-11 回填到今天，最後再跑一次 `sync_delistings` 修正估計的上市日。

### D-052 還原因子用交易所公布的參考價計算
- 每個事件的因子 = 參考價 ÷ 事件前收盤價（除權息參考價、減資或面額變更或 ETF 分割的恢復買賣參考價）。參考價已經把現金股利、股票股利、現金增資、退還股款、換股比例都算進去，所以各種事件用同一個公式，也和交易所、看盤軟體的還原方式一致。
- `prices_daily.adj_factor` = 該日之後所有事件因子的乘積（最新價格不變，舊價格換算到今天的股數基礎）；`corporate_actions.price_factor` 是資料庫產生欄位，不會和原始欄位不一致。累積計算在 `stockhub.engine.adjustments.factor_segments`（純函式、有單元測試），任務 `compute_adj_factors` 依日期區間批次更新，只寫入有變的列（全表約 6 秒）。
- 來源與起始：證交所 TWT49U（除權息，2004 起）、TWTAUU（減資，2011 起；更早的日期會被拒絕）、TWTB8U（面額變更）、TWTCAU（ETF 分割）；櫃買 exDailyQ（除權息，2007 年底起）、revivt（減資，2013 起）。新增 `CorporateActionProvider` 介面與 `PROVIDERS_CORPORATE_ACTIONS`，每個 provider 宣告各表的起始日，任務自動跳過沒有來源的年份。
- 型別：`cash_dividend`、`stock_dividend`、`cash_and_stock_dividend`（證交所 2010 年後只公布合計，無法拆分現金和股票部分，`cash_dividend` 留空）、`rights_issue`（櫃買「除權」但只有現金增資認購價：參考價可能高於前收）、`capital_reduction`、`split`、`reverse_split`。櫃買有確切的現金股利、每仟股配股、減資換股比例與每股退還股款（從詳細資料 HTML 取出）。
- 每日流程：`make etl-daily` 依序跑 `sync_corporate_actions`（近 30 天）→ 日線 → `compute_adj_factors`。

### D-053 沒有來源的事件：用「價格跳空」偵測，進隔離區
- 櫃買的面額變更與 ETF 分割在新版網站沒有歷史表（只有預告），2011／2013 年前的減資也拿不到。這些事件會讓還原價出現無法解釋的跳空。
- `compute_adj_factors` 每次都會找出還原後收盤價相鄰兩日比值超出 0.6～1.5 的情況（遠大於任何漲跌幅限制），寫進 `corporate_actions_quarantine`（`source = derived:price-gap`、`action_type = unknown`），不自動補因子。之後匯入的事件解釋了跳空，就自動標為 `explained`。
- 已驗證：櫃買 8932、8937、4747（新聞報導過的面額變更）都被正確標出。
- 取捨：不自動猜測分割比例（例如比值接近 1/2、1/4、1/10 就自動補），避免錯誤還原；要不要做半自動確認，留到之後的 `/admin`。
- 品質檢查（隔離不寫入）：價格 ≤ 0（實例：櫃買 3454 在 2011-07-27 前收 0.00、參考價 −2.30）、單一因子超出 0.02～50、純現金股利卻讓參考價上升。後來匯入的正確版本會把舊的隔離紀錄標為 `superseded`。

### D-054 K 線圖：lightweight-charts、三個窗格、預設還原價
- 新增依賴 `lightweight-charts@5.2.1`（TradingView 開源，Apache-2.0）：原生 K 線、窗格、觸控縮放，canvas 繪製，幾千根 K 棒也順。授權要求保留 TradingView 標誌，所以圖上左下角的標誌保留。
- 個股頁：主圖（K 線 + MA5/20/60）、成交量、指標（KD／MACD／RSI 切換）三個窗格，不用雙 y 軸。期間 6 個月～全部（預設 1 年）、還原／原始切換（預設還原）。資料由 `/api/stocks/[symbol]/bars` 一次回傳所有有成交的日線（精簡陣列，route handler 檢查 session），TanStack Query 快取 60 秒；期間按鈕只移動可視範圍，不重新請求。
- 顏色：K 棒、量、MACD 柱用 `--price-up`／`--price-down`（遵守規則 10，跟著 `data-price-colors` 切換）；線用新 token `--series-1..3`。均線限三條：線會交錯，dataviz 驗證腳本在 all-pairs 模式下四色（加紫）會失敗，三色在亮、暗模式都通過。亮色模式黃、粉對背景對比低於 3:1，所以圖上方固定顯示數值圖例（滑鼠或手指停留時顯示那一天），下方還有表格。
- Tailwind v4 會移除沒有被任何 utility 用到的 CSS 變數：線色 token 透過 `bg-series-*` 圖例色塊被引用，才會留在輸出裡。
- 表格與摘要卡片仍顯示原始價，但漲跌改用「前收 × 前日因子 ÷ 當日因子」當基準，除權息日的漲跌和交易所公布的一致。

### D-055 技術指標公式（規則 11 從這裡開始執行）
- `py/stockhub/engine/indicators.py` 是基準，`web/src/lib/indicators.ts` 逐式對應；共用測試資料 `testdata/indicators.json` 由 `py/scripts/gen_indicator_fixture.py` 產生，兩邊測試都比對（相對誤差 1e-12）。
- 定義（台灣看盤軟體常見設定）：SMA 每個視窗直接加總；EMA 以前 n 筆 SMA 起算；MACD(12,26,9)；KD(9) 的 K、D 從 50 起算、`(2×前值 + 新值) / 3`，H9 = L9 時 RSV = 50；RSI(14) 用 Wilder 平滑。
- 指標依畫面選的價格（還原或原始）計算；只用有成交的日線。

### D-056 盤中報價：直接呼叫證交所 MIS，不加 twstock 依賴
- twstock 的即時報價就是包裝 `mis.twse.com.tw/stock/api/getStockInfo.jsp`。直接用 httpx 呼叫同一個端點（provider `twse_mis`，`PROVIDERS_QUOTE` 預設），少一個依賴，錯誤分類、限速、RawStore 落地都沿用現有框架。仍然只經由 provider adapter（規則 6）；這是官網頁面用的非正式介面，欄位可能變動，所以有解析測試與 rtcode 檢查。
- 一次請求最多 50 檔，同一來源至少間隔 5 秒（頁面自己的 userDelay）。`v` 是「張」，換算成股；`z` 為 `-`（這一筆沒有成交）時沿用同日稍早的價格；快照時間用 `d + t`（最後成交時間），`tlong` 是頁面更新時間，不用。
- 任務 `poll_quotes`：對象 = 自選股 + 持股（淨股數 > 0）+ 參數 `symbols`；一天一次執行，開盤前啟動，每 30 秒輪詢到 13:35（`until`），休市日 skipped；`once=true` 只抓一次。寫入 `quotes_latest`（每檔一列，較舊的快照不覆蓋較新的）。Redis 要到之後真的需要時再加，這張表先頂替。
- 網頁：個股頁有「加入自選」按鈕（`PUT/DELETE /api/watchlist/[symbol]`，寫入 `audit_log`，重複操作不重複記錄）；有比日線更新的快照時顯示盤中卡片，開盤時間內每 30 秒重新讀取。網頁本身不呼叫外部來源。
- 盤中累計量是一般交易時段的量，會比收盤後的日線成交量小（日線含盤後定價等）。

## 2026-10-19 M1 續：跳空確認、配息拆分、下市 ETF、效能、深色模式、排程

使用者列出的五項依序完成。歷史回填（`make etl-history`，backfill #14）仍在進行，所以需要大量請求或依賴完整歷史的步驟，改由一次性排程在回填結束後自動執行（見 D-063）。

### D-057 `/admin` 確認價格跳空（半自動，取代 D-053 留下的待辦）
- `compute_adj_factors` 標記跳空時，以純函式 `guess_share_ratio`（`engine/adjustments.py`，有單元測試）找出能解釋跳空的常見股數比 2、4、5、10、20（面額 10 元改為 5、2.5、2、1、0.5 元，或反向合併）。判定方式：扣掉事件後，當天剩下的漲跌幅要在 ±10% 以內（漲跌幅限制），取最接近的一個；找不到就不給建議。建議存在隔離紀錄的 `payload.suggestion`。還沒處理的紀錄每次執行都會依最新的價格和因子更新；已處理的不會再動。
- `/admin` 列出待確認的跳空，有建議的排在前面。每筆可以修改股數比（0.02～50，不能是 1）和類型（分割、合併、減資），然後按「確認事件」或「不是事件」。確認後寫入 `corporate_actions`（`source = 'manual'`，只填 `ratio`，因子 = 1 / ratio），隔離紀錄標為 `accepted`；按「不是事件」則標為 `discarded`，之後不會再被標記。兩種操作都會寫入 `audit_log`。API：`POST /api/admin/price-gaps/[id]`，會檢查 session。
- 之後若匯入同一檔、同一天的官方事件，就刪除手動紀錄，避免同一天被調整兩次。
- 取捨：網頁不會直接執行 Python，還原價要等下次 `compute_adj_factors`（每日 18:00 排程，或手動 `make etl-adjust`）才會更新。網頁上有寫明這一點。

### D-058 證交所權息拆分：TWT49UDetail
- 研究結果：證交所每個事件都有明細頁 `exRight/TWT49UDetail?STK_NO=&T1=`，2009 年起提供每股現金股利、每千股無償配股、現金增資認購率與認購價。2008 年以前的明細頁回「無相關資料」，但那些年份的 TWT49U 本身已分開列權值與息值。公開資訊觀測站 t05st09_2 沒有除權息日，每次只能查一家公司，只適合交叉驗證。FinMind `TaiwanStockDividend` 會漏事件（例如鴻海 2009-06-02）。所以主要來源用證交所，暫時不設備援。
- 新介面 `DividendDetailProvider`，設定 `PROVIDERS_DIVIDEND_DETAILS=twse`。新任務 `sync_dividend_details`：對 2009 年起的 `權息` 和 `權` 事件逐筆請求明細（一筆一次請求，證交所限速 3 秒），填入 `cash_dividend`、`stock_dividend_ratio`，以及新欄位 `rights_ratio`、`subscription_price`、`detail_raw_object_id`。`detail_raw_object_id` 有值就代表已處理（明細頁沒有資料也會記下），所以重跑不會重抓，中斷後可以續跑。`make etl-daily` 會處理近 30 天的事件，`make etl-dividends start=2009-01-01` 補完整歷史。
- **`action_type` 保留交易所的標示，不重新分類**：它是 `corporate_actions` 自然鍵的一部分，如果改掉，重新匯入事件表時會多出一筆重複事件，造成同一天被調整兩次（測試抓到了這個問題）。實際內容看拆分後的欄位。例如 1605 華新 2025-06-04 標示為「權息」，實際上是現金股利 0.5 元加上現金增資（每股認購率約 0.079，認購價 20 元），`stock_dividend_ratio = 0`。
- 重新匯入事件表時，表中沒有的拆分數值（NULL）不會覆蓋之前從明細頁補上的值。
- 實測：1773 為 (151 − 2.5) ÷ 1.2 = 123.75，6423 為 89.8 ÷ 1.0203 = 88.01，都和交易所參考價一致。之後可以加一項品質檢查：用拆分後的數值推算參考價，與交易所公布的比對。

### D-059 下市 ETF：從自己存下的日線表推算
- 研究結果：證交所、櫃買都沒有下市 ETF 清單，OpenAPI 的終止上市清單只有公司。FinMind `TaiwanStockDelisting` 雖然有 ETF，但日期有時是最後交易日，有時是終止日，有時根本是錯的（例如 00774C），也漏掉 00793B。
- 改用官方每日行情表推算：任務 `derive_delisted_etfs` 不連網，掃描 RawStore 裡所有 MI_INDEX 和上櫃日線表（約一萬份，3～5 分鐘），找出不在主檔裡的 ETF 代號。ETF 代號的定義：0050～0099，或 00 開頭的五、六碼代號。0001～0049 是封閉式基金，02 開頭是 ETN，都不算。最後一次出現早於該市場最新一份行情表的，就經由既有的 `apply_delisting` 建檔：`delisted_date` 為最後交易日的下一個交易日，`delisting_reason = 'derived:last-trade'`，上市日用第一筆日線並標為估計值。這些 ETF 的日線也一起寫入，每筆日線記錄自己的來源。
- 回填進行中時，行情表只到回填目前的日期，仍在交易的 ETF 會被誤判為下市。所以有 `backfill_prices` 在執行時，任務會拒絕寫入，只允許 `dry_run=true` 試算。
- 試算結果與新聞一致：00883B 終止日 2026-05-07、00794B 2025-08-22，也找到了 FinMind 漏掉的 00793B。
- 取捨：沒有處理 ETF 代號重複使用（目前沒看到這種情形）。暫停交易後又恢復的 ETF 會被當成同一檔，不會誤判為下市。

### D-060 K 線先載入近 3.5 年
- `/api/stocks/[symbol]/bars?period=recent` 回傳最新一筆往前 42 個月的日線，並附 `complete` 表示是否還有更早的資料。多出的半年用來暖機均線和指標，讓「3 年」範圍的 MA60、EMA 一開始就有值。
- 選擇「5 年」或「全部」而且還有更早的資料時，才請求完整歷史，然後取代原本的資料。台積電目前回傳約 20 KB（完整約 75 KB，回填完成後會更大）。

### D-061 `/status` 改讀預先計算的涵蓋表
- 新表 `prices_daily_coverage`（日期、市場、筆數）由觸發器維護：`prices_daily` 的 INSERT、DELETE 使用 statement-level 觸發器搭配 transition table，每個語句只彙總一次；`INSERT … ON CONFLICT DO UPDATE` 的更新部分不會重複計數；TRUNCATE 會一併清空；`stocks.market` 改變（轉市場）時，該股所有日線改計到新市場。分組方式和原本的即時查詢相同。
- 遷移時一次填滿。`CREATE TRIGGER` 會擋住其他寫入直到 commit，所以在回填進行中套用也一致（實測加總與 `count(*)` 都是 2,073,498）。總筆數與最新日期也改讀這張表。
- 取捨：所有寫入日線的語句都多一次彙總，但每次只有數百筆，回填速度不受影響。

### D-062 深色模式與漲跌配色切換
- 偏好存在 localStorage（`stockhub:theme` 可為 system、light、dark；`stockhub:price-colors` 可為 tw、intl）。每台裝置各自設定，不存進資料庫，因為是顯示偏好，而且不需要登入就能在第一次繪製前套用。
- `<head>` 的內嵌腳本在第一次繪製前設定 `.dark` class、`color-scheme` 與 `data-price-colors`，避免畫面閃爍；設為 system 時跟著系統即時切換。`<html>` 加上 `suppressHydrationWarning`。
- 側欄與手機頂列有一鍵切換（系統、淺色、深色輪流）；`/admin` 有完整設定（主題、紅漲綠跌或綠漲紅跌）。K 線圖原本就會監聽 class 與 `data-price-colors` 的變化重新上色，已確認深色版本正確。

### D-063 Windows 工作排程
- `scripts/scheduled.sh <target>`：設定 PATH，必要時啟動本機 Postgres，記錄寫到 `.local/logs/<target>-YYYYMMDD.log`（保留 30 天）。`scripts/register-tasks.ps1` 註冊到工作排程器的 `\StockHub\`：
  - 平日 08:55 執行 `make etl-quotes`，休市日任務會自己略過；
  - 平日 18:00 執行 `make etl-daily`；
  - 錯過的執行時間會在電腦下次可用時補跑。
  - 只在使用者登入時執行，所以不需要儲存密碼；用 `conhost --headless` 執行，不會跳出視窗。
  - 加上 `-Remove` 參數可以移除。
- 一次性任務「StockHub after-history (one-off)」：執行中的 `make etl-history` 用的是舊版 Makefile，所以由 `scripts/after-history.sh 14` 等它結束（每 5 分鐘檢查一次，最多 24 小時）。之後依序執行：
  1. `derive_delisted_etfs`
  2. `sync_corporate_actions`（2004 年起；先建好 ETF 主檔，才能接上它們的配息與分割）
  3. `sync_dividend_details`（2009 年起，約 3,000 次請求，2～3 小時）
  4. `compute_adj_factors`
- 新版 `make etl-history` 已經包含這些步驟，順序也相同。
- 新增 make 目標：`etl-adjust`、`etl-corporate-actions`、`etl-dividends`、`etl-etf-delistings`。

## 2026-10-19 M1 續（二）：參考價檢查、排程狀態

### D-064 權息拆分要能重現參考價（修正 D-058）
- 問題：用拆分後的數值代公式（前收 − 現金 + 認購價 × 增資率）÷（1 + 配股率 + 增資率）算參考價，有現金增資的事件推算值都偏高。原因是交易所算的是「全部現金增資股數」（含公開承銷、員工認購），而明細頁「按股東持股比例每千股認購」只算原股東認購的那一份。例：6225 天瀚 2026-08-18，原股東只認購 75%，換算後增資率 1.158，代入剛好得到公布的 30.04。另外，沒有現金增資時（C = 0），這一欄等於無償配股數，不是認購率（例：2834 臺企銀 2017-08-01）。
- 修正：`rights_ratio` 改為「每股對應的全部現金增資股數」= 每千股認購 ÷ 1000 × C ÷ c；C = 0 時為 0。這和交易所參考價的算法一致。原股東實際可認購的數量，需要時可以從原始明細算回來。
- 新品質檢查 `check_dividend_detail`：推算出的參考價與交易所公布的差距超過 0.5%，或有增資率卻沒有認購價，就不寫入拆分欄位（保持 NULL），改放隔離區（`source = 'twse:detail'`）。修正後重新解析 2,890 筆，最大誤差 0.17%（只是四捨五入到最小跳動單位），全部通過，沒有隔離。公式在 `engine/adjustments.implied_reference_price`。
- `sync_dividend_details` 新增 `reparse=true`：從 RawStore 重新解析已抓過的明細頁，不連網。這次修正就是這樣套用的。
- 適用範圍：只檢查有完整拆分欄位的事件。2008 年以前證交所的權息事件只有現金（`stock_dividend_ratio` 為 NULL），櫃買的現金增資事件沒有增資率，這些都沒有可比對的完整數值，不檢查。

### D-065 `/status` 的排程狀態
- `lib/schedule-health.ts`（純函式，有單元測試）依照每個排程「最近一次應該執行的時間」（平日 08:55、18:00，台北時間），比對 `job_runs`，判定狀態：
  - 已完成：最後一個任務跑完，休市日的「略過」也算；
  - 執行中；
  - 即將執行：排定時間剛過，還在寬限時間內；
  - 失敗：顯示失敗的任務與錯誤。同一個任務之後重跑成功，就不算失敗；
  - 未執行：過了寬限時間（報價 20 分鐘、每日 30 分鐘）仍沒有任何紀錄；
  - 未跑完：過了上限時間，最後一個任務還沒跑。
- 「未執行」是這張卡片的主要用途：電腦沒開、沒有登入、Postgres 沒啟動，都不會留下 `job_runs` 紀錄，原本的任務列表看不出來。
- 取捨：只依時間判斷，不讀 Windows 工作排程器（部署到雲端後讀不到）。手動在排定時間之後執行同樣的任務，也會算成那一次的排程。
- 2026-10-19 08:55 第一次真正由排程器執行：準時啟動，因為自選清單和持股都是空的而略過，卡片顯示正確。

### D-066 櫃買舊格式「0.00」代表沒有成交
- 隔離區的 12,842 筆櫃買日線（2007-07～2011-11），都是開高低收 0.00、成交量 0。那時的表格用 0.00 表示當天沒有成交，現在改用「----」。解析器改成：四個價格都是 0 而且沒有成交量時，價格存 NULL，和現在的格式一樣。價格為 0 但有成交量的情況，仍然會被隔離。
- 新任務 `reparse_daily_prices`（start、end）：從 RawStore 重新解析日線表並寫入，不連網，寫入成功的就把同一天的隔離紀錄標為 `superseded`。「找出已存的日線表」這段查詢抽成 `stored_daily_tables`，和 `derive_delisted_etfs` 共用。
- 實際執行：重新解析 2,242 份，寫入 12,842 筆（只有原本被隔離的那些），隔離區清空。
