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

## 2026-10-18 規劃調整（參考 Threads 自建台股短線系統貼文）

### D-080 採用的部分（PLAN v0.4）
- 編號說明：這兩條原本寫成 D-041、D-042，和既有編號重複（當時在另一個分支），2026-10-20 併入時改為 D-080、D-081。
- **盤中報價主來源改用永豐 Shioaji**，只讀行情。這回答了 §11「盤中報價長期來源」的待決事項。Shioaji 是台股 Python 生態最完整的券商 API，而且免費；缺點是需要開戶，session 約 24 小時過期，所以 adapter 必須自己檢查 session、斷線重新登入，再失敗才交給 router 切換備援。
- **PTT 只抓 [標的] 分類**：成本低，雜訊大幅減少。
- **PTT 情緒每天寫進 `stock_features_daily`**：原本規劃「情緒條件無法回測」，其實只是因為沒存歷史；從 M6 開始累積，之後就能驗證反向指標假設，不用先相信它。
- **情緒判斷沿用 LLM，加上鄉民用語詞典**，不用 CKIP 或繁中 BERT。取捨：本地模型可重現性較好、沒有 API 費用，但需要 torch，放在 Cloud Run Job 裡映像大、啟動慢，也要另外維護一套模型；目前 LLM 流程已經涵蓋新聞，共用流程比較簡單。如果之後 LLM 費用或一致性有問題再重新評估。
- **FinMind MCP 只在開發時使用**。沒有在 repo 加 `.mcp.json`：查不到官方安裝方式，不猜套件名稱；等 M1 開通 token 時，照官方文件設定。

### D-081 不採用的部分
- **自動下單**：會把下單憑證放到雲端，持股資料也會變成有交易權限，風險與範圍都超出「研究平台」的定位。若之後要做，第一步是「訊號出現時用 LINE 通知」，由使用者自己下單。
- **多代理人辯論式 LLM 決策**：每月幾百元的 LLM 預算撐不住，而且結果不可重現、無法回測。
- **FinLab 平台**：M7 已規劃自建回測引擎，不再綁一個付費平台。貼文引用的 FinLab 績效數字沒有處理存活者偏差與財報公布時點，不當作參考基準。

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
| 永豐證券帳戶與 Shioaji API Key | 未開立 | 盤中報價的主來源；沒有之前用證交所 MIS（D-056、D-080） |
| FinMind MCP 安裝方式 | 未確認官方文件 | 開通 FinMind token 時設定（D-080） |

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

## 2026-10-19 M2：持股、費用、配息推算、自選清單

任務檔 `docs/M2.md`。使用者定了兩件事：成本用**平均成本法**；除權息**不調整成本**、股利另列收入。其餘細節依下列決定實作。

### D-067 計算引擎兩邊各一份，用共用測試資料比對（規則 11 延伸到持股）
- `py/stockhub/engine/portfolio.py` 是基準，`web/src/lib/portfolio.ts` 逐式對應；`testdata/portfolio.json` 由 `py/scripts/gen_portfolio_fixture.py` 產生，內容有手續費 36 例、證交稅 10 例、三個重播情境（一般、各種公司事件、260 個交易日的亂數帳本）。兩邊都要求逐欄一致（相對誤差 1e-12）。
- 網頁實際使用的是 TS 版（頁面即時計算，不存結果）；Python 版留給之後的回測與排程（例如持股警示）使用。
- 金額用 IEEE double，「元以下」取整前先加 `EPS = 1e-6`，避免 142.4999999 這類誤差讓兩邊或和券商差 1 元。日期一律用 `YYYY-MM-DD` 字串比較。

### D-068 平均成本法的細節
- 買進：總成本加上「成交金額 + 手續費」。賣出：取出「總成本 × 賣出股數 ÷ 持有股數」（全部賣出時取出全部，避免殘值）；已實現損益 = 成交金額 − 手續費 − 證交稅 − 取出的成本。
- 同一天的順序：先套用公司事件，再處理買進，最後處理賣出（各自依輸入順序）。所以當沖的先賣後買不會被判成賣超。取捨：同一天有庫存又當沖時，當沖那筆的損益會用混合後的平均成本，和券商「當沖單獨結算」的對帳單可能略有差異。
- 賣出超過當時持股：不計入，列為問題（頁面顯示紅色警示）。新增、修改、刪除時重播該股的完整帳本（含公司事件），只要產生**新的**賣超就拒絕（HTTP 409，附說明）；已經存在的問題不會擋住其他修改。寫入時鎖住交易表，避免同時寫入時檢查失準。
- 交易日不能是未來、不能是休市日（依 `trading_calendar`），也不能在終止上市（櫃）日當天或之後。

