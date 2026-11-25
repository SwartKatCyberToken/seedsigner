# Updated Setup Guide: test message signing on a Pi Zero 1.3

This guide sets up a Raspberry Pi Zero v1.3 to run this repository. You load a seed with the joystick, type a message on a USB keyboard, and sign it. You don't need a camera.

It replaces the plan in `testing.md`. That plan used the SeedSigner OS `-dev` image, which you would have to build yourself, and nothing in it makes a USB keyboard type into SeedSigner. This guide uses Raspberry Pi OS Buster Lite instead, plus a new `--usb-keyboard` option in this repository.

> **Test card only.** Use only the public test mnemonic in `test-data/testseed.txt`. The card has SSH, a known password, and a log file. `dilithium-py` and `kyber-py` are prototypes.

## What you need

| Item | Notes |
| --- | --- |
| Raspberry Pi Zero v1.3 | No WiFi, one USB data port |
| Waveshare 1.3" 240×240 LCD HAT | The SeedSigner display, joystick, and three buttons. You need this. |
| microSD card, 8 GB or larger | 4 GB is the minimum, but the builds need room |
| Micro-USB **data** cable | Some cables only carry power. A power-only cable won't work. |
| Micro-USB OTG adapter (male micro-USB to female USB-A) | Lets the keyboard plug into the Pi |
| USB keyboard | A plain wired keyboard. The layout is read as US. |
| 5 V micro-USB power supply | For the testing phase |
| Phone with a QR reader (optional) | For reading the signature QR back to the PC |
| Windows PC with internet | |

## How the single USB port is used

The Pi Zero 1.3 has one USB data port, and it does a different job in each phase:

1. **Setup (gadget mode):** the port connects to your PC as a network adapter. You get SSH, and Windows shares its internet with the Pi.
2. **Testing (host mode):** the port takes the OTG adapter and the keyboard. There is no network.

To switch modes, you edit the SD card on the PC with `pi-setup\sd-usb-mode.ps1`.

## Files added for this

| File | Runs on | Purpose |
| --- | --- | --- |
| `pi-setup/download-for-pi.ps1` | PC | Downloads the OS image (and checks its SHA256), Python 3.10.10, BCM2835, and libzbar, and bundles this repo |
| `pi-setup/sd-usb-mode.ps1` | PC | Switches the SD card between `gadget` and `host` mode |
| `pi-setup/pi-setup.sh` | Pi | Installs everything and creates the `seedsigner.service` that starts with `--usb-keyboard` |
| `test-data/check-helper.py` | PC | Prints what the Pi should show, and verifies signatures read from its QR |
| `seedsigner/src/seedsigner/hardware/usb_keyboard.py` | Pi | Reads the USB keyboard alongside the joystick |

