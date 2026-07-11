import asyncio
import json
import logging
import os
import base64
from db import ArcDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ArcWsServer:
    def __init__(self, host="127.0.0.1", port=59153, db=None, daemon=None):
        self.host = host
        self.port = port
        self.db = db or ArcDatabase()
        self.daemon = daemon
        self.clients = set()
        self.server = None
        self.loop = None
        self.last_transfer_stats = None

    async def register(self, websocket):
        self.clients.add(websocket)
        logging.info(f"UI Client connected. Total: {len(self.clients)}")
        # Replay last known transfer state so panel isn't blind on reconnect
        if hasattr(self, 'last_transfer_stats') and self.last_transfer_stats:
            await websocket.send(json.dumps(self.last_transfer_stats))
        # Send initial state (clipboard history)
        history = self.db.get_clipboard_history(limit=5)
        initial_state = {
            "event": "clipboard_history",
            "data": history
        }
        await websocket.send(json.dumps(initial_state))

        # Send system info (PC IP & Downloads folder path)
        import socket as py_socket
        def get_local_ip():
            try:
                s = py_socket.socket(py_socket.AF_INET, py_socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except Exception:
                return "127.0.0.1"
        
        downloads_path = str(getattr(getattr(self.daemon, "wifi_server", None), "storage_dir", "Downloads"))
        
        sys_info = {
            "event": "system_info",
            "data": {
                "pc_ip": get_local_ip(),
                "downloads_path": downloads_path
            }
        }
        await websocket.send(json.dumps(sys_info))

    async def unregister(self, websocket):
        if websocket in self.clients:
            self.clients.remove(websocket)
            logging.info(f"UI Client disconnected. Total: {len(self.clients)}")

    async def handler(self, websocket, path=None):
        await self.register(websocket)
        try:
            async for message in websocket:
                try:
                    payload = json.loads(message)
                    action = payload.get("action")
                    
                    if action == "clear_history":
                        self.db.clear_clipboard_history()
                        await self.broadcast("clipboard_history", [])
                        
                    elif action == "sync_text":
                        text = payload.get("text")
                        if text:
                            from clipboard import ArcClipboard
                            ArcClipboard().set_clipboard(text)
                            logging.info(f"Synced text from UI to system clipboard: {text[:30]}...")
                        
                    elif action == "open_file_dialog":
                        # Check paired phone IP
                        phone_host = getattr(self.daemon, "phone_host", None)
                        if phone_host:
                            logging.info("Opening native file dialog in background...")
                            asyncio.create_task(
                                self.async_open_file_dialog(phone_host)
                            )
                        else:
                            logging.error("Cannot open file dialog: No phone IP coordinates paired yet.")
                            await self.broadcast("transfer_stats", {
                                "state": "ERROR",
                                "file_name": "NO PHONE LINK",
                                "progress_percent": 0,
                                "speed_mb": 0.0,
                                "error": "No phone connected. Sync phone coordinates first."
                            })
                            
                    elif action == "send_file_path":
                        file_path = payload.get("file_path")
                        phone_host = getattr(self.daemon, "phone_host", None)
                        if file_path and os.path.exists(file_path) and phone_host:
                            logging.info(f"Initiating transfer of drag-dropped path: {file_path}")
                            asyncio.create_task(
                                self.async_send_to_phone(file_path, phone_host)
                            )
                        elif not phone_host:
                            logging.error("Cannot transfer dropped file: No phone IP coordinates paired yet.")
                            await self.broadcast("transfer_stats", {
                                "state": "ERROR",
                                "file_name": "UNPAIRED",
                                "progress_percent": 0,
                                "speed_mb": 0.0,
                                "error": "No phone connected. Sync coordinates first."
                            })
                except Exception as e:
                    logging.error(f"Error handling UI message: {e}")
        except Exception as e:
            pass
        finally:
            await self.unregister(websocket)

    async def async_open_file_dialog(self, phone_host):
        await asyncio.to_thread(self.choose_file_and_send, phone_host)

    def choose_file_and_send(self, phone_host):
        try:
            import tkinter as tk
            from tkinter import filedialog
            
            # Initialize hidden Tkinter root window
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            
            import os
            file_path = filedialog.askopenfilename(
                title="Select File to Send",
                initialdir=os.path.expanduser("~")
            )
            root.destroy()
            
            if file_path and os.path.exists(file_path):
                logging.info(f"User selected native file: {file_path}")
                # Stream file directly from disk inside background thread
                self.send_file_to_phone(file_path, phone_host)
            else:
                logging.info("File selection cancelled by user.")
        except Exception as e:
            logging.error(f"Failed to open native file dialog: {e}")

    async def async_send_to_phone(self, file_path, phone_host, is_clipboard=False):
        # Wrapper to execute blocking network send inside a thread
        await asyncio.to_thread(self.send_file_to_phone, file_path, phone_host, is_clipboard)

    def send_file_to_phone(self, file_path, phone_host, is_clipboard=False):
        from wifi_client import ArcWifiClient
        file_name = os.path.basename(file_path)
        import time as py_time
        start_time = py_time.time()
        last_time = start_time
        last_bytes = 0
        current_speed = 0.0
        
        def on_progress(bytes_sent, total_size):
            nonlocal last_time, last_bytes, current_speed
            now = py_time.time()
            dt = now - last_time
            elapsed = now - start_time
            if dt >= 0.25:
                db = bytes_sent - last_bytes
                raw_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
                if current_speed == 0.0:
                    current_speed = raw_speed
                else:
                    current_speed = 0.3 * raw_speed + 0.7 * current_speed
                last_time = now
                last_bytes = bytes_sent
            elif current_speed == 0.0 and elapsed > 0:
                current_speed = (bytes_sent / elapsed) / (1024 * 1024)
                
            percent = int((bytes_sent / total_size) * 100)
            asyncio.run_coroutine_threadsafe(
                self.broadcast("transfer_stats", {
                    "state": "TRANSFERRING",
                    "file_name": file_name,
                    "progress_percent": percent,
                    "speed_mb": current_speed
                }),
                self.loop
            )

        client = ArcWifiClient(host=phone_host, port=59152)
        
        # Broadcast connecting
        asyncio.run_coroutine_threadsafe(
            self.broadcast("transfer_stats", {
                "state": "CONNECTING",
                "file_name": file_name,
                "progress_percent": 0,
                "speed_mb": 0.0
            }),
            self.loop
        )

        success = client.send_file(file_path, progress_callback=on_progress, is_clipboard=is_clipboard)

        # Broadcast outcome
        asyncio.run_coroutine_threadsafe(
            self.broadcast("transfer_stats", {
                "state": "SENT" if success else "ERROR",
                "file_name": file_name,
                "progress_percent": 100 if success else 0,
                "speed_mb": 0.0
            }),
            self.loop
        )

        # Log sent file in SQLite database and broadcast history updates
        if success and self.db:
            self.db.insert_clipboard(f"SENT: {file_name}", is_file=True)
            history = self.db.get_clipboard_history(limit=5)
            asyncio.run_coroutine_threadsafe(
                self.broadcast("clipboard_history", history),
                self.loop
            )

        # Clean up temp file ONLY if it resides in the temp workspace directory
        try:
            if "daemon/temp" in file_path.replace("\\", "/") and os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"Cleaned up temporary session drop file: {file_path}")
        except Exception as e:
            logging.error(f"Failed to remove temp file: {e}")

    async def start(self):
        self.loop = asyncio.get_running_loop()
        try:
            import websockets
            self.server = await websockets.serve(self.handler, self.host, self.port)
            logging.info(f"WebSocket IPC server running on ws://{self.host}:{self.port}")
        except ImportError:
            logging.error("websockets package not found. Run 'pip install websockets' in daemon environment.")
        except Exception as e:
            logging.error(f"Failed to start WebSocket server: {e}")

    async def broadcast(self, event: str, data: any):
        if event == "transfer_stats":
            self.last_transfer_stats = {"event": event, "data": data}
        if not self.clients:
            return
            
        payload = json.dumps({
            "event": event,
            "data": data
        })
        
        await asyncio.gather(
            *[client.send(payload) for client in self.clients],
            return_exceptions=True
        )

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logging.info("WebSocket IPC server stopped.")
