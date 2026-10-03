"""Database connection, setup, settings and backups for Kurd Garage."""
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_VERSION = 3


def _default_data_dir():
    # Keep the data outside the program folder, so installing a new version never touches it.
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, "KurdGarage")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "kurd_garage")


DATA_DIR = os.environ.get("KURD_GARAGE_DATA") or _default_data_dir()
DB_PATH = os.path.join(DATA_DIR, "garage.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DEFAULT_BACKUP_DIR = (os.path.join(DATA_DIR, "backups") if os.environ.get("KURD_GARAGE_DATA")
                      else os.path.join(os.path.expanduser("~"), "Documents", "Kurd Garage Backups"))
KEEP_BACKUPS = 60

DEFAULT_SETTINGS = {
    "garage_name": "Kurd Garage",
    "street": "", "house_number": "", "postcode": "", "city": "", "canton": "", "country": "CH",
    "phone": "", "email": "", "website": "",
    "uid": "",                       # CHE-123.456.789 MWST
    "iban": "",                      # for QR-bill
    "bank_name": "",
    "vat_registered": "1",
    "vat_rate": "8.1",               # Swiss standard rate since 2024
    "hourly_rate": "13500",          # Rappen, excl. VAT
    "payment_days": "30",
    "round_5_rappen": "1",
    "reminder_fee_2": "2000",        # Rappen
    "reminder_fee_3": "3000",
    "reminder_days": "10",
    "tyre_storage_fee": "9000",
    "invoice_footer": "Thank you for your trust. We look forward to seeing you again.",
    "quote_valid_days": "30",
    "mfk_warn_days": "60",
    "backup_dir": "",
    "last_backup": "",
    # public website
    "web_slogan": "Your car. Our passion.",
    "web_intro": "Service, repairs, MFK, tyres, used cars and parts — all in one place. Honest prices, fast work, Swiss quality.",
    "web_whatsapp": "",
    "web_map_lat": "47.3769",
    "web_map_lon": "8.5417",
    "web_hours": '{"1": [["07:30", "12:00"], ["13:15", "18:00"]], "2": [["07:30", "12:00"], ["13:15", "18:00"]], '
                 '"3": [["07:30", "12:00"], ["13:15", "18:00"]], "4": [["07:30", "12:00"], ["13:15", "18:00"]], '
                 '"5": [["07:30", "12:00"], ["13:15", "17:00"]], "6": [["09:00", "13:00"]], "0": []}',
    "web_owner": "",
    "web_founded": "",
    "web_instagram": "", "web_facebook": "", "web_tiktok": "", "web_google_reviews": "",
    "web_stats": "2'500+ | cars serviced\n4.9 ★ | Google rating\n24 h | average repair time\n12 | months warranty on repairs",
    "web_brands": "Volkswagen, Audi, BMW, Mercedes-Benz, Toyota, Škoda, Ford, Opel, Hyundai, Kia, Renault, Peugeot",
    "web_reviews": "Daniel M. | 5 | Fast, honest and fair prices. My car passed the MFK without any problem.\n"
                   "Sarah K. | 5 | They explained everything and called me before doing extra work. Highly recommended!",
    "web_netlify_token": "",
    "web_netlify_site": "",
    "web_last_build": "",
    "web_last_publish": "",
}

DEFAULT_WEB_SERVICES = [
    ("🛠️", "Service & maintenance", 18900, "2–3 h", "Service according to the manufacturer's plan. Oil, filters, checks — your service book is stamped and your warranty stays valid.", "All brands\nOriginal-quality parts\nDigital service record"),
    ("🚦", "MFK preparation & inspection", 12000, "1 day", "We check and prepare your car and take it to the road traffic office for you. No stress, no queue.", "Pre-check of all MFK points\nPresentation at the office\nRepairs only after your OK"),
    ("🛞", "Tyres & tyre hotel", 8000, "45 min", "Tyre change, balancing and storage of your summer or winter wheels in our tyre hotel. Tyre sales of all brands.", "Change incl. balancing\nStorage per season\nTread depth check"),
    ("🛑", "Brakes", 16000, "1–2 h", "Brake pads, discs and brake fluid. Free brake check with every service.", "Pads & discs\nBrake fluid change\nFree brake check"),
    ("💻", "Diagnosis & electronics", 8000, "30–60 min", "Engine light on? We read the fault memory with professional diagnosis tools and find the real problem.", "All brands\nEngine & airbag lights\nClear explanation"),
    ("❄️", "Air conditioning service", 14900, "1 h", "Cleaning, disinfection and refill of your air conditioning for cool air and fresh smell.", "Refrigerant refill\nLeak test\nDisinfection"),
    ("🔧", "Repairs", 0, "on request", "Clutch, timing belt, suspension, exhaust, engine — we repair it at a fair price with a quote before we start.", "Free quote\n12 months warranty\nCourtesy car on request"),
    ("🔋", "Battery & electrics", 4000, "30 min", "Battery test and replacement, lights, starter and alternator.", "Battery test\nReplacement same day\nLights & bulbs"),
    ("🚗", "Bodywork & glass", 0, "on request", "Small dents, scratches, windscreen chips and replacement — with insurance handling.", "Insurance cases\nWindscreen repair\nPaint touch-ups"),
    ("✨", "Cleaning & detailing", 7900, "2 h", "Interior and exterior cleaning — your car comes back like new.", "Interior cleaning\nHand wash\nSeat cleaning"),
]


