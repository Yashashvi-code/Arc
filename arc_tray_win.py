import subprocess
import os
import threading
import time
import sys
import pystray
from PIL import Image, ImageDraw

# Resolve paths relative to this script's location
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DAEMON_PATH = os.path.join(SCRIPT_DIR, "daemon", "src", "main.py")
DAEMON_DIR  = os.path.join(SCRIPT_DIR, "daemon", "src")

# Look for panel.exe in release build target or locally
PANEL_PATHS = [
    os.path.join(SCRIPT_DIR, "panel", "src-tauri", "target", "release", "panel.exe"),
    os.path.join(SCRIPT_DIR, "panel.exe"),
    os.path.join(SCRIPT_DIR, "panel", "panel.exe"),
]
PANEL_PATH = next((p for p in PANEL_PATHS if os.path.exists(p)), PANEL_PATHS[0])

# Find virtual env python or system python
PYTHON_PATHS = [
    os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe"),
    os.path.join(SCRIPT_DIR, "venv", "Scripts", "python.exe"),
    sys.executable,  # Fallback to current running Python interpreter
]
PYTHON_PATH = next((p for p in PYTHON_PATHS if os.path.exists(p)), "python")

daemon_proc = None
panel_proc = None

def start_processes():
    global daemon_proc, panel_proc
    # Launch Python daemon silently without console window showing
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    
    # Inject PYTHONPATH so daemon can import its sibling modules (db, clipboard, etc.)
    daemon_env = os.environ.copy()
    daemon_env["PYTHONPATH"] = DAEMON_DIR
    
    log_file_path = os.path.join(SCRIPT_DIR, "daemon_startup.log")
    try:
        log_file = open(log_file_path, "w", encoding="utf-8")
    except Exception:
        log_file = subprocess.DEVNULL
        
    daemon_proc = subprocess.Popen(
        [PYTHON_PATH, DAEMON_PATH], 
        creationflags=creation_flags,
        env=daemon_env,
        stdout=log_file,
        stderr=subprocess.STDOUT
    )
    
    # Wait for WebSocket server to start before launching UI panel
    # Tauri dev mode needs ~3s to compile and boot
    time.sleep(3.5)
    
    if os.path.exists(PANEL_PATH):
        panel_proc = subprocess.Popen(
            [PANEL_PATH], 
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        # Fallback to running Tauri in dev mode if exe doesn't exist yet
        panel_dir = os.path.join(SCRIPT_DIR, "panel")
        if os.path.exists(panel_dir):
            panel_proc = subprocess.Popen(
                ["npm.cmd", "run", "tauri", "dev"], 
                cwd=panel_dir, 
                creationflags=creation_flags,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )


def stop_processes():
    global daemon_proc, panel_proc
    if daemon_proc and daemon_proc.poll() is None:
        daemon_proc.terminate()
    if panel_proc and panel_proc.poll() is None:
        panel_proc.terminate()

def open_panel(icon, item):
    global panel_proc
    if panel_proc is None or panel_proc.poll() is not None:
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if os.path.exists(PANEL_PATH):
            panel_proc = subprocess.Popen(
                [PANEL_PATH], 
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            panel_dir = os.path.join(SCRIPT_DIR, "panel")
            if os.path.exists(panel_dir):
                panel_proc = subprocess.Popen(
                    ["npm.cmd", "run", "tauri", "dev"], 
                    cwd=panel_dir, 
                    creationflags=creation_flags,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

def quit_arc(icon, item):
    stop_processes()
    icon.stop()

def make_icon():
    # Make a clean Nothing OS themed dot-accent icon for Windows system tray
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # White monospace outline circle
    d.ellipse([16, 16, 48, 48], outline=(255, 255, 255, 255), width=4)
    # Nothing Red dot in center
    d.ellipse([28, 28, 36, 36], fill=(255, 0, 0, 255))
    return img

def main():
    threading.Thread(target=start_processes, daemon=True).start()
    
    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", open_panel, default=True),
        pystray.MenuItem("Quit Arc", quit_arc)
    )
    
    icon = pystray.Icon("Arc", make_icon(), "Arc Ecosystem Link", menu)
    
    # Run the tray icon loop in a background thread so the main thread remains
    # responsive to KeyboardInterrupt (Ctrl+C) signals in Windows PowerShell
    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] KeyboardInterrupt received. Terminating processes and exiting...")
        stop_processes()
        icon.stop()

if __name__ == "__main__":
    main()