### D-069 除權息與股數事件（不調整成本）
- 權利依「除權息日前一交易日的持股」，也就是除權息日之前所有交易之後的股數。
- 現金股利（含減資退還股款）= 持股 × 每股金額，元以下捨去，計入「股利」；總成本不變。配股 = 持股 × 配股率，股以下捨去（實際上畸零股會折發現金，這裡不估）；分割、合併、減資 = 持股 × 股數比，股以下捨去。總成本不變，所以每股均價會變。
- 現金增資（`rights_issue`）要股東自己認購，不自動變動；`other` 不處理。
- 缺資料時從參考價推算並標示「比例由參考價推算」：證交所 2008 年以前的權息只有現金部分，配股率 =（前收 − 現金）÷ 參考價 − 1；沒有股數比的分割或減資，股數比 =（前收 − 退款）÷ 參考價。都取到小數第三位（參考價有跳動單位誤差，再精確也沒意義）。
- 一律標示「估算」，不存資料庫，每次頁面依最新的 `corporate_actions` 重算。實際入帳會扣匯費與二代健保補充保費，頁面註明以入帳通知為準。
- 未來的除權息（預告）目前沒有來源（只匯入了已除權息的 TWT49U），所以沒有「即將配息」清單。

### D-070 手續費設定
- 存在 `settings`（key `fees`），沒有設定時用預設值：費率 0.1425%、無折扣、最低 20 元、零股最低 1 元、成交時直接折抵、元以下捨去。
- 零股的定義：單筆少於 1,000 股。零股最低收費另設，因為多數券商的電子下單零股是 1 元。
- 折扣方式：「成交時直接折抵」收折扣後的金額；「事後退還」先收全額，差額記在交易的 `fee_rebate`（預估退佣），計入總損益而不是成本。這和券商對帳單一致：事後退的情況下，成本與損益用的是全額手續費。
- 費用設定只影響之後新增或修改的交易；已存的交易保留當時的金額（每筆交易都是當時的事實）。交易表單的費用預設「自動」，手動輸入後記 `fee_manual`／`tax_manual`，之後修改價格或股數也不會被重算。伺服器端會用同一套函式重算自動的費用，不採用瀏覽器傳來的數字。
- 修改設定寫入稽核紀錄（前後值）；`/admin` 有即時試算。

### D-071 證交稅
- 股票 0.3%、ETF 0.1%（含槓桿、反向、期貨 ETF），只在賣出時收，元以下捨去。
- 例外依日期判斷：現股當沖 0.15%（2017-04-28～2027-12-31，交易勾選「當沖」）；債券 ETF（代號以 B 結尾）免徵（2017-01-01～2026-12-31）。期限一到自動恢復原稅率；法規若再延長，改 `BOND_ETF_EXEMPT`、`DAY_TRADE_HALF` 兩個常數（Python 與 TS 都要改，並重產測試資料）。
- ETF 當沖沒有減半，仍是 0.1%。

### D-072 估值與今日損益
- 價格：盤中有比最新日線新的報價（`quotes_latest`）就用報價，否則用最新收盤；前收都換算到同一股數基礎（除權息日是參考價），和網站其他地方一致。
- 未實現損益 = 市值 − 總成本 − 預估賣出成本（依目前設定的實付手續費 + 證交稅），和多數券商 App 的「預估損益」一致。報酬率 = 未實現 ÷ 成本。
- 今日損益 = 現在股數 × 現價 − 昨日股數 × 前收 − 今天買進金額 + 今天賣出金額（不含費用）。今天買進的部分從買價起算，今天賣出的部分算到賣價。如果價格的日期比最後一筆交易還舊（例如今天剛買、還沒有報價），這一檔不算今日損益。
- 總損益 = 未實現 + 已實現 + 股利 + 退佣。
- 有盤中報價時頁面每 30 秒重新整理（只在開盤時間、分頁可見時）。

### D-073 自選清單
- 新頁面 `/watchlist`（導覽「自選」，手機在「更多」裡）：輸入代號加入、移除、備註（點一下就能編輯）、排序（自訂順序、代號、漲跌幅、價格、加入時間，可切換方向）。自訂順序用上下移按鈕調整，不用拖曳（不必加套件，手機也好按），存在新欄位 `watchlist.position`。
- 新增、移除、備註、調整順序都寫入稽核紀錄；內容沒變的操作不記錄。

### D-074 其他
- 首頁「持股損益與今日漲跌」接上真資料；`/admin` 加上手續費設定與最近 50 筆稽核紀錄。
- 新增 `GET /api/stocks/[symbol]`（名稱、類型、最新價），給交易表單顯示名稱與帶入價格。
- `taipeiToday()` 移到 `lib/market-hours.ts` 共用。
- 盤中報價任務找持股的方式仍是「交易股數加總 > 0」，沒有考慮分割與減資；最多是多輪詢一檔已經賣光的股票，不影響正確性。

