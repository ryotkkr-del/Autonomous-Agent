# Optional: run once manually in PowerShell to enable auto-resume while logged in.
param([int]$Minutes = 30)
if ($Minutes -lt 10) { throw 'Minutes must be >= 10' }
$Python = (Get-Command python -ErrorAction Stop).Source
$WorkingDirectory = $PSScriptRoot
$TaskName = 'AutonomousAgentV06-LocalTick'
$Cmd = '"' + $Python + '" "' + (Join-Path $WorkingDirectory 'agent.py') + '" tick --steps 8'
$Action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ' + $Cmd) -WorkingDirectory $WorkingDirectory
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Minutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Resume a local autonomous-agent job in bounded steps.' -Force | Out-Null
Write-Host "Created $TaskName. Remove via: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
