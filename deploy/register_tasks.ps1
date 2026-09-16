# Production scheduled-task registration for the Windows host (2026-09-16).
#
# Registers FOUR tasks covering the two push stacks. Both stacks share the same
# two wake windows -- the cadence tables (config.json push.grid.trading /
# push.grid.restday) are shared, and each stack gates on the wall clock itself
# in code, so the scheduler only has to wake the process at every possible fire
# moment on EVERY day (incl. weekends); the code no-ops the rest.
#
#   - BriefingDay:     Daily 09:00 + Repetition 30 min x 6h -> 09:00..15:00
#   - BriefingEvening: Daily 16:00 + Repetition 1h   x 6h -> 16:00..22:00
#       OLD stack (repo root = old_push\). Non-trading-day slots 09/12/15/18/21
#       fall inside those windows. config.due_boards() returns swing only.
#   - PushDay:         same triggers as BriefingDay
#   - PushEvening:     same triggers as BriefingEvening
#       NEW stack (repo root = the repo root). Board pinned to swing inside
#       deploy\run_push.bat, which also loads the env and writes a log.
#
# The two stacks run CONCURRENTLY in the same slot, by design; they are fully
# separate systems with separate data trees, separate caches and separate
# Feishu groups (old -> the old-push group, new -> the swing group).
#
# Settings: StartWhenAvailable (missed wakes are caught up), MultipleInstances
#   IgnoreNew, principal 24966 Interactive Limited.
#   ExecutionTimeLimit 20 min for the OLD stack (unchanged, < the 30-min grid);
#   30 min for the NEW stack -- its per-slot crawl is serial (~29 bloggers),
#   measurably slower than the old stack's --workers 5.
#
# ALL FOUR TASKS ARE LEFT DISABLED. Enabling is a separate, explicit step:
#   Enable-ScheduledTask -TaskName PushDay
# Do not enable anything until the first manual real push has been verified.
#
# Keep this file ASCII-only (no Chinese) so Windows PowerShell 5.1 parses it
# cleanly regardless of console codepage.
#
# Usage (on the Windows host):
#   powershell -NoProfile -ExecutionPolicy Bypass -File <path>\register_tasks.ps1
$ErrorActionPreference = 'Stop'

$py      = 'C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe'
$root    = 'C:\Users\24966\blogger_ana'
$oldRoot = 'C:\Users\24966\blogger_ana\old_push'
$bat     = 'C:\Users\24966\blogger_ana\deploy\run_push.bat'

# Drop the v13/v9 task names if this box still carries them.
$stale = @('BriefingIntraday', 'BriefingMorning', 'BriefingAfternoon', 'BriefingLate')
foreach ($n in $stale) {
    Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
}

function New-PushTask {
    param(
        [string]$Name,
        [string]$Start,       # 'HH:mm' (Daily)
        [int]$IntervalMin,    # repetition interval in minutes
        [int]$DurationHours,  # repetition duration in hours
        [string]$Exe,
        # NOT $Args -- that name is a PowerShell automatic variable and silently
        # wins over the parameter, leaving -Argument null.
        [string]$ArgLine,
        [string]$WorkingDir,
        [int]$LimitMin
    )
    $action = New-ScheduledTaskAction -Execute $Exe -Argument $ArgLine -WorkingDirectory $WorkingDir
    # New-ScheduledTaskTrigger -Daily has no repetition params; borrow the
    # Repetition pattern from an -Once trigger that declares them.
    $trigger = New-ScheduledTaskTrigger -Daily -At $Start
    $rep = (New-ScheduledTaskTrigger -Once -At $Start `
            -RepetitionInterval (New-TimeSpan -Minutes $IntervalMin) `
            -RepetitionDuration (New-TimeSpan -Hours $DurationHours)).Repetition
    $trigger.Repetition = $rep
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMin) `
        -MultipleInstances IgnoreNew -Compatibility Win7
    $principal = New-ScheduledTaskPrincipal -UserId '24966' `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    # A fresh registration is ENABLED; force it back to Disabled so nothing
    # starts firing before the first real push has been checked by hand.
    Disable-ScheduledTask -TaskName $Name | Out-Null
    Write-Output ('registered (disabled) ' + $Name)
}

# OLD stack: repo root = old_push\, python called directly (no wrapper).
New-PushTask -Name 'BriefingDay' -Start '09:00' -IntervalMin 30 -DurationHours 6 `
    -Exe $py -ArgLine '-m briefing.scripts.run_briefing --push' `
    -WorkingDir $oldRoot -LimitMin 20
New-PushTask -Name 'BriefingEvening' -Start '16:00' -IntervalMin 60 -DurationHours 6 `
    -Exe $py -ArgLine '-m briefing.scripts.run_briefing --push' `
    -WorkingDir $oldRoot -LimitMin 20

# NEW stack: repo root = the repo root, board pinned to swing inside the wrapper.
New-PushTask -Name 'PushDay' -Start '09:00' -IntervalMin 30 -DurationHours 6 `
    -Exe 'cmd.exe' -ArgLine ('/c "' + $bat + '"') `
    -WorkingDir $root -LimitMin 30
New-PushTask -Name 'PushEvening' -Start '16:00' -IntervalMin 60 -DurationHours 6 `
    -Exe 'cmd.exe' -ArgLine ('/c "' + $bat + '"') `
    -WorkingDir $root -LimitMin 30

Write-Output '--- verify ---'
foreach ($tn in @('BriefingDay', 'BriefingEvening', 'PushDay', 'PushEvening')) {
    $t = Get-ScheduledTask -TaskName $tn
    $rep = $t.Triggers[0].Repetition
    Write-Output ($tn + ' | ' + $t.State + ' | ' + $t.Actions[0].Execute + ' ' +
                 $t.Actions[0].Arguments + ' | wd=' + $t.Actions[0].WorkingDirectory)
    Write-Output ('    start=' + $t.Triggers[0].StartBoundary + ' repeatEvery=' + $rep.Interval +
                 ' duration=' + $rep.Duration + ' limit=' + $t.Settings.ExecutionTimeLimit +
                 ' startWhen=' + $t.Settings.StartWhenAvailable)
}
foreach ($n in $stale) {
    $left = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($left) { Write-Output ('LEFTOVER ' + $n) } else { Write-Output ('gone ' + $n) }
}
Write-Output 'All four are DISABLED. Enable explicitly after the first real push checks out.'