## 2026-10-19 M2 續：M2 結束時的六項建議

使用者要求執行 M2 結束時列出的六項。任務 T8～T13 記在 `docs/M2.md`。

### D-075 當沖獨立結算（取代 D-068 的取捨）
- 同一天、同一檔勾選「當沖」的買進與賣出先互相配對，配對量取兩邊較小者，依輸入順序分配。配對的部分損益 = 賣出金額 − 該部分的手續費與證交稅 − 配對到的買進金額與手續費；不進庫存，所以不影響庫存的平均成本。這和券商的現股當沖結算一致。
- 沒配對到的部分照一般買賣處理：多買的進庫存（留倉），多賣的從庫存扣，用平均成本。一筆交易只有部分配對時，手續費和稅依股數比例拆開（剛好整筆時直接用原值，避免浮點誤差）。
- 已實現明細的當沖那筆會標「當沖」；一筆賣出可能拆成當沖與一般兩列。
- 部分配對的當沖賣出，沒配對到的部分超過庫存時只略過那一部分並列為問題，配對的部分照算。

### D-076 除權除息預告表
- 來源照規則 12 用官方 OpenAPI：證交所 `exchangeReport/TWT48U_ALL`、櫃買 `tpex_exright_prepost`（兩者都含 ETF）。新介面 `ExRightsPreviewProvider`、設定 `PROVIDERS_EX_RIGHTS_PREVIEWS`、表 `corporate_action_previews`、任務 `sync_ex_rights_previews`。
- 單位：兩邊的配股率都是「每股」（0.09999999 = 每千股 100 股）；增資率是全部增資股數，和 D-064 的 `rights_ratio` 定義一致。認購價欄位會出現「尚未公告」「註4」之類的文字，存成 NULL。標示「息」但現金是空白或 0，表示金額還沒公告（ETF 常常這樣），存 NULL，頁面顯示「待公告」。
- 類型依內容判斷：有配股就是 `stock_dividend` 或 `cash_and_stock_dividend`，有現金或標示含「息」是 `cash_dividend`，只有增資是 `rights_issue`。
- 預告表沒有日期參數，是一份快照。每次寫入快照列出的事件；同一來源、除權息日在今天以後、但這次沒列出的事件刪除（延期或取消）。已過去的保留。`source`、`raw_object_id`、`fetched_at` 保留第一次看到時的值，所以內容沒變的重跑寫入 0 筆。
- 排程：`make etl-daily` 收盤後跑一次；`make etl-quotes`（平日 08:55）開頭也跑一次（失敗不影響報價），所以當天除息的事件早上就有。
- 引擎的 `with_previews`：除權息日已到、但正式表（TWT49U、櫃買除權息表要等收盤後才匯入）還沒有這一檔這一天的事件時，暫時把預告當事件套用，當天的配息馬上算進持股。正式事件進來後自動改用正式的（只看同一檔同一天有沒有正式事件）。取捨：預告事件沒有參考價，這一天的還原前收要等正式表進來、`compute_adj_factors` 跑過才正確。
- 引擎的 `upcoming`：除權息日在今天以後的預告，依「目前持股不變」推算應收現金、配股與補充保費，顯示在 /portfolio 的「即將除權息（預估）」。

### D-077 股利實收對帳與補充保費
- 新表 `dividend_receipts`（股票、除權息日、事件類型為鍵；實收淨額、實收股數、入帳日、備註）。現金或股數可以只填一個，沒填的那部分沿用估算。輸入或清除都寫稽核紀錄（`portfolio.receipt`、`portfolio.receipt_clear`，含估算值與前後值）。
- 有實收時，損益與持股改用實收的數字（實收股數會改變之後的持股）；所以寫入時和交易一樣重播檢查，會造成新賣超的實收會被拒絕。
- 實收填的是入帳通知上的淨額（已扣匯費、補充保費），表單預設值是「估算 − 補充保費估算」。
- 二代健保補充保費估算：股利（現金 + 股票股利按面額 10 元）單次達門檻時收，2021 年起 2.11%（門檻 2 萬）、2016～2020 年 1.91%（2 萬）、2013～2015 年 2%（5 千），單次上限 1,000 萬，四捨五入；以除權息日判斷年度（實際是發放日，跨年時可能差一年的費率）。估算值只是提示，不從股利收入中扣除；實際數字以輸入的實收為準。
- 實收的鍵包含事件類型。用預告暫時套用的事件，如果正式表的類型不同（例如預告為 `cash_dividend`、正式為 `cash_and_stock_dividend`），之前輸入的實收會對不上，需要重新輸入；目前沒看到這種情況。

