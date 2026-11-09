#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="tyranor-next-renpy-runtime"
VERSION="8.5.3"
URL="https://www.renpy.org/dl/${VERSION}/renpy-${VERSION}-sdk.tar.bz2"
EXPECTED_SHA256="eb0a9be7f0fb13632fe25ceade9a8bed5a1b4d6b6e83bd19eeeb29e1a1bb4a45"
ARCHIVE="${RENPY_SDK_ARCHIVE:-$ROOT/packaging/cache/renpy-${VERSION}-sdk.tar.bz2}"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tyranor-renpy-rpm.XXXXXX")"

cleanup() {
    rm -rf -- "$BUILD_ROOT"
}
trap cleanup EXIT

mkdir -p "$(dirname "$ARCHIVE")"
if [[ ! -s "$ARCHIVE" ]]; then
    if command -v aria2-next >/dev/null 2>&1; then
        aria2-next -x 8 -s 8 -k 1M --file-allocation=none \
            -d "$(dirname "$ARCHIVE")" -o "$(basename "$ARCHIVE")" "$URL"
    else
        curl -fL --retry 5 --retry-all-errors -o "$ARCHIVE" "$URL"
    fi
fi

ACTUAL_SHA256="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
if [[ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]]; then
    echo "Ren'Py archive checksum mismatch." >&2
    echo "expected: $EXPECTED_SHA256" >&2
    echo "actual:   $ACTUAL_SHA256" >&2
    exit 1
fi

mkdir -p \
    "$BUILD_ROOT/BUILD" \
    "$BUILD_ROOT/BUILDROOT" \
    "$BUILD_ROOT/RPMS" \
    "$BUILD_ROOT/SOURCES" \
    "$BUILD_ROOT/SPECS" \
    "$BUILD_ROOT/SRPMS"
cp "$ARCHIVE" "$BUILD_ROOT/SOURCES/renpy-${VERSION}-sdk.tar.bz2"

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
