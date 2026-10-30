# Instala grandMA3 onPC desde el ZIP oficial de MA Lighting.
#
# La descarga NO se puede automatizar: el WAF de malighting.com responde 403 a
# cualquier cliente que no sea un navegador con sesión. Descarga el ZIP desde
# https://www.malighting.com/downloads/products/grandma3/ (botón "grandMA3 onPC
# Software for Windows") y pásalo a este script.
#
# Uso:
#   .\tools\install_gma3_onpc.ps1 -ZipPath "$env:USERPROFILE\Downloads\grandMA3_onPC_win_v2.5.1.1.zip" -Extract
#   .\tools\install_gma3_onpc.ps1 -ZipPath ... -Run       # lanza el setup (GUI)
#
# -Extract sólo descomprime y te dice qué ejecutable hay que lanzar.
# -Run lanza el instalador; el asistente lo completas tú (requiere UAC).

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ZipPath,
    [string]$Destination = "$env:TEMP\gma3_onpc",
    [switch]$Extract,
    [switch]$Run
)

$ErrorActionPreference = 'Stop'

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

if (-not (Test-Path -LiteralPath $ZipPath)) {
    throw "No existe el ZIP: $ZipPath. Descárgalo de https://www.malighting.com/downloads/products/grandma3/"
}

$zip = Get-Item -LiteralPath $ZipPath
$sizeMb = [math]::Round($zip.Length / 1MB, 1)
Write-Step "ZIP: $($zip.FullName) ($sizeMb MB)"

if ($sizeMb -lt 100) {
    throw "El ZIP pesa $sizeMb MB; el paquete oficial de onPC ronda 450 MB. Descarga incompleta."
}

# Firma ZIP: los cuatro primeros bytes deben ser PK\x03\x04.
$stream = [System.IO.File]::OpenRead($zip.FullName)
try {
    $header = New-Object byte[] 4
    $null = $stream.Read($header, 0, 4)
} finally {
    $stream.Dispose()
}
if (-not ($header[0] -eq 0x50 -and $header[1] -eq 0x4B -and $header[2] -eq 0x03 -and $header[3] -eq 0x04)) {
    throw "El archivo no es un ZIP válido (¿descarga a medias o página de error guardada como .zip?)."
}
Write-Step "Firma ZIP correcta."

if (-not ($Extract -or $Run)) {
    Write-Host "Nada que hacer: añade -Extract (o -Run para lanzar el instalador)." -ForegroundColor Yellow
    exit 0
}

if (Test-Path -LiteralPath $Destination) {
    Write-Step "Limpiando extracción previa: $Destination"
    Remove-Item -LiteralPath $Destination -Recurse -Force
}
New-Item -ItemType Directory -Path $Destination -Force | Out-Null

Write-Step "Descomprimiendo en $Destination (puede tardar varios minutos)..."
Expand-Archive -LiteralPath $zip.FullName -DestinationPath $Destination -Force

# El paquete suele traer un setup dentro de una carpeta con la versión.
$setup = Get-ChildItem -LiteralPath $Destination -Recurse -File -Include 'setup.exe', 'grandMA3*.exe', '*.msi' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notmatch 'uninst' } |
    Sort-Object { $_.Name -match 'setup' } -Descending |
    Select-Object -First 1

if (-not $setup) {
    Write-Host "Extraído, pero no encuentro setup.exe ni .msi." -ForegroundColor Yellow
    Write-Host "Revisa el contenido: $Destination"
    Get-ChildItem -LiteralPath $Destination -Recurse -File -Filter *.exe | Select-Object -First 10 FullName
    exit 2
}

Write-Step "Instalador localizado: $($setup.FullName)"

if (-not $Run) {
    Write-Host ""
    Write-Host "Siguiente paso (tú):" -ForegroundColor Green
    Write-Host "  & '$($setup.FullName)'"
    Write-Host "  o bien: .\tools\install_gma3_onpc.ps1 -ZipPath '$($zip.FullName)' -Run"
    exit 0
}

Write-Step "Lanzando el instalador (UAC y asistente: intervención humana)..."
Start-Process -FilePath $setup.FullName -Wait

# Post-comprobación: ¿apareció el ejecutable?
$candidates = @(
    'C:\Program Files\MA Lighting Technologies',
    'C:\Program Files (x86)\MA Lighting Technologies'
) | Where-Object { Test-Path $_ }

$exe = Get-ChildItem -Path $candidates -Recurse -Filter 'gma3onpc*.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($exe) {
    Write-Host ""
    Write-Host "Instalado: $($exe.FullName)" -ForegroundColor Green
    Write-Host "Regenera el inventario: python bridge.py audit"
} else {
    Write-Host ""
    Write-Host "El instalador terminó pero no encuentro gma3onpc*.exe. Revisa la instalación." -ForegroundColor Yellow
}
