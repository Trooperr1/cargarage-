"""Kurd Garage - garage management system (Flask + SQLite)."""
import csv
import io
import os
import secrets
import sqlite3
from datetime import date
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("KURD_GARAGE_SECRET") or db.secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

GARAGE_NAME = "Kurd Garage"
CURRENCY = "IQD"
JOB_STATUSES = ["open", "in_progress", "waiting_parts", "done", "delivered", "cancelled"]
EXPORT_TABLES = ["customers", "vehicles", "jobs", "job_items", "payments", "parts",
                 "stock_movements", "mechanics", "suppliers", "audit_log"]


# ---------------------------------------------------------------- helpers

def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def q(sql, args=(), one=False):
    rows = get_db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def audit(action, entity, entity_id=None, details=None):
    get_db().execute(
        "INSERT INTO audit_log (user_id, action, entity, entity_id, details) VALUES (?, ?, ?, ?, ?)",
        (session.get("user_id"), action, entity, entity_id, details),
    )


def money(value):
    return f"{int(value or 0):,} {CURRENCY}"


app.jinja_env.filters["money"] = money


def to_int(value, default=None):
    value = (value or "").replace(",", "").strip()
    if value == "":
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"'{value}' is not a whole number")


def form(name):
    value = request.form.get(name, "").strip()
    return value or None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf"):
            abort(400, "Form expired, please go back and try again.")


@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf": session["csrf"], "garage": GARAGE_NAME, "currency": CURRENCY,
            "statuses": JOB_STATUSES}


@app.errorhandler(sqlite3.IntegrityError)
def integrity_error(err):
    get_db().rollback()
    msg = str(err)
    if "FOREIGN KEY" in msg:
        msg = "This record is still used by other records (e.g. a customer with cars, or a car with jobs)."
    elif "UNIQUE" in msg:
        msg = "This value already exists: " + msg.split(":")[-1].strip()
    elif "CHECK" in msg and "quantity" in msg:
        msg = "Not enough parts in stock."
    flash(msg, "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.errorhandler(ValueError)
def value_error(err):
    flash(str(err), "error")
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------- auth

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = q("SELECT * FROM users WHERE username = ? AND active = 1",
                 (request.form.get("username", ""),), one=True)
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], name=user["full_name"], role=user["role"])
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Wrong username or password", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        user = q("SELECT * FROM users WHERE id = ?", (session["user_id"],), one=True)
        new = request.form.get("new", "")
        if not check_password_hash(user["password_hash"], request.form.get("old", "")):
            flash("Current password is wrong", "error")
        elif len(new) < 6:
            flash("New password must be at least 6 characters", "error")
        else:
            get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (generate_password_hash(new), user["id"]))
            audit("password_change", "user", user["id"])
            get_db().commit()
            flash("Password changed", "ok")
            return redirect(url_for("dashboard"))
    return render_template("password.html")


# ---------------------------------------------------------------- dashboard

@app.route("/")
@login_required
def dashboard():
    today = date.today().isoformat()
    month = today[:7]
    stats = {
        "open_jobs": q("SELECT COUNT(*) FROM jobs WHERE status IN ('open','in_progress','waiting_parts')", one=True)[0],
        "ready": q("SELECT COUNT(*) FROM jobs WHERE status = 'done'", one=True)[0],
        "today_income": q("SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(paid_at) = ?", (today,), one=True)[0],
        "month_income": q("SELECT COALESCE(SUM(amount),0) FROM payments WHERE strftime('%Y-%m', paid_at) = ?", (month,), one=True)[0],
        "unpaid": q("""SELECT COALESCE(SUM(t.total - t.paid),0) FROM job_totals t JOIN jobs j ON j.id = t.job_id
                       WHERE j.status <> 'cancelled' AND t.total > t.paid""", one=True)[0],
        "customers": q("SELECT COUNT(*) FROM customers", one=True)[0],
    }
    jobs = q(JOB_LIST_SQL + " WHERE j.status IN ('open','in_progress','waiting_parts','done') ORDER BY j.id DESC LIMIT 15")
    low = q("SELECT * FROM low_stock ORDER BY quantity LIMIT 10")
    return render_template("dashboard.html", stats=stats, jobs=jobs, low=low)


