# The same commit always builds the same image

## Problem

"Verify, don't trust" means anyone can rebuild the production image from the repository and get the same SHA-256 as the published one. Today every build gives a different hash. `pi-prod-setup/README.md` lists this as a limit.

Buildroot's reproducible mode is already on (`BR2_REPRODUCIBLE=y` in `seedsigner-os/opt/pi0/configs/pi0_defconfig`). The known source of difference is our own build script. `pi-prod-setup/build-in-container.sh` writes `version.json` with the current time:

```sh
STAMP=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
"name": "encryptor-$(date -u +%Y%m%d)",
"timestamp": "$STAMP"
```

## Done when

1. **Version from the commit:** `version.json` takes its date from the commit being built, not the clock. The container has no `.git` (the repository is mounted read-only without it), so `build-prod-image.sh` and `.ps1` read the commit hash and date on the host and pass them in, for example as `BUILD_COMMIT` and `SOURCE_DATE_EPOCH`. Fill `short_commit_hash` instead of `null`.
2. **`SOURCE_DATE_EPOCH`** is exported into the Buildroot build, so packages that look at it use the same date.
3. **Two builds match:** two clean builds of the same commit, on different machines or at least from an empty `seedsigner-prod-work` volume, give the same `seedsigner_os.encryptor.pi0.img.sha256`. If they don't, compare the images with `diffoscope` and fix each difference.
4. **Docs:** `pi-prod-setup/README.md` drops the "not reproducible" limit and explains how to check a published image against your own build.

## Things that may still differ

- **File modes and order** when copying the app (`copy_tree` already sets modes with `--chmod`).
- **`.pyc` files:** the image test runs Python with `-B`, but check that nothing else writes them.
- **The FAT boot partition:** its timestamps and volume ID.
- **Uncommitted changes:** a build from a working tree with local edits must not claim to be that commit. Mark it as modified.
- **OS snapshots:** an image built on a restored snapshot (see `pi-prod-setup/README.md`) should still match a full build. If it doesn't, the snapshot is leaking state into the image.
