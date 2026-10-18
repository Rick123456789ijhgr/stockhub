# infra：ETL 映像與 Cloud Run Jobs 部署

ETL 是一個容器映像（`infra/Dockerfile`），入口是 `python -m stockhub.etl`。每個排程任務對應一個 Cloud Run Job，由 Cloud Scheduler 定時觸發。M0 只提供說明與指令；使用者備妥 GCP 專案後照下列步驟執行。不使用 Terraform（見 `docs/M0.md` 範圍外清單）。

## 映像

```bash
# 在 repo 根目錄建置（build context 必須是根目錄，.dockerignore 只放行 py/）
docker build -f infra/Dockerfile -t stockhub-etl .

# 本機試跑（Linux/macOS 的 Docker 連主機上的 Postgres 用 host.docker.internal）
docker run --rm --env-file .env \
  -e DATABASE_URL=postgresql://stockhub:stockhub@host.docker.internal:5433/stockhub?sslmode=disable \
  -e RAWSTORE_LOCAL_DIR=/tmp/rawstore \
  stockhub-etl run heartbeat
```

映像細節：多階段建置（uv 只存在於 build stage）、以 uid 10001 的非 root 使用者執行、`PYTHONUTF8=1`、預設指令 `list`。

## 一次性 GCP 設定

先設定變數（自行替換）：

```bash
export PROJECT_ID=your-project
export REGION=asia-east1                     # 台灣彰化
export REPO=stockhub                         # Artifact Registry repository
export BUCKET=${PROJECT_ID}-stockhub-raw     # RawStore bucket
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/etl
gcloud config set project $PROJECT_ID
```

啟用 API、建立 repository 與 bucket：

```bash
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com storage.googleapis.com

gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION

gcloud storage buckets create gs://$BUCKET --location=$REGION \
  --uniform-bucket-level-access --public-access-prevention
```

服務帳號（權限分開，見規劃書第 9 節）：

```bash
# ETL 執行身分：只能寫 RawStore bucket、讀秘密
gcloud iam service-accounts create stockhub-etl --display-name="StockHub ETL"
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member=serviceAccount:stockhub-etl@${PROJECT_ID}.iam.gserviceaccount.com \
  --role=roles/storage.objectAdmin

# 排程觸發身分：只能啟動 Cloud Run Job
gcloud iam service-accounts create stockhub-scheduler --display-name="StockHub Scheduler"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:stockhub-scheduler@${PROJECT_ID}.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

秘密放 Secret Manager（不要放進映像或指令歷史以外的地方）：

```bash
printf '%s' 'postgresql://USER:PASSWORD@HOST/stockhub?sslmode=require' | \
  gcloud secrets create stockhub-database-url --data-file=-
printf '%s' 'smtp-password' | gcloud secrets create stockhub-smtp-password --data-file=-

for s in stockhub-database-url stockhub-smtp-password; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:stockhub-etl@${PROJECT_ID}.iam.gserviceaccount.com \
    --role=roles/secretmanager.secretAccessor
done
```

## 建置與推送映像

```bash
gcloud auth configure-docker ${REGION}-docker.pkg.dev
docker build -f infra/Dockerfile -t $IMAGE:$(git rev-parse --short HEAD) -t $IMAGE:latest .
docker push --all-tags $IMAGE
# 或不用本機 Docker：gcloud builds submit --tag $IMAGE:latest -f infra/Dockerfile .
```

## 建立 Cloud Run Jobs

每個任務一個 Job，共用同一個映像，差別只在 `--args`：

```bash
COMMON_FLAGS=(
  --image=$IMAGE:latest
  --region=$REGION
  --service-account=stockhub-etl@${PROJECT_ID}.iam.gserviceaccount.com
  --set-secrets=DATABASE_URL=stockhub-database-url:latest,SMTP_PASSWORD=stockhub-smtp-password:latest
  --set-env-vars=^@^RAWSTORE_BACKEND=gcs@RAWSTORE_GCS_BUCKET=${BUCKET}@NOTIFIER=email@SMTP_HOST=smtp.example.com@SMTP_PORT=587@SMTP_USERNAME=bot@example.com@SMTP_FROM=bot@example.com@ALERT_EMAIL_TO=me@example.com
  --max-retries=0          # 重試由任務本身的冪等與檢查點處理
  --task-timeout=30m
)

gcloud run jobs create stockhub-heartbeat "${COMMON_FLAGS[@]}" \
  --args=run,heartbeat,--trigger,schedule
gcloud run jobs create stockhub-freshness-check "${COMMON_FLAGS[@]}" \
  --args=run,freshness_check,--trigger,schedule

# 手動執行一次驗證
gcloud run jobs execute stockhub-heartbeat --region=$REGION --wait
```

更新映像後：`gcloud run jobs update <job> --image=$IMAGE:<tag> --region=$REGION`。

`--set-env-vars=^@^...` 是 gcloud 的自訂分隔符語法，因為 `ALERT_EMAIL_TO` 可能含逗號。

## Cloud Scheduler

Scheduler 以 `stockhub-scheduler` 服務帳號呼叫 Cloud Run Admin API 的 `jobs/<name>:run`：

```bash
schedule_job() {  # $1=scheduler name  $2=cron  $3=cloud run job
  gcloud scheduler jobs create http "$1" \
    --location=$REGION \
    --schedule="$2" --time-zone="Asia/Taipei" \
    --http-method=POST \
    --uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/$3:run" \
    --oauth-service-account-email=stockhub-scheduler@${PROJECT_ID}.iam.gserviceaccount.com
}

schedule_job stockhub-heartbeat-daily   "0 7 * * *"   stockhub-heartbeat
schedule_job stockhub-freshness-weekday "30 8 * * 1-5" stockhub-freshness-check
# 盤中報價：開盤前啟動，任務自己每 30 秒輪詢到 13:35 後結束（Cloud Run Job 需 --task-timeout=5h）
schedule_job stockhub-quotes-weekday    "55 8 * * 1-5" stockhub-poll-quotes
```

`stockhub-poll-quotes` 用 `--args=run,poll_quotes,--trigger,schedule` 建立；休市日任務會自己判斷並記為 skipped。

`freshness_check` 檢查「`prices_daily` 最新日期 ≥ 執行日的上一個交易日」，所以排在平日早上；M1 接上日線擷取後，再依實際入庫時間加一個傍晚的同日檢查（見 `docs/DECISIONS.md`）。

## 資料庫遷移

映像不包含遷移。正式環境的遷移在部署前由本機或 CI 執行：

```bash
DATABASE_URL='postgresql://...neon...?sslmode=require' make migrate
```

## 驗證清單

- `gcloud run jobs executions list --job=stockhub-heartbeat --region=$REGION` 有成功紀錄
- 網站 `/status` 看得到 `trigger = schedule` 的 `job_runs`
- `gcloud storage ls gs://$BUCKET/raw/stockhub/heartbeat/` 有物件
