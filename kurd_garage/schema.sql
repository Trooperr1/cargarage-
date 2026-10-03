-- Kurd Garage database schema (SQLite)
-- Money is stored as INTEGER (whole IQD) so totals never suffer rounding errors.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    phone      TEXT    NOT NULL CHECK (length(trim(phone)) > 0),
    phone2     TEXT,
    address    TEXT,
    notes      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_customers_name  ON customers(name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

CREATE TABLE IF NOT EXISTS vehicles (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    plate       TEXT    NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(plate)) > 0),
    make        TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    year        INTEGER CHECK (year IS NULL OR year BETWEEN 1950 AND 2100),
    color       TEXT,
    vin         TEXT    UNIQUE COLLATE NOCASE,
    mileage     INTEGER CHECK (mileage IS NULL OR mileage >= 0),
    notes       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_vehicles_customer ON vehicles(customer_id);

CREATE TABLE IF NOT EXISTS mechanics (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    phone      TEXT,
    specialty  TEXT,
    active     INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS suppliers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    phone      TEXT,
    address    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY,
    part_number   TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT    NOT NULL,
    supplier_id   INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    cost_price    INTEGER NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    sell_price    INTEGER NOT NULL DEFAULT 0 CHECK (sell_price >= 0),
    quantity      INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    location      TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_parts_name ON parts(name);

-- Every stock change is recorded; parts.quantity is maintained by triggers below.
CREATE TABLE IF NOT EXISTS stock_movements (
    id         INTEGER PRIMARY KEY,
    part_id    INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    change     INTEGER NOT NULL CHECK (change <> 0),
    reason     TEXT    NOT NULL CHECK (reason IN ('purchase', 'job', 'job_return', 'adjustment')),
    job_id     INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    note       TEXT,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_stock_part ON stock_movements(part_id);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY,
    vehicle_id   INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE RESTRICT,
    mechanic_id  INTEGER REFERENCES mechanics(id) ON DELETE SET NULL,
    status       TEXT    NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'in_progress', 'waiting_parts', 'done', 'delivered', 'cancelled')),
    complaint    TEXT    NOT NULL,
    diagnosis    TEXT,
    mileage_in   INTEGER CHECK (mileage_in IS NULL OR mileage_in >= 0),
    discount     INTEGER NOT NULL DEFAULT 0 CHECK (discount >= 0),
    opened_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at    TEXT,
    created_by   INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_vehicle ON jobs(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);

-- Line items on a job: labour or a part from stock.
CREATE TABLE IF NOT EXISTS job_items (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('labour', 'part')),
    part_id     INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    description TEXT    NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price  INTEGER NOT NULL CHECK (unit_price >= 0),
    CHECK ((kind = 'part') = (part_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    amount     INTEGER NOT NULL CHECK (amount > 0),
    method     TEXT    NOT NULL DEFAULT 'cash' CHECK (method IN ('cash', 'card', 'transfer')),
    note       TEXT,
    user_id    INTEGER REFERENCES users(id),
    paid_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_payments_job ON payments(job_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    details    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------- Triggers: keep stock in sync automatically ----------

CREATE TRIGGER IF NOT EXISTS trg_stock_apply
AFTER INSERT ON stock_movements
BEGIN
    UPDATE parts SET quantity = quantity + NEW.change WHERE id = NEW.part_id;
END;

-- Adding a part to a job takes it out of stock (fails if not enough stock,
-- because parts.quantity has CHECK (quantity >= 0)).
CREATE TRIGGER IF NOT EXISTS trg_job_item_part_out
AFTER INSERT ON job_items
WHEN NEW.kind = 'part'
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, note)
    VALUES (NEW.part_id, -NEW.quantity, 'job', NEW.job_id, NEW.description);
END;

-- Removing a part from a job puts it back into stock.
CREATE TRIGGER IF NOT EXISTS trg_job_item_part_back
AFTER DELETE ON job_items
WHEN OLD.kind = 'part'
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, note)
    VALUES (OLD.part_id, OLD.quantity, 'job_return', OLD.job_id, OLD.description);
END;

-- ---------- Views ----------

CREATE VIEW IF NOT EXISTS job_totals AS
SELECT
    j.id AS job_id,
    COALESCE((SELECT SUM(quantity * unit_price) FROM job_items WHERE job_id = j.id AND kind = 'labour'), 0) AS labour,
    COALESCE((SELECT SUM(quantity * unit_price) FROM job_items WHERE job_id = j.id AND kind = 'part'), 0)   AS parts,
    j.discount AS discount,
    MAX(COALESCE((SELECT SUM(quantity * unit_price) FROM job_items WHERE job_id = j.id), 0) - j.discount, 0) AS total,
    COALESCE((SELECT SUM(amount) FROM payments WHERE job_id = j.id), 0) AS paid
FROM jobs j;

CREATE VIEW IF NOT EXISTS low_stock AS
SELECT * FROM parts WHERE quantity <= reorder_level;

-- ---------- Payment guard (after views, it uses job_totals) ----------

-- Payments cannot exceed what the job costs.
CREATE TRIGGER IF NOT EXISTS trg_payment_limit
BEFORE INSERT ON payments
WHEN NEW.amount > (
    SELECT total - paid FROM job_totals WHERE job_id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'Payment is larger than the amount still owed');
END;
