#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${KRKR_SOURCE_DIR:-$ROOT/vendor/krkrsdl3}"
VCPKG_ROOT="${VCPKG_ROOT:-}"

if [[ ! -f "$SOURCE/CMakePresets.json" || ! -f "$SOURCE/cpp/CMakeLists.txt" ]]; then
    echo "KiriKiri source is missing." >&2
    echo "Run: git submodule update --init --recursive" >&2
    exit 2
fi
if [[ -z "$VCPKG_ROOT" || ! -x "$VCPKG_ROOT/vcpkg" ]]; then
    echo "VCPKG_ROOT must point to a bootstrapped vcpkg installation." >&2
    exit 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/tyranor-krkr-source.XXXXXX")"
cleanup() {
    rm -rf -- "$WORK"
}
trap cleanup EXIT

SOURCE_COPY="$WORK/source"
STAGE="$WORK/release"
mkdir -p "$SOURCE_COPY" "$STAGE"
tar \
    --exclude='.git' \
    --exclude='out' \
    --exclude='vcpkg_installed' \
    -C "$SOURCE" \
    -cf - . | tar -C "$SOURCE_COPY" -xf -

patch -d "$SOURCE_COPY/cpp" -p1 \
    < "$ROOT/packaging/krkrsdl3/patches/0001-save-directory.patch"
patch -d "$SOURCE_COPY/cpp" -p1 \
    < "$ROOT/packaging/krkrsdl3/patches/0002-sdl3-diagnostics.patch"
patch -d "$SOURCE_COPY" -p1 \
    < "$ROOT/packaging/krkrsdl3/patches/0003-sdl3-linux-features.patch"

export VCPKG_ROOT
export VCPKG_OVERLAY_PORTS="$ROOT/packaging/krkrsdl3/vcpkg-overlays"
export KRKR_ALSA_SYSROOT="${KRKR_ALSA_SYSROOT:-/usr}"

(
    cd "$SOURCE_COPY"
    cmake --preset "Linux Config"
    cmake --build --preset "Linux Release Build" --parallel "${KRKR_BUILD_JOBS:-$(nproc)}"
)

install -m0755 "$SOURCE_COPY/out/linux/Release/krkrsdl3" "$STAGE/krkrsdl3"
cp -a "$SOURCE_COPY/Res" "$STAGE/Res"
install -m0644 "$SOURCE_COPY/LICENSE" "$STAGE/LICENSE"
install -m0644 "$SOURCE_COPY/README.md" "$STAGE/README.md"
patchelf --remove-rpath "$STAGE/krkrsdl3"

KRKR_PREBUILT_DIR="$STAGE" "$ROOT/packaging/build-krkr-rpm.sh"
