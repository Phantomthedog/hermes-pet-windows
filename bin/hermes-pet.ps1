<#
.SYNOPSIS
    Hermes Pet — Windows launcher for the WSL-based Hermes Pet overlay.

.DESCRIPTION
    Runs the hermes-pet WSL wrapper from Windows.
    Supports all same commands as the WSL bin/hermes-pet script.

.PARAMETER Command
    The command to run. Default: status.
    Common: start-all, stop-all, restart-all, status, doctor, test-event

.EXAMPLE
    .\hermes-pet.ps1 status
    .\hermes-pet.ps1 start-all
    .\hermes-pet.ps1 stop-all
    .\hermes-pet.ps1 test-event thinking
    .\hermes-pet.ps1 doctor
#>

param(
    [string]$Command = "status",
    [string]$Arg = ""
)

# Derive project root from script location ($PSScriptRoot = bin/)
$ProjectDir = Split-Path -Parent $PSScriptRoot
$Script = "$ProjectDir/bin/hermes-pet"

# Convert Windows path to WSL path: C:\foo\bar → /mnt/c/foo/bar
$drive = $ProjectDir.Substring(0, 1).ToLower()
$wslPath = $ProjectDir.Substring(2) -replace '\\', '/'
$WslProjectDir = "/mnt/$drive$wslPath"
$WslScript = "$WslProjectDir/bin/hermes-pet"

# Run via WSL (cd to project dir first to avoid bashrc TUI hooks)
if ($Arg -and $Arg -ne "") {
    $cmd = "cd $WslProjectDir && bash $WslScript $Command $Arg"
} else {
    $cmd = "cd $WslProjectDir && bash $WslScript $Command"
}

Write-Host "Hermes Pet — running: $Command" -ForegroundColor Cyan
wsl bash -c $cmd