@app.route("/search")
@login_required
def search():
    term = request.args.get("q", "").strip()
    like = f"%{term}%"
    customers = q("SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? OR phone2 LIKE ? LIMIT 50",
                  (like, like, like)) if term else []
    vehicles = q("""SELECT v.*, c.name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                    WHERE v.plate LIKE ? OR v.vin LIKE ? OR v.make LIKE ? OR v.model LIKE ? LIMIT 50""",
                 (like, like, like, like)) if term else []
    return render_template("search.html", term=term, customers=customers, vehicles=vehicles)


# ---------------------------------------------------------------- customers

CUSTOMER_FIELDS = ["name", "phone", "phone2", "address", "notes"]


@app.route("/customers")
@login_required
def customers():
    term = f"%{request.args.get('q', '').strip()}%"
    rows = q("""SELECT c.*, (SELECT COUNT(*) FROM vehicles WHERE customer_id = c.id) AS cars
                FROM customers c WHERE c.name LIKE ? OR c.phone LIKE ? ORDER BY c.name""", (term, term))
    return render_template("customers.html", rows=rows)


@app.route("/customers/new", methods=["GET", "POST"])
@app.route("/customers/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def customer_form(cid=None):
    row = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True) if cid else None
    if cid and not row:
        abort(404)
    if request.method == "POST":
        values = [form(f) for f in CUSTOMER_FIELDS]
        if not values[0] or not values[1]:
            flash("Name and phone are required", "error")
        else:
            conn = get_db()
            if cid:
                conn.execute(f"UPDATE customers SET {', '.join(f + ' = ?' for f in CUSTOMER_FIELDS)} WHERE id = ?",
                             (*values, cid))
                audit("update", "customer", cid)
            else:
                cid = conn.execute(f"INSERT INTO customers ({', '.join(CUSTOMER_FIELDS)}) VALUES (?,?,?,?,?)",
                                   values).lastrowid
                audit("create", "customer", cid, values[0])
            conn.commit()
            return redirect(url_for("customer_view", cid=cid))
    return render_template("customer_form.html", row=row)


@app.route("/customers/<int:cid>")
@login_required
def customer_view(cid):
    row = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True) or abort(404)
    vehicles = q("SELECT * FROM vehicles WHERE customer_id = ? ORDER BY plate", (cid,))
    jobs = q(JOB_LIST_SQL + " WHERE c.id = ? ORDER BY j.id DESC", (cid,))
    balance = sum(j["total"] - j["paid"] for j in jobs if j["status"] != "cancelled")
    return render_template("customer_view.html", row=row, vehicles=vehicles, jobs=jobs, balance=balance)


@app.route("/customers/<int:cid>/delete", methods=["POST"])
@admin_required
def customer_delete(cid):
    get_db().execute("DELETE FROM customers WHERE id = ?", (cid,))
    audit("delete", "customer", cid)
    get_db().commit()
    flash("Customer deleted", "ok")
    return redirect(url_for("customers"))


# ---------------------------------------------------------------- vehicles

VEHICLE_FIELDS = ["plate", "make", "model", "year", "color", "vin", "mileage", "notes"]


@app.route("/vehicles")
@login_required
def vehicles():
    term = f"%{request.args.get('q', '').strip()}%"
    rows = q("""SELECT v.*, c.name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                WHERE v.plate LIKE ? OR v.make LIKE ? OR v.model LIKE ? OR c.name LIKE ?
                ORDER BY v.plate""", (term, term, term, term))
    return render_template("vehicles.html", rows=rows)


