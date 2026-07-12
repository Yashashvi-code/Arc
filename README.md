# ARC // ECOSYSTEM LINK ENGINE
### v1.0 — Local Subnet Bridge for Linux + Android

```
    ___    ____  ______
   /   |  / __ \/ ____/
  / /| | / /_/ / /     
 / ___ |/ _, _/ /___   
/_/  |_/_/ |_|\____/   
```

> Zero cloud. Zero account. One command.

Arc bridges your Linux laptop and Android phone over your local network — clipboard sync, file transfer, image sync — all over WiFi and Bluetooth LE. Nothing leaves your subnet.

---

## WHAT IT DOES

- **Clipboard sync** — copy on Linux, paste on phone. Copy on phone, open Arc, it's there on Linux.
- **File transfer** — any file, any size. No limit. SHA-256 integrity verified, resume-capable.
- **Image clipboard** — copy a screenshot on Linux, it lands in your phone clipboard automatically.
- **Live transfer panel** — dot-matrix style desktop UI showing transfer speed, progress, and status in real time.
- **BLE pairing** — tap PAIR once. Both devices exchange IPs automatically. Everything works from that point.

---

## REQUIREMENTS

**Linux:**
- Ubuntu 22.04+ (tested on 24.04, Wayland)
- Python 3.10+
- Node.js 18+
- Rust + Cargo (installed via rustup)
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

## ANDROID SETUP

**Install the APK via USB**

1. Enable **Developer Options** on your phone:
   Settings → About Phone → tap Build Number 7 times

2. Enable **USB Debugging**:
   Settings → Developer Options → USB Debugging → ON

3. Connect your phone via USB cable

4. Install ADB if not already installed:
```bash
sudo apt install adb
```

5. Install the Arc APK:
```bash
adb install android/app/build/outputs/apk/debug/app-debug.apk
```

> If you get a signature mismatch error (upgrading from a previous install):
> ```bash
> adb uninstall com.example.arc
> adb install android/app/build/outputs/apk/debug/app-debug.apk
> ```

> If you don't have a prebuilt APK, build it first:
> ```bash
> sudo apt install openjdk-17-jdk
> echo "sdk.dir=/mnt/extra/android-sdk" > android/local.properties
> cd android && chmod +x gradlew && ./gradlew assembleDebug
> cd ..
> ```

---

## RUNNING ARC

```bash
arc
```

Or directly:
```bash
~/Arc/start.sh
```

This starts the daemon and opens the desktop panel. **Ctrl+C** stops everything cleanly.

> The panel must be open before starting a transfer for live progress to show correctly.

---

## PAIRING YOUR PHONE

1. Make sure both devices are on the same WiFi network
2. Start Arc on your laptop (`arc`)
3. Open the Arc app on your phone
4. Tap **PAIR**
5. Wait for status to show **"Ecosystem paired. Laptop IP: x.x.x.x"**

That's it. Both devices now know each other's IPs. Clipboard sync and file transfers are live.

> If pairing times out, tap PAIR again. Arc auto-retries.
> If BLE isn't available, use **Manual Coordinates** → enter your laptop's IP (shown in the panel as PC IP) → tap Sync Ecosystem Coordinates.

---

## DAILY USE

| Task | How |
|------|-----|
| Send file to phone | Drag into the drop zone, or click CHOOSE FILE |
| Send file to laptop | Use the file picker in the Arc Android app |
| Sync clipboard text | Copy on Linux — appears on phone automatically |
| Push phone clipboard | Open Arc app → PUSH SYSTEM CLIPBOARD |
| Sync image clipboard | Copy image on Linux — arrives on phone clipboard within 8 seconds |

**Received files** on Linux land in `~/Downloads/`

---

## PROJECT STRUCTURE

```
Arc/
├── daemon/              # Python backend
│   ├── src/
│   │   ├── main.py      # Entry point
│   │   ├── ble_server.py
│   │   ├── clipboard.py
│   │   ├── db.py
│   │   ├── wifi_server.py
│   │   ├── wifi_client.py
│   │   └── ws_server.py
│   └── requirements.txt
├── panel/               # Tauri desktop UI
│   ├── src/             # HTML + JS frontend
│   └── src-tauri/       # Rust backend
├── android/             # Kotlin Android app
│   └── app/src/main/
│       ├── java/com/example/arc/
│       └── res/
└── start.sh             # Launch script
```

---

## PORTS

| Port | Protocol | Purpose |
|------|----------|---------|
| 59152 | TCP | File transfer + clipboard over WiFi |
| 59153 | WebSocket | Daemon ↔ Panel IPC |

---

## TECHNICAL NOTES

- **Transfer protocol**: Custom 65-byte TCP header with SHA-256 per-chunk integrity check and resume support
- **Speed**: EMA-smoothed throughput display, updates every 250ms
- **BLE**: Used for device presence and pairing only. All data goes over WiFi.
- **Clipboard**: Text syncs via BLE. Images sync via WiFi TCP with `is_clipboard` flag.
- **Storage**: SQLite ring buffer, 200 clipboard entries max, never grows unbounded
- **No cloud**: Everything stays on your local network. No accounts, no telemetry.

---

## TROUBLESHOOTING

**Daemon won't start**
```bash
source ~/Arc/.venv/bin/activate
cd ~/Arc/daemon && python3 src/main.py
```

**BLE not advertising**
- Ensure Bluetooth is on and not blocked: `rfkill list`
- Arc needs Bluetooth access — run from a user session, not SSH

**Files not arriving on phone**
- Confirm both devices are on the same WiFi network
- Check pairing status — phone should show laptop IP
- Verify port is open: `sudo ufw status`

**Panel shows READY during transfer**
- Open the panel *before* starting the transfer
- Panel auto-reconnects within 500ms if it loses the WebSocket

**Dock icon pulsating**
- Run the AppImage extraction step (Step 7 in setup)

---

*Arc — built for the gap between your devices.*
