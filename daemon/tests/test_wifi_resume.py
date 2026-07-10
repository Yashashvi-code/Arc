import os
import subprocess
import time
import hashlib
import uuid
import sys

# Paths
WORKSPACE = "D:/arc"
TEST_DATA_DIR = os.path.join(WORKSPACE, "test_data")
DOWNLOADS_DIR = os.path.join(WORKSPACE, "downloads")
TEMP_DIR = os.path.join(WORKSPACE, "daemon/temp")
DAEMON_SRC = os.path.join(WORKSPACE, "daemon/src")

os.makedirs(TEST_DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

def generate_random_file(path, size_mb):
    print(f"Generating {size_mb}MB random test file at {path}...")
    sha256 = hashlib.sha256()
    with open(path, "wb") as f:
        # Write in 1MB chunks
        for _ in range(size_mb):
            chunk = os.urandom(1024 * 1024)
            f.write(chunk)
            sha256.update(chunk)
    return sha256.hexdigest()

def run_test():
    test_file_path = os.path.join(TEST_DATA_DIR, "test_large_file.bin")
    file_size_mb = 10
    original_hash = generate_random_file(test_file_path, file_size_mb)
    print(f"Original file SHA-256: {original_hash}")

    # 1. Start Server in background
    server_script = os.path.join(DAEMON_SRC, "wifi_server.py")
    print(f"Starting server: {server_script}")
    # Run with python -u to disable log buffering
    server_proc = subprocess.Popen(
        [sys.executable, "-u", server_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    # Wait a bit for server socket to bind
    time.sleep(2)

    # Generate session ID
    session_id = str(uuid.uuid4())
    print(f"Test Session ID: {session_id}")

    client_script = os.path.join(DAEMON_SRC, "wifi_client.py")
    
    try:
        # 2. Start transfer and simulate connection drop at 4MB (4,194,304 bytes)
        drop_bytes = 4 * 1024 * 1024
        print(f"Attempting transfer 1 (simulated drop at {drop_bytes} bytes)...")
        
        # Run client script
        client_res = subprocess.run([
            sys.executable, client_script, test_file_path, session_id, str(drop_bytes)
        ], capture_output=True, text=True)
        
        # Check that it terminated or returned failure (since we simulated a drop)
        print("Transfer 1 output:")
        print(client_res.stderr)
        print(client_res.stdout)
        
        # Verify .part file exists on server side and size is equal to or greater than drop size
        part_file_path = os.path.join(TEMP_DIR, f"{session_id}.part")
        if not os.path.exists(part_file_path):
            print("ERROR: Partial file was not created on the server!")
            return False
            
        part_size = os.path.getsize(part_file_path)
        print(f"Verified partial file size on server: {part_size} bytes")
        if part_size < drop_bytes:
            print(f"ERROR: Partial file size ({part_size}) is smaller than simulated drop offset ({drop_bytes})!")
            return False

        # Wait briefly before resuming
        time.sleep(1)

        # 3. Resume transfer (no drop parameter)
        print("Attempting transfer 2 (resuming)...")
        client_res2 = subprocess.run([
            sys.executable, client_script, test_file_path, session_id
        ], capture_output=True, text=True)
        
        print("Transfer 2 output:")
        print(client_res2.stderr)
        print(client_res2.stdout)

        # 4. Verify completion (with polling to prevent race conditions)
        final_file_path = os.path.join(DOWNLOADS_DIR, "test_large_file.bin")
        success_assembly = False
        for _ in range(50):  # Poll up to 5 seconds
            if os.path.exists(final_file_path):
                success_assembly = True
                break
            time.sleep(0.1)

        if not success_assembly:
            print("ERROR: Assembled file does not exist in downloads directory!")
            # Check if it's still a .part file
            if os.path.exists(part_file_path):
                print(f"Stuck .part file size: {os.path.getsize(part_file_path)} bytes")
            _print_server_output(server_proc)
            return False

        # Calculate final file hash
        print("Verifying final file integrity...")
        sha256 = hashlib.sha256()
        with open(final_file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        final_hash = sha256.hexdigest()
        
        print(f"Final file SHA-256: {final_hash}")
        
        if final_hash == original_hash:
            print("\nSUCCESS: File transfer resumed and assembled bit-perfectly!")
            return True
        else:
            print("\nFAILURE: Checksum mismatch between original and received file!")
            _print_server_output(server_proc)
            return False

    except Exception as e:
        print(f"ERROR: Test execution encountered exception: {e}")
        _print_server_output(server_proc)
        return False

    finally:
        # Cleanup server process
        print("Stopping server process...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            
        # Cleanup files
        print("Cleaning up test files...")
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
        
        # Check if downloaded file exists and remove it
        final_file_path = os.path.join(DOWNLOADS_DIR, "test_large_file.bin")
        if os.path.exists(final_file_path):
            os.remove(final_file_path)
            
        # Clean up session part files
        part_file_path = os.path.join(TEMP_DIR, f"{session_id}.part")
        if os.path.exists(part_file_path):
            os.remove(part_file_path)

def _print_server_output(server_proc):
    # Helper to print server logs
    print("\n--- SERVER OUT ---")
    try:
        # Terminate first so we can read all output without hanging
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except Exception:
            server_proc.kill()
        outs, errs = server_proc.communicate()
        print("STDOUT:")
        print(outs)
        print("STDERR:")
        print(errs)
    except Exception as e:
        print(f"Could not read server logs: {e}")
    print("-------------------\n")

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
