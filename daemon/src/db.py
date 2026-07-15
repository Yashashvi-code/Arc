import sqlite3
import os
import hashlib
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ArcDatabase:
    def __init__(self, db_path=None):
        if db_path is None:
            import os
            db_path = os.path.join(os.path.expanduser("~"), "Arc", "daemon", "storage", "arc.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clipboard (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    hash TEXT UNIQUE NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_file INTEGER DEFAULT 0,
                    expires_at DATETIME
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            conn.commit()
        logging.info("SQLite database initialized successfully.")

    def get_setting(self, key, default=None):
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT value FROM settings WHERE key = ?;", (key,))
                row = cursor.fetchone()
                return row["value"] if row else default
        except Exception as e:
            logging.error(f"Failed to get setting {key}: {e}")
            return default

    def set_setting(self, key, value):
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value;
                """, (key, value))
                conn.commit()
            return True
        except Exception as e:
            logging.error(f"Failed to set setting {key}: {e}")
            return False

    def get_auth_token(self):
        token = self.get_setting("auth_token")
        if not token:
            import secrets
            token = secrets.token_hex(16)
            self.set_setting("auth_token", token)
            logging.info(f"Generated new security auth token: {token}")
        return token

    def insert_clipboard(self, content, is_file=False, expires_minutes=30):
        if not content.strip():
            return False

        # Calculate hash to enforce uniqueness
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        expires_at = None
        if is_file:
            expires_at = (datetime.utcnow() + timedelta(minutes=expires_minutes)).strftime('%Y-%m-%d %H:%M:%S')

        try:
            with self._get_connection() as conn:
                # Insert or update timestamp if already exists (moves it to top of ring buffer)
                conn.execute("""
                    INSERT INTO clipboard (content, hash, is_file, expires_at, timestamp)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(hash) DO UPDATE SET timestamp=CURRENT_TIMESTAMP;
                """, (content, content_hash, 1 if is_file else 0, expires_at))
                
                # Trim buffer to 200 entries (use id as tie-breaker for rapid inserts)
                conn.execute("""
                    DELETE FROM clipboard 
                    WHERE id NOT IN (
                        SELECT id FROM clipboard 
                        ORDER BY timestamp DESC, id DESC 
                        LIMIT 200
                    );
                """)
                conn.commit()
            return True
        except Exception as e:
            logging.error(f"Failed to insert clipboard entry: {e}")
            return False

    def get_clipboard_history(self, limit=200):
        self.cleanup_expired()
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT content, timestamp, is_file, expires_at 
                    FROM clipboard 
                    ORDER BY timestamp DESC, id DESC 
                    LIMIT ?;
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logging.error(f"Failed to retrieve clipboard history: {e}")
            return []

    def clear_clipboard_history(self):
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM clipboard;")
                conn.commit()
            logging.info("Clipboard history cleared in database.")
            return True
        except Exception as e:
            logging.error(f"Failed to clear history: {e}")
            return False

    def cleanup_expired(self):
        try:
            current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    DELETE FROM clipboard 
                    WHERE is_file = 1 AND expires_at < ?;
                """, (current_time,))
                conn.commit()
                if cursor.rowcount > 0:
                    logging.info(f"Cleaned up {cursor.rowcount} expired file clipboard references.")
        except Exception as e:
            logging.error(f"Failed to clean up expired clipboard entries: {e}")

if __name__ == "__main__":
    db = ArcDatabase()
    db.insert_clipboard("Hello world clipboard!")
    db.insert_clipboard("Another clipboard test")
    print(db.get_clipboard_history())
