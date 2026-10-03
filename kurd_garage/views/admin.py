import csv
import io
import os
import sqlite3
import tempfile
import uuid
from datetime import date

from flask import Blueprint, Response, abort, redirect, render_template, request, send_file, send_from_directory, session, url_for
from werkzeug.security import generate_password_hash

import db
from core import (admin_required, audit, checkbox, error, form, get_db, login_required, ok, or_404, q, to_int,
                  to_num, to_rappen)

bp = Blueprint("admin", __name__, url_prefix="/admin")

EXPORT_TABLES = ["customers", "vehicles", "jobs", "job_items", "invoices", "payments", "dunning", "parts",
                 "stock_movements", "suppliers", "employees", "time_entries", "appointments", "tyre_sets", "expenses",
                 "services", "mileage_log", "audit_log"]
MONEY_SETTINGS = ["hourly_rate", "reminder_fee_2", "reminder_fee_3", "tyre_storage_fee"]
TEXT_SETTINGS = ["garage_name", "street", "house_number", "postcode", "city", "canton", "country", "phone", "email",
                 "website", "uid", "iban", "bank_name", "vat_rate", "payment_days", "reminder_days", "invoice_footer",
                 "quote_valid_days", "mfk_warn_days", "backup_dir"]
UPLOAD_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx"}


@bp.route("/", methods=["GET"])
@admin_required
def index():
    users = q("SELECT * FROM users ORDER BY username")
    backup_path, backups = db.list_backups()
    ok_, result, broken = db.check_integrity()
    counts = {t: q(f"SELECT COUNT(*) FROM {t}", one=True)[0] for t in
              ("customers", "vehicles", "jobs", "invoices", "parts", "employees", "attachments")}
    return render_template("admin.html", users=users, backups=backups[:15], backup_count=len(backups),
                           backup_path=backup_path, ok=ok_, result=result, broken=broken, tables=EXPORT_TABLES,
                           counts=counts, db_path=db.DB_PATH)


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    if request.method == "POST":
        conn = get_db()
        values = {k: (request.form.get(k) or "").strip() for k in TEXT_SETTINGS}
        values["vat_rate"] = str(to_num(values["vat_rate"], 0))
        values["iban"] = values["iban"].replace(" ", "").upper()
        for k in ("payment_days", "reminder_days", "quote_valid_days", "mfk_warn_days"):
            values[k] = str(int(to_num(values[k], 0)))
        for k in MONEY_SETTINGS:
            values[k] = str(to_rappen(request.form.get(k), 0))
        values["vat_registered"] = str(checkbox("vat_registered"))
        values["round_5_rappen"] = str(checkbox("round_5_rappen"))
        if values["iban"]:
            try:
                from stdnum import iban
                if not iban.is_valid(values["iban"]):
                    error("The IBAN is not valid. Please check it.")
                    return redirect(url_for("admin.settings_page"))
            except ImportError:
                pass
        if values["backup_dir"]:
            try:
                os.makedirs(values["backup_dir"], exist_ok=True)
            except OSError:
                error("The backup folder cannot be created. Check the path.")
                return redirect(url_for("admin.settings_page"))
        for k, v in values.items():
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (k, v))
        audit("update", "settings")
        conn.commit()
        ok("Settings saved")
        return redirect(url_for("admin.settings_page"))
    return render_template("settings.html", default_backup=db.DEFAULT_BACKUP_DIR)


@bp.route("/services", methods=["GET", "POST"])
@login_required
def services():
    if request.method == "POST":
        if session.get("role") != "admin":
            abort(403)
        sid = request.form.get("id", type=int)
        values = (form("code"), form("name"), to_num(request.form.get("hours"), 1), to_rappen(request.form.get("fixed_price")),
                  checkbox("active") if sid else 1)
        if not values[1]:
            error("Name is required")
        elif sid:
            get_db().execute("UPDATE services SET code=?, name=?, hours=?, fixed_price=?, active=? WHERE id=?", (*values, sid))
            get_db().commit()
            ok("Service saved")
        else:
            get_db().execute("INSERT INTO services (code, name, hours, fixed_price, active) VALUES (?,?,?,?,?)", values)
            get_db().commit()
            ok("Service added")
        return redirect(url_for("admin.services"))
    return render_template("services.html", rows=q("SELECT * FROM services ORDER BY active DESC, name"))


