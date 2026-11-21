<#
.SYNOPSIS
  Starts the whole live demo with one command (Windows PowerShell).

.DESCRIPTION
  Runs `python -m scripts.demo` with the project's own virtual environment, so nothing has to be
  activated first. The demo starts at the fast pace (3600x: one simulated hour per second). Inside the
  dashboard, Senaryo Kontrol > Filo has two buttons that switch the pace while the demo runs:
  "Hizli (3600x)" and "Gercekci (60x: one new reading per station per minute)".

.EXAMPLE
  .\demo.ps1                 # fast demo; switch to realistic in the dashboard (Filo)
  .\demo.ps1 -Realistic      # start at the realistic pace
  .\demo.ps1 -Offline        # recorded run, no broker (backup if the live demo fails)
  .\demo.ps1 -StopOld        # close a demo that is still running from before, then start
  .\demo.ps1 -Smoke          # 10 second end-to-end self test

  If PowerShell refuses to run scripts:
  powershell -ExecutionPolicy Bypass -File .\demo.ps1
#>
param(
    [switch]$Realistic,
    [double]$Speedup = 0,
    [switch]$Offline,
    [switch]$Smoke,
    [switch]$StopOld,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Sanal ortam yok: $py" -ForegroundColor Red
    Write-Host "Kurulum: python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -e .[all]"
    exit 1
}

# a demo that is still running from before keeps the database locked
$old = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.ExecutablePath -like "$root*" -and $_.CommandLine -match "scripts\.demo|airq\.(devices|edge|server)|streamlit|uvicorn" })
if ($old.Count -gt 0 -and -not $Offline -and -not $Smoke) {
    if ($StopOld) {
        Write-Host "Onceki demo kapatiliyor ($($old.Count) surec) ..."
        $old | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
    } else {
        Write-Host "Onceki demo hala calisiyor ($($old.Count) surec). Once Ctrl+C ile kapat ya da: .\demo.ps1 -StopOld" -ForegroundColor Yellow
        exit 1
    }
}

$demoArgs = @()
if ($Smoke) { $demoArgs += "--smoke" }
if ($Offline) { $demoArgs += "--offline" }
if ($Realistic) { $demoArgs += "--realistic" }
if ($Speedup -gt 0) { $demoArgs += @("--speedup", $Speedup) }
if ($NoBrowser) { $demoArgs += "--no-browser" }

Write-Host "Demo basliyor. Pano: http://127.0.0.1:8501  (Ctrl+C her seyi kapatir)" -ForegroundColor Cyan
Write-Host "Hiz: panoda Senaryo Kontrol > Filo > 'Hizli (3600x)' / 'Gercekci (60x)'" -ForegroundColor Cyan
& $py -m scripts.demo @demoArgs
exit $LASTEXITCODE
