# ARC // ECOSYSTEM LINK ENGINE
### v3.0 — Local Subnet Bridge for Linux + Windows + Android

```
    ___    ____  ______
   /   |  / __ \/ ____/
  / /| | / /_/ / /     
 / ___ |/ _, _/ /___   
/_/  |_/_/ |_|\____/   
```

> Zero cloud. Zero account. One command.

Arc bridges your laptop and Android phone over your local network — clipboard sync, file transfer, image sync — all over WiFi and Bluetooth LE. Nothing leaves your subnet.

**v3.0 adds a dynamic multi-drop active transfer queue UI, automated folder zipping for directory drops, local offline font bundling, Compose GPU optimization, and 0% CPU native Win32 ctypes clipboard bindings.**

---

## WHAT IT DOES

- **Clipboard sync** — copy on your laptop, paste on phone. Copy on phone, it's on your laptop.
- **File transfer** — any file, any size. No limit. SHA-256 integrity verified, resume-capable.
- **Image clipboard** — copy a screenshot on your laptop, it lands in your phone clipboard automatically.
- **Live transfer panel** — dot-matrix style desktop UI showing transfer speed, progress, and status in real time.
- **BLE pairing** — tap PAIR once. Both devices exchange IPs and security tokens automatically. Everything works from that point.
- **Security** — Auth token handshake on every TCP connection. No rogue device on your network can interact with Arc.

---

## REQUIREMENTS

**Linux:**
- Ubuntu 22.04+ (tested on 24.04, Wayland)
- Python 3.10+
- Node.js 18+
- Rust + Cargo (via rustup)
- Bluetooth adapter

