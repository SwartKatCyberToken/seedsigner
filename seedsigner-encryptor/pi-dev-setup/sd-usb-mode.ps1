# Switch the Pi Zero 1.3's one USB data port between two jobs, from a PC.
#
#   powershell -ExecutionPolicy Bypass -File pi-setup\sd-usb-mode.ps1 -Mode gadget
#   powershell -ExecutionPolicy Bypass -File pi-setup\sd-usb-mode.ps1 -Mode host
#
# Without -Drive, the script finds the drive that holds config.txt,
# cmdline.txt, and bootcode.bin. Pass -Drive F to pick one yourself.
#
# gadget: the port is a USB network adapter to the PC (SSH, and internet via
#         Windows Internet Connection Sharing). Also enables SSH. Use this
#         while installing and to read ~/seedsigner.log.
# host:   the port takes an OTG adapter and a USB keyboard. No network.
#
# Drive is the SD card's "boot" partition as Windows mounts it. The edits
# follow seedsigner/docs/usb_relay.md: dtoverlay=dwc2 in config.txt and a
# modules-load entry after rootwait in cmdline.txt.
#
# -Gadget picks the USB network function:
#   rndis (default): pi-setup/usb-gadget/ builds an RNDIS gadget through
#     configfs with Microsoft OS descriptors, so Windows loads its built-in
#     Remote NDIS driver by itself. The first gadget boot installs the service
#     (systemd.run, like Raspberry Pi Imager's firstrun.sh) and reboots once.
#   ether: the legacy g_ether module that usb_relay.md uses. Windows often
#     binds it as a COM port, and its RNDIS driver cannot be picked by hand.
# The Buster 5.10 kernel has no g_ncm module, so NCM is not offered.

param(
    [string]$Drive = "",
    [Parameter(Mandatory = $true)][ValidateSet("gadget", "host")][string]$Mode,
    [ValidateSet("rndis", "ether")][string]$Gadget = "rndis"
)

$ErrorActionPreference = "Stop"

$NoLetterHelp = @"
Windows often gives no drive letter to the SD card's boot partition after flashing.
Give it one, then run this script again:
  - Disk Management (Win+X, Disk Management): right-click the 256 MB FAT32 partition
    on the SD card, Change Drive Letter and Paths, Add.
  - Or in an administrator PowerShell:
      Get-Disk | Where-Object BusType -eq USB | Get-Partition |
        Where-Object { `$_.Type -like 'FAT32*' -and -not `$_.DriveLetter } |
        Add-PartitionAccessPath -AssignDriveLetter
If Windows offers to format the other (Linux) partition, choose Cancel.
"@

function Test-BootRoot($Root) {
    (Test-Path (Join-Path $Root "config.txt")) -and
    (Test-Path (Join-Path $Root "cmdline.txt")) -and
    (Test-Path (Join-Path $Root "bootcode.bin"))
}

function Find-BootLetters {
    # DriveInfo sees letters assigned after this session started; Get-PSDrive may not.
    @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and (Test-BootRoot $_.RootDirectory.FullName) } |
        ForEach-Object { $_.Name.Substring(0, 1) })
}

