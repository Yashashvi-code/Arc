import asyncio
import logging
import time
import os
import sys
from threading import Thread

# Import core modules
from db import ArcDatabase
from clipboard import ArcClipboard
from wifi_server import ArcWifiServer
from ble_server import ArcBleServer
from ws_server import ArcWsServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ArcDaemon:
    def __init__(self):
        logging.info("Initializing Arc Ecosystem Daemon...")
        
        # 1. Initialize SQLite Database
        self.db = ArcDatabase()
        
        # 2. Initialize Wi-Fi TCP Server (Quick Drop Receiver)
        self.wifi_server = ArcWifiServer(daemon=self)
        self.wifi_thread = None

        # 3. Initialize WebSocket IPC Server (Tauri Frontend Connector)
        self.ws_server = ArcWsServer(db=self.db, daemon=self)
        
        # 4. Initialize BLE GATT Server (Pairing & Clipboard Control Plane)
        self.ble_server = ArcBleServer(
            db=self.db,
            on_coordinates_received=self.handle_coordinates
        )

        # 5. Initialize Clipboard Monitor (Dual Backend)
        self.clipboard = ArcClipboard(
            db=self.db,
            on_clipboard_change=self.handle_clipboard_change
        )
        self.ble_server.clipboard = self.clipboard

    def handle_clipboard_change(self, text: str, is_file: bool):
        logging.info(f"Broadcast: clipboard changed -> {text[:30]}... (is_file={is_file})")
        
        # We need to run these asyncio coroutines in the main thread loop
        if hasattr(self, 'loop') and self.loop:
            if not is_file:
                asyncio.run_coroutine_threadsafe(
                    self.ble_server.notify_clipboard_change(text), 
                    self.loop
                )
            # Update Tauri Panel UI history
            history = self.db.get_clipboard_history(limit=5)
            asyncio.run_coroutine_threadsafe(
                self.ws_server.broadcast("clipboard_history", history),
                self.loop
            )
            asyncio.run_coroutine_threadsafe(
                self.ws_server.broadcast("clipboard_update", text),
                self.loop
            )
            
            # Synchronize clipboard to phone over Wi-Fi if host is paired
            phone_host = getattr(self, "phone_host", None)
            if phone_host:
                if is_file:
                    asyncio.run_coroutine_threadsafe(
                        self.ws_server.async_send_to_phone(text, phone_host, is_clipboard=True),
                        self.loop
                    )
                else:
                    from wifi_client import ArcWifiClient
                    from threading import Thread
                    def send_wifi_clipboard():
                        client = ArcWifiClient(host=phone_host, port=59152)
                        client.send_clipboard(text)
                    Thread(target=send_wifi_clipboard, daemon=True).start()

    def handle_coordinates(self, host: str, port: int):
        logging.info(f"IPC Coordinate Sync: Client paired at {host}:{port}")
        self.phone_host = host
        self.phone_port = port
        # Notify WebSocket UI of new pairing state
        if hasattr(self, 'loop') and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.ws_server.broadcast("pairing_status", {"connected": True, "ip": host, "strength": "[ |||| ]"}),
                self.loop
            )

    def start_wifi_server(self):
        logging.info("Starting Wi-Fi TCP server thread...")
        self.wifi_thread = Thread(target=self.wifi_server.start, daemon=True)
        self.wifi_thread.start()

    async def run(self):
        # Save current event loop for thread-safe cross-calls
        self.loop = asyncio.get_running_loop()
        
        # 1. Start Wi-Fi TCP Server thread
        self.start_wifi_server()

        # 2. Start WebSocket IPC Server
        await self.ws_server.start()

        # 3. Start BLE GATT Server
        await self.ble_server.start()

        # 4. Start Clipboard Monitor thread
        self.clipboard.start_monitoring()

        logging.info("Arc Daemon fully started. Press Ctrl+C to terminate.")
        
        # Main thread loop: monitor Wi-Fi transfer metrics and broadcast to UI
        try:
            while True:
                # Check for active file transfer speeds and notify UI
                # We can grab metrics from wifi_server sessions
                for session_id, session in list(self.wifi_server.sessions.items()):
                    bytes_received = session.get("bytes_received", 0)
                    total_size = session.get("total_size", 0)
                    file_name = session.get("file_name", "Unknown")
                    
                    if total_size > 0:
                        percent = int((bytes_received / total_size) * 100)
                        
                        # Dynamic speed calculation
                        import time as py_time
                        now = py_time.time()
                        last_time = session.get("last_time", now)
                        last_bytes = session.get("last_bytes", 0)
                        start_time = session.get("start_time", now)
                        
                        dt = now - last_time
                        prev_speed = session.get("speed_mb", 0.0)
                        if dt >= 1.0:
                            db = bytes_received - last_bytes
                            raw_speed = (db / dt) / (1024 * 1024)
                            speed = 0.3 * raw_speed + 0.7 * prev_speed
                            session["last_time"] = now
                            session["last_bytes"] = bytes_received
                            session["speed_mb"] = speed
                        else:
                            speed = prev_speed if prev_speed > 0 else (((bytes_received / (now - start_time)) / (1024 * 1024)) if (now - start_time) > 0 else 0.0)
                            
                        await self.ws_server.broadcast("transfer_stats", {
                            "state": "TRANSFERRING",
                            "file_name": file_name,
                            "progress_percent": percent,
                            "speed_mb": speed
                        })
                
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self):
        logging.info("Shutting down daemon...")
        self.clipboard.stop_monitoring()
        await self.ble_server.stop()
        await self.ws_server.stop()
        logging.info("Clean shutdown completed.")

if __name__ == "__main__":
    daemon = ArcDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        logging.info("Daemon terminated by user.")
