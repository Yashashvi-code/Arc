import os
import sys
import time
import shutil
import logging
from datetime import datetime, timedelta

# Setup paths
WORKSPACE = "D:/arc"
DAEMON_SRC = os.path.join(WORKSPACE, "daemon/src")
sys.path.insert(0, DAEMON_SRC)

from db import ArcDatabase
from clipboard import ArcClipboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def test_db_ring_buffer():
    print("\n--- TEST: Database Ring Buffer ---")
    db_test_path = os.path.join(WORKSPACE, "daemon/temp/test_arc.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)
        
    db = ArcDatabase(db_path=db_test_path)
    
    print("Inserting 210 clipboard items...")
    for i in range(210):
        db.insert_clipboard(f"Clipboard entry index {i}")
        
    history = db.get_clipboard_history()
    print(f"Total history entries in database: {len(history)}")
    
    # Assert size is capped at 200
    assert len(history) == 200, f"Error: history size is {len(history)}, expected exactly 200"
    
    # Assert latest item is index 209 (descending order)
    assert history[0]["content"] == "Clipboard entry index 209", f"Error: latest entry is {history[0]['content']}"
    # Assert oldest item is index 10
    assert history[-1]["content"] == "Clipboard entry index 10", f"Error: oldest entry is {history[-1]['content']}"
    
    print("SUCCESS: Ring buffer successfully capped at 200 entries and orders correctly.")
    return db, db_test_path

def test_db_file_expiration(db):
    print("\n--- TEST: File Path Expiration & Cleanup ---")
    
    # Insert regular text
    db.insert_clipboard("Regular text")
    
    # Insert file reference expiring in -1 minutes (already expired)
    db.insert_clipboard("/path/to/expired/file.png", is_file=True, expires_minutes=-5)
    
    # Insert file reference expiring in +10 minutes (valid)
    db.insert_clipboard("/path/to/valid/file.jpg", is_file=True, expires_minutes=10)
    
    # Run cleanup
    db.cleanup_expired()
    
    history = db.get_clipboard_history()
    contents = [row["content"] for row in history]
    
    # Expired file must be removed
    assert "/path/to/expired/file.png" not in contents, "Error: Expired file reference was not cleaned up!"
    # Valid file must remain
    assert "/path/to/valid/file.jpg" in contents, "Error: Valid file reference was deleted!"
    # Text must remain
    assert "Regular text" in contents, "Error: Regular text was deleted during cleanup!"
    
    print("SUCCESS: Expired file references successfully auto-deleted while keeping valid entries.")

def test_clipboard_read_write():
    print("\n--- TEST: System Clipboard Read / Write ---")
    clip = ArcClipboard()
    
    original = clip.get_content()
    print(f"Original system clipboard content: {original[:30]}...")
    
    test_val = "Arc Ecosystem Test copy value - " + str(time.time())
    success = clip.set_content(test_val)
    if not success:
        print("WARNING: Clipboard write is not supported or failed on this shell backend.")
        return
        
    time.sleep(0.5)
    copied = clip.get_content()
    print(f"Read back from system clipboard: {copied}")
    
    assert copied == test_val, f"Error: read back '{copied}' doesn't match written '{test_val}'"
    
    # Restore original content
    clip.set_content(original)
    print("SUCCESS: Clipboard successfully read and write verified.")

if __name__ == "__main__":
    try:
        db, db_path = test_db_ring_buffer()
        test_db_file_expiration(db)
        test_clipboard_read_write()
        
        # Cleanup test db
        time.sleep(1)
        if os.path.exists(db_path):
            # Close connection by deleting reference
            del db
            # Force sqlite journal release by GC
            import gc
            gc.collect()
            os.remove(db_path)
            # Remove wal/shm if present
            if os.path.exists(db_path + "-wal"):
                os.remove(db_path + "-wal")
            if os.path.exists(db_path + "-shm"):
                os.remove(db_path + "-shm")
                
        print("\nALL CLIPBOARD DAEMON TESTS PASSED!")
        sys.exit(0)
    except Exception as e:
        print(f"\nTEST SUITE ENCOUNTERED EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
