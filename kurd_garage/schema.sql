-- Kurd Garage database schema (SQLite), version 2 - Swiss edition.
--
-- Money is stored as INTEGER Rappen (1 CHF = 100) so totals never suffer rounding errors.
-- VAT rates are stored as REAL percent (e.g. 8.1).
-- Quantities are REAL (e.g. 4.5 litres of oil, 1.5 hours of labour).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'staff' CHECK (role IN ('admin', 'staff')),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    last_login    TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ------------------------------------------------------------------ customers

CREATE TABLE IF NOT EXISTS customers (
    id            INTEGER PRIMARY KEY,
    kind          TEXT    NOT NULL DEFAULT 'private' CHECK (kind IN ('private', 'company')),
    salutation    TEXT    CHECK (salutation IS NULL OR salutation IN ('Mr', 'Ms', 'Family', 'Company')),
    first_name    TEXT,
    last_name     TEXT,
    company       TEXT,
    contact_person TEXT,
    street        TEXT,
    house_number  TEXT,
    postcode      TEXT,
    city          TEXT,
    canton        TEXT,
    country       TEXT    NOT NULL DEFAULT 'CH',
    phone         TEXT,
    mobile        TEXT,
    email         TEXT,
    birth_date    TEXT,
    vat_number    TEXT,
    payment_days  INTEGER CHECK (payment_days IS NULL OR payment_days BETWEEN 0 AND 365),
    discount_pct  REAL    NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 100),
    reminders_ok  INTEGER NOT NULL DEFAULT 1 CHECK (reminders_ok IN (0, 1)),
    source        TEXT,
    notes         TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    display_name  TEXT GENERATED ALWAYS AS (
        COALESCE(NULLIF(trim(company), ''), trim(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')))
    ) VIRTUAL,
    CHECK (length(trim(COALESCE(company, '') || COALESCE(last_name, '') || COALESCE(first_name, ''))) > 0),
    CHECK (length(trim(COALESCE(phone, '') || COALESCE(mobile, '') || COALESCE(email, ''))) > 0)
);
CREATE INDEX IF NOT EXISTS idx_customers_last    ON customers(last_name);
CREATE INDEX IF NOT EXISTS idx_customers_company ON customers(company);
CREATE INDEX IF NOT EXISTS idx_customers_phone   ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_customers_mobile  ON customers(mobile);

-- ------------------------------------------------------------------ vehicles

CREATE TABLE IF NOT EXISTS vehicles (
    id                 INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    plate              TEXT    UNIQUE COLLATE NOCASE,           -- e.g. ZH 123456 (NULL = no plate / export)
    make               TEXT    NOT NULL,
    model              TEXT    NOT NULL,
    variant            TEXT,                                    -- e.g. 2.0 TDI Highline
    body_type          TEXT,
    vin                TEXT    UNIQUE COLLATE NOCASE,           -- chassis number (17 chars)
    master_number      TEXT,                                    -- Stammnummer, e.g. 123.456.789
    type_approval      TEXT,                                    -- Typengenehmigung
    first_registration TEXT,                                    -- YYYY-MM-DD
    year               INTEGER CHECK (year IS NULL OR year BETWEEN 1900 AND 2100),
    fuel               TEXT    CHECK (fuel IS NULL OR fuel IN ('petrol', 'diesel', 'hybrid', 'plug-in hybrid', 'electric', 'gas', 'other')),
    transmission       TEXT    CHECK (transmission IS NULL OR transmission IN ('manual', 'automatic')),
    drive              TEXT    CHECK (drive IS NULL OR drive IN ('FWD', 'RWD', 'AWD')),
    engine_code        TEXT,
    engine_ccm         INTEGER CHECK (engine_ccm IS NULL OR engine_ccm >= 0),
    power_kw           INTEGER CHECK (power_kw IS NULL OR power_kw >= 0),
    color              TEXT,
    mileage            INTEGER CHECK (mileage IS NULL OR mileage >= 0),
    mfk_last           TEXT,                                    -- last MFK (vehicle inspection)
    mfk_next           TEXT,                                    -- next MFK due
    service_next_date  TEXT,
    service_next_km    INTEGER CHECK (service_next_km IS NULL OR service_next_km >= 0),
    oil_spec           TEXT,
    tyre_size_summer   TEXT,
    tyre_size_winter   TEXT,
    key_number         TEXT,
    radio_code         TEXT,
    active             INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes              TEXT,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_vehicles_customer ON vehicles(customer_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_mfk      ON vehicles(mfk_next);

-- Every mileage reading we see, so the history can be checked for tampering.
CREATE TABLE IF NOT EXISTS mileage_log (
    id         INTEGER PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    mileage    INTEGER NOT NULL CHECK (mileage >= 0),
    source     TEXT    NOT NULL,
    read_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mileage_vehicle ON mileage_log(vehicle_id);

-- ------------------------------------------------------------------ staff

CREATE TABLE IF NOT EXISTS employees (
    id          INTEGER PRIMARY KEY,
    first_name  TEXT    NOT NULL,
    last_name   TEXT,
    role        TEXT    NOT NULL DEFAULT 'mechanic'
                CHECK (role IN ('mechanic', 'master mechanic', 'apprentice', 'service advisor', 'office', 'other')),
    phone       TEXT,
    email       TEXT,
    hourly_cost INTEGER NOT NULL DEFAULT 0 CHECK (hourly_cost >= 0),   -- what the employee costs you
    start_date  TEXT,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    full_name   TEXT GENERATED ALWAYS AS (trim(first_name || ' ' || COALESCE(last_name, ''))) VIRTUAL
);

-- ------------------------------------------------------------------ catalogue & stock

CREATE TABLE IF NOT EXISTS suppliers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    contact_person  TEXT,
    phone           TEXT,
    email           TEXT,
    website         TEXT,
    street          TEXT,
    postcode        TEXT,
    city            TEXT,
    customer_number TEXT,          -- our account number at this supplier
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Standard work (oil service, tyre change, MFK preparation...) with preset time or price.
CREATE TABLE IF NOT EXISTS services (
    id          INTEGER PRIMARY KEY,
    code        TEXT    UNIQUE COLLATE NOCASE,
    name        TEXT    NOT NULL,
    hours       REAL    NOT NULL DEFAULT 1 CHECK (hours > 0),
    fixed_price INTEGER CHECK (fixed_price IS NULL OR fixed_price >= 0),   -- NULL = hours x hourly rate
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY,
    part_number   TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    ean           TEXT,
    name          TEXT    NOT NULL,
    brand         TEXT,
    category      TEXT,
    unit          TEXT    NOT NULL DEFAULT 'pc' CHECK (unit IN ('pc', 'set', 'l', 'kg', 'm')),
    supplier_id   INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    supplier_ref  TEXT,
    cost_price    INTEGER NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    sell_price    INTEGER NOT NULL DEFAULT 0 CHECK (sell_price >= 0),
    quantity      REAL    NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level REAL    NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    location      TEXT,
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes         TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_parts_name ON parts(name);
CREATE INDEX IF NOT EXISTS idx_parts_ean  ON parts(ean);

-- Every stock change is recorded; parts.quantity is maintained by triggers below.
CREATE TABLE IF NOT EXISTS stock_movements (
    id         INTEGER PRIMARY KEY,
    part_id    INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    change     REAL    NOT NULL CHECK (change <> 0),
    reason     TEXT    NOT NULL CHECK (reason IN ('purchase', 'job', 'job_return', 'adjustment', 'counter_sale')),
    job_id     INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    unit_cost  INTEGER,
    note       TEXT,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_stock_part ON stock_movements(part_id);

-- ------------------------------------------------------------------ appointments

CREATE TABLE IF NOT EXISTS appointments (
    id           INTEGER PRIMARY KEY,
    starts_at    TEXT    NOT NULL,                 -- YYYY-MM-DD HH:MM
    minutes      INTEGER NOT NULL DEFAULT 60 CHECK (minutes > 0),
    customer_id  INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    vehicle_id   INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    employee_id  INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    contact_name TEXT,                             -- for callers who are not customers yet
    contact_phone TEXT,
    title        TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'arrived', 'no_show', 'cancelled')),
    courtesy_car INTEGER NOT NULL DEFAULT 0 CHECK (courtesy_car IN (0, 1)),
    job_id       INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    notes        TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_appointments_start ON appointments(starts_at);

-- ------------------------------------------------------------------ jobs (quotes & work orders)

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    vehicle_id    INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE RESTRICT,
    employee_id   INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    status        TEXT    NOT NULL DEFAULT 'open'
                  CHECK (status IN ('quote', 'open', 'in_progress', 'waiting_parts', 'done', 'delivered', 'cancelled')),
    complaint     TEXT    NOT NULL,                -- what the customer asked for
    diagnosis     TEXT,                            -- what we found / did (shown on invoice)
    internal_notes TEXT,                           -- never printed
    recommendations TEXT,                          -- work recommended for later (printed)
    mileage_in    INTEGER CHECK (mileage_in IS NULL OR mileage_in >= 0),
    fuel_level    TEXT    CHECK (fuel_level IS NULL OR fuel_level IN ('empty', '1/4', '1/2', '3/4', 'full')),
    damages       TEXT,                            -- existing damage noted at check-in
    customer_waiting INTEGER NOT NULL DEFAULT 0 CHECK (customer_waiting IN (0, 1)),
    promised_at   TEXT,
    quote_valid_until TEXT,
    opened_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    finished_at   TEXT,
    closed_at     TEXT,
    created_by    INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_vehicle ON jobs(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);

CREATE TABLE IF NOT EXISTS job_items (
    id           INTEGER PRIMARY KEY,
    job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL CHECK (kind IN ('labour', 'part', 'other')),
    part_id      INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    service_id   INTEGER REFERENCES services(id) ON DELETE SET NULL,
    employee_id  INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    description  TEXT    NOT NULL,
    quantity     REAL    NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit         TEXT    NOT NULL DEFAULT 'pc',
    unit_price   INTEGER NOT NULL CHECK (unit_price >= 0),      -- excl. VAT, Rappen
    unit_cost    INTEGER NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    discount_pct REAL    NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 100),
    vat_rate     REAL    NOT NULL DEFAULT 0 CHECK (vat_rate BETWEEN 0 AND 100),
    net          INTEGER GENERATED ALWAYS AS (CAST(round(quantity * unit_price * (100 - discount_pct) / 100.0) AS INTEGER)) VIRTUAL,
    CHECK ((kind = 'part') = (part_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);

-- Actual time the mechanics worked (may differ from what is billed).
CREATE TABLE IF NOT EXISTS time_entries (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    work_date   TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    hours       REAL    NOT NULL CHECK (hours > 0 AND hours <= 24),
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_time_job      ON time_entries(job_id);
CREATE INDEX IF NOT EXISTS idx_time_employee ON time_entries(employee_id, work_date);

-- ------------------------------------------------------------------ invoices & money

CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY,
    number        TEXT    NOT NULL UNIQUE,         -- e.g. 2026-0001, never reused
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    customer_id   INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    issue_date    TEXT    NOT NULL,
    due_date      TEXT    NOT NULL,
    bill_to       TEXT    NOT NULL,                -- address frozen at the time of invoicing
    subtotal      INTEGER NOT NULL,                -- excl. VAT
    vat_total     INTEGER NOT NULL,
    rounding      INTEGER NOT NULL DEFAULT 0,      -- 5-Rappen rounding
    total         INTEGER NOT NULL CHECK (total >= 0),
    vat_breakdown TEXT    NOT NULL DEFAULT '[]',   -- JSON [[rate, net, vat], ...]
    status        TEXT    NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'cancelled')),
    cancelled_at  TEXT,
    cancel_reason TEXT,
    notes         TEXT,
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_job      ON invoices(job_id);
CREATE INDEX IF NOT EXISTS idx_invoices_date     ON invoices(issue_date);
-- Only one valid invoice per job.
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_job_active ON invoices(job_id) WHERE status = 'issued';

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
    amount     INTEGER NOT NULL CHECK (amount > 0),
    method     TEXT    NOT NULL DEFAULT 'cash' CHECK (method IN ('cash', 'card', 'twint', 'bank transfer', 'other')),
    paid_on    TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    note       TEXT,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_date    ON payments(paid_on);

-- Payment reminders (Mahnungen), level 1-3, optional fee.
CREATE TABLE IF NOT EXISTS dunning (
    id         INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
    level      INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
    fee        INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
    sent_on    TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    new_due    TEXT    NOT NULL,
    user_id    INTEGER REFERENCES users(id),
    UNIQUE (invoice_id, level)
);

CREATE TABLE IF NOT EXISTS expenses (
    id         INTEGER PRIMARY KEY,
    spent_on   TEXT    NOT NULL,
    category   TEXT    NOT NULL CHECK (category IN ('parts purchase', 'rent', 'energy', 'salaries', 'insurance',
                                                   'tools & equipment', 'vehicles', 'marketing', 'office',
                                                   'disposal', 'taxes & fees', 'other')),
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    description TEXT   NOT NULL,
    amount     INTEGER NOT NULL CHECK (amount > 0),                -- incl. VAT, Rappen
    vat_rate   REAL    NOT NULL DEFAULT 0 CHECK (vat_rate BETWEEN 0 AND 100),
    method     TEXT,
    reference  TEXT,                                               -- supplier invoice number
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    vat_amount INTEGER GENERATED ALWAYS AS (CAST(round(amount * vat_rate / (100 + vat_rate)) AS INTEGER)) VIRTUAL
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(spent_on);

-- ------------------------------------------------------------------ tyre hotel

CREATE TABLE IF NOT EXISTS tyre_sets (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE RESTRICT,
    season      TEXT    NOT NULL CHECK (season IN ('summer', 'winter', 'all-season')),
    brand       TEXT,
    model       TEXT,
    size        TEXT,                          -- e.g. 205/55 R16 91H
    dot         TEXT,                          -- production week/year, e.g. 2323
    rims        TEXT    CHECK (rims IS NULL OR rims IN ('alloy', 'steel', 'none')),
    tread_fl    REAL, tread_fr REAL, tread_rl REAL, tread_rr REAL,   -- mm
    status      TEXT    NOT NULL DEFAULT 'stored' CHECK (status IN ('stored', 'on vehicle', 'returned', 'disposed')),
    location    TEXT,                          -- rack / shelf
    stored_at   TEXT,
    fee         INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),       -- yearly storage fee
    notes       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tyres_vehicle ON tyre_sets(vehicle_id);
-- A shelf place can hold only one stored set.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tyre_location ON tyre_sets(location) WHERE status = 'stored' AND location IS NOT NULL;

-- ------------------------------------------------------------------ files & audit

CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY,
    entity        TEXT    NOT NULL CHECK (entity IN ('job', 'vehicle', 'customer', 'expense')),
    entity_id     INTEGER NOT NULL,
    stored_name   TEXT    NOT NULL UNIQUE,
    original_name TEXT    NOT NULL,
    caption       TEXT,
    size_bytes    INTEGER NOT NULL,
    user_id       INTEGER REFERENCES users(id),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_attachments_entity ON attachments(entity, entity_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    details    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);

-- ------------------------------------------------------------------ views

CREATE VIEW IF NOT EXISTS invoice_balance AS
SELECT
    i.*,
    COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id = i.id), 0) AS paid,
    COALESCE((SELECT SUM(fee) FROM dunning WHERE invoice_id = i.id), 0) AS fees,
    COALESCE((SELECT MAX(level) FROM dunning WHERE invoice_id = i.id), 0) AS dunning_level,
    COALESCE((SELECT MAX(new_due) FROM dunning WHERE invoice_id = i.id), i.due_date) AS effective_due,
    CASE WHEN i.status = 'cancelled' THEN 0
         ELSE i.total + COALESCE((SELECT SUM(fee) FROM dunning WHERE invoice_id = i.id), 0)
                      - COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id = i.id), 0)
    END AS open_amount
FROM invoices i;

CREATE VIEW IF NOT EXISTS low_stock AS
SELECT * FROM parts WHERE active = 1 AND quantity <= reorder_level;

-- ------------------------------------------------------------------ triggers

CREATE TRIGGER IF NOT EXISTS trg_stock_apply
AFTER INSERT ON stock_movements
BEGIN
    UPDATE parts SET quantity = round(quantity + NEW.change, 3) WHERE id = NEW.part_id;
END;

-- Parts on a real job leave the stock (quotes and cancelled jobs do not).
-- Fails with a CHECK error if there is not enough stock.
CREATE TRIGGER IF NOT EXISTS trg_job_item_part_out
AFTER INSERT ON job_items
WHEN NEW.kind = 'part'
 AND (SELECT status FROM jobs WHERE id = NEW.job_id) NOT IN ('quote', 'cancelled')
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, unit_cost, note)
    VALUES (NEW.part_id, -NEW.quantity, 'job', NEW.job_id, NEW.unit_cost, NEW.description);
END;

CREATE TRIGGER IF NOT EXISTS trg_job_item_part_back
AFTER DELETE ON job_items
WHEN OLD.kind = 'part'
 AND (SELECT status FROM jobs WHERE id = OLD.job_id) NOT IN ('quote', 'cancelled')
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, unit_cost, note)
    VALUES (OLD.part_id, OLD.quantity, 'job_return', OLD.job_id, OLD.unit_cost, OLD.description);
