#!/bin/bash
# Build the production SeedSigner OS image for a Pi Zero (pi0) with this
# repository's SeedSigner code (message encryption) and USB keyboard support.
#
# Runs inside the builder container. Start it with build-prod-image.ps1 (Windows)
# or build-prod-image.sh (Linux), which
# mounts:
#   /src                       this repository, read-only
#   /work                      Docker volume: Linux filesystem for the build
#   /root/.buildroot-ccache    Docker volume: compiler cache between builds
#   /out                       pi-prod-setup/output on the PC
#
# Environment:
#   FAST=1              keep the previous Buildroot output (build.sh --no-clean)
#   PRELOADED_KEYS=...  repository-relative INI file to ship as the contact list

set -euo pipefail

SRC=/src
OUT=/out
OS=/work/seedsigner-os
BR="$OS/opt/buildroot"
APP="$OS/opt/rootfs-overlay/opt"
BOARD=pi0
IMAGE_NAME="seedsigner_os.encryptor.$BOARD.img"

# seedsigner-os is tracked by the parent repository, whose .git is outside this
# mount, so git can't supply these two facts here.
# The seedsigner/buildroot commit this OS is built against.
BR_COMMIT=bf2a2858aa675a14b60f1f9142c65b32652609c1
# Files that must be executable. Windows checkouts record every file as 100644.
EXECUTABLE_FILES=(
    docs/scripts/rsync-to-seedsigner.sh
    opt/build.sh
    opt/external-packages/python-embit/verify-secp256k1-binary.sh
    opt/pi02w/board/post-build.sh
    opt/pi02w/board/post-image-seedsigner.sh
    opt/pi02w-dev/board/post-build.sh
    opt/pi02w-dev/board/post-image-seedsigner.sh
    opt/pi0/board/post-build.sh
    opt/pi0/board/post-image-seedsigner.sh
    opt/pi0-dev/board/post-build.sh
    opt/pi0-dev/board/post-image-seedsigner.sh
    opt/pi2/board/post-build.sh
    opt/pi2/board/post-image-seedsigner.sh
    opt/pi2-dev/board/post-build.sh
    opt/pi2-dev/board/post-image-seedsigner.sh
    opt/pi4/board/post-build.sh
    opt/pi4/board/post-image-seedsigner.sh
    opt/pi4-dev/board/post-build.sh
    opt/pi4-dev/board/post-image-seedsigner.sh
    opt/rootfs-overlay-dev/etc/init.d/S02seedsigner
    opt/rootfs-overlay-dev/etc/init.d/S30devdata
    opt/rootfs-overlay-dev/etc/init.d/S31data-automount
    opt/rootfs-overlay-dev/etc/init.d/S35network
    opt/rootfs-overlay-dev/start.sh
    opt/rootfs-overlay-dev/usr/bin/network-info
    opt/rootfs-overlay-dev/usr/bin/seedsigner
    opt/rootfs-overlay-dev/usr/sbin/data-automount
    opt/rootfs-overlay-dev/usr/share/udhcpc/default.script.d/50-mdnsd
    opt/rootfs-overlay/etc/init.d/S02seedsigner
    opt/rootfs-overlay/etc/init.d/S10mdev
    opt/rootfs-overlay/etc/mdev/mdev.sh
    opt/rootfs-overlay/start.sh
)

mkdir -p "$OUT"
exec > >(tee "$OUT/build.log") 2>&1

step() { printf '\n==> %s\n' "$*"; }

# Files on a Windows bind mount all read as 0777, and the rootfs overlay keeps
# the modes it is given. Copy with sane modes, then restore the executable bit
# for EXECUTABLE_FILES.
copy_tree() {
    rsync -a --chmod=D755,F644 "$@"
}

step "Checking the sources"
if [ ! -f "$SRC/seedsigner/src/main.py" ]; then
    echo "Missing seedsigner/src/main.py."
    exit 1
fi
# Shell scripts break with CRLF line endings (Python files don't care).
for f in seedsigner-os/opt/build.sh seedsigner-os/opt/rootfs-overlay/start.sh \
         seedsigner-os/opt/rootfs-overlay/etc/init.d/S02seedsigner \
         seedsigner-os/opt/pi0/board/post-build.sh \
         seedsigner-os/opt/pi0/board/post-image-seedsigner.sh; do
    if [ ! -f "$SRC/$f" ]; then
        echo "Missing $f."
        exit 1
    fi
    if grep -q $'\r' "$SRC/$f"; then
        echo "$f has Windows (CRLF) line endings. Convert it to LF."
        exit 1
    fi
done
for f in "${EXECUTABLE_FILES[@]}"; do
    if [ ! -f "$SRC/seedsigner-os/$f" ]; then
        echo "Missing seedsigner-os/$f, listed in EXECUTABLE_FILES."
        exit 1
    fi
done

step "Copying seedsigner-os (with the USB keyboard and message crypto changes)"
mkdir -p "$OS"
copy_tree --delete \
    --exclude=/.git --exclude=/opt/buildroot --exclude=/output \
    --exclude=/buildroot_dl --exclude=/opt/rootfs-overlay/opt \
    "$SRC/seedsigner-os/" "$OS/"
for f in "${EXECUTABLE_FILES[@]}"; do
    chmod 755 "$OS/$f"
