#!/bin/bash
# USB network gadget that Windows binds to its built-in RNDIS driver.
#
# Runs at boot from seedsigner-usb-gadget.service (installed by
# seedsigner-usb-install.sh). Builds an RNDIS function through configfs and
# advertises the Microsoft OS descriptor compatible ID "RNDIS" / "5162001",
# which Windows' rndiscmp.inf ("Remote NDIS Compatible Device") matches. The
# legacy g_ether module has no OS descriptors, so Windows binds it as a COM
# port instead. Exits quietly in host mode, when no USB device controller is
# present (dtoverlay=dwc2 removed).

set -e

G=/sys/kernel/config/usb_gadget/seedsigner

modprobe libcomposite
UDC=$(ls /sys/class/udc 2>/dev/null | head -n 1)
if [ -z "$UDC" ]; then
    echo "no USB device controller (host mode); gadget not started"
    exit 0
fi
if [ -d "$G" ]; then
    exit 0
fi

mkdir -p "$G"
cd "$G"
echo 0x1d6b > idVendor   # Linux Foundation
echo 0x0104 > idProduct  # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB
# Composite device with an interface association: lets Windows read OS descriptors.
echo 0xEF > bDeviceClass
echo 0x02 > bDeviceSubClass
echo 0x01 > bDeviceProtocol

mkdir -p strings/0x409
echo "seedsigner-test" > strings/0x409/serialnumber
echo "SeedSigner test card" > strings/0x409/manufacturer
echo "SeedSigner USB network" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "RNDIS" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

echo 1 > os_desc/use
echo 0xcd > os_desc/b_vendor_code
echo MSFT100 > os_desc/qw_sign

mkdir -p functions/rndis.usb0
# Fixed, locally administered MACs so Windows keeps one adapter across boots.
echo 02:53:53:00:00:01 > functions/rndis.usb0/host_addr
echo 02:53:53:00:00:02 > functions/rndis.usb0/dev_addr
echo RNDIS > functions/rndis.usb0/os_desc/interface.rndis/compatible_id
echo 5162001 > functions/rndis.usb0/os_desc/interface.rndis/sub_compatible_id

ln -s functions/rndis.usb0 configs/c.1/
ln -s configs/c.1 os_desc
echo "$UDC" > UDC
echo "RNDIS gadget started on $UDC"