END;

CREATE TRIGGER IF NOT EXISTS trg_job_item_part_change
AFTER UPDATE OF quantity ON job_items
WHEN NEW.kind = 'part' AND NEW.quantity <> OLD.quantity
 AND (SELECT status FROM jobs WHERE id = NEW.job_id) NOT IN ('quote', 'cancelled')
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, unit_cost, note)
    VALUES (NEW.part_id, OLD.quantity - NEW.quantity,
            CASE WHEN OLD.quantity > NEW.quantity THEN 'job_return' ELSE 'job' END,
            NEW.job_id, NEW.unit_cost, NEW.description);
END;

-- Moving a job between "quote/cancelled" and a real job takes parts out of / back into stock.
CREATE TRIGGER IF NOT EXISTS trg_job_status_stock_out
AFTER UPDATE OF status ON jobs
WHEN OLD.status IN ('quote', 'cancelled') AND NEW.status NOT IN ('quote', 'cancelled')
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, unit_cost, note)
    SELECT part_id, -quantity, 'job', job_id, unit_cost, description
    FROM job_items WHERE job_id = NEW.id AND kind = 'part';
END;

CREATE TRIGGER IF NOT EXISTS trg_job_status_stock_back
AFTER UPDATE OF status ON jobs
WHEN OLD.status NOT IN ('quote', 'cancelled') AND NEW.status IN ('quote', 'cancelled')
BEGIN
    INSERT INTO stock_movements (part_id, change, reason, job_id, unit_cost, note)
    SELECT part_id, quantity, 'job_return', job_id, unit_cost, description
    FROM job_items WHERE job_id = NEW.id AND kind = 'part';
