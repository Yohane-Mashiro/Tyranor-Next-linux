#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/tyranor-next-linux"
BIN_DIR="$PREFIX/bin"
DESKTOP_DIR="$PREFIX/share/applications"
ICON_ROOT="$PREFIX/share/icons/hicolor"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required." >&2
    exit 1
fi

python3 -m pip install --user -r "$ROOT/requirements.txt"
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR"
cp -a "$ROOT/tyranor" "$APP_DIR/"
cp "$ROOT/README.md" "$ROOT/LICENSE" "$APP_DIR/" 2>/dev/null || true
for size in 16 24 32 48 64 128 256 512; do
    install -Dm0644 \
        "$ROOT/packaging/icons/${size}x${size}/io.github.tyranornext.linux.png" \
        "$ICON_ROOT/${size}x${size}/apps/io.github.tyranornext.linux.png"
    ln -sf io.github.tyranornext.linux.png \
        "$ICON_ROOT/${size}x${size}/apps/tyranor-next.png"
done
install -Dm0644 "$ROOT/tyranor/assets/icon.png" \
    "$ICON_ROOT/1024x1024/apps/io.github.tyranornext.linux.png"
ln -sf io.github.tyranornext.linux.png \
    "$ICON_ROOT/1024x1024/apps/tyranor-next.png"

cat > "$BIN_DIR/tyranor-next" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m tyranor "\$@"
EOF
chmod 755 "$BIN_DIR/tyranor-next"

cat > "$DESKTOP_DIR/tyranor-next.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tyranor Next Linux
Comment=Native Linux multi-engine visual novel launcher
Exec=$BIN_DIR/tyranor-next
TryExec=$BIN_DIR/tyranor-next
Icon=io.github.tyranornext.linux
Terminal=false
Categories=Game;AdventureGame;
StartupNotify=true
StartupWMClass=io.github.tyranornext.linux
EOF
chmod 644 "$DESKTOP_DIR/tyranor-next.desktop"

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true

echo "Installed Tyranor Next Linux to $APP_DIR"
echo "Run: $BIN_DIR/tyranor-next"
