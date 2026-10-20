# StockHub

個人自用的台股研究平台：基本面、籌碼、總經、新聞與社群情緒、持股追蹤、選股篩選與回測。單人使用。

| 文件 | 內容 |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | 規劃摘要與里程碑 |
| [docs/M0.md](docs/M0.md) | 目前里程碑的任務與驗收 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 決策紀錄、偏離與待確認事項 |
| [infra/README.md](infra/README.md) | ETL 映像、Cloud Run Jobs、Cloud Scheduler |
| [CLAUDE.md](CLAUDE.md) | 不可違反的規則與開發慣例 |

## 架構

```
web/   Next.js 16（App Router）+ Auth.js + Kysely  ──►  PostgreSQL（Neon / 本機）
py/    stockhub：common（設定、DB、RawStore、Notifier、交易日曆）
                 etl（provider adapter、排程任務、CLI）      ──►  RawStore（GCS / 本機）
db/    migrations/*.sql（dbmate，唯一 schema 來源）
infra/ ETL Dockerfile 與部署說明
```

網站只做查詢與顯示（部署在 Vercel）；資料擷取由 ETL 容器以 Cloud Run Jobs 執行，Cloud Scheduler 定時觸發。

## 本機快速開始（約 15 分鐘，回填另計）

### 1. 需要的工具

