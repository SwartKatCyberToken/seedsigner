<#
.SYNOPSIS
Builds the production SeedSigner OS image for a Pi Zero 1.3 / Zero W (pi0).

.DESCRIPTION
SeedSigner OS (../seedsigner-os, with the USB keyboard and message crypto
changes) plus this repository's SeedSigner code (../seedsigner) and the ML-DSA /
ML-KEM libraries (../third_party). Everything is compiled in Docker; the Pi
compiles nothing.

The build runs on a Docker volume, not on the Windows drive: Buildroot needs a
case-sensitive Linux filesystem with symlinks. Downloads and the compiler cache
are kept between runs, so later builds are faster.

Writes pi-prod-setup\output\seedsigner_os.encryptor.pi0.img and its .sha256,
plus build.log.

.PARAMETER Fast
Keep the previous Buildroot output and rebuild only what changed: app code, the
rootfs overlay, and the kernel if kernel.config.fragment gained an option. Leave
it off after changing packages or other seedsigner-os configs.

.PARAMETER PreloadedKeys
Repository-relative INI file to ship as the contact list, for example
seedsigner\preloaded-public-keys.ini (the public test-seed keys). Default: none.

.PARAMETER Reset
Delete the build volume first (downloads and the compiler cache are kept).

.EXAMPLE
powershell -ExecutionPolicy Bypass -File pi-prod-setup\build-prod-image.ps1
#>
param(
    [switch]$Fast,
    [string]$PreloadedKeys = "",
    [switch]$Reset
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $PSScriptRoot "output"
$WorkVolume = "seedsigner-prod-work"
$CacheVolume = "seedsigner-prod-ccache"

function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($args[0]) failed (exit code $LASTEXITCODE)."
    }
}

function Invoke-DockerQuiet {
    # Windows PowerShell turns redirected stderr into errors, which "Stop"
    # would make fatal. Only the exit code matters here.
    $ErrorActionPreference = "Continue"
    & docker @args *> $null
    return $LASTEXITCODE
}

if ((Invoke-DockerQuiet info) -ne 0) {
    throw "Docker is not running. Start Docker Desktop and try again."
}

foreach ($Dir in @("seedsigner-os", "seedsigner", "third_party\dilithium-py", "third_party\kyber-py")) {
    if (-not (Test-Path (Join-Path $Root $Dir))) {
        throw "Missing $Dir in $Root."
    }
}

$KeysArg = ""
if ($PreloadedKeys) {
    $KeysPath = Join-Path $Root $PreloadedKeys
    if (-not (Test-Path $KeysPath -PathType Leaf)) {
        throw "PreloadedKeys file not found: $KeysPath"
    }
    # Relative to /src inside the container, with forward slashes.
    $KeysArg = $PreloadedKeys -replace '\\', '/'
}

if ($Reset) {
    Write-Host "Deleting the $WorkVolume volume"
    Invoke-DockerQuiet volume rm $WorkVolume | Out-Null
}

New-Item -ItemType Directory -Force $Out | Out-Null

Write-Host "==> Building the builder images"
Invoke-Docker build -t seedsigner-os-builder (Join-Path $Root "seedsigner-os")
Invoke-Docker build -t seedsigner-prod-builder $PSScriptRoot

Write-Host "==> Building the image (the first build takes 1-3 hours)"
$Started = Get-Date
$FastValue = "0"
if ($Fast) { $FastValue = "1" }
Invoke-Docker run --rm --name seedsigner-prod-build `
    -v "${Root}:/src:ro" `
    -v "${WorkVolume}:/work" `
    -v "${CacheVolume}:/root/.buildroot-ccache" `
    -v "${Out}:/out" `
    -e "FAST=$FastValue" `
    -e "PRELOADED_KEYS=$KeysArg" `
    seedsigner-prod-builder /src/pi-prod-setup/build-in-container.sh

$Minutes = [int]((Get-Date) - $Started).TotalMinutes
Write-Host ""
Write-Host "Finished in $Minutes minutes."
Write-Host "Image: $(Join-Path $Out 'seedsigner_os.encryptor.pi0.img')"
Write-Host "Flash it with Raspberry Pi Imager (Use custom) or balenaEtcher."
