# Unregister the hourly HP printer scheduled task.
param(
    [string]$TaskName = "HP-Printer-Hourly-Print"
)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed scheduled task (if existed): $TaskName"
