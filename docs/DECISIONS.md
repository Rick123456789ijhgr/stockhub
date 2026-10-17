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