### D-078 持股警示（M6 的一部分提前做）
- 規則照 PLAN.md 第 5 節：今天的漲跌幅（對交易所參考價）超過「近 20 日還原報酬的樣本標準差 × 2.5」就警示，門檻最低 3%，最高 9.5%（漲跌停是 10%，但跳動單位讓實際漲跌停略小於 10%，用 10% 會永遠觸發不了）。少於 5 個報酬（新上市）時用最低門檻。公式在 `engine/alerts.py`（純函式，有單元測試）。
- 持股由 Python 引擎重播得到（`common/portfolio_store.py`，和網頁同一套規則），所以分割、減資、配股、實收都算進去。盤中報價任務找持股也改用它，取代原本「交易股數加總 > 0」的 SQL（D-074 提到的問題）。
- 檢查時機：盤中每輪報價寫完後（用今天的報價），以及 `make etl-daily` 最後的 `check_holding_alerts`（今天收盤後用日線）。只判斷今天；同一檔同一天只記一次（`alerts` 表的唯一鍵就是冷卻），所以 30 秒輪詢不會重複通知。檢查失敗只記 log，不影響報價。
- 通知：經 `Notifier`（目前是 Console，設定 SMTP 後就是 Email；LINE 在 M6）。寫入成功才送；送出成功記 `notified_at`。首頁新增「警示」卡片列出最近 10 則。
- 範圍外：法人買賣超、新聞、總經等其他警示（M6）；站內的已讀狀態。

### D-079 效能：量測後不快取重播
- 用 2,010 筆合成交易（30 檔、2010 年起）量測：讀資料約 50 ms，重播 3 ms；正式版（`next start`）整頁 45～65 ms。開發模式要 1.7 秒，原因是 React 開發模式替每個元素記錄除錯資訊，正式版沒有。所以不快取重播（快取還得處理每 30 秒變動的報價）。
- 真正的問題是頁面把全部交易與配息都送進瀏覽器（2.25 MB）。改成預設只送最近 50 筆交易、30 筆配息、30 筆已實現，列表下方有「顯示全部」（`/portfolio?all=1`）。
- 順手：`lib/format.ts` 的數字格式器改成模組層級建立一次，不再每次呼叫都 `new Intl.NumberFormat`。

## 2026-10-20 M3：一般產業基本面與估值（另含缺漏日線補抓）

使用者核可 M3 計畫，提供 FinMind 免費 token，指定回填到 2013 年，並追加「網站上能手動補抓缺漏的日線」。任務 T1～T9 記在 `docs/M3.md`。

### D-082 財報與月營收的來源
- 公開資訊觀測站舊站（`mopsov.twse.com.tw`，財報彙總表與月營收靜態檔都在這裡）的 robots.txt 是 `User-Agent: * / Disallow: /`，依規則 12 不抓。新站沒有對應的資料 API。
- 證交所與櫃買中心 OpenAPI（`t187ap06/07_*_ci` 損益表與資產負債表、`t187ap05_*` 月營收、`t187ap03_*` 公司基本資料）是官方來源，但只有最新一期，而且沒有現金流量表。
- 所以：歷史資料用 FinMind（每家公司每個資料集一次請求，2013 年起，`backfill_fundamentals`）；每天先抓官方快照（4 + 2 + 2 次請求），再只向 FinMind 補「官方已出現新一季、但 FinMind 還沒給」的公司（`sync_financials`）。現金流量表和單季損益表只有 FinMind 有。
- 範圍：一般產業的範本（`_ci`）。金融保險業（`stocks.industry = 金融保險業`）的歷史一樣會抓下來（原始回應在 RawStore，M3b 可以重新解析），但頁面顯示「M3b 提供」。
- 代號重複的下市公司只抓目前上市的那一家：FinMind 以代號查詢，分不出同一代號的前後兩家公司。

### D-083 `financials` 每個來源各存一份
- 各來源的口徑不同：FinMind 的損益表是單季（Q4 由全年減前三季算出），現金流量表是年初至今的累計數，和申報一致；官方 OpenAPI 的損益表是累計數。所以新增 `basis` 欄（`quarter`、`ytd`、`instant`），自然鍵加入 `source`，各來源各存一份，原始數字不改寫（規則 3）。挑選與換算在計算層做。
- 同一來源同一科目的數字有變（重編，或 FinMind 修正）就存成下一個 `revision`；數字沒變的重跑一筆都不寫（規則 4）。
- 科目統一成 `financial_item_map` 的標準代碼（一般業 40 個），各 provider 的 `parse_*` 負責對應。沒有對應的科目、以及占資產百分比的 `*_per`（可以推算）不入庫，原始回應仍在 RawStore。
- 單位：TWD（官方 OpenAPI 的仟元乘以 1000），EPS 與每股淨值是元。

