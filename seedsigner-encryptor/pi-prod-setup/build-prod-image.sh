#!/bin/bash
# Builds the production SeedSigner OS image for a Pi Zero 1.3 / Zero W (pi0),
# on Linux. The same build as build-prod-image.ps1 on Windows, plus OS snapshots.
#
#   pi-prod-setup/build-prod-image.sh [options]
#
# --fast                 Build on whatever is in the build volume and rebuild only
#                        what changed: app code, the rootfs overlay, and the kernel
#                        if kernel.config.fragment gained an option. Skips the
#                        snapshot check, so it's your job to know the OS part is
#                        current.
# --full                 Rebuild the OS part from scratch (1-3 hours) without
#                        asking, then save a new snapshot.
# --reset                Delete the build volume first. Downloads are deleted with
#                        it, unless a snapshot brings them back.
# --no-save              Don't save the builder image or a new snapshot to the
#                        conserve library.
# --trust-unsigned       Use library entries that no signature covers yet,
#                        without asking. See "Snapshots" below.
# --preloaded-keys FILE  Repository-relative INI file to ship as the contact
#                        list, for example seedsigner/preloaded-public-keys.ini
#                        (the public test-seed keys). Default: none.
#
# Snapshots: the slow part of the build (Buildroot's toolchain, kernel and
# packages, 1-3 hours, plus all downloads) doesn't depend on the app code. After
# a full build, the build volume is saved to the conserve library as an "OS
# snapshot", keyed by everything the OS part depends on: the Buildroot commit,
# seedsigner-os/ (without the app), and the builder Dockerfiles. The builder
# image is saved as well. A later run, also on a new or reinstalled PC, restores
# the matching snapshot and only adds the app, which takes minutes and needs no
# network. When the OS inputs changed, it asks before a full rebuild.
#
# The library is $HOME/syncthing-p2p-sync-data/restore/conserved (override with
# CONSERVE_ROOT). Entries come from Syncthing peers and backups, so before
# restoring one the script runs "conserve verify" when that command exists (see
# master-tool/backlog/conserve-tool-signing.md). Until then every entry counts
# as unsigned: the script asks, and with no terminal it refuses unless
# --trust-unsigned is given.
#
# Writes pi-prod-setup/output/seedsigner_os.encryptor.pi0.img and its .sha256,
# plus build.log, owned by the user who ran this script (also under sudo).

set -euo pipefail

usage() { sed -n '5,40p' "$0" | sed 's/^# \{0,1\}//'; }

MODE=auto
PRELOADED_KEYS=""
RESET=0
SAVE=1
TRUST_UNSIGNED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --fast) [ "$MODE" = full ] && { echo "--fast and --full can't be used together." >&2; exit 2; }; MODE=fast ;;
        --full) [ "$MODE" = fast ] && { echo "--fast and --full can't be used together." >&2; exit 2; }; MODE=full ;;
        --reset) RESET=1 ;;
        --no-save) SAVE=0 ;;
        --trust-unsigned) TRUST_UNSIGNED=1 ;;
        --preloaded-keys)
            [ $# -ge 2 ] || { echo "--preloaded-keys needs a file." >&2; exit 2; }
            PRELOADED_KEYS="$2"; shift ;;
        --preloaded-keys=*) PRELOADED_KEYS="${1#*=}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="$HERE/output"
WORK_VOLUME=seedsigner-prod-work
CACHE_VOLUME=seedsigner-prod-ccache
BOARD=pi0
# Bump when the snapshot layout or key inputs change.
SNAPSHOT_FORMAT=1
KEY_FILE=.encryptor-os-key

if ! DOCKER_ERROR="$(docker info 2>&1 >/dev/null)"; then
    if [[ "$DOCKER_ERROR" == *"permission denied"* ]]; then
        echo "Docker is running, but $(id -un) may not use it (not in the docker group)." >&2
        echo "Either run: sudo usermod -aG docker $(id -un)   then log out and back in (or run: newgrp docker)" >&2
        echo "or run this script with sudo." >&2
    else
        echo "Docker is not running. Start it: sudo systemctl enable --now docker" >&2
        echo "$DOCKER_ERROR" >&2
    fi
    exit 1
fi

# Under sudo, the output and the library still belong to the user who ran sudo.
OWNER="${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}"
if [ -n "${SUDO_USER:-}" ]; then
    USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
else
    USER_HOME="$HOME"
fi
CONSERVED="${CONSERVE_ROOT:-$USER_HOME/syncthing-p2p-sync-data/restore/conserved}"

for DIR in seedsigner-os seedsigner third_party/dilithium-py third_party/kyber-py; do
    if [ ! -e "$ROOT/$DIR" ]; then
        echo "Missing $DIR in $ROOT." >&2
        exit 1
    fi