def migrate(conn):
    """Bring an older database up to the current version (never deletes data)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(parts)")}
    for col, decl in [("web_show", "INTEGER NOT NULL DEFAULT 0"), ("web_category", "TEXT"),
                      ("web_fits", "TEXT"), ("web_image", "TEXT")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE parts ADD COLUMN {col} {decl}")

DEFAULT_SERVICES = [
    ("OIL", "Oil service (oil + filter change)", 1.0, None),
    ("SERV-S", "Small service according to manufacturer", 1.5, None),
    ("SERV-L", "Large service according to manufacturer", 3.0, None),
    ("TYRE", "Tyre change (4 wheels, incl. balancing)", 1.0, 8000),
    ("TYRE-ST", "Tyre storage per season (tyre hotel)", 0.25, 4500),
    ("MFK-PREP", "MFK preparation and check", 1.5, None),
    ("MFK", "MFK presentation at road traffic office", 1.0, 12000),
    ("BRAKE-F", "Replace front brake pads and discs", 1.5, None),
    ("BRAKE-R", "Replace rear brake pads and discs", 1.5, None),
    ("BRAKE-FL", "Brake fluid change", 0.75, None),
    ("AC", "Air conditioning service", 1.0, 14900),
    ("DIAG", "Electronic diagnosis / fault reading", 0.5, None),
    ("WIPER", "Replace wiper blades", 0.25, None),
    ("BATT", "Battery test and replacement", 0.5, None),
    ("WASH", "Car wash / interior cleaning", 1.0, None),
    ("ENV", "Disposal / environmental fee", 0.1, 950),
]


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
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
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = connect()
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    migrate(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
            ("admin", generate_password_hash("admin123"), "Administrator"),
        )
    if conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
        conn.executemany("INSERT INTO services (code, name, hours, fixed_price) VALUES (?, ?, ?, ?)",
                         DEFAULT_SERVICES)
    if conn.execute("SELECT COUNT(*) FROM web_services").fetchone()[0] == 0:
        conn.executemany("INSERT INTO web_services (sort, icon, name, price, time, text, points) VALUES (?,?,?,?,?,?,?)",
                         [(i, *row) for i, row in enumerate(DEFAULT_WEB_SERVICES)])
    conn.commit()
    conn.close()


def get_settings(conn):
    return {r["key"]: r["value"] or "" for r in conn.execute("SELECT key, value FROM settings")}


def backup_dir(conn=None):
    own = conn is None
    conn = conn or connect()
    path = get_settings(conn).get("backup_dir") or DEFAULT_BACKUP_DIR
    if own:
        conn.close()
    return path


def backup():
    """Save the database and all uploaded files into one ZIP (safe while the program runs)."""
    conn = connect()
    target_dir = backup_dir(conn)
    os.makedirs(target_dir, exist_ok=True)
    name = "kurd_garage_" + datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".zip"
    target = os.path.join(target_dir, name)
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "garage.db")
        dst = sqlite3.connect(copy)
        with dst:
            conn.backup(dst)
        dst.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy, "garage.db")
            if os.path.isdir(UPLOAD_DIR):
                for f in os.listdir(UPLOAD_DIR):
                    z.write(os.path.join(UPLOAD_DIR, f), "uploads/" + f)
    conn.execute("UPDATE settings SET value = ? WHERE key = 'last_backup'", (date.today().isoformat(),))
    conn.commit()
    conn.close()
    old = sorted(f for f in os.listdir(target_dir) if f.startswith("kurd_garage_") and f.endswith(".zip"))
    for f in old[:-KEEP_BACKUPS]:
        os.remove(os.path.join(target_dir, f))
    return target


def list_backups():
    path = backup_dir()
    if not os.path.isdir(path):
        return path, []
    files = sorted((f for f in os.listdir(path) if f.startswith("kurd_garage_") and f.endswith(".zip")),
                   reverse=True)
    return path, [(f, os.path.getsize(os.path.join(path, f))) for f in files]


def restore(zip_path):
    """Replace all data with the content of a backup ZIP. A safety backup is made first."""
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("This is not a Kurd Garage backup file.")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if "garage.db" not in names:
                raise ValueError("This is not a Kurd Garage backup file.")
            for n in names:
                if n == "garage.db" or (n.startswith("uploads/") and "/" not in n[8:] and ".." not in n):
                    z.extract(n, tmp)
        src = sqlite3.connect(os.path.join(tmp, "garage.db"))
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            src.close()
            raise ValueError("The backup file is damaged.")
        if src.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
            src.close()
            raise ValueError("This backup is from a newer version of the program. Please update the program first.")
        safety = backup()
        live = connect()
        src.backup(live)
        src.close()
        live.close()
        init_db()   # upgrade an older backup to the current version
        up = os.path.join(tmp, "uploads")
        if os.path.isdir(up):
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            for f in os.listdir(up):
                shutil.copy2(os.path.join(up, f), os.path.join(UPLOAD_DIR, f))
    return safety


def backup_if_due():
    """Make one automatic backup per day."""
    conn = connect()
    last = get_settings(conn).get("last_backup")
    conn.close()
    if last != date.today().isoformat():
        backup()


def check_integrity():
    conn = connect()
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    return result == "ok" and not fk, result, len(fk)


if __name__ == "__main__":
    import sys

    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "backup":
        print("Backup saved:", backup())
    elif cmd == "check":
        ok, result, fk = check_integrity()
        print("Database OK" if ok else f"PROBLEM: {result}, {fk} broken links")
    elif cmd == "restore" and len(sys.argv) > 2:
        print("Restored. Safety backup of the old data:", restore(sys.argv[2]))
    else:
        print("Database:", DB_PATH)
        print("Backups: ", backup_dir())
        print("Commands: python db.py backup | check | restore <file.zip>")