## Step 1: Download on the PC

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File pi-setup\download-for-pi.ps1
```

Everything is written to `pi-setup\downloads\`. If the image's SHA256 doesn't match, the script deletes the image and stops. Running it again skips files it already downloaded.

## Step 2: Flash the card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Choose OS, then **Use custom**, then `pi-setup\downloads\2023-05-03-raspios-buster-armhf-lite.img.xz`.
3. Pick the SD card and write it. When Imager offers OS customisation, choose **No**: Buster doesn't support it.
4. Let the verify step finish. If writing never starts on Windows, run Imager as administrator.

Use this exact Buster image. SeedSigner doesn't run on newer Raspberry Pi OS releases.

## Step 3: Set the card to gadget mode

Re-insert the card. Windows should mount a small partition called `boot`.

```powershell
powershell -ExecutionPolicy Bypass -File pi-setup\sd-usb-mode.ps1 -Mode gadget
```

The script finds the `boot` partition on its own. To choose it yourself, add `-Drive F` with your letter.

**If no `boot` drive appears:** Windows often gives no letter to that partition after flashing. Assign one with either of these, then run the script again:

- **Disk Management** (Win+X, then Disk Management): right-click the **256 MB FAT32** partition on the SD card, choose **Change Drive Letter and Paths**, then **Add**.
- **An administrator PowerShell:**

  ```powershell
  Get-Disk | Where-Object BusType -eq USB | Get-Partition | Where-Object { $_.Type -like 'FAT32*' -and -not $_.DriveLetter } | Add-PartitionAccessPath -AssignDriveLetter
  ```

If Windows offers to **format** the other, larger partition, click **Cancel**. That partition is the Pi's Linux filesystem, and Windows can't read it.

This enables SSH and USB networking. Eject the card and put it in the Pi.

## Step 4: Connect the Pi and share internet

1. Fit the LCD HAT. Connect the data cable from the PC to the Pi port marked **USB** (the one nearer the centre). The Pi takes power from that cable, so nothing goes in PWR.
2. Wait about 3 minutes. On its very first boot, the Pi resizes its filesystem and reboots. On the first boot in gadget mode, it also installs a small USB network service (`pi-setup/usb-gadget/`) and reboots once more.
3. In Device Manager, look under **Network adapters** for **Remote NDIS Compatible Device** (sometimes called **USB RNDIS Adapter**). The Pi announces itself with Microsoft's RNDIS identifier, so Windows loads its own driver without asking you.
   - **USB Serial Device (COMx)** under Ports: the card is in the older `g_ether` mode. Windows hides the RNDIS driver from manual selection, so picking it by hand fails. Re-run Step 3, where RNDIS is now the default.
   - **Unknown USB Device (Device Descriptor Request Failed)**: the Pi is still booting, or the card has the old `g_ncm` setting. This Buster kernel has no `g_ncm`. Wait a minute and replug. If it persists, re-run Step 3.
4. Press Win+R and run `ncpa.cpl`. Open the adapter that has your internet (Wi-Fi or Ethernet), then Properties, then the **Sharing** tab. Tick *Allow other network users to connect*, and select the new Ethernet adapter that belongs to the Pi.
5. Unplug the Pi and plug it back in, so it asks for an address again.

## Step 5: Copy the files and run the setup script

```powershell
ssh pi@raspberrypi.local
```

The password is `raspberry`. Change it straight away with `passwd`.

If `raspberrypi.local` doesn't resolve, run `arp -a` on the PC and look for a `192.168.137.x` address. Use `ssh pi@192.168.137.x` instead.

From a second PowerShell window in the repository root:

```powershell
ssh pi@raspberrypi.local "mkdir -p ~/downloads"
scp pi-setup\downloads\seedsigner-encryptor.tar.gz pi-setup\downloads\Python-3.10.10.tgz pi-setup\downloads\bcm2835-1.60.tar.gz "pi-setup\downloads\libzbar0_0.23.90-1+deb11u1+b1_armhf.deb" pi@raspberrypi.local:~/downloads/
```

Back in the SSH window:

```bash
tar -xzf ~/downloads/seedsigner-encryptor.tar.gz -C ~
nohup bash ~/seedsigner-encryptor/pi-setup/pi-setup.sh > ~/setup.log 2>&1 &
tail -f ~/setup.log
```

`nohup` keeps the script running if SSH drops. Expect **3 to 4 hours**: building Python takes about 90 minutes, and SeedSigner's pip packages take over an hour. Press Ctrl+C to stop watching; the script keeps running. Check on it later with `tail ~/setup.log`. If it stops with an error, fix the cause and run the same `nohup` line again. Steps that already finished are skipped.

It's finished when the log ends with `Setup finished.` and shows `message crypto imports OK` a few lines before. If it printed `WARNING: PGPy did not install`, then PGP won't work on this card, but RSA, ML-DSA, and ML-KEM still will.

## Step 6: Switch to keyboard mode

```bash
sudo shutdown -h now
```

Wait for the green LED to stop flashing. Take out the card and, on the PC:

```powershell
powershell -ExecutionPolicy Bypass -File pi-setup\sd-usb-mode.ps1 -Mode host
```

Put the card back. Plug the OTG adapter and keyboard into **USB**, and the power supply into **PWR**. SeedSigner can take up to a minute to appear.

## Keys

The joystick and buttons keep working. The keyboard works at the same time.

| Keyboard | Does |
| --- | --- |
| Arrow keys | Joystick directions |
| Enter | Joystick click |
| F1, F2, F3 | The three buttons (KEY1, KEY2, KEY3) |
| Letters, digits, punctuation, Space | Type text, **only on a message keyboard screen** |
| Backspace | Delete the last character on a message keyboard screen |
| Shift+Enter | New line in a message |
| F3 | **Save** on a message keyboard screen |

Typed letters don't reach the seed-word screen, which uses its own keyboard. Enter the seed with the arrows and Enter, or with the joystick.

## Step 7: Tests

Before you start, print the values you'll compare against. On the PC, from the repository root:

```powershell
cd seedsigner; pip install -r requirements-message.txt; cd ..
python test-data/check-helper.py expected "hello pi"
```

### A. Load the test seed

1. Home, then **Seeds**, then **Enter 12-word seed**.
2. Enter `abandon` eleven times, then `about`. After a few letters, suggestions appear. Accept a suggestion with the matching button.
3. Finish without a passphrase. A passphrase changes every message key.

### B. Check the derived keys

1. On Home, press Right while **Seeds** is highlighted. This opens **Messages**.
2. Choose **View Public Key**, then **RSA sign**, then **Own (Seed)**, then **Show text**.
3. The first time can take several minutes, because the Pi Zero is generating a 2048-bit RSA key.
4. Compare the start of `n` with the `rsa-sign` line that `check-helper.py expected` printed. Scroll with Down to compare the end.
5. Do the same for **ML-DSA (quantum)**.

A match proves the whole derivation on the Pi, from the BIP-39 seed through HKDF to key generation.

### C. Sign a message

1. Choose **Messages**, then **Sign**, then **ML-DSA (quantum)**, then **Own (Seed)**, then **Keyboard**.
2. Type `hello pi` on the USB keyboard and press **F3** (Save).
3. The review screen should say **8 UTF-8 bytes**. Continue, then press **Show QR**.
4. The QR cycles through frames labelled `ssmsg1 1of37`, `2of37`, and so on. These counts assume the default **QR code density** (Medium). If your phone struggles, change **QR code density** or **Message QR speed** under Settings > Advanced.

ML-DSA signing is deterministic, so the Pi's signature must match the PC's. Point your phone's QR reader at frame 1. After `"sig":"`, its text should start with the same 16 characters `check-helper.py` printed.