done
rm -f "$OS"/images/*.img

step "Checking out buildroot $BR_COMMIT"
if [ ! -d "$BR/.git" ]; then
    rm -rf "$BR"
    git clone https://github.com/seedsigner/buildroot "$BR"
fi
if [ "$(git -C "$BR" rev-parse HEAD)" != "$BR_COMMIT" ]; then
    git -C "$BR" fetch origin
    git -C "$BR" checkout -q --force "$BR_COMMIT"
fi

step "Copying the SeedSigner app and the pure-Python ML-DSA / ML-KEM libraries"
rm -rf "$APP"
mkdir -p "$APP"
PY_EXCLUDES=(--exclude=__pycache__ --exclude='*.pyc' --exclude='*.egg-info')
copy_tree "${PY_EXCLUDES[@]}" "$SRC/seedsigner/src/" "$APP/src/"
copy_tree "${PY_EXCLUDES[@]}" "$SRC/third_party/dilithium-py/src/dilithium_py" "$APP/src/"
copy_tree "${PY_EXCLUDES[@]}" "$SRC/third_party/kyber-py/src/kyber_py" "$APP/src/"
if [ -n "${PRELOADED_KEYS:-}" ]; then
    # message_crypto/preloaded.py reads /opt/preloaded-public-keys.ini
    install -m 644 "$SRC/$PRELOADED_KEYS" "$APP/preloaded-public-keys.ini"
    echo "Contact list: $PRELOADED_KEYS"
else
    echo "Contact list: none (pass -PreloadedKeys to add one)"
fi

# build.sh writes version.json from the app's git checkout, but this copy has
# no .git. It leaves an existing version.json alone, so write it here. fork is
# not "seedsigner", so the app never reports this as an official release.
STAMP=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
cat > "$APP/src/seedsigner/version.json" <<EOF
{
    "name": "encryptor-$(date -u +%Y%m%d)",
    "fork": "seedsigner-encryptor",
    "short_commit_hash": null,
    "timestamp": "$STAMP"
}
EOF

step "Building SeedSigner OS for $BOARD (first build: 1-3 hours)"
BUILD_ARGS=(--"$BOARD" --skip-repo)
if [ "${FAST:-0}" = "1" ] && [ -d "$OS/output" ]; then
    BUILD_ARGS+=(--no-clean)
fi
# A fast build keeps the kernel's .config, so a new option in the fragment would
# be ignored. When one is missing, drop the kernel's config and build stamps. Only
# the kernel rebuilds, reusing its objects, which takes minutes rather than hours.
FRAGMENT="$OS/opt/$BOARD/board/kernel.config.fragment"
for LINUX_DIR in "$OS"/output/build/linux-custom; do
    [ -f "$LINUX_DIR/.config" ] || continue
    if ! grep -E '^CONFIG_[A-Z0-9_]+=y' "$FRAGMENT" | grep -qvxFf "$LINUX_DIR/.config"; then
        continue
    fi
    echo "Kernel options changed: rebuilding the kernel"
    rm -f "$LINUX_DIR"/.stamp_dotconfig "$LINUX_DIR"/.stamp_kconfig_fixup_done           "$LINUX_DIR"/.stamp_configured "$LINUX_DIR"/.stamp_built           "$LINUX_DIR"/.stamp_target_installed "$LINUX_DIR"/.stamp_images_installed           "$LINUX_DIR"/.stamp_initramfs_rebuilt
done
(cd "$OS/opt" && ./build.sh "${BUILD_ARGS[@]}")

step "Checking the kernel config for the USB keyboard and relay"
for OPTION in CONFIG_USB_DWC2_HOST CONFIG_USB_HID CONFIG_USB_ACM; do
    if ! grep -qx "$OPTION=y" "$OS"/output/build/linux-custom/.config; then
        echo "$OPTION is not built in."
        exit 1
    fi
    echo "$OPTION=y"
done

IMAGE=$(ls "$OS"/images/seedsigner_os.*."$BOARD".img 2>/dev/null | head -n 1)
if [ -z "$IMAGE" ]; then
    echo "build.sh finished but no image was written to $OS/images."
    exit 1
fi

step "Testing the image's python3 under qemu"
# -B: never write .pyc files into the target tree.
TARGET="$OS/output/target"
qemu-arm-static -L "$TARGET" "$TARGET/usr/bin/python3" -B - "$TARGET/opt/src" <<'EOF'
import os, sys
sys.path.insert(0, sys.argv[1])
os.environ.setdefault("HOME", "/root")

from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
import pgpy
from dilithium_py.ml_dsa import ML_DSA_44
from kyber_py.ml_kem import ML_KEM_512
import seedsigner.message_crypto.rsa_ops
import seedsigner.message_crypto.pgp_ops
import seedsigner.message_crypto.ml_dsa_ops
import seedsigner.message_crypto.ml_kem_ops
import seedsigner.hardware.usb_keyboard
import seedsigner.hardware.usb_relay
import fcntl, select, termios, tty  # usb_relay opens these only when a board is used

key = bytes(range(32))
cipher = AES.new(key, AES.MODE_GCM)
ct, tag = cipher.encrypt_and_digest(b"seedsigner")
assert AES.new(key, AES.MODE_GCM, nonce=cipher.nonce).decrypt_and_verify(ct, tag) == b"seedsigner"

ek, dk = ML_KEM_512.keygen()
shared, ct = ML_KEM_512.encaps(ek)
assert ML_KEM_512.decaps(dk, ct) == shared

print("message crypto OK: pycryptodome, PGPy, ML-DSA, ML-KEM")
EOF
if ! qemu-arm-static -L "$TARGET" "$TARGET/usr/bin/python3" -B \
        "$TARGET/opt/src/main.py" --help | grep -q -- --usb-keyboard; then
    echo "main.py in the image does not accept --usb-keyboard."
    exit 1
fi
echo "main.py accepts --usb-keyboard"

step "Copying the image to pi-prod-setup/output"
cp -f "$IMAGE" "$OUT/$IMAGE_NAME"
(cd "$OUT" && sha256sum "$IMAGE_NAME" | tee "$IMAGE_NAME.sha256")
echo
echo "Done: pi-prod-setup/output/$IMAGE_NAME"
