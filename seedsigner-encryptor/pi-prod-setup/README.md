# Production image (SeedSigner OS)

Builds a SeedSigner OS image for a **Pi Zero 1.3 / Zero W** that contains this repository's SeedSigner code (message encryption) and supports a USB keyboard and the USB relay (Arduino Leonardo). Everything compiles in Docker on the PC. The Pi compiles nothing.

For the Raspberry Pi OS test card, see `../pi-dev-setup` instead.

## What goes into the image

| From | What |
| --- | --- |
| `../seedsigner-os` | SeedSigner OS, plus our changes (below) |
| `../seedsigner/src` | The SeedSigner app with `message_crypto` |
| `../third_party/dilithium-py`, `../third_party/kyber-py` | ML-DSA and ML-KEM (pure Python, copied next to the app) |
| PyPI, hash-checked | pycryptodome 4.2.0, PGPy 0.6.0 |
| Buildroot | cryptography 43.0.3, pyasn1 0.4.8 |

Our changes in `../seedsigner-os` (pi0 only):

- `opt/pi0/board/boot_config.txt`: `dtoverlay=dwc2,dr_mode=host`. The USB port works only as a host port, never as a USB device.
- `opt/pi0/board/kernel.config.fragment`: the USB host controller, HID, evdev and CDC-ACM (Leonardo serial). No USB gadget, networking or storage.
- `opt/rootfs-overlay/start.sh`: starts `main.py --usb-keyboard`.
- `opt/rootfs-overlay/etc/mdev.conf`: creates `/dev/input/event*` for the keyboard and `/dev/ttyACM*` for the Leonardos.
- `opt/external-packages/python-pycryptodome`, `python-pgpy`, and `opt/pi0/configs/pi0_defconfig`: the crypto packages.

## Requirements

- Docker, running: Docker Engine on Linux, Docker Desktop on Windows
- About 30 GB free on Docker's disk (`/var/lib/docker` on Linux, usually C: on Windows)
- Internet during the build

On Linux, your user must be able to run `docker` without `sudo`: `sudo usermod -aG docker $USER`, then log out and back in. Otherwise run the script with `sudo`. Podman's `docker` emulation hasn't been tried.

`../seedsigner-os` must have Linux line endings. It was checked out with `core.autocrlf false`; the build stops with instructions if it finds CRLF.

## Build

From the repository root.

Linux:

```bash
pi-prod-setup/build-prod-image.sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File pi-prod-setup\build-prod-image.ps1
```

The first full build takes 1 to 3 hours. The Buildroot checkout, the downloads and the compiled OS are kept in the `seedsigner-prod-work` Docker volume, and the compiler cache in `seedsigner-prod-ccache`, so later builds are faster. Both scripts use the same volumes and the same output folder.

| Linux option | Windows option | Use |
| --- | --- | --- |
| `--fast` | `-Fast` | Builds on whatever is in the volume and rebuilds only what changed: app code, the rootfs overlay, and the kernel if `kernel.config.fragment` gained an option. Don't use it after changing packages or other seedsigner-os configs. On Linux this also skips the snapshot check below. |
| `--full` | (default without `-Fast`) | Rebuilds the OS part from scratch without asking. |
| `--reset` | `-Reset` | Deletes the build volume first, downloads included. On Linux, a snapshot brings them back. |
| `--no-save` | | Doesn't save the builder image or a new snapshot to the conserve library. |
| `--trust-unsigned` | | Uses unsigned conserve library entries without asking (see below). |
| `--preloaded-keys seedsigner/preloaded-public-keys.ini` | `-PreloadedKeys seedsigner\preloaded-public-keys.ini` | Ships that INI file as the contact list. The repository's file holds only the public **test seed** keys. Default: no contacts. |

### OS snapshots (Linux)

Most of the build time is the OS part: Buildroot's toolchain, kernel and packages. It doesn't depend on the app code. On Linux, `build-prod-image.sh` decides for itself whether that part needs rebuilding:

1. **The volume already holds the current OS part:** it adds the app and repacks the image, which takes minutes.
2. **The volume doesn't, but the conserve library has a matching snapshot** (for example on a new or reinstalled PC): it restores the snapshot into the volume, then does the same. No network is needed.
3. **Neither:** it builds the OS part from scratch. If the volume holds an older OS part, it asks first. Without a terminal, it goes ahead.

"Current" is checked with a key made from the Buildroot commit (`BR_COMMIT` in `build-in-container.sh`), the files in `seedsigner-os/` other than the app folder and the docs, and the builder Dockerfiles. These are the inputs a fast build can't pick up.

After a full build, the script saves two entries in the conserve library at `$HOME/syncthing-p2p-sync-data/restore/conserved/`, or `$CONSERVE_ROOT` if set:

| Entry | Contents |
| --- | --- |
| `docker/linux-amd64/seedsigner-prod-builder/<version>/` | The builder image (`image.tar`), so the apt step isn't repeated |
| `download/x86_64/seedsigner-encryptor-os/<key>/` | `work.tar.zst`: the build volume without the app, including the Buildroot checkout and all downloads. `snapshot.txt` lists what the key was made from. |

The snapshot is several GB. Use `--no-save` if you don't want it synced. Old snapshots stay until you delete them. The script never replaces an entry that's already there. If there's no library folder, it saves nothing.

**Trust:** these entries come back from Syncthing peers and backups, and a compiled OS can't be checked against Buildroot's source hashes. Before using an entry, the script runs `conserve verify` if your conserve has that command. The plan is a Merkle tree signed with a Trezor, described in `master-tool/backlog/conserve-tool-signing.md`. A failed check means the entry isn't used. Until signing exists, every entry counts as unsigned: the script asks you, and without a terminal it doesn't use the entry unless you pass `--trust-unsigned`. Refusing an entry only costs time, because the script then builds that part itself.

The Windows script doesn't use snapshots.

On Linux, the script gives the output files back to your user when the build ends, because the container runs as root. It also turns off SELinux labelling for the build container, so the build works on Fedora and similar systems without relabelling the repository.

Before writing the image, the build runs the image's own ARM Python under qemu. It checks that the kernel has the USB keyboard and CDC-ACM drivers built in, that pycryptodome, PGPy, ML-DSA, ML-KEM, the `message_crypto` modules, `usb_keyboard`, `usb_relay` and `termios` import, does an AES-GCM and an ML-KEM round trip, and checks that `main.py` accepts `--usb-keyboard`.

Output in `pi-prod-setup/output/`:

- `seedsigner_os.encryptor.pi0.img`: the image (about 50 MB)
- `seedsigner_os.encryptor.pi0.img.sha256`
- `build.log`

## Flash and run

1. Write `seedsigner_os.encryptor.pi0.img` with Raspberry Pi Imager (**Use custom**) or balenaEtcher. Any SD card size works. On Linux you can also check the hash and write it with `dd`, after finding the card with `lsblk`. Use the whole disk, such as `/dev/sdX`, not a partition such as `/dev/sdX1`:

   ```bash
   cd pi-prod-setup/output
   sha256sum -c seedsigner_os.encryptor.pi0.img.sha256
   sudo dd if=seedsigner_os.encryptor.pi0.img of=/dev/sdX bs=4M conv=fsync status=progress
   ```

2. Put the card in the Pi. Plug the OTG adapter and keyboard into **USB**, and power into **PWR**.
3. SeedSigner starts after about 30 to 60 seconds. The joystick, buttons and keyboard all work. The keys are the same as on the test card.
4. For the USB relay, plug in the Leonardos through the OTG adapter or a hub. See [USB relay](../README.md#usb-relay).

The image runs from RAM and writes nothing to the SD card.

## Limits

- English only: the app copy has no `seedsigner-translations` checkout.
- `version.json` is written by the build (`encryptor-YYYYMMDD`, fork `seedsigner-encryptor`), because the app folder is not a git repository.
- The image hash is not reproducible yet: the version timestamp changes with every build.
- `dilithium-py` and `kyber-py` are prototypes, as on the test card.