**Full verify (easier with RSA, which uses 5 frames):** sign with **RSA sign**. Read each frame with the phone and paste the lines into `frames.txt` on the PC, one per line, in any order. Then run:

```powershell
python test-data/check-helper.py verify frames.txt
```

It should print `VALID signature from the test seed`. RSA and PGP signatures change on every run, so verify them this way, not by comparing text.

### D. Encrypt (optional)

Choose **Messages**, then **Encrypt**, then **ML-KEM (quantum)**, then **Contact (preloaded) testseed**, and type a message. The device produces a ciphertext QR. That shows the encrypt path works. Decrypting it needs the ciphertext fed back in, and without a camera you'd have to type the whole envelope.

## Reading the log

The service writes errors to `~/seedsigner.log`. To read it:

1. Go back to the Home screen and pull the power. SeedSigner's own Power off option also just tells you to unplug.
2. Switch the card to `gadget` mode (Step 3).
3. Connect the Pi to the PC as in Step 4 and SSH in. Then run:

```bash
tail -n 50 ~/seedsigner.log
```

To watch errors live, stop the service and run the app by hand. Run this over SSH in gadget mode; there is no keyboard in that mode, so use the joystick:

```bash
sudo systemctl stop seedsigner.service
cd ~/seedsigner-encryptor/seedsigner/src && python3 main.py --usb-keyboard
```

## Troubleshooting

[troubleshoot.md](troubleshoot.md) covers every problem hit so far: the missing drive letter, the COM port, Have Disk refusing the driver, and the missing `g_ncm`. The table below is a quick summary.

| Symptom | Check |
| --- | --- |
| Screen stays black | Wait 60 seconds. Then read the log. Check that SPI is on (`pi-setup.sh` turns it on) and that the HAT is seated. |
| Keyboard does nothing, joystick works | The card is still in gadget mode, the OTG adapter is in PWR, or the adapter is a charge-only type. The log should say `reading keyboard input from /dev/input/event0`. |
| Letters don't type, arrows do | You aren't on a message keyboard screen. That's expected on menus and on seed entry. |
| "Scan QR" crashes or hangs | There's no camera. Use **Enter key** or the preloaded contact instead. |
| `ssh: Could not resolve hostname` | Use the `192.168.137.x` address from `arp -a`. Check that internet sharing points at the Pi's adapter. |
| Setup log stops at `ping` | Internet sharing isn't active. Redo Step 4, items 4 and 5. |

## When you're done testing

This card isn't air-gapped. Leave it in `host` mode, and never load a real seed on it. For hardware closer to the real thing, see `Setup.md`'s "Build a SeedSigner OS image" section. Note that `--usb-keyboard` won't help there: SeedSigner OS has no USB drivers.