END;

-- A job with a valid invoice is frozen: its lines cannot change.
CREATE TRIGGER IF NOT EXISTS trg_invoiced_items_insert
BEFORE INSERT ON job_items
WHEN EXISTS (SELECT 1 FROM invoices WHERE job_id = NEW.job_id AND status = 'issued')
BEGIN
    SELECT RAISE(ABORT, 'This job is already invoiced. Cancel the invoice first to change it.');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoiced_items_delete
BEFORE DELETE ON job_items
WHEN EXISTS (SELECT 1 FROM invoices WHERE job_id = OLD.job_id AND status = 'issued')
BEGIN
    SELECT RAISE(ABORT, 'This job is already invoiced. Cancel the invoice first to change it.');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoiced_items_update
BEFORE UPDATE ON job_items
WHEN EXISTS (SELECT 1 FROM invoices WHERE job_id = OLD.job_id AND status = 'issued')
BEGIN
    SELECT RAISE(ABORT, 'This job is already invoiced. Cancel the invoice first to change it.');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoiced_job_status
BEFORE UPDATE OF status ON jobs
WHEN NEW.status IN ('quote', 'cancelled')
 AND EXISTS (SELECT 1 FROM invoices WHERE job_id = OLD.id AND status = 'issued')
BEGIN
    SELECT RAISE(ABORT, 'This job is already invoiced. Cancel the invoice first.');