done
if [ -z "$(ls -A "$ROOT/third_party/dilithium-py")" ] || [ -z "$(ls -A "$ROOT/third_party/kyber-py")" ]; then
    echo "third_party/dilithium-py or kyber-py is empty. They're part of this repository: restore them with git checkout -- third_party" >&2
    exit 1
fi

if [ -n "$PRELOADED_KEYS" ]; then
    # Relative to /src inside the container, with forward slashes.
    PRELOADED_KEYS="${PRELOADED_KEYS//\\//}"
    if [ ! -f "$ROOT/$PRELOADED_KEYS" ]; then
        echo "Preloaded keys file not found: $ROOT/$PRELOADED_KEYS" >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Keys: what the builder image and the OS part depend on
# ---------------------------------------------------------------------------

sha() { sha256sum | cut -c1-16; }

# The builder Dockerfiles copy nothing from their folders, so they are the
# builder's only inputs (apart from the debian:12 tag, which the stored image pins).
BUILDER_VER="$(cat "$ROOT/seedsigner-os/Dockerfile" "$HERE/Dockerfile" | sha)"
BUILDER="seedsigner-prod-builder:$BUILDER_VER"

BR_COMMIT="$(sed -n 's/^BR_COMMIT=\([0-9a-f]\{40\}\)$/\1/p' "$HERE/build-in-container.sh")"
if [ -z "$BR_COMMIT" ]; then
    echo "Couldn't read BR_COMMIT from build-in-container.sh." >&2
    exit 1
fi

# seedsigner-os/ as build-in-container.sh copies it, minus the app folder (which
# every build replaces) and the docs (which the build doesn't read).
os_tree_hash() {
    (cd "$ROOT/seedsigner-os" && find . -type f \
        ! -path './.git/*' ! -path './opt/buildroot/*' ! -path './output/*' \
        ! -path './buildroot_dl/*' ! -path './opt/rootfs-overlay/opt/*' \
        ! -path './images/*' ! -path './docs/*' -print0 \
        | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | cut -d' ' -f1
}
OS_TREE="$(os_tree_hash)"
KEY_INPUTS="format=$SNAPSHOT_FORMAT
board=$BOARD
buildroot=$BR_COMMIT
seedsigner-os=$OS_TREE
builder=$BUILDER_VER"
OS_KEY="$(printf '%s\n' "$KEY_INPUTS" | sha)"

SNAP_NAME=seedsigner-encryptor-os
SNAP_DIR="$CONSERVED/download/x86_64/$SNAP_NAME/$OS_KEY"
BUILDER_DIR="$CONSERVED/docker/linux-amd64/seedsigner-prod-builder/$BUILDER_VER"

# ---------------------------------------------------------------------------
# Conserve library helpers
# ---------------------------------------------------------------------------

ask_yes() { # $1 question, $2 default (y or n). No terminal: the default.
    local answer
    if [ ! -t 0 ]; then
        [ "$2" = y ]
        return
    fi
    if [ "$2" = y ]; then read -r -p "$1 [Y/n] " answer; else read -r -p "$1 [y/N] " answer; fi
    case "${answer:-$2}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

# Runs conserve as the library's owner, so it reads the right $HOME.
conserve_cmd() {
    if [ -n "${SUDO_USER:-}" ]; then
        sudo -u "$SUDO_USER" env HOME="$USER_HOME" PATH="$USER_HOME/.local/bin:$PATH" conserve "$@"
    else
        PATH="$HOME/.local/bin:$PATH" conserve "$@"
    fi
}

have_verify() {
    conserve_cmd --help 2>/dev/null | grep -q '^  conserve verify '
}

# $1 kind, $2 arch, $3 name, $4 version, $5 what it is (for messages).
# Succeeds when the entry may be used.
trust_entry() {
    local rc=2
    if have_verify; then
        conserve_cmd verify "$1" "$2" "$3" "$4" && rc=0 || rc=$?
    fi
    case "$rc" in
        0) return 0 ;;
        2)
            if [ "$TRUST_UNSIGNED" = 1 ]; then
                echo "Using the unsigned $5 (--trust-unsigned)."
                return 0
            fi
            if [ ! -t 0 ]; then
                echo "The $5 in the conserve library isn't signed, so it isn't used. Pass --trust-unsigned to use it anyway."
                return 1
            fi
            echo "The $5 in the conserve library isn't signed. Anything that can write to"
            echo "a Syncthing peer or a backup could have changed it."
            ask_yes "Use it anyway?" n
            ;;
        *)
            echo "The $5 in the conserve library failed verification, so it isn't used."
            return 1
            ;;
    esac
}

