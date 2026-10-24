# StockHub 本機啟動與關閉：私有 Postgres（port 5433）+ Next.js 正式建置（port 3000，只綁 127.0.0.1）。
# 用法：stockhub.bat [start|stop|restart|status|dev]；不帶參數（直接雙擊）等於 start。
# 正式建置會自動更新（D-131）：start／restart 會一起啟動背景監看，程式碼改完靜置 15 秒就建置新版本。
# 建置寫到另一個資料夾（web\.next 與 web\.next-b 輪流用），舊版網站建置期間照常服務；建好才切換，
# 只中斷幾秒；建置失敗就維持舊版。記錄在 .local\logs\web-build-*.log 與 web-watch-*.log。
# dev 直接用開發模式（存檔即更新，但每頁第一次開比較慢；見 D-117）。
# 網站在背景執行（沒有視窗），輸出寫到 .local\logs\web-YYYYMMDD.log；用 stop 關閉（監看一起關）。
# 排程任務（scripts/register-tasks.ps1）會自行啟動資料庫，所以關閉後排程照常執行；
# 但不要在排程正在跑（08:55～13:35 報價、18:00 每日）時關閉，會讓該次任務失敗。
param([ValidateSet("start", "stop", "restart", "status", "dev", "watch", "")][string]$Command = "")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bash = "C:\Program Files\Git\bin\bash.exe"
$port = 3000
# 用 127.0.0.1 而不是 localhost：網站只綁 IPv4，localhost 會先試 ::1 被拒，每條新連線多約 0.2 秒。
$url = "http://127.0.0.1:$port"
$pidFile = Join-Path $root ".local\web.pid"
$watchPidFile = Join-Path $root ".local\web-watch.pid"
# 目前網站用的建置資料夾（.next 或 .next-b）；新版本建置到另一個（D-131）。
$slotFile = Join-Path $root ".local\web-slot"
$logDir = Join-Path $root ".local\logs"
$webDir = Join-Path $root "web"
# 會影響建置結果的檔案；任何一個比目前建置新就重新建置。.env 也算（NEXT_PUBLIC_* 在建置時寫死）。
$buildInputs = @("src", "public", "package.json", "pnpm-lock.yaml", "next.config.ts", "tsconfig.json", "postcss.config.mjs", "..\.env")
# 最後一次修改後等這麼久才建置，避免改到一半就開始建置。
$quietSeconds = 15
$watchIntervalSeconds = 5
# 建置成功時寫在建置資料夾裡：建置開始的時間（UTC ticks）。建置期間又改的檔案比它新，下一輪會再建置。
$sourceStampName = "stockhub-source-time.txt"

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

# 只認自己啟動的程序（PID + 啟動時間都相符），避免 PID 被重用時誤殺別的程式。
function Get-SavedProcess([string]$file) {
  if (-not (Test-Path $file)) { return $null }
  $saved = (Get-Content $file -Raw).Trim() -split ","
  $proc = Get-Process -Id ([int]$saved[0]) -ErrorAction SilentlyContinue
  if ($proc -and $proc.StartTime.Ticks -eq [long]$saved[1]) { return $proc }
  return $null
}