### D-084 單季化、來源優先順序與每股淨值
- 流量科目（損益、現金流）：官方來源優先，其次 FinMind。來源本身有單季值就直接用；只有累計數時，用「累計數 − 上一季的累計數（任何來源）」，沒有上一季的累計數時，改用「累計數 − 今年前幾季已算出的單季合計」。Q1 就是它的累計數。例如 2026Q2 = 官方上半年累計 − FinMind 的 Q1。
- 時點科目（資產負債表）：官方優先，其次 FinMind。
- 近四季（TTM）要四個單季都有才計算。ROE、ROA、杜邦三因子都用「期末與四季前的平均」，所以 ROE 恰好等於淨利率 × 資產週轉率 × 權益乘數。ROE 用歸屬母公司的淨利與權益；平均權益為負時不算。
- 股數 = 普通股股本 ÷ 面額。面額取公司基本資料（`stocks.par_value`）；資料沒寫新台幣面額時（少數 KY 公司），當作 10 元。每股淨值優先用官方的「每股參考淨值」，沒有時用歸屬母公司權益 ÷ 股數。取捨：曾經變更面額的公司，變更前各季的股數會算錯；這種公司很少，而且官方值會蓋過最新一季。
- 推導結果寫進 `fundamentals_quarterly`（`compute_fundamentals` 依每家公司「有新資料就整家重算」），網站只讀這張表，所以公式只在 Python（`engine/fundamentals.py`）。

### D-085 公布日與可用日
- 官方快照裡第一次看到某一季，就把那天記為 `publish_date`；但如果那天已經超過法定截止日 7 天以上，多半是我們之前沒在抓（例如第一次同步），就留空。重編的數字記成看到的那天。FinMind 的資料沒有公布日，一律留空。
- 法定截止日（一般業）：Q1 5/15、Q2 8/14、Q3 11/14、年報隔年 3/31；月營收是次月 10 日（`common/filings.py`）。
- 可用日 `available_date` = 已知的公布日（包含晚申報），否則用截止日。估值與之後的回測都以可用日對齊，避免用到當天還沒公布的財報（PLAN 第 4 節的「財報時點」陷阱）。

### D-086 品質檢查與隔離（FinMind 實測問題）
- 一份報表（同一公司、期別、報表、來源）沒過檢查就整份放進 `financials_quarantine`，不進正式表（規則 7）。之後抓到通過檢查的版本時，自動標為 `superseded`。`/admin` 可以「捨棄」或「仍然採用」，兩者都寫稽核紀錄。
- 實測找到兩類 FinMind 的錯誤，都有對應的檢查：
  1. **最新一季的單季損益其實是累計數**。例如台積電 2026Q2 的營收 2,404 億，其實是上半年合計，但 EPS 又是單季的。檢查方式：單季營收和那一季三個月的月營收合計差超過 3%，卻和年初至今的月營收合計相差 1% 以內，就標為 `ytd_as_quarter`。2012～2026Q1 台積電的單季營收和月營收合計完全一致，所以這個檢查不會誤判。被隔離的那一季改用官方累計數換算。
  2. **部分公司的負債數字錯誤**。例如新纖：流動負債和非流動負債是同一個數字，負債總額也不對，但資產（流動 + 非流動 = 總額）和權益（母公司 + 非控制 = 總額）各自加總都正確。這種情況只隔離負債科目（`liabilities_inconsistent`），其他科目照常寫入；負債比率改用「資產 − 權益」。前 63 家公司裡有 55 份屬於這一類。
- `recheck_financials_quarantine` 用目前的檢查規則重新檢查所有待處理的隔離紀錄（不連網），規則改變後執行一次即可。
- 單季營收為負也會隔離（`negative_revenue`）：可能是退貨或重編造成，需要人看。

### D-087 FinMind 額度保護（使用者要求避免被封鎖）
- 免費帳號每小時 600 次。程式自己限制在 500 次：每次請求間隔至少 7.2 秒；同一個程式內，任一連續 60 分鐘不超過 500 次；每 25 次查一次帳號的用量（`user_info` 不算進額度），用量達到上限的 90% 或我們自己的上限時，每 5 分鐘再查一次，直到降下來。所以同時跑兩個程式（回填和每日更新）加起來也不會超過。
- 萬一還是收到 402（超過上限），就等到下一個整點過 1 分鐘再試一次，不會連續重試。
- token 放在 `.env` 的 `FINMIND_TOKEN`，用 Authorization 標頭送出，不會出現在網址或 RawStore 的參數裡。
- 回填進行時，`sync_financials` 不碰回填還沒輪到的公司，避免重複花額度。

