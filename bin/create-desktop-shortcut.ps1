<#
.SYNOPSIS
    Creates a Windows desktop shortcut for Hermes Pet.

.DESCRIPTION
    Creates a shortcut on the current user's desktop that launches HermesPet.exe.
    Does NOT enable autostart. The user must double-click the shortcut manually.

    Usage:
      powershell -ExecutionPolicy Bypass -File create-desktop-shortcut.ps1
#>

# Derive project root from script location ($PSScriptRoot = bin/)
$ProjectDir = Split-Path -Parent $PSScriptRoot
$ExePath = "$ProjectDir\src\wpf\HermesPet\bin\Release\net8.0-windows\win-x64\HermesPet.exe"
$IconPath = "$ExePath"  # Use the exe's own icon
$ShortcutName = "Hermes Pet.lnk"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = "$DesktopPath\$ShortcutName"

if (!(Test-Path $ExePath)) {
    Write-Host "Error: HermesPet.exe not found at:" -ForegroundColor Red
    Write-Host "  $ExePath" -ForegroundColor Red
    Write-Host "Build it first:" -ForegroundColor Yellow
    Write-Host "  cd $ProjectDir\src\wpf\HermesPet" -ForegroundColor Yellow
    Write-Host "  dotnet build -c Release" -ForegroundColor Yellow
    exit 1
}

$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.Arguments = "--port 5731"
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = "Hermes Pet — Hermes Agent desktop companion"
$Shortcut.IconLocation = "$IconPath, 0"
$Shortcut.Save()

if (Test-Path $ShortcutPath) {
    Write-Host "Shortcut created:" -ForegroundColor Green
    Write-Host "  $ShortcutPath" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "Double-click 'Hermes Pet' on your desktop to launch." -ForegroundColor Cyan
    Write-Host "This does NOT enable autostart. Manual launch only." -ForegroundColor Cyan
} else {
    Write-Host "Error: Failed to create shortcut." -ForegroundColor Red
    exit 1
}
