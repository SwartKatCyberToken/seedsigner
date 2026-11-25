# Troubleshooting the Pi Zero 1.3 test card

These are the problems hit while setting up the test card from [Updated Setup Guide.md](Updated%20Setup%20Guide.md), with the cause and fix for each. Most are now handled by the scripts in `pi-setup/`. If you see one of them again, check the fix below first.

Setup: Raspberry Pi Zero v1.3 (no WiFi, one USB data port), Raspberry Pi OS Buster Lite 2023-05-03, a Windows 11 PC, and no camera.

## Windows and the SD card

### `sd-usb-mode.ps1`: "Cannot find drive. A drive with the name 'E' does not exist."

**Cause:** the guide used `E` as an example drive letter. Also, after flashing, Windows often gives the SD card's 256 MB `boot` partition no drive letter at all. Disk Management shows the card, but Explorer doesn't.

**Fix:** run the script without `-Drive`:

```powershell
powershell -ExecutionPolicy Bypass -File pi-setup\sd-usb-mode.ps1 -Mode gadget
```

It finds the partition that holds `config.txt`, `cmdline.txt` and `bootcode.bin`. If that partition has no letter, it asks for administrator rights (a Windows prompt) and assigns one. Assigning a letter needs admin rights, so a normal PowerShell can't do it.

**Doing it by hand:** open Disk Management (Win+X), right-click the **256 MB FAT32** partition on the SD card, choose **Change Drive Letter and Paths**, then **Add**.

If Windows offers to **format** the larger partition, click **Cancel**. That partition is the Pi's Linux filesystem.

### The `gadget` line went into a Pi 4-only section

**Cause:** Raspberry Pi OS's `config.txt` ends inside a `[pi4]` section. Any line added at the end applies only to a Pi 4, so a Pi Zero ignores `dtoverlay=dwc2`.

**Fix (already in the script):** `sd-usb-mode.ps1` adds its line in its own `[all]` block, marked `# sd-usb-mode.ps1 gadget`. Host mode removes that block again.

## The Pi doesn't appear as a network adapter

What Windows shows tells you which mode the card is in:

| Device Manager shows | Cause | Fix |
| --- | --- | --- |
| **USB Serial Device (COMx)** under Ports | Old `g_ether` mode. Windows binds that RNDIS device to its serial-port driver. | Re-run `sd-usb-mode.ps1 -Mode gadget` (RNDIS is the default) |
| **Unknown USB Device (Device Descriptor Request Failed)** | The card has `modules-load=dwc2,g_ncm`. This kernel has no `g_ncm` module. The Pi can also show this briefly while booting. | Wait a minute and replug. If it stays, re-run `sd-usb-mode.ps1 -Mode gadget`. |
| **Remote NDIS Compatible Device** / **USB RNDIS Adapter** under Network adapters | Working | Share your internet with it (`ncpa.cpl`, then Sharing) |

### Why picking the RNDIS driver by hand fails

With the old `g_ether` mode, you can try Update driver, then Browse, then Have Disk, then `C:\Windows\INF\rndiscmp.inf`. Windows replies: *"The folder you specified doesn't contain driver software for your device"*. This happens whether or not "Show compatible hardware" is ticked.

`rndiscmp.inf` contains `[ControlFlags] ExcludeFromSelect=*`, which hides "Remote NDIS Compatible Device" from manual selection. Windows only loads that driver when the device asks for it with Microsoft's OS descriptor (compatible ID `RNDIS`, sub-ID `5162001`). The legacy `g_ether` module can't send that descriptor.

Also check the spelling: the file is `rndiscmp.inf`. In the dialog's font, "rn" looks like "m".

### Why not NCM?

Windows 10 (2004 or later) and Windows 11 include an NCM driver, but this Buster 5.10 kernel has no `g_ncm` module. Listing the modules in the image shows `g_ether` but not `g_ncm`. It does include `libcomposite` and `usb_f_rndis`, which the fix below uses.

### The fix: RNDIS with Microsoft OS descriptors

The gadget is now built through configfs instead of `g_ether`. The scripts are in `pi-setup/usb-gadget/`:

- `seedsigner-usb-gadget.sh`: runs at every boot. It creates an RNDIS function that announces compatible ID `RNDIS` / `5162001`, so Windows loads its own driver without asking. It exits without doing anything in host mode.
- `seedsigner-usb-install.sh`: a one-time installer. You can't SSH in before the network works, so `sd-usb-mode.ps1` copies it to the boot partition and adds this to `cmdline.txt`:

  ```text
  systemd.run=/boot/seedsigner-usb-install.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target
  ```

  Raspberry Pi Imager uses the same mechanism for `firstrun.sh`. The Pi runs the installer, removes those words, writes `boot/seedsigner-usb-installed`, and reboots. Allow about 3 minutes for the first boot in gadget mode.

**If it still doesn't appear after 5 minutes and a replug,** put the card in the PC and check:

- whether `cmdline.txt` still contains `systemd.run=`. If it does, the installer didn't finish.
- whether `seedsigner-usb-installed` exists on the boot partition.

`-Gadget ether` brings back the old `g_ether` behaviour if you ever need it.

## Getting in over SSH

