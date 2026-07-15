import os
import socket
import struct
import hashlib
import json
import logging
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MAGIC_BYTES = b"ARC\x01"
HEADER_SIZE = 81  # 4 (magic) + 1 (type) + 16 (token) + 16 (uuid) + 8 (chunk_idx) + 4 (length) + 32 (checksum)

# Packet types
TYPE_METADATA = 0x01
TYPE_DATA = 0x02
TYPE_CANCEL = 0x03

class ArcWifiServer:
    def __init__(self, host="0.0.0.0", port=59152, storage_dir=None, temp_dir=None, daemon=None):
        self.host = host
        self.port = port
        self.storage_dir = storage_dir or str(Path.home() / "Downloads")
        self.temp_dir = temp_dir or os.path.join(str(Path.home()), ".arc", "temp")
        self.daemon = daemon
        self.sessions = {}  # session_id (uuid) -> metadata dict
        self.pairing_requests = {}  # client_ip -> (client_socket, threading.Event)
        import threading
        self.requests_lock = threading.Lock()
        
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
 
    def parse_header(self, header_bytes):
        if len(header_bytes) != HEADER_SIZE:
            return None
        
        magic = header_bytes[0:4]
        if magic != MAGIC_BYTES:
            logging.error(f"Invalid magic bytes: {magic}")
            return None
            
        p_type = header_bytes[4]
        token_bytes = header_bytes[5:21]
        
        # Verify auth token if running as daemon (bypass for pairing requests)
        if p_type != 0x05 and self.daemon and hasattr(self.daemon, "db"):
            expected_token = self.daemon.db.get_auth_token()
            expected_bytes = bytes.fromhex(expected_token)
            if token_bytes != expected_bytes:
                logging.error("Unauthorized TCP packet: security token mismatch.")
                return None

        session_uuid_bytes = header_bytes[21:37]
        session_uuid = str(uuid.UUID(bytes=session_uuid_bytes))
        chunk_idx = struct.unpack("!Q", header_bytes[37:45])[0]
        payload_len = struct.unpack("!I", header_bytes[45:49])[0]
        checksum = header_bytes[49:81]
        
        return {
            "type": p_type,
            "session_id": session_uuid,
            "chunk_idx": chunk_idx,
            "payload_len": payload_len,
            "checksum": checksum
        }

    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind((self.host, self.port))
            server_socket.listen(5)
            logging.info(f"Arc WiFi server listening on {self.host}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to bind WiFi server: {e}")
            return

        try:
            while True:
                client_socket, client_address = server_socket.accept()
                logging.info(f"Accepted connection from {client_address}")
                if self.daemon:
                    self.daemon.phone_host = client_address[0]
                    logging.info(f"Auto-paired phone IP coordinates: {client_address[0]}")
                
                import threading
                threading.Thread(
                    target=self.handle_client,
                    args=(client_socket,),
                    daemon=True
                ).start()
        except KeyboardInterrupt:
            logging.info("Shutting down server.")
        finally:
            server_socket.close()

    def receive_all(self, sock, num_bytes):
        data = bytearray()
        while len(data) < num_bytes:
            packet = sock.recv(num_bytes - len(data))
            if not packet:
                return None
            data.extend(packet)
        return bytes(data)

    def handle_client(self, client_socket):
        client_socket.settimeout(30.0)
        try:
            while True:
                header_bytes = self.receive_all(client_socket, HEADER_SIZE)
                if not header_bytes:
                    # Connection closed by client
                    break
                    
                header = self.parse_header(header_bytes)
                if not header:
                    logging.warning("Malformed header or invalid token. Closing connection.")
                    break

                session_id = header["session_id"]
                
                # Handle Metadata Packet (Init / Query Resume)
                if header["type"] == TYPE_METADATA:
                    payload = self.receive_all(client_socket, header["payload_len"])
                    if not payload:
                        logging.error("Failed to read metadata payload.")
                        break
                    
                    # Verify metadata checksum
                    calc_checksum = hashlib.sha256(payload).digest()
                    if calc_checksum != header["checksum"]:
                        logging.error("Metadata checksum mismatch!")
                        break
                    
                    metadata = json.loads(payload.decode('utf-8'))
                    raw_file_name = metadata["file_name"]
                    
                    # Sanitize file_name to prevent path traversal
                    file_name = os.path.basename(raw_file_name)
                    if not file_name or file_name in (".", "..") or "/" in raw_file_name or "\\" in raw_file_name or ".." in raw_file_name:
                        logging.warning(f"Malicious or invalid filename detected: '{raw_file_name}'. Sanitizing to 'safe_transfer'.")
                        file_name = "safe_transfer"
                        
                    total_size = metadata["total_size"]
                    file_hash = metadata.get("file_hash", "")
                    is_clipboard = metadata.get("is_clipboard", False)
                    
                    logging.info(f"Metadata received for session {session_id}: {file_name} ({total_size} bytes, is_clip={is_clipboard})")
                    
                    # Check for existing partial file to resume
                    part_file_path = os.path.join(self.temp_dir, f"{session_id}.part")
                    offset = 0
                    if os.path.exists(part_file_path):
                        offset = os.path.getsize(part_file_path)
                        logging.info(f"Found partial file. Resume offset: {offset} bytes")
                    
                    # Save session state
                    import time as py_time
                    self.sessions[session_id] = {
                        "file_name": file_name,
                        "total_size": total_size,
                        "file_hash": file_hash,
                        "is_clipboard": is_clipboard,
                        "part_file_path": part_file_path,
                        "bytes_received": offset,
                        "start_time": py_time.time(),
                        "last_time": py_time.time(),
                        "last_bytes": offset
                    }
                    
                    # Respond to sender with the resume offset
                    # Response format: !Q (8 bytes for offset)
                    response = struct.pack("!Q", offset)
                    client_socket.sendall(response)
                    logging.info(f"Sent handshake resume response offset: {offset}")
                    
                # Handle Data Chunk Packet
                elif header["type"] == TYPE_DATA:
                    session = self.sessions.get(session_id)
                    if not session:
                        # Session state lost (e.g. server restarted mid-transfer)
                        part_file_path = os.path.join(self.temp_dir, f"{session_id}.part")
                        if os.path.exists(part_file_path):
                            bytes_received = os.path.getsize(part_file_path)
                        else:
                            bytes_received = 0
                        session = {
                            "part_file_path": part_file_path,
                            "bytes_received": bytes_received
                        }
                        self.sessions[session_id] = session

                    payload = self.receive_all(client_socket, header["payload_len"])
                    if not payload:
                        logging.error("Failed to read chunk payload.")
                        break
                    
                    # Verify chunk checksum
                    calc_checksum = hashlib.sha256(payload).digest()
                    if calc_checksum != header["checksum"]:
                        logging.error(f"Chunk {header['chunk_idx']} checksum mismatch! Rejecting.")
                        break
                    
                    # Write chunk to the partial file
                    part_file_path = session["part_file_path"]
                    with open(part_file_path, "ab") as f:
                        f.write(payload)
                    
                    session["bytes_received"] += len(payload)

                    # Broadcast inbound progress to panel
                    if self.daemon and self.daemon.loop and "total_size" in session:
                        import asyncio
                        import time as py_time
                        total = session["total_size"]
                        received = session["bytes_received"]
                        percent = int((received / total) * 100) if total > 0 else 0
                        now = py_time.time()
                        dt = now - session.get("last_time", now)
                        db = received - session.get("last_bytes", 0)
                        raw_speed = (db / dt) / (1024 * 1024) if dt > 0 else 0
                        speed = 0.3 * raw_speed + 0.7 * session.get("current_speed", 0.0)
                        session["current_speed"] = speed
                        session["last_time"] = now
                        session["last_bytes"] = received
                        asyncio.run_coroutine_threadsafe(
                            self.daemon.ws_server.broadcast("transfer_stats", {
                                "session_id": session_id,
                                "state": "RECEIVING",
                                "file_name": session.get("file_name", ""),
                                "progress_percent": percent,
                                "speed_mb": speed
                            }),
                            self.daemon.loop
                        )

                    # If total size reached and we already have the hash (legacy mode), finalize
                    if "total_size" in session and session["bytes_received"] >= session["total_size"]:
                        if session.get("file_hash"):
                            self.finalize_file(session_id)
                            break

                elif header["type"] == 0x04: # CLIPBOARD
                    payload = self.receive_all(client_socket, header["payload_len"])
                    if not payload:
                        break
                    
                    # Verify checksum
                    calc_checksum = hashlib.sha256(payload).digest()
                    if calc_checksum != header["checksum"]:
                        logging.error("Clipboard checksum mismatch! Rejecting.")
                        break
                        
                    text = payload.decode('utf-8')
                    logging.info(f"Received clipboard content over Wi-Fi: {text[:30]}")
                    
                    if self.daemon:
                        import asyncio
                        # Update PC clipboard safely without triggering loopback
                        self.daemon.clipboard.set_content(text)
                        
                        # Save to database
                        self.daemon.db.insert_clipboard(text, is_file=False)
                        
                        # Notify WebSocket UI
                        if self.daemon.loop:
                            history = self.daemon.db.get_clipboard_history(limit=5)
                            asyncio.run_coroutine_threadsafe(
                                self.daemon.ws_server.broadcast("clipboard_history", history),
                                self.daemon.loop
                            )
                            asyncio.run_coroutine_threadsafe(
                                self.daemon.ws_server.broadcast("clipboard_update", text),
                                self.daemon.loop
                            )
                    break

                elif header["type"] == 0x05:  # PAIR_REQUEST
                    import threading
                    client_ip = client_socket.getpeername()[0]
                    logging.info(f"Incoming Wi-Fi pairing request from {client_ip}")
                    
                    event = threading.Event()
                    with self.requests_lock:
                        self.pairing_requests[client_ip] = (client_socket, event)
                    
                    if self.daemon and self.daemon.loop:
                        import asyncio
                        asyncio.run_coroutine_threadsafe(
                            self.daemon.ws_server.broadcast("pairing_request", {"ip": client_ip}),
                            self.daemon.loop
                        )
                        
                    # Wait up to 30 seconds for user approval in panel
                    approved = event.wait(timeout=30.0)
                    if not approved:
                        logging.warning(f"Pairing request from {client_ip} timed out or was rejected.")
                        try:
                            client_socket.sendall(b"REJECTED")
                        except Exception:
                            pass
                    
                    with self.requests_lock:
                        if client_ip in self.pairing_requests:
                            del self.pairing_requests[client_ip]
                    break

                elif header["type"] == 0x06:  # HASH_VERIFY
                    session = self.sessions.get(session_id)
                    if not session:
                        break
                        
                    payload = self.receive_all(client_socket, header["payload_len"])
                    if not payload:
                        break
                        
                    # Verify payload checksum
                    calc_checksum = hashlib.sha256(payload).digest()
                    if calc_checksum != header["checksum"]:
                        logging.error("Hash verify packet checksum mismatch!")
                        break
                        
                    file_hash = payload.decode('utf-8')
                    session["file_hash"] = file_hash
                    logging.info(f"Verification hash received for session {session_id}: {file_hash}")
                    
                    self.finalize_file(session_id)
                    break

                elif header["type"] == TYPE_CANCEL:
                    logging.info(f"Cancel request received for session {session_id}")
                    part_file_path = os.path.join(self.temp_dir, f"{session_id}.part")
                    if os.path.exists(part_file_path):
                        os.remove(part_file_path)
                    if session_id in self.sessions:
                        del self.sessions[session_id]
                    break

        except Exception as e:
            logging.error(f"Error handling client: {e}")
        finally:
            client_socket.close()

    def finalize_file(self, session_id):
        session = self.sessions.get(session_id)
        if not session:
            logging.warning(f"Finalize failed: session {session_id} not found in state.")
            return
            
        part_file_path = session["part_file_path"]
        file_name = session.get("file_name", f"downloaded_{session_id}")
        is_clipboard = session.get("is_clipboard", False)
        
        logging.info(f"Verifying final integrity for: {file_name} (Part path: {part_file_path})")
        
        # Verify complete file hash if we have it
        expected_hash = session.get("file_hash", "")
        logging.info(f"Expected file hash: {expected_hash}")
        if expected_hash:
            logging.info("Calculating SHA-256 hash of the partial file...")
            sha256 = hashlib.sha256()
            try:
                with open(part_file_path, "rb") as f:
                    while chunk := f.read(8192):
                        sha256.update(chunk)
                calc_hash = sha256.hexdigest()
                logging.info(f"Calculated file hash: {calc_hash}")
                if calc_hash != expected_hash:
                    logging.error(f"Integrity check failed! Expected hash: {expected_hash}, calculated: {calc_hash}")
                    if os.path.exists(part_file_path):
                        try:
                            os.remove(part_file_path)
                            logging.info("Deleted corrupted partial file from temp storage.")
                        except Exception as rm_err:
                            logging.error(f"Failed to delete corrupted file: {rm_err}")
                    if self.daemon and self.daemon.loop:
                        asyncio.run_coroutine_threadsafe(
                            self.daemon.ws_server.broadcast("transfer_stats", {
                                "session_id": session_id,
                                "state": "ERROR",
                                "file_name": file_name,
                                "progress_percent": 0,
                                "speed_mb": 0.0,
                                "error": "Integrity check failed"
                            }),
                            self.daemon.loop
                        )
                    return
            except Exception as e:
                logging.error(f"Failed to verify integrity hash: {e}")
                if os.path.exists(part_file_path):
                    try:
                        os.remove(part_file_path)
                        logging.info("Deleted corrupted partial file from temp storage after exception.")
                    except Exception as rm_err:
                        logging.error(f"Failed to delete corrupted file: {rm_err}")
                if self.daemon and self.daemon.loop:
                    asyncio.run_coroutine_threadsafe(
                        self.daemon.ws_server.broadcast("transfer_stats", {
                            "session_id": session_id,
                            "state": "ERROR",
                            "file_name": file_name,
                            "progress_percent": 0,
                            "speed_mb": 0.0,
                            "error": f"Integrity check exception: {str(e)}"
                        }),
                        self.daemon.loop
                    )
                return
                
        if is_clipboard:
            try:
                import subprocess
                import shutil
                import platform
                system = platform.system()
                
                cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "arc")
                os.makedirs(cache_dir, exist_ok=True)
                img_dest = os.path.join(cache_dir, file_name)
                shutil.move(part_file_path, img_dest)
                
                if system == "Linux":
                    with open(img_dest, 'rb') as f:
                        subprocess.run(
                            ['wl-copy', '--type', 'image/png'],
                            stdin=f,
                            stderr=subprocess.DEVNULL
                        )
                    logging.info("Synced phone image to Linux clipboard.")
                elif system == "Windows":
                    ps_cmd = (
                        "Add-Type -AssemblyName System.Windows.Forms; "
                        "Add-Type -AssemblyName System.Drawing; "
                        f"$img = [System.Drawing.Image]::FromFile('{img_dest}'); "
                        "[System.Windows.Forms.Clipboard]::SetImage($img); "
                        "$img.Dispose();"
                    )
                    subprocess.run(
                        ['powershell.exe', '-NoProfile', '-Command', ps_cmd],
                        stderr=subprocess.DEVNULL
                    )
                    logging.info("Synced phone image to Windows clipboard.")

                if self.daemon and self.daemon.db:
                    self.daemon.db.insert_clipboard("RCVD: CLIPBOARD IMAGE", is_file=True)
                    if self.daemon.loop:
                        import asyncio
                        history = self.daemon.db.get_clipboard_history(limit=5)
                        asyncio.run_coroutine_threadsafe(
                            self.daemon.ws_server.broadcast("clipboard_history", history),
                            self.daemon.loop
                        )
                        asyncio.run_coroutine_threadsafe(
                            self.daemon.ws_server.broadcast("clipboard_update", "Image synced from phone."),
                            self.daemon.loop
                        )
            except Exception as e:
                logging.error(f"Failed to copy synced image to clipboard: {e}")

            if session_id in self.sessions:
                del self.sessions[session_id]
            return

        # Move file to storage
        import shutil
        base, extension = os.path.splitext(file_name)
        dest_path = os.path.join(self.storage_dir, file_name)
        counter = 1
        logging.info(f"Checking destination path availability: {dest_path}")
        while os.path.exists(dest_path):
            dest_path = os.path.join(self.storage_dir, f"{base}_{counter}{extension}")
            counter += 1
            
        logging.info(f"Moving {part_file_path} to {dest_path}...")
        try:
            shutil.move(part_file_path, dest_path)
            logging.info(f"File transfer complete. Saved to {dest_path}")
            if self.daemon and self.daemon.db:
                final_name = os.path.basename(dest_path)
                self.daemon.db.insert_clipboard(f"RCVD: {final_name}", is_file=True)
        except Exception as e:
            logging.error(f"Move failed: {e}")
            logging.error(f"Rename failed: {e}")
        
        # Broadcast completion to panel
        if self.daemon and self.daemon.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self.daemon.ws_server.broadcast("transfer_stats", {
                    "session_id": session_id,
                    "state": "COMPLETED",
                    "file_name": file_name,
                    "progress_percent": 100,
                    "speed_mb": 0.0
                }),
                self.daemon.loop
            )

        # Cleanup session
        if session_id in self.sessions:
            del self.sessions[session_id]
            logging.info(f"Cleaned up session {session_id} state.")

    def approve_pairing(self, ip):
        with self.requests_lock:
            if ip in self.pairing_requests:
                client_socket, event = self.pairing_requests[ip]
                try:
                    auth_token = self.daemon.db.get_auth_token()
                    # Send auth token (32 bytes) back to phone
                    client_socket.sendall(auth_token.encode('utf-8'))
                    logging.info(f"Pairing request approved for {ip}. Sent auth token.")
                    # Set phone host IP coordinates
                    self.daemon.phone_host = ip
                    if hasattr(self.daemon, 'loop') and self.daemon.loop:
                        import asyncio
                        asyncio.run_coroutine_threadsafe(
                            self.daemon.ws_server.broadcast("pairing_status", {"connected": True, "ip": ip, "strength": "[ |||| ]"}),
                            self.daemon.loop
                        )
                except Exception as e:
                    logging.error(f"Failed to send pairing token: {e}")
                event.set()

    def reject_pairing(self, ip):
        with self.requests_lock:
            if ip in self.pairing_requests:
                client_socket, event = self.pairing_requests[ip]
                try:
                    client_socket.sendall(b"REJECTED")
                    logging.info(f"Pairing request rejected for {ip}.")
                except Exception:
                    pass
                event.set()

if __name__ == "__main__":
    server = ArcWifiServer()
    server.start()