# Same layout as conserve's lockfile.sh: a header-only lock, and the lock's path
# in conservation.index, sorted, under its header.
write_lock_and_index() { # $1 entry directory
    local index="$CONSERVED/conservation.index" rel="${1#"$CONSERVED"/}/conservation.lock" body
    printf 'conservation-lock 1\n' > "$1/conservation.lock"
    body="$(mktemp)"
    if [ -f "$index" ]; then
        grep -v -x -F 'conservation-index 1' "$index" | grep -v '^$' > "$body" || true
    fi
    printf '%s\n' "$rel" >> "$body"
    { printf 'conservation-index 1\n'; LC_ALL=C sort -u "$body"; } > "$index.tmp"
    mv -f "$index.tmp" "$index"
    rm -f "$body"
}

give_back_library() { # $1 entry directory: chown it and the folders this run made
    local dir="$1"
    [ -n "${SUDO_UID:-}" ] || return 0
    while [ "$dir" != "$CONSERVED" ] && [ "$dir" != / ]; do
        chown "$OWNER" "$dir"
        dir="$(dirname "$dir")"
    done
    chown -R "$OWNER" "$1"
    chown "$OWNER" "$CONSERVED/conservation.index"
}

# Runs a command in the builder with the work volume mounted.
in_work() { # $1 extra docker args (string, may be empty), rest: bash -c script
    local extra="$1"; shift
    # shellcheck disable=SC2086
    docker run --rm --security-opt label=disable $extra -v "$WORK_VOLUME:/work" "$BUILDER" -c "$*"
}

# ---------------------------------------------------------------------------
# Builder image
# ---------------------------------------------------------------------------

echo "==> Builder image $BUILDER"
if docker image inspect "$BUILDER" >/dev/null 2>&1; then
    echo "Already on this machine."
elif [ -f "$BUILDER_DIR/image.tar" ] && trust_entry docker linux-amd64 seedsigner-prod-builder "$BUILDER_VER" "builder image"; then
    if ! docker load -i "$BUILDER_DIR/image.tar" >/dev/null 2>&1; then
        echo "The saved builder image could not be loaded. The file in the conserve library is incomplete." >&2
        exit 1
    fi
    echo "Loaded from the conserve library."
else
    echo "Building it (needs the network for debian:12 and apt)."
    docker build -t seedsigner-os-builder "$ROOT/seedsigner-os"
    docker build -t "$BUILDER" -t seedsigner-prod-builder:latest "$HERE"
fi

# ---------------------------------------------------------------------------
# Build volume: reuse it, restore a snapshot, or rebuild the OS part
# ---------------------------------------------------------------------------

if [ "$RESET" = 1 ]; then
    echo "Deleting the $WORK_VOLUME volume"
    docker volume rm "$WORK_VOLUME" >/dev/null 2>&1 || true
fi

# Prints the volume's key, "none" if it holds an OS build without one (made
# before snapshots, or by --fast after a change), or nothing if it's empty.
volume_state() {
    in_work "" "if [ -f /work/$KEY_FILE ]; then cat /work/$KEY_FILE;
                elif [ -d /work/seedsigner-os/output ]; then echo none; fi"
}

restore_snapshot() {
    echo "==> Restoring the OS snapshot $OS_KEY"
    echo "$(du -h "$SNAP_DIR/work.tar.zst" | cut -f1) to unpack. This takes a few minutes."
    in_work "" "find /work -mindepth 1 -maxdepth 1 -exec rm -rf {} +"
    # zstd checks its own frame checksum, so a damaged file fails here. The key
    # is written only after the whole tree unpacked.
    if ! zstd -dc "$SNAP_DIR/work.tar.zst" | in_work "-i" "tar -C /work -xf -"; then
        echo "The OS snapshot could not be unpacked. The file in the conserve library is incomplete." >&2
        in_work "" "find /work -mindepth 1 -maxdepth 1 -exec rm -rf {} +"
        return 1
    fi
    in_work "" "echo $OS_KEY > /work/$KEY_FILE"
}