END;

-- Issued invoices can only be cancelled, never edited or deleted.
CREATE TRIGGER IF NOT EXISTS trg_invoice_frozen
BEFORE UPDATE ON invoices
WHEN OLD.status = 'cancelled'
  OR NEW.number <> OLD.number OR NEW.total <> OLD.total OR NEW.subtotal <> OLD.subtotal
  OR NEW.vat_total <> OLD.vat_total OR NEW.job_id <> OLD.job_id OR NEW.issue_date <> OLD.issue_date
BEGIN
    SELECT RAISE(ABORT, 'Invoices cannot be changed. Cancel it and make a new one.');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_no_delete
BEFORE DELETE ON invoices
BEGIN
    SELECT RAISE(ABORT, 'Invoices cannot be deleted. Cancel it instead.');
END;

CREATE TRIGGER IF NOT EXISTS trg_payment_limit
BEFORE INSERT ON payments
WHEN NEW.amount > (SELECT open_amount FROM invoice_balance WHERE id = NEW.invoice_id)
BEGIN
    SELECT RAISE(ABORT, 'Payment is larger than the amount still open on this invoice.');
END;

CREATE TRIGGER IF NOT EXISTS trg_payment_cancelled_invoice
BEFORE INSERT ON payments
WHEN (SELECT status FROM invoices WHERE id = NEW.invoice_id) = 'cancelled'
BEGIN
    SELECT RAISE(ABORT, 'This invoice is cancelled.');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_cancel_paid
