#!/bin/bash
# One-time installer for the RNDIS gadget service. Runs once, before SSH works.
#
# sd-usb-mode.ps1 copies this file and seedsigner-usb-gadget.sh to the boot
# partition and adds, to cmdline.txt:
#   systemd.run=/boot/seedsigner-usb-install.sh
#   systemd.run_success_action=reboot systemd.unit=kernel-command-line.target
# (the same mechanism Raspberry Pi Imager uses for firstrun.sh). The Pi boots
# into that minimal target, runs this script, and reboots normally. This
# script removes those words from cmdline.txt and leaves
# /boot/seedsigner-usb-installed so sd-usb-mode.ps1 does not add them again.

set -e

install -m 0755 /boot/seedsigner-usb-gadget.sh /usr/local/sbin/seedsigner-usb-gadget

cat > /etc/systemd/system/seedsigner-usb-gadget.service <<'EOF'
[Unit]
Description=SeedSigner test card USB network gadget (RNDIS)
After=sys-kernel-config.mount systemd-modules-load.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/seedsigner-usb-gadget

[Install]
WantedBy=multi-user.target
EOF
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/seedsigner-usb-gadget.service \
    /etc/systemd/system/multi-user.target.wants/seedsigner-usb-gadget.service

# Turn SSH on here as well, in case the boot-partition ssh file was already consumed.
systemctl enable ssh >/dev/null 2>&1 || true

sed -i -e 's| systemd\.run=[^ ]*||g' \
       -e 's| systemd\.run_success_action=[^ ]*||g' \
       -e 's| systemd\.unit=kernel-command-line\.target||g' /boot/cmdline.txt
touch /boot/seedsigner-usb-installed
sync
exit 0
