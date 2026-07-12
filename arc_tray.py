import subprocess
import os
import threading
import time
import pystray
from PIL import Image, ImageDraw

# Force pystray to use GTK backend (Wayland compatible)
os.environ.setdefault("PYSTRAY_BACKEND", "gtk")

DAEMON_PATH = os.path.expanduser("~/Arc/daemon/src/main.py")
PANEL_PATH = "/mnt/extra/arc-panel/AppRun"
PYTHON_PATH = os.path.expanduser("~/Arc/.venv/bin/python3")

daemon_proc = None
panel_proc = None

def start_processes():
    global daemon_proc, panel_proc
    daemon_proc = subprocess.Popen([PYTHON_PATH, DAEMON_PATH])
    time.sleep(3)
    panel_proc = subprocess.Popen([PANEL_PATH])

def stop_processes():
    global daemon_proc, panel_proc
    if daemon_proc and daemon_proc.poll() is None:
        daemon_proc.terminate()
    if panel_proc and panel_proc.poll() is None:
        panel_proc.terminate()

def open_panel(icon, item):
    global panel_proc
    if panel_proc is None or panel_proc.poll() is not None:
        panel_proc = subprocess.Popen([PANEL_PATH])

def quit_arc(icon, item):
    stop_processes()
    icon.stop()

def make_icon():
    img = Image.new("RGB", (64, 64), color=(13, 13, 13))
    d = ImageDraw.Draw(img)
    d.ellipse([16, 16, 48, 48], outline=(255, 255, 255), width=3)
    d.ellipse([28, 28, 36, 36], fill=(255, 255, 255))
    return img

def main():
    threading.Thread(target=start_processes, daemon=True).start()
    menu = pystray.Menu(
        pystray.MenuItem("Open Panel", open_panel, default=True),
        pystray.MenuItem("Quit Arc", quit_arc)
    )
    # ASCII only in title to avoid latin-1 encoding error
    icon = pystray.Icon("Arc", make_icon(), "Arc Link Engine", menu)
    icon.run()

if __name__ == "__main__":
    main()
