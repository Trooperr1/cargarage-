import re

from flask import Blueprint, redirect, render_template, request, url_for

from core import (CANTONS, FUELS, admin_required, audit, checkbox, choice, error, get_db, login_required, ok,
                  or_404, q, to_date, to_int)
from views.jobs import JOB_LIST_SQL

bp = Blueprint("vehicles", __name__, url_prefix="/vehicles")

FIELDS = ["plate", "make", "model", "variant", "body_type", "vin", "master_number", "type_approval",
          "first_registration", "year", "fuel", "transmission", "drive", "engine_code", "engine_ccm", "power_kw",
          "color", "mileage", "mfk_last", "mfk_next", "service_next_date", "service_next_km", "oil_spec",
          "tyre_size_summer", "tyre_size_winter", "key_number", "radio_code", "active", "notes"]


def normalise_plate(text):
    """'zh123456' -> 'ZH 123456'"""
    if not text:
        return None
    text = re.sub(r"[\s\-.]+", "", text.upper())
    m = re.fullmatch(r"([A-Z]{2})(\d{1,6})([A-Z]?)", text)
    if m and m.group(1) in CANTONS:
        return f"{m.group(1)} {m.group(2)}{(' ' + m.group(3)) if m.group(3) else ''}"
    return text


def read_form():
    f = {k: (request.form.get(k) or "").strip() or None for k in FIELDS}
    f["plate"] = normalise_plate(f["plate"])
    f["vin"] = re.sub(r"\s+", "", f["vin"]).upper() if f["vin"] else None
    if f["vin"] and len(f["vin"]) != 17:
        raise ValueError("A VIN / chassis number has exactly 17 characters")
    for k in ("first_registration", "mfk_last", "mfk_next", "service_next_date"):
        f[k] = to_date(f[k])
    for k in ("year", "engine_ccm", "power_kw", "mileage", "service_next_km"):
        f[k] = to_int(f[k])
    if not f["year"] and f["first_registration"]:
        f["year"] = int(f["first_registration"][:4])
    f["fuel"] = choice("fuel", FUELS + [""], "") or None
    f["transmission"] = choice("transmission", ["manual", "automatic", ""], "") or None
    f["drive"] = choice("drive", ["FWD", "RWD", "AWD", ""], "") or None
    f["active"] = checkbox("active") if "active_shown" in request.form else 1
    return f


@bp.route("/")
@login_required
def index():
    term = request.args.get("q", "").strip()
    like = f"%{term}%"
    rows = q("""SELECT v.*, c.display_name AS owner,
                  (SELECT MAX(opened_at) FROM jobs WHERE vehicle_id = v.id) AS last_visit
                FROM vehicles v JOIN customers c ON c.id = v.customer_id
                WHERE replace(v.plate,' ','') LIKE ? OR v.make LIKE ? OR v.model LIKE ? OR c.display_name LIKE ?
                   OR v.vin LIKE ? OR v.master_number LIKE ?
                ORDER BY v.active DESC, v.plate""", (f"%{term.replace(' ', '')}%", like, like, like, like, like))
    return render_template("vehicles.html", rows=rows)


