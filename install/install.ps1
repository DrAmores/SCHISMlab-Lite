# ---------------------------------------------------------------------------
# SCHISMlab: instalador para Windows 10/11.
# Instala WSL2 con Ubuntu si no estan, y dentro ejecuta install/install.sh.
# Ejecutar en PowerShell como administrador:
#   Set-ExecutionPolicy -Scope Process Bypass; .\install\install.ps1
# ---------------------------------------------------------------------------
param([string]$Variant = "hydro", [string]$Distro = "Ubuntu-24.04")
$ErrorActionPreference = "Stop"
$RepoWin = (Resolve-Path "$PSScriptRoot\..").Path

function Test-Admin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

# 1. WSL2 ----------------------------------------------------------------------
$wslOk = $false
try { wsl.exe --status *> $null; $wslOk = ($LASTEXITCODE -eq 0) } catch {}
if (-not $wslOk) {
    if (-not (Test-Admin)) { throw "Falta WSL2: vuelve a ejecutar este script como administrador para instalarlo." }
    Write-Host ">> Instalando WSL2 + $Distro (puede pedir reiniciar; tras reiniciar, ejecuta este script de nuevo)"
    wsl.exe --install -d $Distro
    Write-Host ">> Reinicia el ordenador y vuelve a ejecutar install.ps1"; exit 0
}
$distros = (wsl.exe -l -q) -replace "`0", "" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if ($distros -notcontains $Distro) {
    Write-Host ">> Instalando la distribucion $Distro (se te pedira crear un usuario de Linux)"
    wsl.exe --install -d $Distro
}

# 2. El repositorio se clona dentro de Linux (compilar en /mnt/c es lento y fragil; un clon se puede actualizar) -----------
$RepoWsl = "~/schismlab"
$RepoWinWsl = (wsl.exe -d $Distro wslpath -a ($RepoWin -replace "\\", "/")).Trim()
$RemoteUrl = (git -C $RepoWin remote get-url origin 2>$null)
if (-not $RemoteUrl) { $RemoteUrl = "https://github.com/DrAmores/SCHISMlab-Lite.git" }
Write-Host ">> Clonando SCHISMlab ($RemoteUrl) en $RepoWsl dentro de $Distro (si pide usuario y contrasena de GitHub, usa un token)"
$cloned = $false
try {
    wsl.exe -d $Distro -- bash -lc "command -v git >/dev/null || (sudo apt-get update -qq && sudo apt-get install -y -qq git); test -d $RepoWsl/.git || git clone '$RemoteUrl' $RepoWsl"
    $cloned = ($LASTEXITCODE -eq 0)
} catch {}
if (-not $cloned) {
    Write-Host ">> No se ha podido clonar (sin acceso al repositorio privado): se copia la carpeta de Windows (esta copia no podra actualizarse sola)"
    wsl.exe -d $Distro -- bash -lc "mkdir -p $RepoWsl && rsync -a --exclude .pixi '$RepoWinWsl/' $RepoWsl/ 2>/dev/null || cp -r '$RepoWinWsl/.' $RepoWsl/"
}

# 3. Instalador de Linux dentro de WSL --------------------------------------------------
wsl.exe -d $Distro -- bash -lc "cd $RepoWsl && bash install/install.sh $Variant"
Write-Host "== SCHISMlab instalado en WSL ($Distro). Abre 'wsl -d $Distro' y usa ~/schismlab"
