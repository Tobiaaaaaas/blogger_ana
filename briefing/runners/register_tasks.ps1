# Briefing scheduled-task registration (v15: two daily tasks, unified cadence).
# 2026-09-07 v15: BOTH boards push on the same cadence inside run_briefing.py;
#   trading day = 09:00..15:00 every 30 min + 16:00..22:00 every hour; non-trading
#   day = 09:00..21:00 every 3 hours (swing only). Day type / cadence / boards are
#   decided in code by wall clock (config.in_trading_grid / in_restday_grid /
#   due_boards), so the scheduler only needs to wake the process at every possible
#   fire moment on EVERY day (incl. weekends) and the code no-ops the rest.
# Two tasks cover all fire moments:
#   - BriefingDay:     Daily 09:00 + Repetition 30 min x 6h  -> 09:00..15:00 (:00/:30)
#   - BriefingEvening: Daily 16:00 + Repetition 1h   x 6h  -> 16:00..22:00 (:00)
#   Non-trading-day slots 09/12/15/18/21 fall inside those wake windows; code gates.
# We bypass briefing_runner.bat and call python.exe directly with --push.
# Settings: StartWhenAvailable, ExecutionTimeLimit 20 min (< 30-min grid so a run
#   never crosses into the next tick), MultipleInstances IgnoreNew, principal 24966
#   Interactive Limited.
# Keep this file ASCII-only (no Chinese) so Windows PowerShell 5.1 parses it
# cleanly regardless of console codepage.
#
# Usage (on the Windows host):
#   powershell -NoProfile -ExecutionPolicy Bypass -File <path>\register_tasks.ps1
$ErrorActionPreference = 'Stop'

$py = 'C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe'
$wd = 'C:\Users\24966\blogger_ana'

# Drop the v13 single task and the v9/v12 three-daily-task set so only the two
# v15 tasks remain.
$oldNames = @('BriefingIntraday', 'BriefingMorning', 'BriefingAfternoon', 'BriefingLate')
foreach ($n in $oldNames) {
    Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
}

function New-BriefingTask {
    param(
        [string]$Name,
        [string]$Start,      # 'HH:mm' (Daily)
        [int]$IntervalMin,   # repetition interval in minutes
        [int]$DurationHours  # repetition duration in hours
    )
    $action = New-ScheduledTaskAction -Execute $py `
        -Argument '-m briefing.scripts.run_briefing --push' `
        -WorkingDirectory $wd
    # New-ScheduledTaskTrigger -Daily has no repetition params; borrow the
    # Repetition pattern from an -Once trigger that declares them.
    $trigger = New-ScheduledTaskTrigger -Daily -At $Start
    $rep = (New-ScheduledTaskTrigger -Once -At $Start `
            -RepetitionInterval (New-TimeSpan -Minutes $IntervalMin) `
            -RepetitionDuration (New-TimeSpan -Hours $DurationHours)).Repetition
    $trigger.Repetition = $rep
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
        -MultipleInstances IgnoreNew -Compatibility Win7
    $principal = New-ScheduledTaskPrincipal -UserId '24966' `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output ('registered ' + $Name)
}

# Trading-day 30-min grid 09:00..15:00 (also wakes non-trading-day 09/12/15).
New-BriefingTask -Name 'BriefingDay' -Start '09:00' -IntervalMin 30 -DurationHours 6

# Trading-day hourly 16:00..22:00 (also wakes non-trading-day 18/21).
New-BriefingTask -Name 'BriefingEvening' -Start '16:00' -IntervalMin 60 -DurationHours 6

Write-Output '--- verify ---'
foreach ($tn in @('BriefingDay', 'BriefingEvening')) {
    $t = Get-ScheduledTask -TaskName $tn
    $rep = $t.Triggers[0].Repetition
    Write-Output ($tn + ' | ' + $t.State + ' | start=' + $t.Triggers[0].StartBoundary +
                 ' | repeatEvery=' + $rep.Interval + ' | duration=' + $rep.Duration +
                 ' | stopAtEnd=' + $rep.StopAtDurationEnd)
    $info = $t | Get-ScheduledTaskInfo
    Write-Output ('next=' + $info.NextRunTime + ' | last=' + $info.LastRunTime + ' | result=' + $info.LastTaskResult)
}
foreach ($n in $oldNames) {
    $left = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($left) { Write-Output ('LEFTOVER ' + $n) } else { Write-Output ('gone ' + $n) }
}
