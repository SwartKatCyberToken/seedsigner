#!/bin/bash
# Download everything the Pi Zero 1.3 test card needs, on a Linux PC.
# The same downloads as download-for-pi.ps1 on Windows.
#
#   pi-dev-setup/download-for-pi.sh
#
# Writes into pi-dev-setup/downloads/:
#   - Raspberry Pi OS Buster Lite 2023-05-03 (.img.xz), SHA256-checked
#   - Python 3.10.10 source, the BCM2835 C library, and libzbar0
#     (pi-setup.sh uses these instead of downloading them again on the Pi)
#   - seedsigner-encryptor.tar.gz: this repository, ready to copy to the Pi
#
# Re-running skips files that are already complete. apt and pip packages are
# still fetched by the Pi itself, so the Pi needs internet once (see the guide).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="$HERE/downloads"
mkdir -p "$OUT"

IMAGE_NAME=2023-05-03-raspios-buster-armhf-lite.img.xz
IMAGE_URL="https://downloads.raspberrypi.org/raspios_oldstable_lite_armhf/images/raspios_oldstable_lite_armhf-2023-05-03/$IMAGE_NAME"
# Published SHA256, also recorded in seedsigner/docs/raspberry_pi_os_build_instructions.md.
IMAGE_SHA256=3d210e61b057de4de90eadb46e28837585a9b24247c221998f5bead04f88624c

get_file() {
    local name="$1" url="$2" path="$OUT/$1"
    if [ -f "$path" ]; then
        echo "-> $name (already downloaded)"
        return
    fi
    echo "-> $name"
    # The .part file lets a rerun resume.
    curl --fail --location --retry 3 --continue-at - --output "$path.part" "$url"
    mv -f "$path.part" "$path"
}

get_file "$IMAGE_NAME" "$IMAGE_URL"
get_file Python-3.10.10.tgz https://www.python.org/ftp/python/3.10.10/Python-3.10.10.tgz
get_file bcm2835-1.60.tar.gz http://www.airspayce.com/mikem/bcm2835/bcm2835-1.60.tar.gz
# The upstream guide's libzbar0_0.23.90-1+deb11u1 link is gone; this is the rebuilt package.
get_file "libzbar0_0.23.90-1+deb11u1+b1_armhf.deb" \
    "http://raspbian.raspberrypi.org/raspbian/pool/main/z/zbar/libzbar0_0.23.90-1%2Bdeb11u1%2Bb1_armhf.deb"

ACTUAL=$(sha256sum "$OUT/$IMAGE_NAME" | cut -d' ' -f1)
if [ "$ACTUAL" != "$IMAGE_SHA256" ]; then
    rm -f "$OUT/$IMAGE_NAME"
    echo "image SHA256 mismatch: got $ACTUAL, expected $IMAGE_SHA256. The file was deleted; run again." >&2
    exit 1
fi
echo "image SHA256 OK"

# Bundle the repo. third_party/pycryptodome is a reference checkout only;
# pip installs pycryptodome on the Pi, so it is left out. Enclosure models,
# doc images, and the PQ libraries' test-vector assets are not needed to run.
echo "-> seedsigner-encryptor.tar.gz"
REPO_NAME="$(basename "$ROOT")"
tar -C "$(dirname "$ROOT")" -czf "$OUT/seedsigner-encryptor.tar.gz" \
    --exclude "__pycache__" \
    --exclude ".pytest_cache" \
    --exclude "$REPO_NAME/third_party/pycryptodome" \
    --exclude "$REPO_NAME/pi-dev-setup/downloads" \
    --exclude "$REPO_NAME/pi-prod-setup/output" \
    --exclude "$REPO_NAME/seedsigner/enclosures" \
    --exclude "$REPO_NAME/seedsigner/docs/img" \
    --exclude "$REPO_NAME/third_party/*/assets" \
    "$REPO_NAME"

echo
echo "Done. Files are in $OUT"
echo "Next: flash $IMAGE_NAME with Raspberry Pi Imager (Choose OS -> Use custom),"
echo "then run pi-dev-setup/sd-usb-mode.sh gadget"
