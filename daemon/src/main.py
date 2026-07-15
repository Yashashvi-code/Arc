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
                auth_token = self.db.get_auth_token()
                if is_file:
                    from wifi_client import ArcWifiClient
                    from threading import Thread
                    def send_wifi_image():
                        client = ArcWifiClient(host=phone_host, port=59152, auth_token=auth_token)
                        client.send_file(text, is_clipboard=True)
                    Thread(target=send_wifi_image, daemon=True).start()
                else:
                    from wifi_client import ArcWifiClient
                    from threading import Thread
                    def send_wifi_clipboard():
                        client = ArcWifiClient(host=phone_host, port=59152, auth_token=auth_token)
                        client.send_clipboard(text)
                    Thread(target=send_wifi_clipboard, daemon=True).start()

    def get_local_ip(self):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def handle_coordinates(self, host: str, port: int):
        logging.info(f"IPC Coordinate Sync: Client paired at {host}:{port}")
        self.phone_host = host
        self.phone_port = port
        # Send laptop IP and auth token back to phone over BLE so phone knows where to send files and can authenticate
        if hasattr(self, 'loop') and self.loop:
            laptop_ip = self.get_local_ip()
            auth_token = self.db.get_auth_token()
            payload = f"{laptop_ip}|{auth_token}"
            logging.info(f"Sending laptop IP and auth token to phone: {laptop_ip}")
            asyncio.run_coroutine_threadsafe(
                self.ble_server.notify_pc_ip(payload),
                self.loop
            )
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
        
        # Daemon stays alive — transfer stats are broadcast by wifi_server.py (inbound)
        # and ws_server.py (outbound) as single sources of truth
        try:
            while True:
                await asyncio.sleep(60)
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
