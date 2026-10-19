# StockHub 本機啟動與關閉：私有 Postgres（port 5433）+ Next.js 開發伺服器（port 3000）。
# 用法：stockhub.bat [start|stop|restart|status]；不帶參數顯示選單（可直接雙擊）。
# 網站跑在最小化的「StockHub web」視窗，關掉該視窗等於關閉網站。
# 排程任務（scripts/register-tasks.ps1）會自行啟動資料庫，所以關閉後排程照常執行；
# 但不要在排程正在跑（08:55～13:35 報價、18:00 每日）時關閉，會讓該次任務失敗。
param([ValidateSet("start", "stop", "restart", "status", "")][string]$Command = "")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bash = "C:\Program Files\Git\bin\bash.exe"
$port = 3000
$url = "http://localhost:$port"
$pidFile = Join-Path $root ".local\web.pid"

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
  Write-Host "啟動網站（最小化視窗「StockHub web」）..."
  # 伺服器異常結束時 pause 讓視窗停住，才看得到錯誤訊息。
  $proc = Start-Process cmd.exe -ArgumentList "/c title StockHub web & pnpm dev || pause" `
    -WorkingDirectory (Join-Path $root "web") -WindowStyle Minimized -PassThru
  New-Item -ItemType Directory -Force (Split-Path $pidFile) | Out-Null
  Set-Content $pidFile "$($proc.Id),$($proc.StartTime.Ticks)"
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    if (Get-PortProcess) { Write-Host "網站已啟動：$url"; return $true }
    if ($proc.HasExited) { break }
    Start-Sleep -Seconds 1
  }
  Write-Host "網站沒有在 90 秒內啟動，請看「StockHub web」視窗的錯誤訊息" -ForegroundColor Red
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
    "start" {
      if ((Start-Db) -and (Start-Web)) { Start-Process $url }
    }
    "stop" { Stop-Web; Stop-Db }
    "restart" {
      Stop-Web
      if ((Start-Db) -and (Start-Web)) { Start-Process $url }
    }
    "status" { Show-Status }
  }
}

if ($Command) {
  Invoke-Action $Command
  exit 0
}

while ($true) {
  Write-Host ""
  Show-Status
  Write-Host ""
  Write-Host "  1 啟動   2 關閉   3 重新啟動網站   4 重新整理狀態   0 離開"
  $choice = Read-Host "請選擇"
  switch ($choice) {
    "1" { Invoke-Action "start" }
    "2" { Invoke-Action "stop" }
    "3" { Invoke-Action "restart" }
    "4" { }
    "0" { exit 0 }
    default { Write-Host "請輸入 0～4" }
  }
}
