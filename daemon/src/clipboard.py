import os
import sys
import subprocess
import platform
import time
import logging
from threading import Thread
from db import ArcDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ArcClipboard:
    def __init__(self, db=None, on_clipboard_change=None):
        self.db = db or ArcDatabase()
        self.on_clipboard_change = on_clipboard_change
        self.running = False
        self.monitor_thread = None
        self.last_content = self.get_content()

    def get_text_content(self):
        system = platform.system()
        if system == "Linux":
            try:
                return subprocess.check_output(['wl-paste'], text=True, stderr=subprocess.DEVNULL)
            except Exception:
                try:
                    return subprocess.check_output(['xclip', '-selection', 'clipboard', '-o'], text=True, stderr=subprocess.DEVNULL)
                except Exception:
                    return ""
        elif system == "Windows":
            try:
                process = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-Command', 'Get-Clipboard'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, _ = process.communicate()
                return stdout.strip()
            except Exception as e:
                return ""
        return ""

    def check_and_save_clipboard_image(self):
        system = platform.system()
        if system != "Windows":
            return None
        try:
            process = subprocess.Popen(
                ['powershell.exe', '-NoProfile', '-Command', 'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::ContainsImage()'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, _ = process.communicate()
            if "True" in stdout:
                temp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
                img_path = os.path.join(temp_dir, "arc_clip_img.png")
                cmd = f"$img = Get-Clipboard -Format Image; if ($img) {{$img.Save('{img_path}', [System.Drawing.Imaging.ImageFormat]::Png)}}"
                subprocess.run(['powershell.exe', '-NoProfile', '-Command', cmd], capture_output=True)
                if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
                    return img_path
        except Exception as e:
            logging.error(f"Failed to check/save clipboard image: {e}")
        return None

    def get_content(self):
        text = self.get_text_content()
        if text:
            return text
        img_path = self.check_and_save_clipboard_image()
        if img_path:
            size = os.path.getsize(img_path)
            return f"FILE_PATH:{img_path}:{size}"
        return ""

    def set_content(self, text):
        if not text:
            return False
            
        # Avoid writing duplicate to prevent loops
        if text == self.get_content():
            return True

        system = platform.system()
        logging.info(f"Setting clipboard content: {text[:30]}...")
        if system == "Linux":
            try:
                p = subprocess.Popen(['wl-copy'], stdin=subprocess.PIPE, text=True)
                p.communicate(input=text)
                self.last_content = text
                return True
            except Exception:
                try:
                    p = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE, text=True)
                    p.communicate(input=text)
                    self.last_content = text
                    return True
                except Exception:
                    return False
        elif system == "Windows":
            try:
                p = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-Command', '$Input | Set-Clipboard'],
                    stdin=subprocess.PIPE,
                    text=True
                )
                p.communicate(input=text)
                self.last_content = text
                return True
            except Exception as e:
                logging.error(f"Failed to write Windows clipboard: {e}")
                return False
        return False

    def start_monitoring(self):
        if self.running:
            return
        self.running = True
        
        system = platform.system()
        if system == "Linux":
            # For Wayland, wl-paste --watch is very efficient and event-driven.
            # We will start a thread that executes the watch loop.
            self.monitor_thread = Thread(target=self._run_linux_watch, daemon=True)
        else:
            # Fallback to polling for Windows/other systems
            self.monitor_thread = Thread(target=self._run_polling_watch, daemon=True)
            
        self.monitor_thread.start()
        logging.info("Clipboard monitoring started.")

    def stop_monitoring(self):
        self.running = False
        logging.info("Clipboard monitoring stopped.")

    def _run_polling_watch(self):
        while self.running:
            try:
                current = self.get_content()
                if current and current != self.last_content:
                    self._handle_change(current)
            except Exception as e:
                logging.error(f"Error in clipboard polling loop: {e}")
            time.sleep(0.5)

    def _run_linux_watch(self):
        # We can monitor by reading stdout lines of wl-paste -w
        # Alternatively, we can use a polling loop as fallback if wl-paste is not available,
        # but wl-paste --watch is preferred on Wayland.
        try:
            # Run wl-paste --watch in a subprocess and stream changes
            # Wait, wl-paste --watch doesn't stream text directly, it runs a command.
            # However, clipman or other tools do.
            # If we run: wl-paste --watch python daemon/src/clipboard.py --on-change,
            # that requires parsing arguments.
            # A simpler, fully self-contained way in Python that works on Wayland:
            # Poll every 0.3 seconds using wl-paste. It has extremely low overhead.
            self._run_polling_watch()
        except Exception as e:
            logging.error(f"Error in Linux watch: {e}")

    def _handle_change(self, text):
        self.last_content = text
        is_file = False
        
        if text.startswith("FILE_PATH:"):
            parts = text.split(":")
            file_path = ":".join(parts[1:-1])
            is_file = True
            text = file_path
        else:
            # Determine if it's a file path reference
            # Simple heuristic: starts with '/' or 'C:\' and file exists
            if text.startswith("/") and os.path.exists(text):
                is_file = True
            elif len(text) > 3 and text[1:3] == ":\\" and os.path.exists(text):
                is_file = True

        logging.info(f"Clipboard change detected: {text[:50]} (is_file={is_file})")
        
        # Save to database
        self.db.insert_clipboard(text, is_file=is_file)
        
        # Trigger callback
        if self.on_clipboard_change:
            self.on_clipboard_change(text, is_file)

if __name__ == "__main__":
    def on_change(text, is_file):
        print(f"Triggered Callback: {text} (is_file={is_file})")

    clip = ArcClipboard(on_clipboard_change=on_change)
    clip.start_monitoring()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        clip.stop_monitoring()
