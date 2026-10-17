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
- 原因：遷移是純 SQL 檔（符合「SQL 為唯一 schema 來源」），只需要一個執行檔，Python 與 Node 兩邊都不用綁特定 ORM；會產生 `db/schema.sql` 快照，方便審查。
- 取捨：放棄 Alembic 的自動比對產生遷移；本專案本來就要求手寫 SQL，影響不大。
- `make migrate` 在還沒有遷移檔時只做連線檢查（dbmate 遇到空目錄會報錯）。

### D-010 單一 `.env` 放在 repo 根目錄，`DATABASE_URL` 用 `postgresql://` 格式
- dbmate、Python、Next.js 共用同一份；Python 端在程式內把 scheme 換成 `postgresql+psycopg://`。
- Auth.js 的變數採 v5 慣例名稱（`AUTH_SECRET`、`AUTH_GOOGLE_ID`、`AUTH_GOOGLE_SECRET`）。
- 測試用獨立的 `TEST_DATABASE_URL`（`stockhub_test`），測試會清空它的資料表。