@app.route("/vehicles/new/<int:cid>", methods=["GET", "POST"])
@app.route("/vehicles/<int:vid>/edit", methods=["GET", "POST"])
@login_required
def vehicle_form(cid=None, vid=None):
    row = q("SELECT * FROM vehicles WHERE id = ?", (vid,), one=True) if vid else None
    if vid and not row:
        abort(404)
    cid = row["customer_id"] if row else cid
    owner = q("SELECT * FROM customers WHERE id = ?", (cid,), one=True) or abort(404)
    if request.method == "POST":
        values = {f: form(f) for f in VEHICLE_FIELDS}
        values["plate"] = (values["plate"] or "").upper() or None
        values["vin"] = values["vin"].upper() if values["vin"] else None
        values["year"] = to_int(values["year"])
        values["mileage"] = to_int(values["mileage"])
        if not values["plate"] or not values["make"] or not values["model"]:
            flash("Plate, make and model are required", "error")
        else:
            conn = get_db()
            if vid:
                conn.execute(f"UPDATE vehicles SET {', '.join(f + ' = ?' for f in VEHICLE_FIELDS)} WHERE id = ?",
                             (*values.values(), vid))
                audit("update", "vehicle", vid)
            else:
                vid = conn.execute(
                    f"INSERT INTO vehicles (customer_id, {', '.join(VEHICLE_FIELDS)}) VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, *values.values())).lastrowid
                audit("create", "vehicle", vid, values["plate"])
            conn.commit()
            return redirect(url_for("vehicle_view", vid=vid))
    return render_template("vehicle_form.html", row=row, owner=owner)


@app.route("/vehicles/<int:vid>")
@login_required
def vehicle_view(vid):
    row = q("""SELECT v.*, c.name AS owner, c.phone FROM vehicles v JOIN customers c ON c.id = v.customer_id
               WHERE v.id = ?""", (vid,), one=True) or abort(404)
    jobs = q(JOB_LIST_SQL + " WHERE v.id = ? ORDER BY j.id DESC", (vid,))
    return render_template("vehicle_view.html", row=row, jobs=jobs)


@app.route("/vehicles/<int:vid>/delete", methods=["POST"])
@admin_required
def vehicle_delete(vid):
    row = q("SELECT customer_id FROM vehicles WHERE id = ?", (vid,), one=True) or abort(404)
    get_db().execute("DELETE FROM vehicles WHERE id = ?", (vid,))
    audit("delete", "vehicle", vid)
    get_db().commit()
    flash("Vehicle deleted", "ok")
    return redirect(url_for("customer_view", cid=row["customer_id"]))


# ---------------------------------------------------------------- jobs

JOB_LIST_SQL = """
SELECT j.*, v.plate, v.make, v.model, c.id AS customer_id, c.name AS customer, c.phone,
       m.name AS mechanic, t.total, t.paid
FROM jobs j
JOIN vehicles v ON v.id = j.vehicle_id
JOIN customers c ON c.id = v.customer_id
LEFT JOIN mechanics m ON m.id = j.mechanic_id
JOIN job_totals t ON t.job_id = j.id
"""


@app.route("/jobs")
@login_required
def jobs():
    status = request.args.get("status", "")
    if status in JOB_STATUSES:
        rows = q(JOB_LIST_SQL + " WHERE j.status = ? ORDER BY j.id DESC", (status,))
    elif status == "unpaid":
        rows = q(JOB_LIST_SQL + " WHERE j.status <> 'cancelled' AND t.total > t.paid ORDER BY j.id DESC")
    else:
        rows = q(JOB_LIST_SQL + " ORDER BY j.id DESC LIMIT 300")
    return render_template("jobs.html", rows=rows, status=status)


@app.route("/jobs/new/<int:vid>", methods=["GET", "POST"])
@login_required
def job_new(vid):
    vehicle = q("""SELECT v.*, c.name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                   WHERE v.id = ?""", (vid,), one=True) or abort(404)
    if request.method == "POST":
        complaint = form("complaint")
        if not complaint:
            flash("Write what the customer wants fixed", "error")
        else:
            mileage = to_int(request.form.get("mileage_in"))
            conn = get_db()
            jid = conn.execute(
                "INSERT INTO jobs (vehicle_id, mechanic_id, complaint, mileage_in, created_by) VALUES (?,?,?,?,?)",
                (vid, to_int(request.form.get("mechanic_id")), complaint, mileage, session["user_id"])).lastrowid
            if mileage is not None:
                conn.execute("UPDATE vehicles SET mileage = MAX(COALESCE(mileage, 0), ?) WHERE id = ?", (mileage, vid))
            audit("create", "job", jid, vehicle["plate"])
            conn.commit()
            return redirect(url_for("job_view", jid=jid))
    mechanics = q("SELECT * FROM mechanics WHERE active = 1 ORDER BY name")
    return render_template("job_new.html", vehicle=vehicle, mechanics=mechanics)


def load_job(jid):
    return q(JOB_LIST_SQL + " WHERE j.id = ?", (jid,), one=True) or abort(404)


@app.route("/jobs/<int:jid>")
@login_required
def job_view(jid):
    job = load_job(jid)
    items = q("SELECT * FROM job_items WHERE job_id = ? ORDER BY id", (jid,))
    payments = q("""SELECT p.*, u.full_name AS taken_by FROM payments p LEFT JOIN users u ON u.id = p.user_id
                    WHERE job_id = ? ORDER BY p.id""", (jid,))
    totals = q("SELECT * FROM job_totals WHERE job_id = ?", (jid,), one=True)
    parts = q("SELECT * FROM parts WHERE quantity > 0 ORDER BY name")
    mechanics = q("SELECT * FROM mechanics WHERE active = 1 OR id = ? ORDER BY name", (job["mechanic_id"],))
    return render_template("job_view.html", job=job, items=items, payments=payments, totals=totals,
                           parts=parts, mechanics=mechanics)


def job_locked(job):
    if job["status"] in ("delivered", "cancelled"):
        flash("This job is closed. Change its status first to edit it.", "error")
        return True
    return False


@app.route("/jobs/<int:jid>/update", methods=["POST"])
@login_required
def job_update(jid):
    job = load_job(jid)
    status = request.form.get("status")
    if status not in JOB_STATUSES:
        abort(400)
    closed = "datetime('now','localtime')" if status in ("delivered", "cancelled") else "NULL"
    get_db().execute(
        f"UPDATE jobs SET status = ?, mechanic_id = ?, diagnosis = ?, discount = ?, closed_at = {closed} WHERE id = ?",
        (status, to_int(request.form.get("mechanic_id")), form("diagnosis"),
         to_int(request.form.get("discount"), 0), jid))
    audit("update", "job", jid, f"{job['status']} -> {status}")
    get_db().commit()
    flash("Job saved", "ok")
    return redirect(url_for("job_view", jid=jid))


@app.route("/jobs/<int:jid>/items", methods=["POST"])
@login_required
def job_item_add(jid):
    job = load_job(jid)
    if job_locked(job):
        return redirect(url_for("job_view", jid=jid))
    qty = to_int(request.form.get("quantity"), 1)
    if request.form.get("kind") == "part":
        part = q("SELECT * FROM parts WHERE id = ?", (to_int(request.form.get("part_id")),), one=True) or abort(400)
        price = to_int(request.form.get("unit_price"), part["sell_price"])
        get_db().execute(
            "INSERT INTO job_items (job_id, kind, part_id, description, quantity, unit_price) VALUES (?, 'part', ?, ?, ?, ?)",
            (jid, part["id"], f"{part['name']} ({part['part_number']})", qty, price))
    else:
        desc = form("description") or abort(400)
        get_db().execute(
            "INSERT INTO job_items (job_id, kind, description, quantity, unit_price) VALUES (?, 'labour', ?, ?, ?)",
            (jid, desc, qty, to_int(request.form.get("unit_price"), 0)))
    audit("add_item", "job", jid)
    get_db().commit()
    return redirect(url_for("job_view", jid=jid))


@app.route("/jobs/<int:jid>/items/<int:iid>/delete", methods=["POST"])
@login_required
def job_item_delete(jid, iid):
    if job_locked(load_job(jid)):
        return redirect(url_for("job_view", jid=jid))
    get_db().execute("DELETE FROM job_items WHERE id = ? AND job_id = ?", (iid, jid))
    audit("remove_item", "job", jid, str(iid))
    get_db().commit()
    return redirect(url_for("job_view", jid=jid))


@app.route("/jobs/<int:jid>/pay", methods=["POST"])
@login_required
def job_pay(jid):
    load_job(jid)
    amount = to_int(request.form.get("amount"))
    method = request.form.get("method", "cash")
    if not amount or amount <= 0:
        flash("Enter an amount", "error")
        return redirect(url_for("job_view", jid=jid))
    try:
        get_db().execute("INSERT INTO payments (job_id, amount, method, note, user_id) VALUES (?,?,?,?,?)",
                         (jid, amount, method, form("note"), session["user_id"]))
    except sqlite3.IntegrityError as err:
        get_db().rollback()
        flash(str(err), "error")
        return redirect(url_for("job_view", jid=jid))
    audit("payment", "job", jid, str(amount))
    get_db().commit()
    flash(f"Payment of {money(amount)} saved", "ok")
    return redirect(url_for("job_view", jid=jid))


@app.route("/jobs/<int:jid>/invoice")
@login_required
def job_invoice(jid):
    job = load_job(jid)
    vehicle = q("SELECT * FROM vehicles WHERE id = ?", (job["vehicle_id"],), one=True)
    items = q("SELECT * FROM job_items WHERE job_id = ? ORDER BY kind DESC, id", (jid,))
    totals = q("SELECT * FROM job_totals WHERE job_id = ?", (jid,), one=True)
    return render_template("invoice.html", job=job, vehicle=vehicle, items=items, totals=totals)


# ---------------------------------------------------------------- parts / inventory

PART_FIELDS = ["part_number", "name", "supplier_id", "cost_price", "sell_price", "reorder_level", "location"]


@app.route("/parts")
@login_required
def parts():
    term = f"%{request.args.get('q', '').strip()}%"
    low = request.args.get("low")
    sql = """SELECT p.*, s.name AS supplier FROM parts p LEFT JOIN suppliers s ON s.id = p.supplier_id
             WHERE (p.name LIKE ? OR p.part_number LIKE ?)"""
    if low:
        sql += " AND p.quantity <= p.reorder_level"
    rows = q(sql + " ORDER BY p.name", (term, term))
    value = q("SELECT COALESCE(SUM(quantity * cost_price),0) FROM parts", one=True)[0]
    return render_template("parts.html", rows=rows, value=value, low=low)


@app.route("/parts/new", methods=["GET", "POST"])
@app.route("/parts/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def part_form(pid=None):
    row = q("SELECT * FROM parts WHERE id = ?", (pid,), one=True) if pid else None
    if pid and not row:
        abort(404)
    if request.method == "POST":
        values = {f: form(f) for f in PART_FIELDS}
        for f in ("supplier_id", "cost_price", "sell_price", "reorder_level"):
            values[f] = to_int(values[f], None if f == "supplier_id" else 0)
        if not values["part_number"] or not values["name"]:
            flash("Part number and name are required", "error")
        else:
            conn = get_db()
            if pid:
                conn.execute(f"UPDATE parts SET {', '.join(f + ' = ?' for f in PART_FIELDS)} WHERE id = ?",
                             (*values.values(), pid))
                audit("update", "part", pid)
            else:
                pid = conn.execute(f"INSERT INTO parts ({', '.join(PART_FIELDS)}) VALUES (?,?,?,?,?,?,?)",
                                   tuple(values.values())).lastrowid
                start = to_int(request.form.get("quantity"), 0)
                if start > 0:
                    conn.execute("INSERT INTO stock_movements (part_id, change, reason, note, user_id) "
                                 "VALUES (?, ?, 'purchase', 'Opening stock', ?)", (pid, start, session["user_id"]))
                audit("create", "part", pid, values["name"])
            conn.commit()
            return redirect(url_for("part_view", pid=pid))
    suppliers = q("SELECT * FROM suppliers ORDER BY name")
    return render_template("part_form.html", row=row, suppliers=suppliers)


@app.route("/parts/<int:pid>")
@login_required
def part_view(pid):
    row = q("""SELECT p.*, s.name AS supplier FROM parts p LEFT JOIN suppliers s ON s.id = p.supplier_id
               WHERE p.id = ?""", (pid,), one=True) or abort(404)
    moves = q("""SELECT m.*, u.full_name AS who FROM stock_movements m LEFT JOIN users u ON u.id = m.user_id
                 WHERE part_id = ? ORDER BY m.id DESC LIMIT 200""", (pid,))
    return render_template("part_view.html", row=row, moves=moves)


@app.route("/parts/<int:pid>/stock", methods=["POST"])
@login_required
def part_stock(pid):
    q("SELECT id FROM parts WHERE id = ?", (pid,), one=True) or abort(404)
    change = to_int(request.form.get("change"))
    reason = request.form.get("reason")
    if not change or reason not in ("purchase", "adjustment"):
        flash("Enter a quantity (use minus for removing)", "error")
    else:
        get_db().execute("INSERT INTO stock_movements (part_id, change, reason, note, user_id) VALUES (?,?,?,?,?)",
                         (pid, change, reason, form("note"), session["user_id"]))
        audit("stock", "part", pid, str(change))
        get_db().commit()
        flash("Stock updated", "ok")
    return redirect(url_for("part_view", pid=pid))


@app.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers():
    if request.method == "POST":
        name = form("name") or abort(400)
        sid = get_db().execute("INSERT INTO suppliers (name, phone, address) VALUES (?,?,?)",
                               (name, form("phone"), form("address"))).lastrowid
        audit("create", "supplier", sid, name)
        get_db().commit()
        return redirect(url_for("suppliers"))
    return render_template("suppliers.html", rows=q("SELECT * FROM suppliers ORDER BY name"))


# ---------------------------------------------------------------- mechanics

@app.route("/mechanics", methods=["GET", "POST"])
@login_required
def mechanics():
    if request.method == "POST":
        name = form("name") or abort(400)
        mid = get_db().execute("INSERT INTO mechanics (name, phone, specialty) VALUES (?,?,?)",
                               (name, form("phone"), form("specialty"))).lastrowid
        audit("create", "mechanic", mid, name)
        get_db().commit()
        return redirect(url_for("mechanics"))
    rows = q("""SELECT m.*,
                  (SELECT COUNT(*) FROM jobs WHERE mechanic_id = m.id AND status IN ('open','in_progress','waiting_parts')) AS active_jobs,
                  (SELECT COUNT(*) FROM jobs WHERE mechanic_id = m.id AND status IN ('done','delivered')) AS finished
                FROM mechanics m ORDER BY m.active DESC, m.name""")
    return render_template("mechanics.html", rows=rows)


@app.route("/mechanics/<int:mid>/toggle", methods=["POST"])
@admin_required
def mechanic_toggle(mid):
    get_db().execute("UPDATE mechanics SET active = 1 - active WHERE id = ?", (mid,))
    audit("toggle", "mechanic", mid)
    get_db().commit()
    return redirect(url_for("mechanics"))


# ---------------------------------------------------------------- reports

@app.route("/reports")
@login_required
def reports():
    start = request.args.get("start") or date.today().replace(day=1).isoformat()
    end = request.args.get("end") or date.today().isoformat()
    rng = (start, end)
    income = q("""SELECT date(paid_at) AS day, method, SUM(amount) AS total, COUNT(*) AS n FROM payments
                  WHERE date(paid_at) BETWEEN ? AND ? GROUP BY day, method ORDER BY day""", rng)
    total_income = sum(r["total"] for r in income)
    parts_cost = q("""SELECT COALESCE(SUM(i.quantity * p.cost_price),0) FROM job_items i
                      JOIN parts p ON p.id = i.part_id JOIN jobs j ON j.id = i.job_id
                      WHERE i.kind = 'part' AND j.status <> 'cancelled' AND date(j.opened_at) BETWEEN ? AND ?""",
                   rng, one=True)[0]
    by_mechanic = q("""SELECT COALESCE(m.name, '(none)') AS name, COUNT(*) AS jobs, SUM(t.labour) AS labour,
                              SUM(t.total) AS total
                       FROM jobs j JOIN job_totals t ON t.job_id = j.id LEFT JOIN mechanics m ON m.id = j.mechanic_id
                       WHERE j.status <> 'cancelled' AND date(j.opened_at) BETWEEN ? AND ?
                       GROUP BY m.id ORDER BY total DESC""", rng)
    top_parts = q("""SELECT i.description, SUM(i.quantity) AS qty, SUM(i.quantity * i.unit_price) AS total
                     FROM job_items i JOIN jobs j ON j.id = i.job_id
                     WHERE i.kind = 'part' AND j.status <> 'cancelled' AND date(j.opened_at) BETWEEN ? AND ?
                     GROUP BY i.part_id ORDER BY qty DESC LIMIT 15""", rng)
    return render_template("reports.html", start=start, end=end, income=income, total_income=total_income,
                           parts_cost=parts_cost, by_mechanic=by_mechanic, top_parts=top_parts)


# ---------------------------------------------------------------- admin

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    if request.method == "POST":
        username, name, password = form("username"), form("full_name"), request.form.get("password", "")
        role = "admin" if request.form.get("role") == "admin" else "staff"
        if not username or not name or len(password) < 6:
            flash("Username, name and a password of 6+ characters are required", "error")
        else:
            uid = get_db().execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                                   (username, generate_password_hash(password), name, role)).lastrowid
            audit("create", "user", uid, username)
            get_db().commit()
            flash("User created", "ok")
        return redirect(url_for("admin"))
    users = q("SELECT * FROM users ORDER BY username")
    log = q("""SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
               ORDER BY a.id DESC LIMIT 100""")
    backups = sorted(os.listdir(db.BACKUP_DIR), reverse=True) if os.path.isdir(db.BACKUP_DIR) else []
    ok, result, broken = db.check_integrity()
    return render_template("admin.html", users=users, log=log, backups=backups, ok=ok, result=result,
                           broken=broken, tables=EXPORT_TABLES)


@app.route("/admin/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def user_toggle(uid):
    if uid == session["user_id"]:
        flash("You cannot disable yourself", "error")
    else:
        get_db().execute("UPDATE users SET active = 1 - active WHERE id = ?", (uid,))
        audit("toggle", "user", uid)
        get_db().commit()
    return redirect(url_for("admin"))


@app.route("/admin/backup", methods=["POST"])
@admin_required
def admin_backup():
    path = db.backup()
    audit("backup", "database", None, os.path.basename(path))
    get_db().commit()
    return send_file(path, as_attachment=True)


@app.route("/admin/export/<table>.csv")
@admin_required
def export_csv(table):
    if table not in EXPORT_TABLES:
        abort(404)
    cur = get_db().execute(f"SELECT * FROM {table}")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([d[0] for d in cur.description])
    writer.writerows(cur.fetchall())
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={table}_{date.today()}.csv"})


db.init_db()

if __name__ == "__main__":
    db.backup()  # automatic backup every time the program starts
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