### D-088 月營收
- 歷史用 FinMind（它的 `date` 是營收月份的下一個月，所以從 2013-01-01 開始抓會多拿到 2012 年 12 月），每天用官方 OpenAPI 的當月營收。官方數字優先：FinMind 不會覆蓋官方寫入的列；已經知道的公布日不會被取代（FinMind 只有近幾個月有 `create_time`）。
- 月增、年增、累計年增由檢視表 `monthly_revenue_growth` 計算，Python 和網站讀同一份定義。累計年增只在兩年都有完整月份時計算。

### D-089 估值公式（Python 與 TS 逐式對應）
- `engine/valuation.py` 和 `web/src/lib/valuation.ts` 共用測試資料 `testdata/valuation.json`（`py/scripts/gen_valuation_fixture.py`），測試資料涵蓋虧損期、晚申報、閏日與窗口邊界。
- 價格用原始收盤價（EPS、淨值都是當時的每股數字）。每天採用「可用日在當天或之前」的最新一季。本益比只在近四季 EPS 為正時計算（排除虧損期）；股價淨值比要每股淨值為正。殖利率 = 前 365 天內（不含剛好一年前那天）除息的現金股利 ÷ 收盤價。現金股利來自 `corporate_actions` 的 `cash_dividend` 與 `cash_and_stock_dividend`；減資退還的現金不算。
- 百分位 = (低於目前值的天數 + 相等天數的一半) ÷ 天數，期間 5 年與 10 年。河流圖的倍數是期間內第 5 到第 95 百分位之間等距的 5 條（線性內插）。不直接取最低與最高，是為了不讓個別極端值把河道拉寬。
- 本益比不抓證交所的 BWIBBU：自己算的口徑和我們的 EPS 一致，也省下約 1 萬次請求。
- 已知限制：改成季配或半年配的那一年，前 12 個月會含到較多次配息，殖利率會短暫偏高（例如台積電 2019 年中到 2020 年中約 6～7%）。配股與分割前後的歷史殖利率也以當時的股數計算。這兩點都在頁面上註明。

### D-090 規則式重大變化提示
- 寫進 `fundamental_signals`，每次重算時整家公司重建。季度規則：毛利率或營業利益率年變動 ≥ 3 個百分點；轉盈或轉虧（和去年同季比）；單季營收年增減 ≥ 30%；存貨或應收帳款的年增率比近四季營收年增高 30 個百分點以上，而且占總資產 5% 以上；自由現金流連續 4 季為負（只在剛滿 4 季時提示一次）。月份規則：單月營收創歷史新高（要先有兩年資料）、單月營收年增減 ≥ 30%。
- 這些提示只顯示在個股頁，沒有接到警示通知（M6 再決定要不要通知）。

### D-091 網站排入任務與缺漏日線補抓（使用者追加）
- 查證結果：2004 年到今天真正缺漏的交易日只有 2026-07-10。證交所那天沒有資料（應該是臨時休市，例如颱風），重新抓取後日曆改標為休市，`/status` 就沒有缺漏日了。個股層級的缺漏多半是停止交易：減資換股通常停 7 個交易日，也有長期停牌的，交易所當天的日線表本來就沒有那一檔。
- 機制：新表 `job_requests`（同一任務、同樣參數，等待或執行中時不會重複排入；寫稽核紀錄 `jobs.request`），新指令 `python -m stockhub.etl drain-requests` 依序執行，用 advisory lock 確保一次只有一個在跑，執行超過 3 小時還沒結束的視為中斷。網站可以排入的任務只有四個（`daily_prices`、`catch_up_prices`、`refetch_stock_prices`、`refresh_stock_fundamentals`），網站和資料庫的 CHECK 都會驗證，Python 任務本身也會再驗證參數。
- 執行：`.env` 設 `JOB_RUNNER=local` 時，網站在背景執行 `scripts/scheduled.sh etl-requests`（和排程用同一套 PATH、資料庫啟動與 log 設定）。在 Vercel 或正式版建置裡這個設定一律無效，請求會留在佇列，在下一次 `make etl-daily` 開頭執行。
- 介面：`/status` 的「手動更新與補抓」有「日線更新到今天」（`catch_up_prices`：最新日線之後的每個交易日，今天要過 14:30 才抓），每個缺漏日都有「重新抓取」按鈕，另有「重新抓取全部缺漏日」（最多 30 天）。個股頁在近一年有缺漏時顯示天數和「重新抓取」（`refetch_stock_prices`，每次最多 30 天，結果會說明哪些天交易所本來就沒有這一檔）。「缺漏日」的定義放在 SQL 函式 `stock_missing_days`，頁面和任務共用。

