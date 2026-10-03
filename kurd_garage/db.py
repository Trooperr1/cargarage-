"""Database connection, setup and backups for Kurd Garage."""
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("KURD_GARAGE_DATA", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "kurd_garage.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
KEEP_BACKUPS = 30


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # safe against crashes / power loss
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def secret_key():
    """Random key used to sign login cookies; created once and kept in the data folder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(os.urandom(32).hex())
    with open(path) as f:
        return f.read().strip()


def init_db():
    conn = connect()
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
            ("admin", generate_password_hash("admin123"), "Administrator"),
        )
    conn.commit()
    conn.close()


def backup():
    """Copy the live database to backups/ safely (works while the app is running)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = "kurd_garage_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
    target = os.path.join(BACKUP_DIR, name)
    src = connect()
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    old = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".db"))
    for f in old[:-KEEP_BACKUPS]:
        os.remove(os.path.join(BACKUP_DIR, f))
    return target


def check_integrity():
    conn = connect()
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    return result == "ok" and not fk, result, len(fk)


if __name__ == "__main__":
    import sys

    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "backup":
        print("Backup saved:", backup())
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        ok, result, fk = check_integrity()
        print("Database OK" if ok else f"PROBLEM: {result}, {fk} broken links")
    else:
        print("Database ready at", DB_PATH)