**Windows:**
- Windows 10/11 (64-bit)
- Python 3.10+ ([python.org](https://python.org))
- Node.js 18+ ([nodejs.org](https://nodejs.org))
- Rust + Cargo (via [rustup.rs](https://rustup.rs))
- Bluetooth adapter

**Android:**
- Android 8.0+
- Bluetooth + WiFi enabled
- Both devices on the same local network

---

## LINUX SETUP

**1. Clone the repo**
```bash
git clone https://github.com/Yashashvi-code/Arc.git
cd Arc
```

**2. Install system dependencies**
```bash
sudo apt update
sudo apt install python3-full python3-tk wl-clipboard xclip \
  libwebkit2gtk-4.1-dev build-essential libssl-dev \
  libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
```

**3. Install Rust** (skip if already installed)
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

**4. Redirect Rust build artifacts** (saves root partition space)
```bash
echo 'export CARGO_TARGET_DIR=/mnt/extra/arc-target' >> ~/.bashrc
source ~/.bashrc
```
> Change `/mnt/extra/` to any partition with at least 3GB free.

**5. Set up Python environment**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r daemon/requirements.txt
```

**6. Build the desktop panel**
```bash
cd panel
npm install
npm run tauri build
cd ..
```
> First build takes 3–5 minutes. Subsequent builds are fast.

**7. Extract the AppImage** (prevents dock pulsating)
```bash
APPIMAGE_PATH=$(find /mnt/extra/arc-target/release/bundle/appimage -name "*.AppImage" 2>/dev/null || \
                find panel/src-tauri/target/release/bundle/appimage -name "*.AppImage" 2>/dev/null)
"$APPIMAGE_PATH" --appimage-extract 2>/dev/null
mv squashfs-root /mnt/extra/arc-panel
```

**8. Open firewall port**
```bash
sudo ufw allow 59152/tcp
```

**9. Add launch alias** (optional but recommended)
```bash
echo "alias arc='~/Arc/start.sh'" >> ~/.bashrc
source ~/.bashrc
```

---

## WINDOWS SETUP

**1. Clone the repo**
```powershell
git clone https://github.com/Yashashvi-code/Arc.git
cd Arc
```

**2. Install Python dependencies**
```powershell
pip install -r daemon/requirements.txt
pip install pystray pillow
```

**3. Open firewall port**

Run PowerShell **as Administrator**:
```powershell
New-NetFirewallRule -DisplayName "Arc Ecosystem" -Direction Inbound -Protocol TCP -LocalPort 59152 -Action Allow
```

**4. Build the desktop panel**
```powershell
cd panel
npm install
npm run tauri build
cd ..
```
> First build takes 3–5 minutes. Rust will be downloaded automatically if needed.
> The built panel binary will be at `panel\src-tauri\target\release\panel.exe`.

**5. Launch Arc**
```powershell
python arc_tray_win.py
```

A white circle icon with a red dot appears in your **system tray** (bottom-right, near the clock). The Arc daemon starts silently in the background. The desktop panel opens automatically after a few seconds and switches to **ONLINE**.

> **No panel.exe yet?** Arc automatically falls back to launching the panel in development mode (`npm run tauri dev`). The first launch in dev mode takes ~30 seconds to compile — the dashboard will show OFFLINE and then flip to ONLINE once the daemon is connected. This is normal.

---

## ANDROID SETUP

The same Android app works with both the Linux and Windows PC daemon.

**1. Enable Developer Options on your phone**

Settings → About Phone → tap **Build Number** 7 times

**2. Enable USB Debugging**

Settings → Developer Options → USB Debugging → **ON**

**3. Connect your phone via USB cable**

**4. Install via ADB** (from Linux or Windows)

Linux:
```bash
sudo apt install adb
```

Windows — ADB is bundled with the Android SDK Platform Tools. If you have Android Studio installed, adb is already available. Otherwise download [Platform Tools](https://developer.android.com/studio/releases/platform-tools).

**5. Build and install the APK**

Linux:
```bash
# Install Java 17 if needed
sudo apt install openjdk-17-jdk

# Set SDK path
echo "sdk.dir=$HOME/.local/share/android-sdk" > android/local.properties

# Build
cd android && chmod +x gradlew && ./gradlew assembleDebug

# Install on phone
adb install app/build/outputs/apk/debug/app-debug.apk
cd ..
```

Windows:
```powershell
# Gradle uses the JDK 17 it downloads automatically via toolchain
cd android
.\gradlew.bat assembleDebug

# Install on phone (using full adb path if needed)
adb install app\build\outputs\apk\debug\app-debug.apk
cd ..
```

> **Signature mismatch error?** (upgrading from a previous install)
> ```
> adb uninstall com.example.arc
> adb install app/build/outputs/apk/debug/app-debug.apk
> ```

---

## RUNNING ARC

**Linux:**
```bash
arc
```
Or directly:
```bash
~/Arc/start.sh
```

**Windows:**
```powershell
python arc_tray_win.py
```
Right-click the tray icon to open the dashboard or quit.

> The panel must be connected (ONLINE) before starting a transfer for live progress to show correctly.

---

## PAIRING YOUR PHONE

1. Make sure both devices are on the **same WiFi network**
2. Start Arc on your laptop
3. Open the Arc app on your phone
4. Tap **PAIR ECOSYSTEM**
5. Wait for status to show **"Ecosystem paired. Laptop IP: x.x.x.x"**

That's it. Both devices now know each other's IPs and have exchanged a security token. Clipboard sync and file transfers are live.

> **BLE not available?** Use **Manual Coordinates** in the app → enter your laptop's IP (shown in the panel as PC IP) and the security token (shown in panel Settings) → tap Sync Ecosystem Coordinates.

> If pairing times out, tap PAIR again. Arc auto-retries.

---

## DAILY USE

| Task | How |
|------|-----|
| Send file to phone | Drag into the drop zone, or click CHOOSE FILE |
| Send file to laptop | Use the file picker in the Arc Android app |
| Sync clipboard text | Copy on laptop — appears on phone automatically |
| Push phone clipboard | Open Arc app → PUSH SYSTEM CLIPBOARD |
| Sync image clipboard | Copy image on laptop — arrives on phone clipboard within 8 seconds |
| Custom text push | Type in the Quick Text box → SYNC TEXT |

**Received files** land in `~/Downloads/` (Linux) or `C:\Users\<you>\Downloads\` (Windows).

---

## PROJECT STRUCTURE

```
Arc/
├── daemon/              # Python backend (cross-platform)
│   ├── src/
│   │   ├── main.py      # Entry point & orchestrator
│   │   ├── ble_server.py    # BLE GATT pairing server
│   │   ├── clipboard.py     # Clipboard monitor (Win32 ctypes + wl-paste)
│   │   ├── db.py            # SQLite ring buffer + auth token store
│   │   ├── wifi_server.py   # TCP file/clipboard receiver
│   │   ├── wifi_client.py   # TCP file/clipboard sender
│   │   └── ws_server.py     # WebSocket IPC → Tauri panel
│   └── requirements.txt
├── panel/               # Tauri desktop UI (builds on Linux + Windows)
│   ├── src/             # HTML + JS frontend
│   └── src-tauri/       # Rust backend
├── android/             # Kotlin Android companion app
│   └── app/src/main/
│       ├── java/com/example/arc/
│       └── res/
├── arc_tray.py          # Linux GTK system tray launcher
├── arc_tray_win.py      # Windows system tray launcher
└── start.sh             # Linux launch script
```

---

## PORTS

| Port | Protocol | Purpose |
|------|----------|---------| 
| 59152 | TCP | File transfer + clipboard over WiFi |
| 59153 | WebSocket | Daemon ↔ Panel IPC (localhost only) |

---

## TECHNICAL NOTES

- **Transfer protocol**: Custom 81-byte TCP header — `[4B magic] [1B type] [16B auth token] [16B session UUID] [8B chunk index] [4B payload length] [32B SHA-256 checksum]`
- **Security**: Auth token generated on first run, stored in SQLite, exchanged invisibly over BLE on every pairing. Every TCP packet is validated against it.
- **Clipboard (Windows)**: Native Win32 `ctypes` bindings for zero-overhead text read/write. PowerShell only spawned when a clipboard image is actually detected.
- **Clipboard (Linux)**: `wl-paste --watch` event-driven model on Wayland. Falls back to `xclip` on X11.
- **Speed**: EMA-smoothed throughput display, updates every 250ms
- **BLE**: Used for device presence and IP/token exchange only. All data goes over WiFi.
- **Storage**: SQLite ring buffer, 200 clipboard entries max, never grows unbounded
- **No cloud**: Everything stays on your local network. No accounts, no telemetry, no analytics.

---

## TROUBLESHOOTING

**Dashboard shows OFFLINE**

Linux:
```bash
source ~/Arc/.venv/bin/activate
cd ~/Arc/daemon && python3 src/main.py
```

Windows:
```powershell
python D:\Arc\daemon\src\main.py
```
Check the output for errors. Common causes: missing pip packages, port 59152 blocked by firewall.

**BLE not advertising**
- Ensure Bluetooth is on and not blocked: `rfkill list` (Linux)
- Arc needs Bluetooth access — run from a user session, not SSH
- On Windows, BLE runs in mock mode if the hardware driver doesn't support GATT server — use Manual Coordinates instead

**Files not arriving on phone**
- Confirm both devices are on the same WiFi network
- Check pairing status — phone should show laptop IP
- Verify port is open: `sudo ufw status` (Linux) / check Windows Firewall for port 59152

**Panel shows READY during transfer**
- Open the panel *before* starting the transfer
- Panel reconnects automatically with exponential backoff (up to 30s)

**Dock icon pulsating** (Linux)
- Run the AppImage extraction step (Step 7 in Linux setup)

**Signature mismatch on APK install**
```
adb uninstall com.example.arc
adb install app-debug.apk
```

---

## CHANGELOG

### v2.0 — 2026-07-15
- **Windows support**: Native system tray launcher (`arc_tray_win.py`), Win32 ctypes clipboard, Windows image clipboard sync via PowerShell
- **Security**: 81-byte TCP auth handshake — random 32-char token generated on setup, exchanged over BLE, verified on every packet
- **Path traversal protection**: Filename sanitization on both PC and Android sides
- **Socket timeouts**: 30-second read/write timeouts on all connections
- **Bug fixes**: `sync_text` daemon crash, cross-filesystem file renames, drag-drop payload mismatch
- **Panel**: Exponential WebSocket reconnect backoff, Content Security Policy, minimum window dimensions
- **Android**: Removed mock transfer history, clean first-launch state

### v1.0 — 2026-07-12
- Initial release: Linux + Android only
- BLE pairing, WiFi file transfer, clipboard sync, Tauri panel

---

*Arc — built for the gap between your devices.*