| Problem | Fix |
| --- | --- |
| `ssh: Could not resolve hostname raspberrypi.local` | Run `arp -a` on the PC, find the `192.168.137.x` address, and use `ssh pi@192.168.137.x` |
| Pi has no internet (`ping 8.8.8.8` fails, or `pi-setup.sh` stops at its ping check) | In `ncpa.cpl`, open the adapter that has internet, then Properties, then Sharing, and select the Remote NDIS adapter. Then replug the Pi so it gets a `192.168.137.x` address. |
| Pi keeps a `169.254.x.x` address even though sharing is on (common after a Windows restart) | Windows' sharing often stops handing out addresses but still forwards traffic. Give the Pi a fixed address. To test: `sudo ip addr add 192.168.137.2/24 dev usb0; sudo ip route replace default via 192.168.137.1 dev usb0; echo "nameserver 8.8.8.8" \| sudo tee /etc/resolv.conf`, then `ping -c 3 8.8.8.8`. To keep it, add `interface usb0`, `static ip_address=192.168.137.2/24`, `static routers=192.168.137.1` and `static domain_name_servers=8.8.8.8 1.1.1.1` to `/etc/dhcpcd.conf`. If the pings fail, run `Restart-Service SharedAccess` in an administrator PowerShell, or untick and re-tick sharing. |
| Password | `pi` / `raspberry` on this image (its `raspberrypi-sys-mods` predates the 2022 default-user change). Change it with `passwd`. |

## `pi-setup.sh`

Run it under `nohup` so it survives SSH disconnects, and watch it with `tail -f ~/setup.log`:

```bash
nohup bash ~/seedsigner-encryptor/pi-setup/pi-setup.sh > ~/setup.log 2>&1 &
```

| What you see | Meaning |
| --- | --- |
| `E: The repository 'http://raspbian.raspberrypi.org/raspbian buster Release' no longer has a Release file.` (404) | Buster moved to `http://legacy.raspbian.org/raspbian`. `pi-setup.sh` now rewrites `/etc/apt/sources.list` and runs `apt-get update --allow-releaseinfo-change`, because the archive's Suite is now `oldoldstable`. On an older copy of the script, copy the new one over (`scp pi-setup\pi-setup.sh pi@raspberrypi.local:~/seedsigner-encryptor/pi-setup/`) and run it again. |
| Long silence after `Adding 1 GB of temporary swap` | Normal. It's writing 1 GB to the SD card, which takes several minutes on a Pi Zero. |
| Long silence during `Building Python 3.10.10` | Normal. About 90 minutes. |
| `Building wheel for numpy (pyproject.toml): still running...` for a long time | `requirements-raspi.txt` pins `numpy==1.25.0`, which has no ready-built ARMv6 version for Python 3.10, so the Pi Zero compiles it. That can take hours. numpy is only used by the camera stream, so `pi-setup.sh` now skips it unless you run it with `SEEDSIGNER_CAMERA=1`. To stop a build already in progress: `pkill -f pi-setup.sh; pkill -f "pip install"`, then copy the new script over and run the `nohup` line again. Without numpy, the log shows `background import stopped: ModuleNotFoundError` once at start-up. That's harmless: it's the app's optional warm-up step. |
| `WARNING: PGPy did not install` | PGPy needs `cryptography`. Current releases need Rust to build on the Pi Zero's ARMv6 chip, so the script tries 3.3.2, which builds with C only. If that fails too, PGP is unavailable on this card, but RSA, ML-DSA and ML-KEM still work. |
| `libzbar0 … 404` | The upstream guide's `libzbar0_0.23.90-1+deb11u1` link is gone. The scripts use `…+deb11u1+b1_armhf.deb`. |
| PC restarted or slept (e.g. Windows Update) mid-setup | The Pi is powered from the PC's USB port, so it lost power and the script stopped. After the PC is back: (1) open `ncpa.cpl` and check that Internet Connection Sharing is still ticked for the Remote NDIS adapter (Windows sometimes resets it; untick and re-tick), (2) replug the Pi, SSH in, `tail -n 30 ~/setup.log` to see the last step, (3) run the `nohup` line again. The script finishes interrupted package installs (`dpkg --configure -a`), rebuilds a swap file cut short, and redoes the Python build unless it completed (`/usr/local/lib/python3.10/seedsigner-build-ok`). To avoid this, power the Pi from the PWR port with a separate supply during setup; the USB cable then carries only data. |
| Any other error | Fix it, then run the same `nohup` line again. Finished steps are skipped. |

It's finished when the log shows `message crypto imports OK`, then `Setup finished.`

## Keyboard and screen (host mode)

| Problem | Fix |
| --- | --- |
| Keyboard does nothing, joystick works | The card is still in gadget mode (run `sd-usb-mode.ps1 -Mode host`), the OTG adapter is in **PWR** instead of **USB**, or the adapter only carries power. `~/seedsigner.log` should say `reading keyboard input from /dev/input/event0`. |
| Arrows work, letters don't type | Expected outside message keyboard screens. Seed-word entry uses its own keyboard: use the arrows and Enter. |
| Screen stays black | Wait 60 seconds. Check the LCD HAT is seated. `pi-setup.sh` enables SPI. Read the log (below). |
| "Scan QR" fails | There's no camera. Use **Enter key** or a preloaded contact. |

**Reading `~/seedsigner.log`:** pull the power at the Home screen, switch the card to `gadget` mode, connect over USB, SSH in, and run `tail -n 50 ~/seedsigner.log`.

## Corrections to earlier advice

- A USB keyboard does work on this card. Earlier notes said it couldn't, which was true only for the unmodified app. `--usb-keyboard` (`seedsigner/src/seedsigner/hardware/usb_keyboard.py`) adds it.
- `g_ncm` was suggested before the kernel was checked. This image doesn't have it (see above).
- `pycryptodome==4.2.0` is a real PyPI release, so that pin in `requirements-message.txt` is fine.
