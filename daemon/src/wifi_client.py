import os
import socket
import struct
import hashlib
import json
import logging
import uuid
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MAGIC_BYTES = b"ARC\x01"
HEADER_SIZE = 81

TYPE_METADATA = 0x01
TYPE_DATA = 0x02
TYPE_CANCEL = 0x03

class ArcWifiClient:
    def __init__(self, host="127.0.0.1", port=59152, chunk_size=1024*1024, auth_token=""):
        self.host = host
        self.port = port
        self.chunk_size = chunk_size
        self.auth_token_bytes = bytes.fromhex(auth_token) if auth_token else b"\x00" * 16
        if len(self.auth_token_bytes) != 16:
            self.auth_token_bytes = b"\x00" * 16

    def make_header(self, p_type, session_id, chunk_idx, payload):
        session_uuid_bytes = uuid.UUID(session_id).bytes
        payload_len = len(payload)
        checksum = hashlib.sha256(payload).digest()
        
        header = bytearray()
        header.extend(MAGIC_BYTES)
        header.append(p_type)
        header.extend(self.auth_token_bytes)
        header.extend(session_uuid_bytes)
        header.extend(struct.pack("!Q", chunk_idx))
        header.extend(struct.pack("!I", payload_len))
        header.extend(checksum)
        
        return bytes(header)

    def send_file(self, file_path, session_id=None, simulate_drop_at=None, progress_callback=None, is_clipboard=False):
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return False

        file_name = os.path.basename(file_path)
        total_size = os.path.getsize(file_path)

        if not session_id:
            session_id = str(uuid.uuid4())
            logging.info(f"Generated new session UUID: {session_id}")
        else:
            logging.info(f"Resuming existing session: {session_id}")

        # Connect to server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((self.host, self.port))
            logging.info(f"Connected to server {self.host}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to connect to server: {e}")
            return False

        try:
            # 1. Send Metadata (send empty file_hash to signal incremental hashing mode)
            metadata = {
                "file_name": file_name,
                "total_size": total_size,
                "file_hash": "",
                "is_clipboard": is_clipboard
            }
            metadata_bytes = json.dumps(metadata).encode('utf-8')
            metadata_header = self.make_header(TYPE_METADATA, session_id, 0, metadata_bytes)
            
            sock.sendall(metadata_header)
            sock.sendall(metadata_bytes)
            
            # Read resume offset response (8 bytes, Big-Endian uint64)
            response_bytes = sock.recv(8)
            if len(response_bytes) != 8:
                logging.error("Failed to receive handshake offset from server.")
                return False
                
            offset = struct.unpack("!Q", response_bytes)[0]
            logging.info(f"Server returned resume offset: {offset} bytes")
            
            # Initialize incremental hash
            sha256 = hashlib.sha256()
            if offset > 0:
                logging.info(f"Resuming session: Seeding hash generator with first {offset} bytes...")
                with open(file_path, "rb") as f_seed:
                    bytes_seeded = 0
                    while bytes_seeded < offset:
                        to_read = min(65536, offset - bytes_seeded)
                        seed_chunk = f_seed.read(to_read)
                        if not seed_chunk:
                            break
                        sha256.update(seed_chunk)
                        bytes_seeded += len(seed_chunk)
            
            # 2. Stream Data Chunks
            bytes_sent = offset
            chunk_idx = offset // self.chunk_size
            
            with open(file_path, "rb") as f:
                f.seek(offset)
                
                while bytes_sent < total_size:
                    # Check if we should simulate a drop
                    if simulate_drop_at is not None and bytes_sent >= simulate_drop_at:
                        logging.warning(f"Simulating network drop as requested at {bytes_sent} bytes.")
                        sock.close()
                        return False
                        
                    payload = f.read(self.chunk_size)
                    if not payload:
                        break
                    
                    # Update hash
                    sha256.update(payload)
                    
                    chunk_header = self.make_header(TYPE_DATA, session_id, chunk_idx, payload)
                    sock.sendall(chunk_header)
                    sock.sendall(payload)
                    
                    bytes_sent += len(payload)
                    if progress_callback:
                        try:
                            progress_callback(bytes_sent, total_size)
                        except Exception:
                            pass
                    logging.info(f"Sent chunk {chunk_idx}. Total sent: {bytes_sent}/{total_size} bytes")
                    chunk_idx += 1

            # 3. Send final verification hash packet
            final_hash = sha256.hexdigest()
            logging.info(f"Sending final verification hash: {final_hash}")
            hash_payload = final_hash.encode('utf-8')
            hash_header = self.make_header(0x06, session_id, 0, hash_payload)
            sock.sendall(hash_header)
            sock.sendall(hash_payload)

            logging.info("File transfer complete from client side.")
            return True
            
        except Exception as e:
            logging.error(f"Error during transfer: {e}")
            return False
        finally:
            sock.close()

    def send_clipboard(self, text):
        payload = text.encode('utf-8')
        session_id = str(uuid.uuid4())
        header = self.make_header(0x04, session_id, 0, payload)
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((self.host, self.port))
            sock.sendall(header)
            sock.sendall(payload)
            logging.info(f"Successfully synced clipboard over Wi-Fi: {text[:30]}...")
            return True
        except Exception as e:
            logging.error(f"Failed to sync clipboard over Wi-Fi: {e}")
            return False
        finally:
            sock.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python wifi_client.py <file_path> [session_uuid] [simulate_drop_bytes]")
        sys.exit(1)
        
    f_path = sys.argv[1]
    s_id = sys.argv[2] if len(sys.argv) > 2 else None
    drop_at = int(sys.argv[3]) if len(sys.argv) > 3 else None
    
    client = ArcWifiClient()
    client.send_file(f_path, session_id=s_id, simulate_drop_at=drop_at)
