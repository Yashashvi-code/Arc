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
        if system != "Linux":
            return None
        try:
            # Check if clipboard contains an image via wl-paste (Wayland)
            result = subprocess.run(
                ['wl-paste', '--list-types'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            mime_types = result.stdout.strip().split('\n')
            image_type = next((t for t in mime_types if t.startswith('image/')), None)
            if not image_type:
                # Fallback: try xclip for X11
                result = subprocess.run(
                    ['xclip', '-selection', 'clipboard', '-t', 'TARGETS', '-o'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                if 'image/png' in result.stdout:
                    image_type = 'image/png'
            if image_type:
                cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "arc")
                os.makedirs(cache_dir, exist_ok=True)
                img_path = os.path.join(cache_dir, "arc_clip_img.png")
                # Try Wayland first
                try:
                    result = subprocess.run(
                        ['wl-paste', '--type', image_type],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True
                    )
                    if result.returncode == 0 and len(result.stdout) > 0:
                        with open(img_path, 'wb') as f:
                            f.write(result.stdout)
                        return img_path
                except Exception:
                    pass
                # Fallback to xclip
                try:
                    result = subprocess.run(
                        ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    if result.returncode == 0 and len(result.stdout) > 0:
                        with open(img_path, 'wb') as f:
                            f.write(result.stdout)
                        return img_path
                except Exception:
                    pass
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
        
        # Set last_content BEFORE writing to clipboard
        # so wl-paste --watch doesn't echo it back as a new change
        self.last_content = text

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
            self.monitor_thread = Thread(target=self._run_linux_watch, daemon=True)
            self.image_thread = Thread(target=self._run_image_poll, daemon=True)
            self.monitor_thread.start()
            self.image_thread.start()
        else:
            self.monitor_thread = Thread(target=self._run_polling_watch, daemon=True)
            self.monitor_thread.start()
            
        logging.info("Clipboard monitoring started.")

    def _run_image_poll(self):
        """Separate polling loop for image clipboard detection on Wayland."""
        last_image_path = None
        while self.running:
            try:
                result = subprocess.run(
                    ['wl-paste', '--list-types'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True
                )
                mime_types = result.stdout.strip().split('\n')
                image_type = next((t for t in mime_types if t.startswith('image/')), None)
                if image_type:
                    img_path = self.check_and_save_clipboard_image()
                    if img_path and img_path != last_image_path:
                        last_image_path = img_path
                        size = os.path.getsize(img_path)
                        ref = f"FILE_PATH:{img_path}:{size}"
                        if ref != self.last_content:
                            self._handle_change(ref)
                else:
                    last_image_path = None
            except Exception as e:
                logging.error(f"Image poll error: {e}")
            time.sleep(8.0)

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
        try:
            proc = subprocess.Popen(
                ['wl-paste', '--watch', 'cat'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )
            for line in proc.stdout:
                if not self.running:
                    proc.terminate()
                    break
                content = line.strip()
                if content and content != self.last_content:
                    self._handle_change(content)
        except Exception as e:
            logging.error(f"Error in Linux watch: {e}")
            self._run_polling_watch()

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
