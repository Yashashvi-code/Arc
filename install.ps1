# Windows installer script for Arc Ecosystem Link

$TargetDir = "D:\arc"

Write-Host "=========================================" -ForegroundColor Green
Write-Host "   ARC WINDOWS SYSTEM SETUP & INSTALL" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

# 1. Ensure python dependencies are installed in venv
Write-Host "[1/5] Restoring Python virtual environment dependencies..." -ForegroundColor Cyan
if (Test-Path "$TargetDir\.venv") {
    & "$TargetDir\.venv\Scripts\pip.exe" install -r "$TargetDir\daemon\requirements.txt" --quiet
} else {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv "$TargetDir\.venv"
    & "$TargetDir\.venv\Scripts\pip.exe" install --upgrade pip --quiet
    & "$TargetDir\.venv\Scripts\pip.exe" install -r "$TargetDir\daemon\requirements.txt" --quiet
}

# 2. Build Tauri Panel
Write-Host "[2/5] Compiling production Tauri Desktop Panel..." -ForegroundColor Cyan
Set-Location "$TargetDir\panel"
npm install --no-audit --no-fund
npm run tauri build

# 3. Copy compiled panel.exe to root folder for easy access
Write-Host "[3/5] Publishing panel executable..." -ForegroundColor Cyan
$BuiltExe = "$TargetDir\panel\src-tauri\target\release\panel.exe"
if (Test-Path $BuiltExe) {
    Copy-Item -Path $BuiltExe -Destination "$TargetDir\panel.exe" -Force
    Write-Host "Published panel.exe to root successfully!" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Could not locate compiled panel.exe. Development fallback will be used." -ForegroundColor Yellow
}

# 4. Create Start Menu Shortcut (No startup/boot shortcut)
Write-Host "[4/5] Creating Start Menu shortcut..." -ForegroundColor Cyan
$WshShell = New-Object -ComObject WScript.Shell

# Start Menu Shortcut
$StartMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Arc.lnk"
$Shortcut = $WshShell.CreateShortcut($StartMenuPath)
$Shortcut.TargetPath = "$TargetDir\.venv\Scripts\pythonw.exe"
$Shortcut.Arguments = """$TargetDir\arc_tray_win.py"""
$Shortcut.WorkingDirectory = $TargetDir
if (Test-Path "$TargetDir\panel.exe") {
    $Shortcut.IconLocation = "$TargetDir\panel.exe,0"
}
$Shortcut.Description = "Arc Local Ecosystem Link Bridge"
$Shortcut.Save()
Write-Host "Start Menu shortcut created at: $StartMenuPath" -ForegroundColor Green

# Remove any existing startup boot shortcut
$StartupPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Arc.lnk"
if (Test-Path $StartupPath) {
    Remove-Item -Path $StartupPath -Force
    Write-Host "Removed legacy boot shortcut from Startup folder." -ForegroundColor Yellow
}

# 5. Launch Arc Tray App
Write-Host "[5/5] Launching Arc in the background..." -ForegroundColor Cyan
Start-Process -FilePath "$TargetDir\.venv\Scripts\pythonw.exe" -ArgumentList """$TargetDir\arc_tray_win.py""" -WorkingDirectory $TargetDir

Write-Host "=========================================" -ForegroundColor Green
Write-Host "   INSTALL COMPLETED SUCCESSFULLY!       " -ForegroundColor Green
Write-Host "   Arc is now active in your System Tray!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
