# Register the StockHub schedule in Windows Task Scheduler (current user, no admin needed):
#   StockHub markets weekdays 07:30  make etl-markets (international closes, US rates, NDC
#                                                     indicators, macro alerts)
#   StockHub quotes  weekdays 08:55  make etl-quotes  (polls until 13:35; skips market holidays)
#   StockHub daily   weekdays 18:00  make etl-daily   (calendar, master, events, prices, factors,
#                                                     fundamentals, chips)
#   StockHub chips   weekdays 21:30  make etl-chips   (margin tables are published in the evening)
#   StockHub news    every day 06:55 make etl-news    (news, announcements, forum posts and
#                                                     LLM summaries every minute until 23:00)
#   StockHub cluster Saturday 10:00  make db-cluster  (per-stock tables in stock order; a run that
#                                                     starts on a weekday daytime skips itself)
#   StockHub database  at logon       scripts/local-pg.sh start (no time limit; the other tasks
#                                     start it through this one so it never belongs to them)
# Runs only while the user is logged on; a run missed while the PC was off starts when it
# is next available. Logs: .local/logs/<target>-YYYYMMDD.log. Re-running replaces the tasks.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\register-tasks.ps1 [-Remove]
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bash = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path $bash)) { throw "Git Bash not found at $bash" }
$folder = "\StockHub\"

$tasks = @(
  @{ Name = "StockHub markets"; Target = "etl-markets"; At = "07:30"; Limit = (New-TimeSpan -Hours 1) },
  @{ Name = "StockHub quotes"; Target = "etl-quotes"; At = "08:55"; Limit = (New-TimeSpan -Hours 6) },
  @{ Name = "StockHub daily"; Target = "etl-daily"; At = "18:00"; Limit = (New-TimeSpan -Hours 3) },
  @{ Name = "StockHub chips"; Target = "etl-chips"; At = "21:30"; Limit = (New-TimeSpan -Hours 1) },
  @{ Name = "StockHub news"; Target = "etl-news"; At = "06:55"; Limit = (New-TimeSpan -Hours 17);
     Days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") },
  @{ Name = "StockHub cluster"; Target = "db-cluster"; At = "10:00"; Limit = (New-TimeSpan -Hours 2); Days = @("Saturday") }
)
$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

$dbTask = "StockHub database"
Unregister-ScheduledTask -TaskPath $folder -TaskName $dbTask -Confirm:$false -ErrorAction SilentlyContinue
if ($Remove) {
  Write-Host "removed $dbTask"
} elseif (Test-Path (Join-Path $root ".local\pgdata")) {
  $pgScript = ($root -replace '\\', '/') + "/scripts/local-pg.sh"
  $action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless `"$bash`" -l `"$pgScript`" start" -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  # Zero time limit = run indefinitely: postgres stays in this task's process tree.
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskPath $folder -TaskName $dbTask -Action $action -Trigger $trigger `
    -Settings $settings -Description "StockHub: private Postgres cluster on port 5433" | Out-Null
  Write-Host "registered ${dbTask}: at logon -> scripts/local-pg.sh start"
}

foreach ($t in $tasks) {
  Unregister-ScheduledTask -TaskPath $folder -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
  if ($Remove) { Write-Host "removed $($t.Name)"; continue }
  $script = ($root -replace '\\', '/') + "/scripts/scheduled.sh"
  # conhost --headless keeps the console window from popping up.
  $action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless `"$bash`" -l `"$script`" $($t.Target)" -WorkingDirectory $root
  $days = if ($t.Days) { $t.Days } else { $weekdays }
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $t.At
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit $t.Limit `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskPath $folder -TaskName $t.Name -Action $action -Trigger $trigger `
    -Settings $settings -Description "StockHub: make $($t.Target) (scripts/scheduled.sh)" | Out-Null
  $when = if ($t.Days) { $t.Days -join "," } else { "weekdays" }
  Write-Host "registered $($t.Name): $when $($t.At) -> make $($t.Target)"
}
