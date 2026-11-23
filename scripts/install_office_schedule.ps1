$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'Local AI Job Application Office' -ErrorAction SilentlyContinue
if ($task) { Disable-ScheduledTask -TaskName 'Local AI Job Application Office' | Select-Object TaskName,State }
Write-Output 'Scheduled startup is disabled by user policy. Start the dashboard manually.'