@bp.route("/new/<int:cid>", methods=["GET", "POST"])
@bp.route("/<int:vid>/edit", methods=["GET", "POST"])
@login_required
def edit(cid=None, vid=None):
    row = or_404(q("SELECT * FROM vehicles WHERE id = ?", (vid,), one=True)) if vid else None
    cid = row["customer_id"] if row else cid
    owner = or_404(q("SELECT * FROM customers WHERE id = ?", (cid,), one=True))
    if request.method == "POST":
        f = read_form()
        if not f["make"] or not f["model"]:
            error("Make and model are required")
            row = request.form
        else:
            conn = get_db()
            new_owner = to_int(request.form.get("customer_id")) or cid
            if vid:
                old_km = row["mileage"]
                conn.execute(f"UPDATE vehicles SET customer_id = ?, {', '.join(k + ' = ?' for k in FIELDS)} WHERE id = ?",
                             (new_owner, *f.values(), vid))
                if f["mileage"] is not None and f["mileage"] != old_km:
                    conn.execute("INSERT INTO mileage_log (vehicle_id, mileage, source) VALUES (?, ?, 'manual')",
                                 (vid, f["mileage"]))
                audit("update", "vehicle", vid, f"owner {cid} -> {new_owner}" if new_owner != cid else None)
            else:
                vid = conn.execute(
                    f"INSERT INTO vehicles (customer_id, {', '.join(FIELDS)}) VALUES (?, {', '.join('?' * len(FIELDS))})",
                    (cid, *f.values())).lastrowid
                if f["mileage"] is not None:
                    conn.execute("INSERT INTO mileage_log (vehicle_id, mileage, source) VALUES (?, ?, 'new vehicle')",
                                 (vid, f["mileage"]))
                audit("create", "vehicle", vid, f["plate"])
            conn.commit()
            ok("Vehicle saved")
            return redirect(url_for("vehicles.view", vid=vid))
    customers = q("SELECT id, display_name FROM customers ORDER BY display_name") if vid else []
    return render_template("vehicle_form.html", row=row, owner=owner, vid=vid, customers=customers, fuels=FUELS)


@bp.route("/<int:vid>")
@login_required
def view(vid):
    row = or_404(q("""SELECT v.*, c.display_name AS owner, c.phone, c.mobile, c.email FROM vehicles v
                      JOIN customers c ON c.id = v.customer_id WHERE v.id = ?""", (vid,), one=True))
    jobs = q(JOB_LIST_SQL + " WHERE v.id = ? ORDER BY j.id DESC", (vid,))
    mileage = q("SELECT * FROM mileage_log WHERE vehicle_id = ? ORDER BY read_at DESC, id DESC", (vid,))
    tyres = q("SELECT * FROM tyre_sets WHERE vehicle_id = ? ORDER BY status = 'stored' DESC, id DESC", (vid,))
    files = q("SELECT * FROM attachments WHERE entity = 'vehicle' AND entity_id = ? ORDER BY id DESC", (vid,))
    # Warn when a reading is lower than an earlier one (possible tampering or typing error).
    readings = sorted(mileage, key=lambda m: (m["read_at"], m["id"]))
    km_warning = any(b["mileage"] < a["mileage"] for a, b in zip(readings, readings[1:]))
    return render_template("vehicle_view.html", row=row, jobs=jobs, mileage=mileage, tyres=tyres, files=files,
                           km_warning=km_warning)


@bp.route("/<int:vid>/history")
@login_required
def history(vid):
    """Printable service history for the customer."""
    row = or_404(q("""SELECT v.*, c.display_name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                      WHERE v.id = ?""", (vid,), one=True))
    jobs = q("SELECT * FROM jobs WHERE vehicle_id = ? AND status NOT IN ('quote','cancelled') ORDER BY opened_at", (vid,))
    items = {j["id"]: q("SELECT * FROM job_items WHERE job_id = ? ORDER BY CASE kind WHEN 'labour' THEN 0 WHEN 'part' THEN 1 ELSE 2 END, id", (j["id"],)) for j in jobs}
    return render_template("vehicle_history.html", row=row, jobs=jobs, items=items)


@bp.route("/<int:vid>/delete", methods=["POST"])
@admin_required
def delete(vid):
    row = or_404(q("SELECT customer_id FROM vehicles WHERE id = ?", (vid,), one=True))
    get_db().execute("DELETE FROM mileage_log WHERE vehicle_id = ?", (vid,))
    get_db().execute("DELETE FROM vehicles WHERE id = ?", (vid,))
    audit("delete", "vehicle", vid)
    get_db().commit()
    ok("Vehicle deleted")
    return redirect(url_for("customers.view", cid=row["customer_id"]))