@bp.route("/users", methods=["POST"])
@admin_required
def user_add():
    username, name, password = form("username"), form("full_name"), request.form.get("password", "")
    role = "admin" if request.form.get("role") == "admin" else "staff"
    if not username or not name or len(password) < 6:
        error("Username, name and a password of 6+ characters are required")
    else:
        uid = get_db().execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                               (username, generate_password_hash(password), name, role)).lastrowid
        audit("create", "user", uid, username)
        get_db().commit()
        ok("User created")
    return redirect(url_for("admin.index"))


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def user_toggle(uid):
    if uid == session["user_id"]:
        error("You cannot disable yourself")
    else:
        get_db().execute("UPDATE users SET active = 1 - active WHERE id = ?", (uid,))
        audit("toggle", "user", uid)
        get_db().commit()
    return redirect(url_for("admin.index"))


@bp.route("/users/<int:uid>/password", methods=["POST"])
@admin_required
def user_password(uid):
    password = request.form.get("password", "")
    if len(password) < 6:
        error("Password must be at least 6 characters")
    else:
        get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), uid))
        audit("password_reset", "user", uid)
        get_db().commit()
        ok("Password changed")
    return redirect(url_for("admin.index"))


@bp.route("/backup", methods=["POST"])
@admin_required
def backup():
    path = db.backup()
    audit("backup", "database", None, os.path.basename(path))
    get_db().commit()
    return send_file(path, as_attachment=True)


@bp.route("/backup/<name>")
@admin_required
def backup_download(name):
    path, files = db.list_backups()
    if name not in {f for f, _ in files}:
        abort(404)
    return send_from_directory(path, name, as_attachment=True)


@bp.route("/restore", methods=["POST"])
@admin_required
def restore():
    upload = request.files.get("file")
    if not upload or not upload.filename.endswith(".zip"):
        error("Choose a backup .zip file")
        return redirect(url_for("admin.index"))
    if request.form.get("confirm") != "RESTORE":
        error("Type RESTORE in the box to confirm")
        return redirect(url_for("admin.index"))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "upload.zip")
        upload.save(path)
        conn = get_db()
        conn.close()
        from flask import g
        g.pop("db", None)
        safety = db.restore(path)
    ok(f"Data restored. Your previous data was saved first as {os.path.basename(safety)}. Please log in again.")
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/export/<table>.csv")
@admin_required
def export_csv(table):
    if table not in EXPORT_TABLES:
        abort(404)
    cur = get_db().execute(f"SELECT * FROM {table}")
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")   # Swiss Excel expects semicolons
    writer.writerow([d[0] for d in cur.description])
    writer.writerows(cur.fetchall())
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={table}_{date.today()}.csv"})


IMPORT_COLUMNS = ["company", "salutation", "first_name", "last_name", "street", "house_number", "postcode", "city",
                  "mobile", "phone", "email", "notes", "plate", "make", "model", "year", "vin", "mileage", "mfk_next"]


@bp.route("/import/template.csv")
@admin_required
def import_template():
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(IMPORT_COLUMNS)
    w.writerow(["", "Mr", "Hans", "Muster", "Dorfstrasse", "5", "3000", "Bern", "079 123 45 67", "", "hans@example.ch",
                "", "BE 12345", "Volkswagen", "Golf", "2018", "", "85000", "2027-05-31"])
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=import_template.csv"})


@bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_data():
    """Import customers (and their vehicles) from a CSV file saved from Excel."""
    if request.method == "GET":
        return render_template("import.html", columns=IMPORT_COLUMNS, report=None)
    from views.vehicles import normalise_plate
    upload = request.files.get("file")
    if not upload or not upload.filename:
        error("Choose a CSV file")
        return redirect(url_for("admin.import_data"))
    raw = upload.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    dialect = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=dialect)
    reader.fieldnames = [(h or "").strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])]
    conn = get_db()
    report = {"customers": 0, "vehicles": 0, "skipped": [], "existing": 0}
    for n, row in enumerate(reader, start=2):
        r = {k: (row.get(k) or "").strip() or None for k in IMPORT_COLUMNS}
        if not (r["company"] or r["last_name"] or r["first_name"]):
            report["skipped"].append(f"line {n}: no name")
            continue
        if not (r["mobile"] or r["phone"] or r["email"]):
            report["skipped"].append(f"line {n}: no phone or e-mail")
            continue
        try:
            existing = conn.execute(
                """SELECT id FROM customers WHERE COALESCE(company,'') = COALESCE(?, '') AND COALESCE(last_name,'') = COALESCE(?, '')
                   AND COALESCE(first_name,'') = COALESCE(?, '') AND (mobile = ? OR phone = ? OR email = ?)""",
                (r["company"], r["last_name"], r["first_name"], r["mobile"], r["phone"], r["email"])).fetchone()
            if existing:
                cid = existing[0]
                report["existing"] += 1
            else:
                cid = conn.execute(
                    """INSERT INTO customers (kind, salutation, company, first_name, last_name, street, house_number,
                       postcode, city, mobile, phone, email, notes, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'Import')""",
                    ("company" if r["company"] else "private",
                     r["salutation"] if r["salutation"] in ("Mr", "Ms", "Family", "Company") else None,
                     r["company"], r["first_name"], r["last_name"], r["street"], r["house_number"], r["postcode"],
                     r["city"], r["mobile"], r["phone"], (r["email"] or "").lower() or None, r["notes"])).lastrowid
                report["customers"] += 1
            if r["make"] and r["model"]:
                plate = normalise_plate(r["plate"])
                if plate and conn.execute("SELECT 1 FROM vehicles WHERE plate = ?", (plate,)).fetchone():
                    report["skipped"].append(f"line {n}: plate {plate} already exists")
                else:
                    conn.execute(
                        """INSERT INTO vehicles (customer_id, plate, make, model, year, vin, mileage, mfk_next)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (cid, plate, r["make"], r["model"], to_int(r["year"]), (r["vin"] or "").upper() or None,
                         to_int(r["mileage"]), r["mfk_next"] if r["mfk_next"] and len(r["mfk_next"]) == 10 else None))
                    report["vehicles"] += 1
        except (ValueError, sqlite3.IntegrityError) as err:
            report["skipped"].append(f"line {n}: {err}")
    audit("import", "customer", None, f"{report['customers']} customers, {report['vehicles']} vehicles")
    conn.commit()
    return render_template("import.html", columns=IMPORT_COLUMNS, report=report)


@bp.route("/log")
@admin_required
def log():
    rows = q("""SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
                ORDER BY a.id DESC LIMIT 500""")
    return render_template("audit_log.html", rows=rows)


# ---------------------------------------------------------------- attachments (photos, documents)

ENTITY_PAGES = {"job": ("jobs.view", "jid"), "vehicle": ("vehicles.view", "vid"),
                "customer": ("customers.view", "cid"), "expense": ("expenses.index", "xid")}


@bp.route("/files/<entity>/<int:eid>", methods=["POST"])
@login_required
def upload(entity, eid):
    if entity not in ENTITY_PAGES:
        abort(404)
    endpoint, arg = ENTITY_PAGES[entity]
    saved = 0
    for f in request.files.getlist("files"):
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in UPLOAD_TYPES:
            error(f"{f.filename}: this file type is not allowed")
            continue
        stored = uuid.uuid4().hex + ext
        os.makedirs(db.UPLOAD_DIR, exist_ok=True)
        path = os.path.join(db.UPLOAD_DIR, stored)
        f.save(path)
        get_db().execute("""INSERT INTO attachments (entity, entity_id, stored_name, original_name, caption, size_bytes, user_id)
                            VALUES (?,?,?,?,?,?,?)""",
                         (entity, eid, stored, os.path.basename(f.filename)[:200], form("caption"), os.path.getsize(path),
                          session["user_id"]))
        saved += 1
    if saved:
        audit("upload", entity, eid, f"{saved} file(s)")
        get_db().commit()
        ok(f"{saved} file(s) uploaded")
    return redirect(url_for(endpoint, **{arg: eid}) + "#files")


@bp.route("/files/<int:fid>")
@login_required
def file(fid):
    row = or_404(q("SELECT * FROM attachments WHERE id = ?", (fid,), one=True))
    return send_from_directory(db.UPLOAD_DIR, row["stored_name"], download_name=row["original_name"],
                               as_attachment=request.args.get("download") == "1")


@bp.route("/files/<int:fid>/delete", methods=["POST"])
@login_required
def file_delete(fid):
    row = or_404(q("SELECT * FROM attachments WHERE id = ?", (fid,), one=True))
    get_db().execute("DELETE FROM attachments WHERE id = ?", (fid,))
    audit("delete_file", row["entity"], row["entity_id"], row["original_name"])
    get_db().commit()
    try:
        os.remove(os.path.join(db.UPLOAD_DIR, row["stored_name"]))
    except OSError:
        pass
    endpoint, arg = ENTITY_PAGES[row["entity"]]
    return redirect(url_for(endpoint, **{arg: row["entity_id"]}) + "#files")
