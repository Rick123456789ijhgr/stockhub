# Register the StockHub schedule in Windows Task Scheduler (current user, no admin needed):
#   StockHub quotes  weekdays 08:55  make etl-quotes  (polls until 13:35; skips market holidays)
#   StockHub daily   weekdays 18:00  make etl-daily   (calendar, master, events, prices, factors)
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
  @{ Name = "StockHub quotes"; Target = "etl-quotes"; At = "08:55"; Limit = (New-TimeSpan -Hours 6) },
  @{ Name = "StockHub daily"; Target = "etl-daily"; At = "18:00"; Limit = (New-TimeSpan -Hours 3) }
)

foreach ($t in $tasks) {
  Unregister-ScheduledTask -TaskPath $folder -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
  if ($Remove) { Write-Host "removed $($t.Name)"; continue }
  $script = ($root -replace '\\', '/') + "/scripts/scheduled.sh"
  # conhost --headless keeps the console window from popping up.
  $action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless `"$bash`" -l `"$script`" $($t.Target)" -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $t.At
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit $t.Limit `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskPath $folder -TaskName $t.Name -Action $action -Trigger $trigger `
    -Settings $settings -Description "StockHub: make $($t.Target) (scripts/scheduled.sh)" | Out-Null
  Write-Host "registered $($t.Name): weekdays $($t.At) -> make $($t.Target)"
}