### D-092 本機資料庫改由獨立的排程工作啟動
- 發現的問題：每日排程啟動資料庫時，postgres 會留在那個工作的處理程序樹裡，所以工作結束後狀態仍顯示「執行中」，隔天的同一工作會因為「已在執行」被略過；工作的 3 小時上限一到，資料庫可能被一起關掉，回填就會中斷。
- 做法：`register-tasks.ps1` 新增「StockHub database」（登入時執行，沒有時間上限）。`scheduled.sh` 需要資料庫時，先觸發這個工作啟動它，觸發失敗才自己直接啟動。已經切換：目前的 postgres 由新工作啟動。

### D-093 範圍與限制
- 財報從 2013 年起（使用者指定，也是 IFRS 的起點），舊會計準則的期間不收錄。
- 全部回填約 2,139 家 × 4 個資料集，每小時 500 次，約 17 小時。用一次性的排程工作「StockHub fundamentals backfill (one-off)」執行，中斷後重跑會從 `financial_fetch_state` 接續。
- 同業比較依 `stocks.industry`（ISIN 頁面的產業名稱），依市值（收盤價 × 發行股數）排序，顯示前 15 家，另外一定包含目前這一檔。

### D-094 介面密度與分頁（使用者追加，2026-10-20）
- 目標：仿富途牛牛的緊湊排版，減少頁面長度。個股頁桌面版從約 9,300 px 縮到約 2,800 px，設定頁從約 11,400 px 縮到一個畫面。
- 全站：主內容寬度 `max-w-6xl` → `max-w-7xl`，卡片頂端的長段說明改收進「說明」（`InfoNote`）。一開始也縮小了卡片內距與表格列高，但摺疊與分頁後內容已經變少，畫面反而太擠，所以改回原本的間距（`sm` 卡片 3 → 3.5，表格標題列 40 → 36 px），個股頁各區塊之間也加大。頁面長度主要靠分頁與摺疊縮短，不靠壓縮間距。
- 分頁列的底線用內陰影，不用負邊距：負邊距會溢出可橫向捲動的容器，讓瀏覽器顯示垂直捲軸。表單欄位的 grid label 加 `content-start`，同一列有提示文字的欄位才不會把沒有提示的欄位撐開、造成錯位。
- 分頁一律用網址 `?tab=`（`components/page-tabs.tsx`），不加新依賴：伺服器只渲染目前分頁，其他分頁的查詢不會跑，可以直接分享連結，session 檢查照舊。個股頁：報價頭與 K 線常駐，下方分「基本面／估值／歷史日線」（ETF 沒有基本面分頁）。設定頁：「一般／待確認（帶筆數）／稽核紀錄」。
- 報價頭合併原本的標題、加入自選與收盤卡：盤中快照比最新日線新時顯示盤中價，否則顯示收盤。拿掉了「盤中報價由 poll_quotes 每 30 秒更新」的提示（README 已有）。
- 摺疊用原生 `<details>`（`components/disclosure.tsx`），伺服器元件也能用，內容仍在 HTML 中。長列表與長表格用 `components/show-more.tsx`：近 120 個交易日先顯示 20 列；待確認與稽核紀錄每次 20 筆。待確認每筆收成一行，按鈕放在 `<summary>` 裡（按按鈕不會展開），細節點開才顯示。
- 待確認財報原本只取 50 筆而且徽章顯示 50；改成另外計數（`countQuarantinedStatements`），列表載入最新的 200 筆，和價格跳空一致。

### D-095 頁面效能與本機啟動（使用者追加，2026-10-21）
- 量測：個股頁估值分頁 3～5 秒，其他頁 0.1～1 秒。原因是同業比較對每家同業查 `monthly_revenue_growth`，而這個檢視表的 CTE 被引用三次、會先整張實體化，`stock_id` 條件推不進去：207 家 × 3 次全表掃描約 2.3 秒，而且會隨月營收回填線性變慢（回填完約 5 倍）。
- 做法：檢視表改寫成一層子查詢加 RANGE 視窗（上個月、去年同月剛好是一個 1 號日期，框內只有那一列或沒有），欄位與數字不變（和舊檢視表逐列比對 0 筆差異）。`stock_id` 是所有 PARTITION BY 的欄位，條件可以推到主鍵索引。估值分頁降到約 0.3 秒；pytest 檢查計畫使用索引，避免退化。
- `/status` 的「最新一季官方財報」兩個查詢會掃整張 `financials`（85 萬列、回填後數百萬），加上只含官方來源的部分索引 `financials_official_period_idx`，從約 150 ms 降到約 4 ms。
- `stockhub.bat`：不帶參數直接啟動（原本是選單），網站改在背景執行、輸出寫到 `.local/logs/web-YYYYMMDD.log`。原本的最小化視窗會被 Next.js 改標題成 next-server，看起來像多開了一個程式。啟動失敗時視窗停住並顯示記錄的最後 20 行。關閉用 `stockhub.bat stop`。
- 關掉開發模式左下角的「N」指示器（`devIndicators: false`），它蓋住側邊欄；編譯錯誤的提示仍會顯示。
- 未做：本機仍跑開發模式（`next dev`），換頁時的編譯與未壓縮的 React 仍會讓操作有些延遲。改用正式建置（`next build` + `next start`）會快很多，但 D-041 的免登入與網站觸發任務在 production 模式一律關閉，要改需要使用者決定。

