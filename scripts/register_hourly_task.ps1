# Register an hourly Windows scheduled task for HP printer reports.
param(
    [string]$ProjectRoot = "G:\TOOL_PROJECT\hp_printer",
    [string]$PythonExe = "D:\anaconda\envs\mcp_printer\python.exe",
    [string]$TaskName = "HP-Printer-Hourly-Print"
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $ProjectRoot "scripts\hourly_print.py"
if (-not (Test-Path $scriptPath)) {
    throw "Script not found: $scriptPath"
}
if (-not (Test-Path $PythonExe)) {
    throw "Python not found: $PythonExe"
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$scriptPath`"" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Hourly print report via HP Smart Tank 750 MCP project" `
    -Force | Out-Null

Write-Host "Scheduled task registered: $TaskName"
Write-Host "Runs every 1 hour. Test now with:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
