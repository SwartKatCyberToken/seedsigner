#!/bin/bash
# Switch the Pi Zero 1.3's one USB data port between two jobs, from a Linux PC.
# The same edits as sd-usb-mode.ps1 on Windows; the two can be mixed.
#
#   pi-dev-setup/sd-usb-mode.sh gadget [--boot DIR] [--gadget rndis|ether]
#   pi-dev-setup/sd-usb-mode.sh host   [--boot DIR]
#
# DIR is where the SD card's boot partition is mounted. Without --boot, the
# script looks under /run/media/$USER, /media/$USER, /media and /mnt for a
# folder holding config.txt, cmdline.txt and bootcode.bin. Most desktops mount
# the card there when you click it in the file manager. Otherwise:
#   sudo mount /dev/sdX1 /mnt    (check the device with lsblk first)
#
# gadget: the port is a USB network adapter to the PC (SSH, and internet via
#         connection sharing). Also enables SSH. Use this while installing and
#         to read ~/seedsigner.log.
# host:   the port takes an OTG adapter and a USB keyboard. No network.
#
# --gadget picks the USB network function:
#   rndis (default): usb-gadget/ builds an RNDIS gadget through configfs. Linux
#     binds it with the rndis_host driver. The first gadget boot installs the
#     service (systemd.run) and reboots once.
#   ether: the legacy g_ether module that usb_relay.md uses. Linux binds it with
#     cdc_ether, which also works fine.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=""
BOOT=""
GADGET=rndis

while [ $# -gt 0 ]; do
    case "$1" in
        gadget|host) MODE="$1" ;;
        --boot) [ $# -ge 2 ] || { echo "--boot needs a folder." >&2; exit 2; }; BOOT="$2"; shift ;;
        --boot=*) BOOT="${1#*=}" ;;
        --gadget) [ $# -ge 2 ] || { echo "--gadget needs rndis or ether." >&2; exit 2; }; GADGET="$2"; shift ;;
        --gadget=*) GADGET="${1#*=}" ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$MODE" ] || { echo "Say gadget or host. See --help." >&2; exit 2; }
case "$GADGET" in rndis|ether) ;; *) echo "--gadget must be rndis or ether." >&2; exit 2 ;; esac

is_boot() { [ -f "$1/config.txt" ] && [ -f "$1/cmdline.txt" ] && [ -f "$1/bootcode.bin" ]; }

