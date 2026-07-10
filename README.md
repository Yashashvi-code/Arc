# ARC // ECOSYSTEM LINK ENGINE

```
    ___    ____  ______
   /   |  / __ \/ ____/
  / /| | / /_/ / /     
 / ___ |/ _, _/ /___   
/_/  |_/_/ |_|\____/   
                       
// NOTHING OS STYLED PAIRING & CLIPBOARD BRIDGE
```

**Arc** is a premium, zero-configuration local network utility designed to bridge the gap between Windows/Linux laptops and Android mobile devices. Inspired by the hardware-diagnostic, monochrome design language of Nothing OS, Arc implements a custom high-performance TCP multiplexing protocol that offers lightning-fast file drops and real-time bi-directional clipboard sync.

---

## ⚡ Core Architecture & Highlights

### 1. Zero-Pollution Clipboard Image Sync
*   **Zero Storage Waste**: Unlike generic file-sharing apps that pollute your Downloads directory with every screenshot you sync, Arc handles clipboard image transfers in-memory or inside volatile caches.
*   **Android Integration**: Synced images are saved temporarily to the app's internal cache folder and securely bound to the system clipboard using Android's native `FileProvider` (`com.example.arc.fileprovider`). Once copied, the cache is freed.
*   **Windows Integration**: Incoming phone images are loaded into RAM and written directly to the Windows clipboard buffer using PowerShell bindings, immediately cleaning up temporary disk assets.

### 2. High-Speed Multiplexed Wi-Fi Drops
*   **TCP Multiplexing Protocol**: All transfers (metadata, data streams, clipboard contents) run on a unified TCP socket on port `59152` using a custom 65-byte header:
    `[4 Bytes Magic Magic (ARC\x01)] [1 Byte Type] [16 Bytes Session UUID] [8 Bytes Chunk Index] [4 Bytes Payload Length] [32 Bytes SHA-256 Checksum]`
*   **Checksum Verification**: Every chunk is validated against its SHA-256 checksum in real-time, preventing corruption.
*   **Bit-Perfect Resume Support**: If a connection drops mid-transfer, the receiver reports its current offset, allowing the sender to resume bytes seamlessly without re-uploading from scratch.

### 3. Damped Throughput Indicators (EMA Filter)
*   Network transfer speeds are calculated dynamically and smoothed out in real-time using an **Exponential Moving Average (EMA)** filter (`speed = 0.3 * raw_speed + 0.7 * previous_speed`) throttled to a clean 1.0-second refresh cycle to prevent wild visual fluctuations.

---

## 📱 Features

*   🔄 **Bi-Directional Clipboard Sync**: Instantly share copied text and images between PC and Mobile over local Wi-Fi.
*   🚀 **Unlimited File Drops**: Share files of any size (fully tested on files >5 GB) with dynamic rolling speed metrics.
*   🎨 **Nothing OS Theme**: A hardware-diagnostic user interface featuring dot-matrix fonts, thin geometric lines, and a custom monochrome vector adaptive launcher icon.
*   📶 **Flexible Pairing**: Pair coordinates manually by typing your laptop's local IP or leverage BLE advertising (fully unlocked on Linux).

---

## 🚀 Setup & Installation

### 🖥️ 1. PC Daemon (Windows & Ubuntu Linux)

#### Prerequisites
Ensure Python 3.10+ is installed on your system.

#### Ubuntu/Linux Clipboard setup
Linux requires command-line utilities to interact with X11 or Wayland clipboards. Run:
```bash
sudo apt update
sudo apt install wl-clipboard xclip
```

#### Install Dependencies
From the repository root:
```bash
pip install -r daemon/requirements.txt
```

#### Firewall Rules
*   **Windows (PowerShell as Admin)**:
    ```powershell
    New-NetFirewallRule -DisplayName "Arc WiFi Server" -Direction Inbound -LocalPort 59152 -Protocol TCP -Action Allow -Force
    ```
*   **Ubuntu/Linux (UFW)**:
    ```bash
    sudo ufw allow 59152/tcp
    ```

#### Running the Daemon
*   **Windows**:
    ```cmd
    python daemon/src/main.py
    ```
*   **Ubuntu/Linux (BLE Advertising Unlocked)**:
    ```bash
    sudo python3 daemon/src/main.py
    ```
    *(Running with sudo unlocks raw socket capability for BLE peripheral advertising via BlueZ).*

---

### 🎨 2. PC Desktop UI (Tauri Panel)

The Tauri panel offers a gorgeous desktop monitoring dashboard to clear history, view diagnostic logs, and drag-and-drop files.

#### Prerequisites
*   Node.js 18+
*   Rust Compiler (`cargo`)

#### Run Developer Server
From the `panel/` directory:
```bash
npm install
npm run tauri dev
```

---

### 🤖 3. Android Companion App

The companion app is written in modern **Kotlin + Jetpack Compose**.

#### Build & Deploy APK
Make sure USB debugging is enabled on your phone and run from the `android/` directory:
```cmd
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## 🛠️ Project Structure

```
├── android/               # Jetpack Compose Companion Android App
│   ├── app/src/main/      # App source code, manifest, resources & FileProvider
│   └── build.gradle.kts   # Kotlin gradle dependencies
│
├── daemon/                # Core Python Ecosystem Engine
│   └── src/
│       ├── main.py        # Central coordination engine
│       ├── clipboard.py   # Windows/Linux OS clipboard pollers & injects
│       ├── wifi_server.py # Wi-Fi TCP server (Inbound drops & clipboard)
│       ├── wifi_client.py # Wi-Fi TCP client (Outbound drops & clipboard)
│       └── ws_server.py   # WebSocket server linking daemon to Tauri UI
│
├── panel/                 # Tauri Desktop Dashboard UI
│   ├── src/               # HTML, CSS & JS source
│   └── src-tauri/         # Rust Tauri configuration & backend
│
└── README.md              # Project Documentation
```

---

## 📄 License
Custom studio license. Developed with care for the ultimate Nothing OS experience.
