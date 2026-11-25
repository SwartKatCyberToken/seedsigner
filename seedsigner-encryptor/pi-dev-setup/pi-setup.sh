#!/bin/bash
# Install this repository on a Pi Zero 1.3 running Raspberry Pi OS Buster Lite.
#
#   bash ~/seedsigner-encryptor/pi-setup/pi-setup.sh
#
# Follows seedsigner/docs/raspberry_pi_os_build_instructions.md, then adds
# the message requirements and a service that starts SeedSigner with
# --usb-keyboard. Needs internet (USB gadget mode plus Windows Internet
# Connection Sharing). Expect 3-4 hours on a Pi Zero 1.3; the Python build
# alone is about 80 minutes. Safe to re-run: finished steps are skipped.
#
# Files from download-for-pi.ps1 in ~/downloads are used when present.
#
# This is a test card. Never load a real seed on it.

set -euo pipefail

REPO="$HOME/seedsigner-encryptor"
APP="$REPO/seedsigner"
DL="$HOME/downloads"
PY=/usr/local/bin/python3.10
ZBAR_DEB="libzbar0_0.23.90-1+deb11u1+b1_armhf.deb"
ZBAR_URL="http://raspbian.raspberrypi.org/raspbian/pool/main/z/zbar/libzbar0_0.23.90-1%2Bdeb11u1%2Bb1_armhf.deb"
LOG="$HOME/seedsigner.log"

step() { printf '\n==> %s\n' "$*"; }

fetch() {
    # fetch NAME URL: use ~/downloads/NAME if it is there, else download it.
    if [ -f "$DL/$1" ]; then
        cp "$DL/$1" "./$1"
    else
        wget -O "./$1" "$2"
    fi
}

step "Checking the OS"
if ! grep -q 'VERSION_CODENAME=buster' /etc/os-release; then
    echo "This script needs Raspberry Pi OS Buster (2023-05-03 Lite). Found:"
    cat /etc/os-release
    exit 1
fi
if [ ! -d "$APP/src" ]; then
    echo "Expected the repository at $REPO. Unpack seedsigner-encryptor.tar.gz in $HOME first."
    exit 1
fi
if ! ping -c 1 -W 5 8.8.8.8 >/dev/null 2>&1; then
    echo "No internet. Set up Windows Internet Connection Sharing (see the guide) and retry."
    exit 1
fi

step "Enabling SPI and setting the en_US.UTF-8 locale"
sudo raspi-config nonint do_spi 0
if ! locale -a 2>/dev/null | grep -qi '^en_US.utf8$'; then
    sudo raspi-config nonint do_change_locale en_US.UTF-8
fi

step "Adding 1 GB of temporary swap for the builds"
if ! swapon --show | grep -q /swapfile; then
    # A power cut during dd leaves a short file that swapon rejects; rebuild it.
    if [ ! -f /swapfile ] || ! sudo swapon /swapfile 2>/dev/null; then
        sudo rm -f /swapfile
        sudo dd if=/dev/zero of=/swapfile bs=4096 count=$((1024 * 256))
        sudo chmod 0600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
    fi
fi

step "Pointing apt at the Buster archive"
# raspbian.raspberrypi.org no longer serves buster (its Release file is 404).
# The same repository now lives at legacy.raspbian.org. Its Suite changed to
# oldoldstable, which apt refuses without --allow-releaseinfo-change.
sudo sed -i 's|http://raspbian.raspberrypi.org/raspbian|http://legacy.raspbian.org/raspbian|g' \
    /etc/apt/sources.list
# Finish any package install a power cut interrupted; apt refuses to run until then.
sudo dpkg --configure -a
sudo apt-get update --allow-releaseinfo-change

step "Installing apt packages"
# python3-opencv and python3-picamera from the upstream list are left out:
# nothing in this tree imports cv2, and pip installs picamera.
sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev \
    libnss3-dev openssl libssl-dev libreadline-dev libffi-dev wget libsqlite3-dev \
    libraqm-dev wiringpi python3-pip python-pil libjpeg-dev libopenjp2-7 git \
    libatlas-base-dev qrencode

step "Building Python 3.10.10 (about 90 minutes on a Pi Zero 1.3)"
# The marker is written only after make altinstall finishes and the build
# imports its compiled modules, so a build cut short by a power loss is redone
# even though python3.10 itself may already exist.
PY_DONE=/usr/local/lib/python3.10/seedsigner-build-ok
if [ ! -f "$PY_DONE" ]; then
    cd "$HOME"
    sudo rm -rf Python-3.10.10
    fetch Python-3.10.10.tgz https://www.python.org/ftp/python/3.10.10/Python-3.10.10.tgz
    tar -xzf Python-3.10.10.tgz
    cd Python-3.10.10
    ./configure --enable-optimizations
    sudo make altinstall
    "$PY" -c "import ssl, ctypes, zlib, sqlite3, readline; import ensurepip"
    sudo touch "$PY_DONE"
    cd "$HOME"
    sudo rm -rf Python-3.10.10 Python-3.10.10.tgz
    # Upstream reinstalls python3-apt after switching python3.
    sudo update-alternatives --install /usr/bin/python3 python3 "$PY" 1
    sudo apt-get remove --purge -y python3-apt || true
    sudo apt-get autoremove -y
    sudo apt-get install -y python3-apt