# 1 when the volume ends up holding the OS part for $OS_KEY.
CURRENT=0
FAST=0
case "$MODE" in
    fast)
        FAST=1
        echo "==> --fast: building on the current build volume"
        ;;
    full)
        echo "==> --full: rebuilding the OS part"
        CURRENT=1
        ;;
    auto)
        STATE="$(volume_state)"
        if [ "$STATE" = "$OS_KEY" ]; then
            echo "==> The build volume holds the current OS part ($OS_KEY). Adding the app."
            FAST=1
            CURRENT=1
        elif [ -f "$SNAP_DIR/work.tar.zst" ] && command -v zstd >/dev/null \
                && trust_entry download x86_64 "$SNAP_NAME" "$OS_KEY" "OS snapshot $OS_KEY" \
                && restore_snapshot; then
            FAST=1
            CURRENT=1
        else
            if [ -n "$STATE" ]; then
                echo "The OS part in the build volume doesn't match the current Buildroot commit,"
                echo "seedsigner-os/ or builder, and there's no usable snapshot for $OS_KEY."
                if ! ask_yes "Rebuild the OS part from scratch (1-3 hours)?" y; then
                    echo "Nothing built. Use --fast to build on the old OS part anyway."
                    exit 1
                fi
            fi
            echo "==> Building the OS part from scratch (1-3 hours)"
            CURRENT=1
        fi
        ;;
esac

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

mkdir -p "$OUT"

# The container runs as root, so give the output back to this user afterwards,
# even if the build fails (build.log is still worth reading).
give_back_output() {
    docker run --rm --security-opt label=disable -v "$OUT:/out" \
        "$BUILDER" -c "chown -R $OWNER /out" >/dev/null 2>&1 || true
}

STARTED=$(date +%s)
trap give_back_output EXIT
if [ "$FAST" = 0 ]; then
    # A half-finished full build must not look like a finished one.
    in_work "" "rm -f /work/$KEY_FILE"
fi
# label=disable: on SELinux hosts (Fedora and similar) the bind mounts are
# otherwise unreadable inside the container. It does nothing elsewhere.
docker run --rm --name seedsigner-prod-build \
    --security-opt label=disable \
    -v "$ROOT:/src:ro" \
    -v "$WORK_VOLUME:/work" \
    -v "$CACHE_VOLUME:/root/.buildroot-ccache" \
    -v "$OUT:/out" \
    -e "FAST=$FAST" \
    -e "PRELOADED_KEYS=$PRELOADED_KEYS" \
    "$BUILDER" /src/pi-prod-setup/build-in-container.sh

if [ "$FAST" = 0 ]; then
    in_work "" "echo $OS_KEY > /work/$KEY_FILE"
fi
MINUTES=$(( ($(date +%s) - STARTED) / 60 ))

# ---------------------------------------------------------------------------
# Save to the conserve library
# ---------------------------------------------------------------------------

if [ "$SAVE" = 1 ] && [ -d "$CONSERVED" ]; then
    # Never replace an entry that is already there: it may be the signed one.
    if [ ! -f "$BUILDER_DIR/image.tar" ]; then
        echo "==> Saving the builder image to the conserve library"
        mkdir -p "$BUILDER_DIR"
        docker save -o "$BUILDER_DIR/image.tar.part" "$BUILDER"
        mv -f "$BUILDER_DIR/image.tar.part" "$BUILDER_DIR/image.tar"
        write_lock_and_index "$BUILDER_DIR"
        give_back_library "$BUILDER_DIR"
        echo "$BUILDER_DIR"
    fi
    if [ "$CURRENT" = 1 ] && [ ! -f "$SNAP_DIR/work.tar.zst" ]; then
        if ! command -v zstd >/dev/null; then
            echo "zstd isn't installed, so no OS snapshot was saved."
        else
            echo "==> Saving the OS snapshot $OS_KEY to the conserve library"
            mkdir -p "$SNAP_DIR"
            # The app folder and finished images are replaced by every build.
            in_work "" "tar -C /work --exclude=./$KEY_FILE \
                --exclude=./seedsigner-os/opt/rootfs-overlay/opt \
                --exclude=./seedsigner-os/images -cf - ." \
                | zstd -q -f -T0 -3 -o "$SNAP_DIR/work.tar.zst.part"
            mv -f "$SNAP_DIR/work.tar.zst.part" "$SNAP_DIR/work.tar.zst"
            {
                echo "SeedSigner Encryptor OS snapshot: the Buildroot build volume after a"
                echo "full $BOARD build, without the app. Restored by pi-prod-setup/build-prod-image.sh."
                echo "Made $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)."
                echo
                printf '%s\n' "$KEY_INPUTS"
            } > "$SNAP_DIR/snapshot.txt"
            write_lock_and_index "$SNAP_DIR"
            give_back_library "$SNAP_DIR"
            echo "$SNAP_DIR ($(du -h "$SNAP_DIR/work.tar.zst" | cut -f1))"
        fi
    fi
elif [ "$SAVE" = 1 ]; then
    echo "No conserve library at $CONSERVED, so nothing was saved there."
fi

echo
echo "Finished in $MINUTES minutes."
echo "Image: $OUT/seedsigner_os.encryptor.pi0.img"
echo "Flash it with Raspberry Pi Imager (Use custom), balenaEtcher or dd."
