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
