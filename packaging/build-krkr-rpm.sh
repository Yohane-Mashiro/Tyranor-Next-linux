#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="tyranor-next-krkr-runtime"
VERSION="0.0.6"
PREBUILT_DIR="${KRKR_PREBUILT_DIR:-${1:-}}"
if [[ -z "$PREBUILT_DIR" ]]; then
    echo "Usage: KRKR_PREBUILT_DIR=/path/to/build-release $0" >&2
    echo "The directory must contain krkrsdl3, Res/ and LICENSE." >&2
    exit 2
fi
PREBUILT_DIR="$(cd "$PREBUILT_DIR" && pwd)"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tyranor-krkr-rpm.XXXXXX")"

cleanup() {
    rm -rf -- "$BUILD_ROOT"
}
trap cleanup EXIT

STAGE="$BUILD_ROOT/stage/krkrsdl3-runtime"
mkdir -p "$STAGE"
install -m0755 "$PREBUILT_DIR/krkrsdl3" "$STAGE/krkrsdl3"
cp -a "$PREBUILT_DIR/Res" "$STAGE/Res"
install -m0644 "$PREBUILT_DIR/LICENSE" "$STAGE/LICENSE"
install -m0644 "$PREBUILT_DIR/README.md" "$STAGE/README.upstream.md"

mkdir -p \
    "$BUILD_ROOT/BUILD" \
    "$BUILD_ROOT/BUILDROOT" \
    "$BUILD_ROOT/RPMS" \
    "$BUILD_ROOT/SOURCES" \
    "$BUILD_ROOT/SPECS" \
    "$BUILD_ROOT/SRPMS"
tar -C "$BUILD_ROOT/stage" -czf \
    "$BUILD_ROOT/SOURCES/krkrsdl3-runtime-${VERSION}-gitbe6db96-linux-x86_64.tar.gz" \
    krkrsdl3-runtime

rpmbuild \
    --define "_topdir $BUILD_ROOT" \
    --define "_sourcedir $BUILD_ROOT/SOURCES" \
    --define "_specdir $ROOT/packaging" \
    --define "_builddir $BUILD_ROOT/BUILD" \
    --define "_buildrootdir $BUILD_ROOT/BUILDROOT" \
    --define "_rpmdir $BUILD_ROOT/RPMS" \
    --define "_srcrpmdir $BUILD_ROOT/SRPMS" \
    -ba "$ROOT/packaging/${NAME}.spec"

mkdir -p "$ROOT/dist/release" "$ROOT/dist/source"
cp "$BUILD_ROOT/RPMS/x86_64/"*.rpm "$ROOT/dist/release/"
cp "$BUILD_ROOT/SRPMS/"*.src.rpm "$ROOT/dist/source/"

echo "Built:"
find "$ROOT/dist" -maxdepth 2 -type f \
    \( -name "${NAME}-${VERSION}*.rpm" -o -name "${NAME}-${VERSION}*.src.rpm" \) \
    -printf '  %p\n' | sort
