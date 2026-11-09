#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
NAME="tyranor-next-linux"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tyranor-next-rpm.XXXXXX")"

cleanup() {
    rm -rf -- "$BUILD_ROOT"
}
trap cleanup EXIT

mkdir -p \
    "$BUILD_ROOT/BUILD" \
    "$BUILD_ROOT/BUILDROOT" \
    "$BUILD_ROOT/RPMS" \
    "$BUILD_ROOT/SOURCES" \
    "$BUILD_ROOT/SPECS" \
    "$BUILD_ROOT/SRPMS"

tar \
    --exclude-vcs \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='dist' \
    --exclude='.rpmbuild' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.egg-info' \
    --transform="s,^\.,${NAME}-${VERSION}," \
    -C "$ROOT" \
    -czf "$BUILD_ROOT/SOURCES/${NAME}-${VERSION}.tar.gz" \
    .

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
cp "$BUILD_ROOT/RPMS/noarch/"*.rpm "$ROOT/dist/release/"
cp "$BUILD_ROOT/SRPMS/"*.src.rpm "$ROOT/dist/source/"

echo "Built:"
find "$ROOT/dist" -maxdepth 2 -type f \( -name '*.rpm' -o -name '*.src.rpm' \) -printf '  %p\n' | sort