if [ -z "$BOOT" ]; then
    FOUND=()
    for DIR in /run/media/"$USER"/* /media/"$USER"/* /media/* /mnt /mnt/*; do
        if [ -d "$DIR" ] && is_boot "$DIR"; then FOUND+=("$DIR"); fi
    done
    if [ ${#FOUND[@]} -eq 0 ]; then
        echo "No mounted Raspberry Pi boot partition was found." >&2
        echo "Mount it (click it in the file manager, or: sudo mount /dev/sdX1 /mnt) and pass --boot if needed." >&2
        exit 1
    fi
    if [ ${#FOUND[@]} -gt 1 ]; then
        echo "Several Pi boot partitions found: ${FOUND[*]}. Pass --boot." >&2
        exit 1
    fi
    BOOT="${FOUND[0]}"
    echo "Using boot partition $BOOT"
fi
is_boot "$BOOT" || { echo "$BOOT is not a Raspberry Pi boot partition (config.txt, cmdline.txt, bootcode.bin missing)." >&2; exit 1; }
if [ ! -w "$BOOT/config.txt" ]; then
    echo "Can't write to $BOOT. Run with sudo, or mount the card as your user." >&2
    exit 1
fi

CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"
OVERLAY="dtoverlay=dwc2"
if [ "$GADGET" = ether ]; then MODULES="modules-load=dwc2,g_ether"; else MODULES="modules-load=dwc2"; fi
INSTALLED="$BOOT/seedsigner-usb-installed"
# Shared with sd-usb-mode.ps1, so either script can undo the other's edit.
MARKER="# sd-usb-mode.ps1 gadget"

# config.txt: one dtoverlay=dwc2 line in gadget mode, none in host mode.
# The stock file ends inside a [pi4] filter, so the line gets its own [all]
# block; otherwise a Pi Zero would ignore it. The marker finds that block again.
NEW_CONFIG="$(awk -v marker="$MARKER" -v overlay="$OVERLAY" '
    function trim(s) { gsub(/^[ \t\r]+|[ \t\r]+$/, "", s); return s }
    skip_all && trim($0) == "[all]" { skip_all = 0; next }
    { skip_all = 0 }
    trim($0) == marker { skip_all = 1; next }
    trim($0) == overlay { next }
    { sub(/\r$/, ""); lines[++n] = $0 }
    END {
        while (n > 0 && trim(lines[n]) == "") n--
        for (i = 1; i <= n; i++) print lines[i]
    }' "$CONFIG")"
if [ "$MODE" = gadget ]; then
    NEW_CONFIG+=$'\n\n'"$MARKER"$'\n[all]\n'"$OVERLAY"
fi
printf '%s\n' "$NEW_CONFIG" > "$CONFIG"

# The RNDIS gadget scripts go on the boot partition with Unix line endings.
NEEDS_INSTALL=0
if [ "$MODE" = gadget ] && [ "$GADGET" = rndis ]; then
    for NAME in seedsigner-usb-gadget.sh seedsigner-usb-install.sh; do
        sed 's/\r$//' "$HERE/usb-gadget/$NAME" > "$BOOT/$NAME"
    done
    if [ ! -e "$INSTALLED" ]; then NEEDS_INSTALL=1; fi
fi

# cmdline.txt must stay one line. Drop the module list and any pending
# installer words, then re-add what this mode needs after rootwait.
RUN_WORDS=(
    systemd.run=/boot/seedsigner-usb-install.sh
    systemd.run_success_action=reboot
    systemd.unit=kernel-command-line.target
)
# tr removes the final newline, so read reports end of file; that's expected.
read -r -a OLD_WORDS < <(tr -s ' \t\r\n' ' ' < "$CMDLINE") || true
WORDS=()
for W in "${OLD_WORDS[@]}"; do
    case "$W" in
        modules-load=dwc2|modules-load=dwc2,g_ether|modules-load=dwc2,g_ncm) continue ;;
    esac
    for R in "${RUN_WORDS[@]}"; do
        if [ "$W" = "$R" ]; then continue 2; fi
    done
    WORDS+=("$W")
done
if [ "$MODE" = gadget ]; then
    OUT_WORDS=()
    SEEN_ROOTWAIT=0
    for W in "${WORDS[@]}"; do
        OUT_WORDS+=("$W")
        if [ "$W" = rootwait ] && [ "$SEEN_ROOTWAIT" = 0 ]; then
            OUT_WORDS+=("$MODULES")
            SEEN_ROOTWAIT=1
        fi
    done
    [ "$SEEN_ROOTWAIT" = 1 ] || { echo "rootwait not found in cmdline.txt; edit it by hand" >&2; exit 1; }
    if [ "$NEEDS_INSTALL" = 1 ]; then OUT_WORDS+=("${RUN_WORDS[@]}"); fi
    WORDS=("${OUT_WORDS[@]}")
fi
printf '%s\n' "${WORDS[*]}" > "$CMDLINE"

if [ "$MODE" = gadget ]; then
    # An empty file named ssh turns on the SSH server at boot.
    if [ ! -e "$BOOT/ssh" ]; then : > "$BOOT/ssh"; fi
fi
sync

echo "SD card set to $MODE mode."
echo "cmdline.txt: $(cat "$CMDLINE")"
if [ "$MODE" = gadget ]; then
    if [ "$NEEDS_INSTALL" = 1 ]; then
        echo "First RNDIS boot: the Pi installs the gadget service, then reboots by itself (allow about 3 minutes)."
    fi
    echo "Plug a data micro-USB cable into the port marked USB (closer to the centre), not PWR."
    echo "Linux should then show a new network interface (usb0 or enx...), see: ip link"
else
    echo "Plug the OTG adapter and keyboard into the USB port, and power into PWR."
fi
echo "Unmount the card before removing it (eject it in the file manager, or: sudo umount $BOOT)."