- GNU make、git、bash（Windows 用 Git Bash）
- [uv](https://docs.astral.sh/uv/getting-started/installation/)（會自動安裝 Python 3.12）
- Node.js ≥ 20.9（建議 22）與 pnpm（`corepack enable`）
- [dbmate](https://github.com/amacneil/dbmate/releases) v2.36 以上，放進 PATH
- 資料庫二選一：Docker Desktop，或已安裝的 PostgreSQL 執行檔（16 以上）

### 2. 設定環境變數

```bash
cp .env.example .env
# 目前階段先不登入：把 AUTH_DISABLED 改成 true（只在 make web-dev 生效，部署環境一律無效）
# 之後要啟用登入：AUTH_DISABLED=false，並填 AUTH_SECRET、ALLOWED_EMAIL、AUTH_GOOGLE_ID / SECRET
```

### 3. 啟動資料庫並套用遷移

```bash
make db-up            # Docker：Postgres 16，localhost:5433
# 或沒有 Docker：
make db-local-init    # 第一次：在 .local/pgdata 建立叢集（之後用 make db-local-up 啟動）

make migrate          # 套用 db/migrations 到 DATABASE_URL
```

### 4. 安裝依賴並跑檢查

```bash
make py-install web-install
make check            # = make py-test（ruff + mypy + pytest）+ make web-check（lint + typecheck + test）
```

### 5. 抓資料（證交所、櫃買中心官方資料）

```bash
make etl-daily                        # 休市表、主檔、下市、除權息、今天的日線、還原因子（收盤後約 14:30 才有日線）
make etl-daily date=2026-10-16        # 指定某一天
make etl-backfill                     # 回填過去一年的日線（約 25 分鐘；中斷後重跑會接續）
make etl-history                      # 完整歷史：下市清單 + 2004-02-11 起的日線 + 除權息 + 還原因子（約 7～8 小時，可續跑）
make etl-quotes                       # 盤中：自選股與持股每 30 秒更新到 13:35（symbols=2330,0050 可另外指定）
make etl-quotes symbols=2330 once=1   # 只抓一次
make etl-fundamentals                 # 財報與月營收歷史（2013 年起，FinMind；約 17 小時，可續跑）
make etl-fundamentals symbols=2330    # 只抓某幾檔（refetch=true 重抓已抓過的）
make etl-financials                   # 最新一季財報與月營收（官方 OpenAPI），再向 FinMind 補新申報的公司
make etl-chips                        # 籌碼：補近 10 個交易日缺的三大法人／融資融券／外資持股，集保本週，摘要與法人警示
make etl-chips date=2026-10-16        # 重抓某一天的籌碼
make etl-chips-history                # 籌碼歷史（2012-05-02 起，約 11 小時，可續跑；start= end= datasets=margin,...）
```

財報歷史來自 FinMind（公開資訊觀測站的 robots.txt 禁止爬取）：先到 finmindtrade.com 註冊免費帳號，把 token 填進 `.env` 的 `FINMIND_TOKEN`。免費帳號每小時 600 次，程式自己限制在 500 次以內，並在接近上限時暫停。品質檢查沒過的財報會進隔離區，在 `/admin` 確認（見 `docs/DECISIONS.md` D-086）。

籌碼全部來自證交所、櫃買中心與集保結算所的官方資料。上櫃的三大法人個股資料只有 2014-12-01 以後；集保股權分散表官方只公開最新一週，所以大戶資料從 M4 上線開始逐週累積（見 `docs/DECISIONS.md` D-097）。融資融券晚上才公布，`etl-daily`（18:00）抓不到的部分由 21:30 的 `etl-chips` 補上。

上櫃日線官方資料從 2007-07-02 起才有；還原價無法解釋的跳空（例如櫃買的面額變更）會列在 `corporate_actions_quarantine`，見 `docs/DECISIONS.md` D-053。

其他任務：`make etl-list` 列出全部；`cd py && uv run python -m stockhub.etl run freshness_check` 檢查資料是否落後。

### 6. 開網站

```bash
make web-dev          # http://localhost:3000
```

- `/stocks`：搜尋股票與 ETF（搜尋時也會列出已下市公司）
- `/stocks/2330`：K 線（還原／原始、MA、KD／MACD／RSI）、加入自選、盤中報價；基本面（月營收、獲利率、EPS、現金流、ROE 與杜邦、變化提示、單季財報）；估值（本益比、股價淨值比、殖利率的歷史百分位、河流圖、同業比較）；籌碼（三大法人買賣超與連買天數、融資融券、外資持股比、集保大戶持股比）；近 120 日表格
- `/`（首頁）：持股損益、警示、三大法人買賣超排行（全市場金額與個股前 10 名）
- `/status`：任務紀錄、日線涵蓋、財報與籌碼的回填進度；「日線更新到今天」「籌碼更新到今天」與缺漏日的「重新抓取」按鈕
- 網站上的手動更新按鈕會把任務排入 `job_requests`。`.env` 設 `JOB_RUNNER=local` 時網站會立刻在背景執行（`scripts/scheduled.sh etl-requests`，log 在 `.local/logs/etl-requests-*.log`）；其他環境（例如 Vercel）會在下一次 `make etl-daily` 開頭執行。

### 7. 每天自動更新（選用，Windows 工作排程器）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/register-tasks.ps1          # 註冊
powershell -ExecutionPolicy Bypass -File scripts/register-tasks.ps1 -Remove  # 移除
```

會建立四個工作（目前使用者，不需系統管理員）：平日 08:55 盤中報價、平日 18:00 每日更新（日線、除權息、財報、月營收、籌碼）、平日 21:30 籌碼（融資融券晚上才公布），以及登入時啟動本機資料庫的「StockHub database」。排程任務需要資料庫時會透過「StockHub database」啟動它，資料庫因此不會被排程任務的時間上限一起關掉。log 在 `.local/logs`，非交易日會自動略過（`skipped`）。

## 常用指令

`make help` 會列出全部指令。

| 指令 | 說明 |
|---|---|
| `make db-up` / `db-down` | docker compose 的 Postgres |
| `make db-local-init` / `db-local-up` / `db-local-down` | 不用 Docker 的本機 Postgres |
| `make migrate` / `migrate-status` | 套用遷移／查看狀態 |
| `make db-new name=add_foo` | 新增遷移檔 |
| `make db-types` | 遷移後重新產生 `web/src/lib/db/types.gen.ts` |
| `make py-test` / `py-fmt` | Python 檢查／自動修正格式 |
| `make etl-daily` / `etl-backfill` / `etl-history` | 每日更新／回填日線／完整歷史 |
| `make etl-quotes` | 盤中報價輪詢 |
| `make etl-fundamentals` / `etl-financials` | 財報與月營收歷史／最新一季與月營收 |
| `make etl-compute-fundamentals` | 重算基本面與變化提示（`all=true` 全部重算） |
| `make etl-chips` / `etl-chips-history` | 籌碼（補近 10 個交易日、集保、摘要、法人警示）／籌碼歷史 |
| `make etl-requests` | 執行網站排入的任務 |
| `make etl-list` / `etl-heartbeat` | ETL CLI |
| `make web-dev` / `web-build` / `web-check` | 網站開發、建置、檢查 |

ETL CLI 的結束碼：0 成功或略過、1 任務失敗、2 用法或設定錯誤、3 同一參數已在執行中。

## 環境變數

完整說明見 [.env.example](.env.example)。`.env` 放在 repo 根目錄，dbmate、Python 與 Next.js 共用；正式環境的值放在 Vercel 與 Secret Manager。

| 變數 | 使用者 | 必要 | 說明 |
|---|---|---|---|
| `DATABASE_URL` | web、py、dbmate | ✔ | `postgresql://…`；Neon 需加 `?sslmode=require` |
| `TEST_DATABASE_URL` | pytest | 測試時 | 測試會清空資料表，絕不可指向正式庫 |
| `AUTH_SECRET` | web | ✔ | Auth.js 加密金鑰 |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | web | ✔ | Google OAuth client |
| `ALLOWED_EMAIL` | web | ✔ | 可登入的 email，逗號分隔；空白表示沒人能登入 |
| `AUTH_TRUST_HOST` | web | 非 Vercel | 自架時設 `true` |
| `RAWSTORE_BACKEND` | py | | `local`（預設）或 `gcs` |
| `RAWSTORE_LOCAL_DIR` | py | | 預設 `.local/rawstore` |
| `RAWSTORE_GCS_BUCKET` | py | gcs 時 | bucket 名稱，用 ADC 驗證 |
| `NOTIFIER` | py | | `console`（預設）或 `email` |
| `ALERT_EMAIL_TO`、`SMTP_*` | py | email 時 | 告警收件人與 SMTP 設定 |
| `PROVIDERS_*` | py | | 各資料類型的主來源與備援順序，逗號分隔（見 `.env.example`） |
| `FINMIND_TOKEN` | py | 財報 | FinMind token；沒有時每小時只能 300 次 |
| `FINMIND_REQUESTS_PER_HOUR` | py | | 自己的每小時上限，預設 500 |
| `JOB_RUNNER` | web | | `local`：網站自己執行排入的任務（只在本機開發有效） |
| `SERVICE_AUTH_SECRET` | web、FastAPI | M7 | 服務間驗證，預留 |
| `APP_ENV`、`LOG_LEVEL` | py | | `development` / `production`；log 等級 |

缺少必要設定時，Python 會在啟動時列出所有缺少的變數並結束。

### Email 通知（持股警示、任務失敗）

預設 `NOTIFIER=console`，通知只印在終端機與 `.local/logs`。改用 Email（以 Gmail 為例）：

1. Google 帳戶開啟兩步驟驗證，到「應用程式密碼」（myaccount.google.com/apppasswords）建立一組 16 碼密碼。不要用帳號本身的密碼。
2. 在根目錄 `.env` 填入（不要提交到版本庫）：

   ```
   NOTIFIER=email
   ALERT_EMAIL_TO=收件信箱（可逗號分隔多個）
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_STARTTLS=true
   SMTP_USERNAME=你的 Gmail 地址
   SMTP_PASSWORD=應用程式密碼（16 碼，空白可省略）
   SMTP_FROM=你的 Gmail 地址
   ```

3. `make notify-test` 寄一封測試信；失敗時會印出 SMTP 錯誤（例如帳密錯誤、連不上）。
4. 排程任務每次執行都會重新讀 `.env`，不用重新註冊。

其他郵件服務：port 465 用 `SMTP_STARTTLS=false`（直接 TLS），587 用 `true`。

## 部署

### Neon（資料庫）

1. 建立 Neon 專案，區域選離台灣最近的（例如 AWS ap-southeast-1）。
2. 取得兩種連線字串：**pooled**（主機名稱含 `-pooler`）給 Vercel；**direct** 給遷移與 ETL。
3. 套用遷移：`DATABASE_URL='<direct>?sslmode=require' make migrate`。
4. 之後每次有新的遷移檔：先在 Neon 開一個 branch 試跑，確認無誤再套用到主分支。

### Google OAuth

Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID（Web application）：

- Authorized JavaScript origins：`http://localhost:3000`、`https://<你的網域>`
- Authorized redirect URIs：`http://localhost:3000/api/auth/callback/google`、`https://<你的網域>/api/auth/callback/google`
- OAuth consent screen 設為 External + Testing，把自己的帳號加進 Test users 就好（單人使用不必送審）。

### Vercel（網站）

1. Vercel → Add New Project → 匯入這個 GitHub repo。
2. **Root Directory 設為 `web`**；Framework 會自動偵測為 Next.js，install／build 指令用預設值（pnpm、`pnpm build`）。
3. Environment Variables（Production 與 Preview）：`DATABASE_URL`（Neon pooled）、`AUTH_SECRET`、`AUTH_GOOGLE_ID`、`AUTH_GOOGLE_SECRET`、`ALLOWED_EMAIL`。
4. 部署後，把正式網域加進 Google OAuth 的 redirect URI。
5. 之後 push 到 `main` 會自動部署，PR 會產生 Preview。Preview 網址每次不同，Google OAuth 只對已登記的網域有效，所以 Preview 需要登入的功能請在本機測。

### Cloud Run Jobs 與 Cloud Scheduler（ETL）

見 [infra/README.md](infra/README.md)：建立 Artifact Registry 與 bucket、服務帳號、Secret Manager、每個任務一個 Cloud Run Job，再用 Cloud Scheduler 依台北時間觸發。CI 的 `ETL image` workflow 也可以手動推送映像（需要先設定 GCP repository variables）。

## CI

GitHub Actions（`.github/workflows/`）：

- `CI`（每個 PR 與 main）：
  - **web**：lint、typecheck、test、production build
  - **py**：ruff、mypy、pytest，用 Postgres 16 service container
  - **migrations**：在空資料庫套用全部遷移 → 全部回滾 → 重新套用，並檢查 Kysely 型別沒有過期
- `ETL image`（py 或 infra 有變動時）：建置映像並做冒煙測試（列出任務、確認以非 root 執行）；推送是手動觸發。

## 備份與還原（預定作法，M0 只寫文件）

要保護的是**無法重建**的資料：`portfolio_transactions`、`watchlist`、`settings`、`audit_log`，以及之後的題材、警示規則、策略與回測結果。市場資料可以從 RawStore 或資料源重新抓取。

1. **託管備份**：Neon 內建的時間點還原（保留天數依方案而定）。
2. **定期匯出**：一個每日執行的 Cloud Run Job 跑 `pg_dump --format=custom`（全庫，或至少上述表）→ 用 `age` 加密 → 上傳到獨立的 GCS bucket（`backups/daily/`、`backups/monthly/`）。用 lifecycle rule 保留每日 30 天、每月一份 12 個月。
3. **還原測試**：上線前做一次，之後每季一次。從最新的匯出檔還原到新的 Neon branch，再跑 `make migrate-status`，並抽查持股筆數與最新交易；結果寫進 `audit_log`。
4. 加密金鑰與 bucket 權限要和 ETL 服務帳號分開；還原步驟另外寫成 runbook（M2 持股功能上線前完成）。

## 授權與資料來源

僅供個人研究使用。各資料源的使用條款與額度，在正式串接前（M1 起）逐一確認並記錄在 `docs/DECISIONS.md`；爬取一律限速，優先使用官方 OpenAPI。財報歷史用 FinMind（公開資訊觀測站 robots.txt 禁止爬取，所以不抓），每天的最新一季、月營收與公司基本資料用證交所與櫃買中心 OpenAPI。籌碼用證交所、櫃買中心的盤後公告與集保結算所 opendata（集保網站沒有 robots.txt，每天只抓一次）。
