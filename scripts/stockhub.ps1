# StockHub 本機啟動與關閉：私有 Postgres（port 5433）+ Next.js 開發伺服器（port 3000）。
# 用法：stockhub.bat [start|stop|restart|status]；不帶參數（直接雙擊）等於 start。
# 網站在背景執行（沒有視窗），輸出寫到 .local\logs\web-YYYYMMDD.log；用 stop 關閉。
# 排程任務（scripts/register-tasks.ps1）會自行啟動資料庫，所以關閉後排程照常執行；
# 但不要在排程正在跑（08:55～13:35 報價、18:00 每日）時關閉，會讓該次任務失敗。
param([ValidateSet("start", "stop", "restart", "status", "")][string]$Command = "")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bash = "C:\Program Files\Git\bin\bash.exe"
$port = 3000
$url = "http://localhost:$port"
$pidFile = Join-Path $root ".local\web.pid"
$logDir = Join-Path $root ".local\logs"

function Invoke-LocalPg([string]$action) {
  # local-pg.sh 需要 Git Bash；輸出在 bash 內處理，避免 PowerShell 5.1 把 stderr 當成錯誤。
  $unixRoot = $root -replace '\\', '/'
  $quiet = if ($action -eq "status") { " >/dev/null 2>&1" } else { "" }
  & $bash -c "cd '$unixRoot' && scripts/local-pg.sh $action$quiet" | Out-Host
  return $LASTEXITCODE -eq 0
}

function Test-Db { (Test-Path (Join-Path $root ".local\pgdata")) -and (Invoke-LocalPg "status") }

function Get-PortProcess {
  $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) { Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue }
}

# 只認自己啟動的那個 cmd（PID + 啟動時間都相符），避免 PID 被重用時誤殺別的程式。
function Get-LauncherProcess {
  if (-not (Test-Path $pidFile)) { return $null }
  $saved = (Get-Content $pidFile -Raw).Trim() -split ","
  $proc = Get-Process -Id ([int]$saved[0]) -ErrorAction SilentlyContinue
  if ($proc -and $proc.StartTime.Ticks -eq [long]$saved[1]) { return $proc }
  return $null
}

function Start-Db {
  if (-not (Test-Path (Join-Path $root ".local\pgdata"))) {
    Write-Host "找不到 .local\pgdata：第一次使用請先執行 make db-local-init" -ForegroundColor Red
    return $false
  }
  if (Test-Db) { Write-Host "資料庫已在執行（localhost:5433）"; return $true }
  Write-Host "啟動資料庫..."
  return (Invoke-LocalPg "start")
}

function Start-Web {
  $existing = Get-PortProcess
  if ($existing) {
    if ($existing.ProcessName -ne "node") {
      Write-Host "port $port 被 $($existing.ProcessName)（PID $($existing.Id)）占用，無法啟動網站" -ForegroundColor Red
      return $false
    }
    Write-Host "網站已在執行：$url"
    return $true
  }
  New-Item -ItemType Directory -Force $logDir | Out-Null
  $log = Join-Path $logDir ("web-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
  Write-Host "啟動網站（背景執行，記錄在 $log）..."
  # 不開視窗：Next.js 會把主控台標題改成 next-server，留著視窗只會多一個工作列項目。
  $proc = Start-Process cmd.exe -ArgumentList "/c pnpm dev >> `"$log`" 2>&1" `
    -WorkingDirectory (Join-Path $root "web") -WindowStyle Hidden -PassThru
  New-Item -ItemType Directory -Force (Split-Path $pidFile) | Out-Null
  Set-Content $pidFile "$($proc.Id),$($proc.StartTime.Ticks)"
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    if (Get-PortProcess) { Write-Host "網站已啟動：$url"; return $true }
    if ($proc.HasExited) { break }
    Start-Sleep -Seconds 1
  }
  Write-Host "網站沒有在 90 秒內啟動，記錄的最後幾行：" -ForegroundColor Red
  if (Test-Path $log) { Get-Content $log -Tail 20 | Out-Host }
  return $false
}

function Stop-Web {
  $stopped = $false
  $launcher = Get-LauncherProcess
  if ($launcher) {
    taskkill /PID $launcher.Id /T /F | Out-Null
    $stopped = $true
  }
  Remove-Item $pidFile -ErrorAction SilentlyContinue
  # 不是由本腳本啟動的（例如手動 make web-dev）：只關 port 上的 node。
  Start-Sleep -Milliseconds 500
  $left = Get-PortProcess
  if ($left -and $left.ProcessName -eq "node") {
    taskkill /PID $left.Id /T /F | Out-Null
    $stopped = $true
  } elseif ($left) {
    Write-Host "port $port 上是 $($left.ProcessName)（PID $($left.Id)），不是網站，不處理" -ForegroundColor Yellow
  }
  Write-Host $(if ($stopped) { "網站已關閉" } else { "網站沒有在執行" })
}

function Stop-Db {
  if (-not (Test-Db)) { Write-Host "資料庫沒有在執行"; return }
  Write-Host "關閉資料庫..."
  if (Invoke-LocalPg "stop") { Write-Host "資料庫已關閉" }
}

function Show-Status {
  $db = if (Test-Db) { "執行中（localhost:5433）" } else { "已停止" }
  $web = Get-PortProcess
  $webText = if ($web) { "執行中（$url，$($web.ProcessName) PID $($web.Id)）" } else { "已停止" }
  Write-Host "資料庫：$db"
  Write-Host "網站：  $webText"
}

function Invoke-Action([string]$name) {
  switch ($name) {
    "start" { return ((Start-Db) -and (Start-Web) -and (Open-Site)) }
    "stop" { Stop-Web; Stop-Db; return $true }
    "restart" {
      Stop-Web
      return ((Start-Db) -and (Start-Web) -and (Open-Site))
    }
    "status" { Show-Status; return $true }
  }
}

function Open-Site { Start-Process $url; return $true }

if (-not $Command) { $Command = "start" }
$ok = Invoke-Action $Command
# 直接雙擊時視窗會自己關；失敗就停住，才看得到錯誤訊息。
if (-not $ok) {
  Read-Host "按 Enter 關閉"
  exit 1
}
if ($Command -ne "status") { Start-Sleep -Seconds 2 }
exit 0
