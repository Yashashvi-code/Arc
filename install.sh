#!/bin/bash
set -e

ARC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[ ARC ] Installing from $ARC_DIR..."

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "[ERROR] Python3 not found. Install it first."; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "[ERROR] Rust not found. Run: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "[ERROR] Node.js not found. Install Node.js 18+."; exit 1; }

echo "[ ARC ] Installing system dependencies..."
sudo apt install -y \
  python3-full python3-tk python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
  wl-clipboard xclip \
  libwebkit2gtk-4.1-dev build-essential libssl-dev \
  libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev \
  adb 2>/dev/null || true

echo "[ ARC ] Setting up Python environment..."
python3 -m venv "$ARC_DIR/.venv"
source "$ARC_DIR/.venv/bin/activate"
pip install -r "$ARC_DIR/daemon/requirements.txt"
pip install pystray pillow

echo "[ ARC ] Building desktop panel (this takes a few minutes)..."
export CARGO_TARGET_DIR="$HOME/.local/share/arc/target"
cd "$ARC_DIR/panel"
npm install
npm run tauri build
cd "$ARC_DIR"

echo "[ ARC ] Extracting panel..."
APPIMAGE=$(find "$HOME/.local/share/arc/target/release/bundle/appimage" -name "*.AppImage" 2>/dev/null | head -1)
if [ -z "$APPIMAGE" ]; then
    APPIMAGE=$(find "$ARC_DIR/panel/src-tauri/target/release/bundle/appimage" -name "*.AppImage" 2>/dev/null | head -1)
fi
mkdir -p "$HOME/.local/share/arc"
"$APPIMAGE" --appimage-extract 2>/dev/null
mv squashfs-root "$HOME/.local/share/arc/panel"

echo "[ ARC ] Updating panel path..."
sed -i "s|/mnt/extra/arc-panel/AppRun|$HOME/.local/share/arc/panel/AppRun|g" "$ARC_DIR/arc_tray.py"

echo "[ ARC ] Opening firewall port..."
sudo ufw allow 59152/tcp 2>/dev/null || true

echo "[ ARC ] Creating desktop entry..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/arc.desktop" << DESKTOP
[Desktop Entry]
Name=Arc
Comment=Local Ecosystem Link Engine
Exec=$ARC_DIR/.venv/bin/python3 $ARC_DIR/arc_tray.py
Icon=$ARC_DIR/arc.png
Terminal=false
Type=Application
Categories=Utility;Network;
StartupNotify=false
DESKTOP
update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true

echo "[ ARC ] Adding shell alias..."
grep -q "alias arc=" "$HOME/.bashrc" || echo "alias arc='$ARC_DIR/.venv/bin/python3 $ARC_DIR/arc_tray.py &'" >> "$HOME/.bashrc"

echo "[ ARC ] Launching Arc in the background..."
nohup "$ARC_DIR/.venv/bin/python3" "$ARC_DIR/arc_tray.py" > /dev/null 2>&1 &

echo ""
echo "==========================================="
echo "   INSTALL COMPLETED SUCCESSFULLY!"
echo "   Arc is now active in your System Tray!"
echo "==========================================="
echo "[ ARC ] Right-click the tray icon to quit."
