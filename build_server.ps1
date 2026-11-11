# Baut den FederPDF-Server (PyInstaller).
# Ortunabhängig: liegt im Projektordner, nutzt $PSScriptRoot.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$venv = Join-Path $root "venv\Scripts"

if (-not (Test-Path (Join-Path $root "venv\Scripts\python.exe"))) {
    Write-Host "venv fehlt - lege an (py -3.14):"
    py -3.14 -m venv (Join-Path $root "venv")
}

Write-Host "=== pyinstaller sicherstellen ==="
& "$venv\python.exe" -m pip install --quiet --disable-pip-version-check pyinstaller pymupdf fastapi "uvicorn[standard]" python-multipart pillow cryptography==46.0.3   # PIN: neuere haben keine win_arm64-Wheels (Notebook-ARM64-Build)
Write-Host "pip exit: $LASTEXITCODE"

$mp = & "$venv\python.exe" -c "import importlib.util; print('multipart' if importlib.util.find_spec('multipart') else ('python_multipart' if importlib.util.find_spec('python_multipart') else 'none'))"
Write-Host "multipart-Modul: $mp"

Set-Location (Join-Path $root "app")
$pargs = @("--noconfirm","--clean","--onedir","--name","FederPDFServer",
           "--icon",(Join-Path $root "wrapper\federpdf_icon.ico"),
           "--add-data","static;static",
           "--collect-all","pymupdf","--collect-all","uvicorn","--collect-all","fastapi",
           "--collect-all","cryptography")
if ($mp -eq "multipart") { $pargs += @("--collect-all","multipart") }
if ($mp -eq "python_multipart") { $pargs += @("--collect-all","python_multipart") }

Write-Host "=== PyInstaller-Build ==="
# python -m statt pyinstaller.exe-Shim: der Shim traegt eine absolute Python-
# Pfadangabe und bricht, wenn der Projektordner verschoben/umbenannt wurde.
& "$venv\python.exe" -m PyInstaller @pargs server.py 2>&1 | Select-Object -Last 5
Write-Host "pyinstaller exit: $LASTEXITCODE"

$dist = Join-Path $root "app\dist\FederPDFServer\FederPDFServer.exe"
if ($LASTEXITCODE -ne 0) {
    # HÄRTUNG (11.11.2026): PyInstaller kann beim COLLECT am RAUMEN des alten
    # dist scheitern (PermissionError, weil noch eine dist-EXE LAEUFT - z.B.
    # ein Suite-/Debug-Server) und ein HALBBUNDLE hinterlassen (fehlende
    # cryptography-Rust-PYD). Die EXE existiert trotzdem -> das alte
    # "Test-Path -> OK" meldete einen kaputten Build als gut. Exit != 0 ist
    # IMMER FEHLER, danach nichts weiter verkaufen.
    Write-Host "SERVER-EXE UNGUELTIG: PyInstaller-Exit $LASTEXITCODE (Halbbundle moeglich - laeuft noch eine EXE aus diesem dist?)"
    exit 1
}
if (Test-Path $dist) {
    $size = [math]::Round((Get-ChildItem (Split-Path $dist) -Recurse | Measure-Object Length -Sum).Sum/1MB,1)
    Write-Host "SERVER-EXE OK: $dist ($size MB)"
    # OCR-Sprachdaten mit ins Paket legen (Tesseract selbst steckt im PyMuPDF-Wheel)
    $tessquelle = Join-Path $root "tessdata"
    $tessziel = Join-Path (Split-Path $dist) "tessdata"
    if (Test-Path $tessquelle) {
        if (Test-Path $tessziel) { Remove-Item $tessziel -Recurse -Force }
        Copy-Item $tessquelle $tessziel -Recurse
        Write-Host ("TESSDATA OK: " + $tessziel + " (" + ((Get-ChildItem $tessziel).Name -join ", ") + ")")
    } else {
        Write-Host "TESSDATA FEHLT (OCR ohne Sprachdaten!): $tessquelle"
    }
} else {
    Write-Host "SERVER-EXE FEHLT!"
}
