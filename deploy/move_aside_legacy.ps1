# One-time migration: clear the Windows repo root before the first sync.
#
# The host still carries the pre-rebuild layout (root-level briefing/ opinion/
# knowledge/ scripts/ data/ reports/ docs/ archive/ .git plus a pile of loose
# debug scripts). The new layout puts the NEW stack at the root and the OLD
# stack under old_push\ -- and tar only overwrites, it never deletes. Without
# this step the two layouts end up mixed together.
#
# This MOVES, never deletes: everything lands in _superseded_20260916\ and can
# be moved back. Check it, then delete the folder yourself.
#
# Keep this file ASCII-only. See deploy\DEPLOY.md.
#
# Usage (on the Windows host):
#   powershell -NoProfile -ExecutionPolicy Bypass -File <path>\move_aside_legacy.ps1
$ErrorActionPreference = 'Stop'

$root = 'C:\Users\24966\blogger_ana'
$dst  = Join-Path $root '_superseded_20260916'
if (-not (Test-Path $dst)) { New-Item -ItemType Directory -Path $dst | Out-Null }

$moved = 0
Get-ChildItem -LiteralPath $root -Force | ForEach-Object {
    if ($_.Name -eq '_superseded_20260916') { return }
    Move-Item -LiteralPath $_.FullName -Destination $dst -Force
    $moved++
    Write-Output ('moved ' + $_.Name)
}
Write-Output ('--- moved ' + $moved + ' entries ---')
Write-Output '--- root now ---'
Get-ChildItem -LiteralPath $root -Force | ForEach-Object { Write-Output $_.Name }
