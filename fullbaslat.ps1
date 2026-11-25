<#
.SYNOPSIS
  Full start: does everything needed and opens the live demo (Windows PowerShell).

.DESCRIPTION
  One command, nothing to prepare first:
    1. creates the virtual environment and installs the project if they are missing,
    2. closes a demo that is still running (and the broker it started), frees ports 8000/8501,
    3. downloads the raw data and the trained models if they are missing,
    4. starts the whole demo from scratch and opens the dashboard in the browser.
  Ctrl+C in this window closes everything.

  Right-click the file > "Run with PowerShell" (or double-click fullbaslat.cmd): nothing else to do.

.EXAMPLE
  .\fullbaslat.cmd               # normal start (fast pace; switch to realistic in the dashboard)
  .\fullbaslat.cmd -Realistic    # start at the realistic pace (60x)
  .\fullbaslat.cmd -NoBrowser    # do not open the browser

  Without the .cmd wrapper: powershell -ExecutionPolicy Bypass -File .\fullbaslat.ps1
#>
param(
    [switch]$Realistic,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

try { $Host.UI.RawUI.WindowTitle = "airq-iot demo (kapatmak icin Ctrl+C)" } catch { }

# Started with "Run with PowerShell" the window closes when the script ends: keep it open so a
# message can be read. Not when the input is redirected (another program runs the script).
function Wait-Key {
    if ($Host.Name -eq "ConsoleHost" -and -not [Console]::IsInputRedirected) {
        Write-Host ""
        Read-Host "Kapatmak icin Enter'a bas" | Out-Null
    }
}
trap {
    Write-Host ""
    Write-Host "HATA: $_" -ForegroundColor Red
    Wait-Key
    exit 1
}

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "HATA: $text" -ForegroundColor Red; Wait-Key; exit 1 }

# ---------------------------------------------------------------- 1. environment
Step "1/4 Ortam kontrolu"
if (-not (Test-Path $py)) {
    Write-Host "Sanal ortam yok, olusturuluyor (ilk seferde birkac dakika surer) ..."
    $sys = $null
    foreach ($cand in @("py", "python")) {
        if (Get-Command $cand -ErrorAction SilentlyContinue) { $sys = $cand; break }
    }
    if (-not $sys) { Fail "Python bulunamadi. https://www.python.org adresinden Python 3.11+ kur." }
    if ($sys -eq "py") { & py -3 -m venv .venv } else { & python -m venv .venv }
    if (-not (Test-Path $py)) { Fail "Sanal ortam olusturulamadi." }
}
& $py -c "import airq, streamlit, paho.mqtt, lightgbm, fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Paketler kuruluyor (pip install -e .[all]) ..."
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -e ".[all]"
    if ($LASTEXITCODE -ne 0) { Fail "Paket kurulumu basarisiz oldu." }
}
Write-Host "Ortam hazir."

# ---------------------------------------------------------------- 2. close an old demo
Step "2/4 Acik demo varsa kapatiliyor"
function Get-DemoProcesses {
    $procs = @()
    $procs += Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.ExecutablePath -like "$root*" -and $_.CommandLine -match "scripts\.demo|airq\.|streamlit|uvicorn" }
    # the broker the demo started (Mosquitto with a temp config, or the python fallback broker)
    $procs += Get-CimInstance Win32_Process -Filter "Name='mosquitto.exe'" |
        Where-Object { $_.CommandLine -match "airq-mosq" }
    return @($procs)
}
$old = Get-DemoProcesses
if ($old.Count -gt 0) {
    Write-Host "$($old.Count) eski surec kapatiliyor ..."
    # a process may already be gone when its parent is stopped: that is fine
    foreach ($round in 1..3) {
        foreach ($p in (Get-DemoProcesses)) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
        if ((Get-DemoProcesses).Count -eq 0) { break }
    }
} else {
    Write-Host "Acik demo yok."
}
foreach ($port in 8000, 8501) {
    for ($i = 0; $i -lt 10; $i++) {
        $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if (-not $busy) { break }
        Start-Sleep -Seconds 1
    }
    if ($busy) {
        $owner = (Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Fail "Port $port baska bir program tarafindan kullaniliyor ($owner). Onu kapat ve tekrar dene."
    }
}
Write-Host "Portlar bos."

# ---------------------------------------------------------------- 3. data and models
Step "3/4 Veri ve model kontrolu"
# single quotes inside the python code: Windows PowerShell 5.1 strips double quotes from native arguments
$check = "from airq.config import load_config; from airq.pipelines.demo import missing_inputs; m = missing_inputs(load_config(), models=True); print(int(any('veri' in x for x in m)), int(any('model' in x for x in m)))"
$flags = @((& $py -c $check) -split "\s+")
$needData = ($flags[0] -eq "1")
$needModels = ($flags[1] -eq "1")
if ($needData) {
    Write-Host "Ham veri indiriliyor ..."
    & $py -m scripts.download_data
    if ($LASTEXITCODE -ne 0) { Fail "Ham veri indirilemedi (internet baglantisini kontrol et)." }
}
if ($needModels) {
    Write-Host "Egitilmis modeller indiriliyor ..."
    & $py -m scripts.fetch_release --only models
    if ($LASTEXITCODE -ne 0) { Fail "Modeller indirilemedi (internet baglantisini kontrol et)." }
}
if (-not $needData -and -not $needModels) { Write-Host "Veri ve modeller hazir." }

# ---------------------------------------------------------------- 4. start
Step "4/4 Demo basliyor"
$demoArgs = @()
if ($Realistic) { $demoArgs += "--realistic" }
if ($NoBrowser) { $demoArgs += "--no-browser" }
Write-Host "Pano: http://127.0.0.1:8501" -ForegroundColor Green
Write-Host "Ilk yaklasik 1 dakika tahmin modeli isiniyor; kartlarda 'isiniyor' yazar, sonra tahminler gelir." -ForegroundColor Green
Write-Host "Hiz: panoda Senaryo Kontrol > Hiz ve duraklatma. Kapatmak icin Ctrl+C." -ForegroundColor Green
try {
    & $py -m scripts.demo @demoArgs
} finally {
    # whatever is left of this run (a killed window leaves children behind)
    foreach ($p in (Get-DemoProcesses)) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
}
Write-Host ""
Write-Host "Demo kapandi."
Wait-Key
exit $LASTEXITCODE