### D-096 個股頁仿富途的報價頭（使用者追加，2026-10-21）
- 順序改成富途的：分頁在最上方（走勢／基本面／估值／歷史日線，ETF 沒有基本面），下面是報價頭，再下面是分頁內容。K 線收進「走勢」分頁，其他分頁不載入圖表。
- 報價頭：代號與名稱一行；下一行是狀態（收盤日期，或盤中「交易中／盤後 時間」）與產業。價格大字、漲跌色加箭頭，漲跌額與百分比在下一行。右側是「標籤—數值」兩兩一組（手機兩組一列、寬螢幕三組）：最高、今開、最低依昨收上色，另有昨收、成交量、成交額（盤中改為買／賣）、本益比 TTM、股價淨值比、市值（滿一萬億改用「兆」）。ETF 不顯示本益比與股價淨值比。
- 本益比與股價淨值比用估值分頁的同一條規則：從 `valuationSeries` 抽出 `peRatio`、`pbRatio`，公式不變（`testdata/valuation.json` 照樣通過），Python 端不需要改。財報取「今天已可用」的最新一季（`available_date`），市值 = 價格 × `issued_shares`。

## M4 籌碼（2026-10-21）

### D-097 資料源與歷史起點
- 全部用官方來源：證交所 T86／MI_MARGN／MI_QFIIS／BFI82U、櫃買 insti/dailyTrade、margin/balance、insti/qfii、insti/summary、集保 opendata 1-5。都在既有的 `twse`／`tpex` provider 加功能，集保另寫 `tdcc` provider；每台主機每 3 秒一次。
- 實測歷史：證交所三大法人個股從 2012-05-02 起（更早的日期回「查詢日期小於 101年05月02日」）；櫃買三大法人個股在新網站只有 2014-12-01 起，舊網站已關閉，所以上櫃 2012-05～2014-11 沒有法人資料（provider 宣告起點，任務不送請求，介面標示）。櫃買全市場金額彙總只有近期。
- 回填統一從 2012-05-02 開始（使用者核可）。融資融券、外資持股雖然更早就有，回測用不到單獨的更早期間，所以不抓。
- 集保股權分散表只公開最新一週（opendata 沒有日期參數），從現在每週累積；集保查詢頁一次只能查一檔一週，回填 2,000 檔 × 數百週不實際，不抓。

### D-098 單位與欄位
- 股數一律存「股」：融資融券以張公布，provider 乘 1000，和 `prices_daily.volume` 可以直接相除。
- 外資用「不含外資自營商」的數字；交易所的三大法人合計 = 外資 + 投信 + 自營商（外資自營商已含在自營商內，所以不加），照存，品質檢查驗證這條等式。
- 舊格式沒有拆分的欄位（2014-12 前的自營商自行／避險、2017-12 前的外資自營商）存 NULL，不填 0，介面與計算才分得出「沒有資料」和「零」。
- 比率存小數（0.7234），和 `fundamentals_quarterly` 一致。

### D-099 抓取時機與涵蓋表
- `chip_coverage` 記錄每個資料集、市場、日期抓過沒有（含筆數），取代「掃資料表找缺漏」：`sync_chips` 不帶日期時補近 10 個交易日缺的表，`backfill_chips` 跳過已抓的表、可中斷續跑，`/status` 也只讀這張表。
- 當天還沒公布（例如 18:00 時的融資融券）不算失敗，也不寫涵蓋，留給 21:30 或隔天的執行；過去的交易日若交易所回空表，寫一筆 0 列的涵蓋，避免每次重抓。14:30 以前不嘗試當天。
- 回填時上市、上櫃交錯請求，兩邊各自每 3 秒一次：實測一天 8 個請求約 10 秒，2012-05 起約 3,550 個交易日，約 10 小時。
- 集保檔案每天抓一次，同一週已存過就略過（`force=true` 可重寫）；RawStore 以內容雜湊去重，同一週的檔案只存一份。
- 交易所表中不在股票主檔的代號（TDR、特別股、興櫃股票）略過不存，和日線一致。