else
    echo "already installed: $("$PY" --version)"
fi
# Repeated every run in case a power cut came between the build and this step.
sudo update-alternatives --install /usr/bin/python python "$PY" 1
sudo update-alternatives --install /usr/bin/python3 python3 "$PY" 1

step "Installing libzbar0"
if ! dpkg -s libzbar0 >/dev/null 2>&1; then
    cd "$HOME"
    fetch "$ZBAR_DEB" "$ZBAR_URL"
    sudo apt-get install -y "./$ZBAR_DEB"
    rm -f "./$ZBAR_DEB"
fi

step "Building the BCM2835 library"
if [ ! -f /usr/local/lib/libbcm2835.a ]; then
    cd "$HOME"
    fetch bcm2835-1.60.tar.gz http://www.airspayce.com/mikem/bcm2835/bcm2835-1.60.tar.gz
    tar -xzf bcm2835-1.60.tar.gz
    cd bcm2835-1.60
    sudo ./configure
    sudo make
    sudo make install
    cd "$HOME"
    sudo rm -rf bcm2835-1.60 bcm2835-1.60.tar.gz
fi

step "Installing SeedSigner pip requirements (over an hour)"
cd "$APP"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements.txt
if [ "${SEEDSIGNER_CAMERA:-0}" = "1" ]; then
    # numpy 1.25.0 has no armv6 wheel for Python 3.10, so this compiles it (hours).
    "$PY" -m pip install -r requirements-raspi.txt
    # start_x=1 and gpu_mem=128 in /boot/config.txt; takes effect after a reboot.
    sudo raspi-config nonint do_camera 0
else
    # No camera: numpy is only used by the camera stream (pivideostream.py), and
    # the controller's warm-up import tolerates its absence. picamera goes in
    # without dependencies so the pin is still satisfied. Set SEEDSIGNER_CAMERA=1
    # to install requirements-raspi.txt in full.
    "$PY" -m pip install RPi.GPIO==0.7.1 spidev==3.6
    "$PY" -m pip install --no-deps picamera==1.13
fi

step "Installing the message requirements"
# pycryptodome and the two pure-Python PQ libraries are required for RSA,
# ML-DSA, and ML-KEM. PGP is optional: PGPy needs cryptography, and current
# cryptography releases need Rust to build on armv6. cryptography 3.3.2 is
# the oldest version PGPy 0.6.0 accepts and builds with C only.
"$PY" -m pip install pycryptodome==4.2.0 -e ../third_party/dilithium-py -e ../third_party/kyber-py
if "$PY" -m pip install "cryptography==3.3.2" "PGPy==0.6.0"; then
    echo "PGP is available."
else
    echo "WARNING: PGPy did not install. RSA, ML-DSA, and ML-KEM still work; skip PGP on this card."
fi

step "Giving the pi user keyboard access"
sudo usermod -aG input "$USER"

step "Raising the SPI buffer for the ST7789 display"
if ! grep -q 'spidev.bufsiz=' /boot/cmdline.txt; then
    sudo sed -i '1 s/$/ spidev.bufsiz=131072/' /boot/cmdline.txt
fi

step "Installing seedsigner.service with --usb-keyboard"
# stderr goes to ~/seedsigner.log so a failed start can be read later over SSH.
# Test cards only: the log is on the SD card.
sudo tee /etc/systemd/system/seedsigner.service >/dev/null <<EOF
[Unit]
Description=Seedsigner

[Service]
User=$USER
WorkingDirectory=$APP/src/
ExecStart=/usr/bin/python3 main.py --usb-keyboard
StandardOutput=null
StandardError=append:$LOG
Restart=no

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable seedsigner.service

step "Checking the message code imports"
cd "$APP/src"
"$PY" -c "import Crypto, dilithium_py, kyber_py, seedsigner.message_crypto.operations, seedsigner.hardware.usb_keyboard; print('message crypto imports OK')"

cat <<EOF

Setup finished.

  1. sudo shutdown -h now
  2. On the PC: pi-setup\\sd-usb-mode.ps1 -Mode host
  3. Put the card back, plug the OTG adapter + keyboard into USB, power into PWR.

The swap file is not re-enabled after a reboot. Delete it later with: sudo rm /swapfile
EOF