function Save-Process([string]$file, $proc) {
  New-Item -ItemType Directory -Force (Split-Path $file) | Out-Null
  Set-Content $file "$($proc.Id),$($proc.StartTime.Ticks)"
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

# ------------------------------------------------------------------ build folders (D-131)

function Get-ActiveSlot {
  if (Test-Path $slotFile) {
    $slot = (Get-Content $slotFile -Raw).Trim()
    if ($slot -eq ".next" -or $slot -eq ".next-b") { return $slot }
  }
  return ".next"
}

function Get-OtherSlot([string]$slot) { if ($slot -eq ".next") { ".next-b" } else { ".next" } }

function Test-SlotBuilt([string]$slot) { Test-Path (Join-Path $webDir "$slot\BUILD_ID") }

# 這個資料夾的建置包含到哪個時間點的程式碼；沒有建置就是 $null。
function Get-BuiltAt([string]$slot) {
  if (-not (Test-SlotBuilt $slot)) { return $null }
  $stamp = Join-Path $webDir "$slot\$sourceStampName"
  if (Test-Path $stamp) { return [datetime]::new([long](Get-Content $stamp -Raw).Trim(), [DateTimeKind]::Utc) }
  return (Get-Item (Join-Path $webDir "$slot\BUILD_ID")).LastWriteTimeUtc
}

# 建置輸入中最新的修改時間（UTC）；資料夾也算，刪檔會改到上層資料夾的時間。
function Get-SourceTime {
  $latest = [datetime]::MinValue
  foreach ($item in $buildInputs) {
    $path = Join-Path $webDir $item
    if (-not (Test-Path $path)) { continue }
    $self = Get-Item $path
    if ($self.LastWriteTimeUtc -gt $latest) { $latest = $self.LastWriteTimeUtc }
    # 只有資料夾才往下找：對檔名用 -Recurse 會變成在所有子資料夾找同名檔（含建置輸出裡的 package.json）。
    if (-not $self.PSIsContainer) { continue }
    $newest = Get-ChildItem $path -Recurse -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if ($newest -and $newest.LastWriteTimeUtc -gt $latest) { $latest = $newest.LastWriteTimeUtc }
  }
  return $latest
}

function Test-BuildStale([string]$slot) {
  $built = Get-BuiltAt $slot
  return ($null -eq $built) -or ((Get-SourceTime) -gt $built)
}

# 建置到指定資料夾；網站可同時用另一個資料夾照常服務。
function Invoke-Build([string]$slot) {
  $log = Join-Path $logDir ("web-build-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
  $started = [DateTime]::UtcNow
  Write-Host "建置網站到 web\$slot（約 1～2 分鐘，記錄在 $log）..."
  Add-Content -Encoding UTF8 $log ("`r`n==== {0} 建置到 {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $slot)
  $proc = Start-Process cmd.exe -ArgumentList "/c set NEXT_DIST_DIR=$slot&& pnpm build >> `"$log`" 2>&1" `
    -WorkingDirectory $webDir -WindowStyle Hidden -PassThru -Wait
  if ($proc.ExitCode -eq 0) {
    Set-Content (Join-Path $webDir "$slot\$sourceStampName") $started.Ticks
    return $true
  }
  Write-Host "建置失敗，記錄的最後幾行：" -ForegroundColor Yellow
  Get-Content $log -Tail 20 | Out-Host
  return $false
}

# 要用哪個資料夾啟動：目前的過期就先建置到另一個，成功才切換；失敗時有舊建置就用舊的，都沒有回傳 $null。
function Update-Build {
  $active = Get-ActiveSlot
  if (-not (Test-BuildStale $active)) { return $active }
  Write-Host "程式碼有更新，先建置新版本（目前的網站照常可用）"
  $next = Get-OtherSlot $active
  if (Invoke-Build $next) {
    Set-Content $slotFile $next
    return $next
  }
  if (Test-SlotBuilt $active) {
    Write-Host "改用上一次成功的建置" -ForegroundColor Yellow
    return $active
  }
  return $null
}

# ------------------------------------------------------------------ web server

function Start-Web([string]$slot) {
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
  # 正式建置只綁 127.0.0.1（區網連不進來）；STOCKHUB_LOCAL_SERVER 讓本機免登入與網站觸發任務照常運作（D-117）。
  # $slot 為空＝開發模式（輸出在 .next\dev，與正式建置分開）。
  $command = if ($slot) {
    "set NEXT_DIST_DIR=$slot&& set STOCKHUB_LOCAL_SERVER=true&& pnpm start -H 127.0.0.1 -p $port"
  } else { "pnpm dev" }
  $mode = if ($slot) { "正式建置 web\$slot" } else { "開發模式" }
  Write-Host "啟動網站（$mode，背景執行，記錄在 $log）..."
  # 不開視窗：Next.js 會把主控台標題改成 next-server，留著視窗只會多一個工作列項目。
  $proc = Start-Process cmd.exe -ArgumentList "/c $command >> `"$log`" 2>&1" `
    -WorkingDirectory $webDir -WindowStyle Hidden -PassThru
  Save-Process $pidFile $proc
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    if (Get-PortProcess) { Write-Host "網站已啟動：$url"; return $true }
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 300
  }
  Write-Host "網站沒有在 90 秒內啟動，記錄的最後幾行：" -ForegroundColor Red
  if (Test-Path $log) { Get-Content $log -Tail 20 | Out-Host }
  return $false
}

# 正式建置啟動；沒有可用的建置時退回開發模式。
function Start-ProdWeb {
  if (Get-PortProcess) { return (Start-Web (Get-ActiveSlot)) }
  $slot = Update-Build
  if (-not $slot) { Write-Host "沒有可用的建置，改用開發模式啟動（比較慢）" -ForegroundColor Yellow }
  return (Start-Web $slot)
}

function Stop-Web([switch]$Quiet) {
  $stopped = $false
  $launcher = Get-SavedProcess $pidFile
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
  if (-not $Quiet) { Write-Host $(if ($stopped) { "網站已關閉" } else { "網站沒有在執行" }) }
}

# 網站在跑時換成新版本：先建置（舊版照常服務），再重啟到新的資料夾，只中斷幾秒。
function Restart-ProdWeb {
  if (-not (Get-PortProcess)) { return (Start-ProdWeb) }
  $slot = Update-Build
  Stop-Web
  return (Start-Web $slot)
}

# ------------------------------------------------------------------ watcher (D-131)

function Start-Watcher {
  if (Get-SavedProcess $watchPidFile) { return }
  $proc = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList `
    "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" watch"
  Save-Process $watchPidFile $proc
  Write-Host "自動更新已開啟：程式碼改完約 $quietSeconds 秒後自動建置並切換"
}

function Stop-Watcher {
  $proc = Get-SavedProcess $watchPidFile
  # /T：監看中途的建置也一起結束。
  if ($proc) { taskkill /PID $proc.Id /T /F | Out-Null }
  Remove-Item $watchPidFile -ErrorAction SilentlyContinue
}

# 背景監看（由 Start-Watcher 啟動）：每 5 秒比對程式碼與目前建置；改完靜置 15 秒就建置到另一個資料夾，
# 成功才切換。同一批修改建置失敗只試一次，下次存檔再試。網站被關掉（不是自己切換造成的）就結束。
function Invoke-Watch {
  New-Item -ItemType Directory -Force $logDir | Out-Null
  $log = Join-Path $logDir ("web-watch-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
  $write = { param($message) Add-Content -Encoding UTF8 $log ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message) }
  & $write "開始監看（web\$(Get-ActiveSlot)）"
  $failedSource = [datetime]::MinValue
  while ($true) {
    Start-Sleep -Seconds $watchIntervalSeconds
    if (-not (Get-SavedProcess $pidFile)) { & $write "網站已關閉，停止監看"; break }
    $active = Get-ActiveSlot
    $source = Get-SourceTime
    $built = Get-BuiltAt $active
    if ($built -and $source -le $built) { continue }
    if ($source -le $failedSource) { continue }
    if (([DateTime]::UtcNow - $source).TotalSeconds -lt $quietSeconds) { continue }
    $next = Get-OtherSlot $active
    & $write "偵測到程式碼更新，建置到 web\$next"
    if (-not (Invoke-Build $next)) {
      $failedSource = $source
      & $write "建置失敗，網站維持舊版（見 web-build 記錄）；下次存檔再試"
      continue
    }
    Set-Content $slotFile $next
    $began = Get-Date
    Stop-Web -Quiet
    if (Start-Web $next) {
      & $write ("已切換到新版本（中斷 {0:N1} 秒）" -f ((Get-Date) - $began).TotalSeconds)
    } else {
      & $write "新版本啟動失敗，改回 web\$active"
      Set-Content $slotFile $active
      Start-Web $active | Out-Null
    }
  }
}

# ------------------------------------------------------------------ commands

function Stop-Db {
  if (-not (Test-Db)) { Write-Host "資料庫沒有在執行"; return }
  Write-Host "關閉資料庫..."
  if (Invoke-LocalPg "stop") { Write-Host "資料庫已關閉" }
}

function Show-Status {
  $db = if (Test-Db) { "執行中（localhost:5433）" } else { "已停止" }
  $web = Get-PortProcess
  $webText = if ($web) { "執行中（$url，$($web.ProcessName) PID $($web.Id)，web\$(Get-ActiveSlot)）" } else { "已停止" }
  $watch = if (Get-SavedProcess $watchPidFile) { "開啟" } else { "關閉" }
  $stale = if (Test-BuildStale (Get-ActiveSlot)) { "（程式碼比目前建置新）" } else { "" }
  Write-Host "資料庫：  $db"
  Write-Host "網站：    $webText"
  Write-Host "自動更新：$watch$stale"
}

function Invoke-Action([string]$name) {
  switch ($name) {
    "start" {
      if (-not (Start-Db)) { return $false }
      if (-not (Start-ProdWeb)) { return $false }
      if (Get-SavedProcess $pidFile) { Start-Watcher }
      return (Open-Site)
    }
    "stop" { Stop-Watcher; Stop-Web; Stop-Db; return $true }
    "restart" {
      Stop-Watcher
      if (-not (Start-Db)) { return $false }
      if (-not (Restart-ProdWeb)) { return $false }
      if (Get-SavedProcess $pidFile) { Start-Watcher }
      return (Open-Site)
    }
    "status" { Show-Status; return $true }
    "dev" {
      Stop-Watcher
      Stop-Web
      return ((Start-Db) -and (Start-Web "") -and (Open-Site))
    }
  }
}

function Open-Site { Start-Process $url; return $true }

if ($Command -eq "watch") { Invoke-Watch; exit 0 }
if (-not $Command) { $Command = "start" }
$ok = Invoke-Action $Command
# 直接雙擊時視窗會自己關；失敗就停住，才看得到錯誤訊息。
if (-not $ok) {
  Read-Host "按 Enter 關閉"
  exit 1
}
if ($Command -ne "status") { Start-Sleep -Seconds 2 }
exit 0