function Request-BootLetter {
    # A FAT32 partition of 1 GB or less on a USB disk, with no letter: a freshly flashed boot partition.
    $Candidates = @(Get-Disk | Where-Object BusType -eq USB | Get-Partition |
        Where-Object { $_.Type -like "FAT32*" -and -not $_.DriveLetter -and $_.Size -le 1GB })
    if ($Candidates.Count -ne 1) { return $false }
    $Part = $Candidates[0]
    Write-Host "The SD card's boot partition (disk $($Part.DiskNumber), partition $($Part.PartitionNumber)) has no drive letter."
    Write-Host "Assigning one needs administrator rights. Approve the Windows prompt to continue."
    $Command = "Get-Partition -DiskNumber $($Part.DiskNumber) -PartitionNumber $($Part.PartitionNumber) | Add-PartitionAccessPath -AssignDriveLetter"
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden `
            -ArgumentList "-NoProfile", "-Command", $Command
    } catch {
        Write-Host "The administrator prompt was declined."
        return $false
    }
    for ($i = 0; $i -lt 10; $i++) {
        if ((Find-BootLetters).Count -gt 0) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

if ($Drive -ne "") {
    $Letter = $Drive.TrimEnd(":", "\")
    if (-not (Test-Path "$($Letter):\")) {
        Write-Host "Drive $($Letter): does not exist on this PC. Looking for the SD card instead."
        $Drive = ""
    }
}

if ($Drive -eq "") {
    $Found = Find-BootLetters
    if ($Found.Count -eq 0 -and (Request-BootLetter)) {
        $Found = Find-BootLetters
    }
    if ($Found.Count -eq 0) {
        Write-Host "No Raspberry Pi boot partition with a drive letter was found."
        Write-Host $NoLetterHelp
        exit 1
    }
    if ($Found.Count -gt 1) {
        throw "Several Pi boot partitions found ($($Found -join ', ')). Pass -Drive."
    }
    $Drive = $Found[0]
    Write-Host "Using boot partition $($Drive):"
}

$Letter = $Drive.TrimEnd(":", "\")
$Boot = "$($Letter):\"
if (-not (Test-BootRoot $Boot)) {
    throw "$Boot is not a Raspberry Pi boot partition (config.txt, cmdline.txt, bootcode.bin missing)."
}
$Config = Join-Path $Boot "config.txt"
$Cmdline = Join-Path $Boot "cmdline.txt"

$Overlay = "dtoverlay=dwc2"
if ($Gadget -eq "ether") { $Modules = "modules-load=dwc2,g_ether" } else { $Modules = "modules-load=dwc2" }
$AnyModules = @("modules-load=dwc2", "modules-load=dwc2,g_ether", "modules-load=dwc2,g_ncm")
$RunWords = @(
    "systemd.run=/boot/seedsigner-usb-install.sh",
    "systemd.run_success_action=reboot",
    "systemd.unit=kernel-command-line.target"
)
$Installed = Join-Path $Boot "seedsigner-usb-installed"
$Ascii = New-Object System.Text.UTF8Encoding($false)

# config.txt: one dtoverlay=dwc2 line in gadget mode, none in host mode.
# The stock file ends inside a [pi4] filter, so the line gets its own [all]
# block; otherwise a Pi Zero would ignore it. The marker finds that block again.
$Marker = "# sd-usb-mode.ps1 gadget"
$Lines = New-Object System.Collections.Generic.List[string]
$Source = [IO.File]::ReadAllLines($Config)
for ($i = 0; $i -lt $Source.Count; $i++) {
    $Line = $Source[$i]
    if ($Line.Trim() -eq $Marker) {
        if ($i + 1 -lt $Source.Count -and $Source[$i + 1].Trim() -eq "[all]") { $i++ }
        continue
    }
    if ($Line.Trim() -eq $Overlay) { continue }
    $Lines.Add($Line)
}
while ($Lines.Count -gt 0 -and $Lines[$Lines.Count - 1].Trim() -eq "") {
    $Lines.RemoveAt($Lines.Count - 1)
}
if ($Mode -eq "gadget") {
    $Lines.AddRange([string[]]@("", $Marker, "[all]", $Overlay))
}
[IO.File]::WriteAllText($Config, (($Lines -join "`n") + "`n"), $Ascii)

# The RNDIS gadget scripts go on the boot partition with Unix line endings.
$NeedsInstall = $false
if ($Mode -eq "gadget" -and $Gadget -eq "rndis") {
    foreach ($Name in "seedsigner-usb-gadget.sh", "seedsigner-usb-install.sh") {
        $Text = [IO.File]::ReadAllText((Join-Path $PSScriptRoot "usb-gadget\$Name")) -replace "`r`n", "`n"
        [IO.File]::WriteAllText((Join-Path $Boot $Name), $Text, $Ascii)
    }
    $NeedsInstall = -not (Test-Path $Installed)
}

# cmdline.txt must stay one line. Drop the module list and any pending
# installer words, then re-add what this mode needs after rootwait.
$Words = ([IO.File]::ReadAllText($Cmdline).Trim() -split "\s+") |
    Where-Object { $AnyModules -notcontains $_ -and $RunWords -notcontains $_ }
if ($Mode -eq "gadget") {
    $Index = [Array]::IndexOf($Words, "rootwait")
    if ($Index -lt 0) { throw "rootwait not found in cmdline.txt; edit it by hand" }
    $Words = @($Words[0..$Index]) + $Modules + @($Words | Select-Object -Skip ($Index + 1))
    if ($NeedsInstall) { $Words = @($Words) + $RunWords }
}
[IO.File]::WriteAllText($Cmdline, (($Words -join " ") + "`n"), $Ascii)

if ($Mode -eq "gadget") {
    # An empty file named ssh turns on the SSH server at boot.
    $Ssh = Join-Path $Boot "ssh"
    if (-not (Test-Path $Ssh)) { [IO.File]::WriteAllText($Ssh, "", $Ascii) }
}

Write-Host "SD card set to $Mode mode."
Write-Host "cmdline.txt: $([IO.File]::ReadAllText($Cmdline).Trim())"
if ($Mode -eq "gadget") {
    if ($NeedsInstall) {
        Write-Host "First RNDIS boot: the Pi installs the gadget service, then reboots by itself (allow about 3 minutes)."
    }
    Write-Host "Plug a data micro-USB cable into the port marked USB (closer to the centre), not PWR."
    if ($Gadget -eq "rndis") {
        Write-Host "Windows should then show 'Remote NDIS Compatible Device' (or 'USB RNDIS Adapter') under Network adapters."
    }
} else {
    Write-Host "Plug the OTG adapter and keyboard into the USB port, and power into PWR."
}