BEFORE UPDATE OF status ON invoices
WHEN NEW.status = 'cancelled' AND EXISTS (SELECT 1 FROM payments WHERE invoice_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'This invoice has payments. It cannot be cancelled.');
END;

-- Keep a mileage history and the latest reading on the vehicle.
CREATE TRIGGER IF NOT EXISTS trg_job_mileage
AFTER INSERT ON jobs
WHEN NEW.mileage_in IS NOT NULL
BEGIN
    INSERT INTO mileage_log (vehicle_id, mileage, source) VALUES (NEW.vehicle_id, NEW.mileage_in, 'job #' || NEW.id);
    UPDATE vehicles SET mileage = MAX(COALESCE(mileage, 0), NEW.mileage_in) WHERE id = NEW.vehicle_id;
END;

-- ------------------------------------------------------------------ public website (version 3)

-- Cars for sale shown on the website.
CREATE TABLE IF NOT EXISTS web_cars (
    id          INTEGER PRIMARY KEY,
    make        TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    year        INTEGER CHECK (year IS NULL OR year BETWEEN 1900 AND 2100),
    km          INTEGER CHECK (km IS NULL OR km >= 0),
    price       INTEGER NOT NULL CHECK (price >= 0),           -- Rappen, incl. VAT
    fuel        TEXT,
    gearbox     TEXT,
    power_ps    INTEGER CHECK (power_ps IS NULL OR power_ps >= 0),
    body        TEXT,
    doors       INTEGER,
    seats       INTEGER,
    color_name  TEXT,
    color_hex   TEXT    NOT NULL DEFAULT '#64748b',
    first_reg   TEXT,                                          -- MM.YYYY
    mfk         TEXT,
    warranty    TEXT,
    status      TEXT    NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'reserved', 'sold', 'hidden')),
    is_new      INTEGER NOT NULL DEFAULT 1 CHECK (is_new IN (0, 1)),
    features    TEXT,                                          -- one per line
    description TEXT,
    cost        INTEGER,                                       -- what you paid (never shown online)
    sold_at     TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS web_car_photos (
    id          INTEGER PRIMARY KEY,
    car_id      INTEGER NOT NULL REFERENCES web_cars(id) ON DELETE CASCADE,
    stored_name TEXT    NOT NULL UNIQUE,
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_web_car_photos ON web_car_photos(car_id, sort);

-- Services and starting prices shown on the website.
CREATE TABLE IF NOT EXISTS web_services (
    id      INTEGER PRIMARY KEY,
    sort    INTEGER NOT NULL DEFAULT 0,
    icon    TEXT    NOT NULL DEFAULT '🔧',
    name    TEXT    NOT NULL,
    price   INTEGER NOT NULL DEFAULT 0 CHECK (price >= 0),     -- Rappen "from", 0 = on request
    time    TEXT,
    text    TEXT,
    points  TEXT,                                              -- one per line
    active  INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
