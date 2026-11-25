# Download everything the Pi Zero 1.3 test card needs, on a Windows PC.
#
#   powershell -ExecutionPolicy Bypass -File pi-setup\download-for-pi.ps1
#
# Writes into pi-setup\downloads\:
#   - Raspberry Pi OS Buster Lite 2023-05-03 (.img.xz), SHA256-checked
#   - Python 3.10.10 source, the BCM2835 C library, and libzbar0
#     (pi-setup.sh uses these instead of downloading them again on the Pi)
#   - seedsigner-encryptor.tar.gz: this repository, ready to copy to the Pi
#
# Re-running skips files that are already complete. apt and pip packages are
# still fetched by the Pi itself, so the Pi needs internet once (see the guide).

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $PSScriptRoot "downloads"
New-Item -ItemType Directory -Force $Out | Out-Null

$ImageName = "2023-05-03-raspios-buster-armhf-lite.img.xz"
$ImageUrl = "https://downloads.raspberrypi.org/raspios_oldstable_lite_armhf/images/raspios_oldstable_lite_armhf-2023-05-03/$ImageName"
# Published SHA256, also recorded in seedsigner/docs/raspberry_pi_os_build_instructions.md.
$ImageSha256 = "3d210e61b057de4de90eadb46e28837585a9b24247c221998f5bead04f88624c"

$Files = @(
    @{ Name = $ImageName; Url = $ImageUrl },
    @{ Name = "Python-3.10.10.tgz"; Url = "https://www.python.org/ftp/python/3.10.10/Python-3.10.10.tgz" },
    @{ Name = "bcm2835-1.60.tar.gz"; Url = "http://www.airspayce.com/mikem/bcm2835/bcm2835-1.60.tar.gz" },
    # The upstream guide's libzbar0_0.23.90-1+deb11u1 link is gone; this is the rebuilt package.
    @{ Name = "libzbar0_0.23.90-1+deb11u1+b1_armhf.deb"; Url = "http://raspbian.raspberrypi.org/raspbian/pool/main/z/zbar/libzbar0_0.23.90-1%2Bdeb11u1%2Bb1_armhf.deb" }
)

function Get-File($Name, $Url) {
    $Path = Join-Path $Out $Name
    if (Test-Path $Path) {
        Write-Host "-> $Name (already downloaded)"
        return
    }
    Write-Host "-> $Name"
    # curl.exe ships with Windows 10 and 11. The .part file lets a rerun resume.
    $Part = "$Path.part"
    & curl.exe --fail --location --retry 3 --continue-at - --output $Part $Url
    if ($LASTEXITCODE -ne 0) {
        throw "download failed ($LASTEXITCODE): $Url"
    }
    Move-Item -Force $Part $Path
}

foreach ($File in $Files) {
    Get-File $File.Name $File.Url
}

$ImagePath = Join-Path $Out $ImageName
$Actual = (Get-FileHash -Algorithm SHA256 $ImagePath).Hash.ToLower()
if ($Actual -ne $ImageSha256) {
    Remove-Item $ImagePath
    throw "image SHA256 mismatch: got $Actual, expected $ImageSha256. The file was deleted; run again."
}
Write-Host "image SHA256 OK"

# Bundle the repo. third_party\pycryptodome is a reference checkout only;
# pip installs pycryptodome on the Pi, so it is left out. Enclosure models,
# doc images, and the PQ libraries' test-vector assets are not needed to run.
$Bundle = Join-Path $Out "seedsigner-encryptor.tar.gz"
Write-Host "-> seedsigner-encryptor.tar.gz"
Push-Location (Split-Path -Parent $Root)
try {
    $RepoName = Split-Path -Leaf $Root
    & tar.exe -czf $Bundle `
        --exclude "__pycache__" `
        --exclude ".pytest_cache" `
        --exclude "$RepoName/third_party/pycryptodome" `
        --exclude "$RepoName/pi-dev-setup/downloads" `
        --exclude "$RepoName/pi-prod-setup/output" `
        --exclude "$RepoName/seedsigner/enclosures" `
        --exclude "$RepoName/seedsigner/docs/img" `
        --exclude "$RepoName/third_party/*/assets" `
        $RepoName
    if ($LASTEXITCODE -ne 0) { throw "tar failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. Files are in $Out"
Write-Host "Next: flash $ImageName with Raspberry Pi Imager (Choose OS -> Use custom),"
Write-Host "then run pi-setup\sd-usb-mode.ps1 -Mode gadget"
