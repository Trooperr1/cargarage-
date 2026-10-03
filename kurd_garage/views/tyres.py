from flask import Blueprint, redirect, render_template, request, url_for

from core import audit, choice, error, form, get_db, login_required, ok, or_404, q, to_date, to_int, to_num, to_rappen, today

bp = Blueprint("tyres", __name__, url_prefix="/tyres")

FIELDS = ["vehicle_id", "season", "brand", "model", "size", "dot", "rims", "tread_fl", "tread_fr", "tread_rl",
          "tread_rr", "status", "location", "stored_at", "fee", "notes"]
STATUSES = ["stored", "on vehicle", "returned", "disposed"]
MIN_TREAD = {"summer": 1.6, "winter": 4.0, "all-season": 4.0}   # legal minimum 1.6 mm; 4 mm recommended for winter


@bp.route("/")
@login_required
def index():
    status = request.args.get("status", "stored")
    term = request.args.get("q", "").strip()
    sql = """SELECT t.*, v.plate, v.make, v.model AS car_model, c.display_name AS customer, c.mobile, c.phone
             FROM tyre_sets t JOIN vehicles v ON v.id = t.vehicle_id JOIN customers c ON c.id = v.customer_id
             WHERE (? = 'all' OR t.status = ?)"""
    args = [status, status]
    if term:
        sql += " AND (v.plate LIKE ? OR c.display_name LIKE ? OR t.location LIKE ? OR t.size LIKE ?)"
        args += [f"%{term}%"] * 4
    rows = q(sql + " ORDER BY t.location, v.plate", args)
    return render_template("tyres.html", rows=rows, status=status, statuses=STATUSES, min_tread=MIN_TREAD)


@bp.route("/new/<int:vid>", methods=["GET", "POST"])
@bp.route("/<int:tid>/edit", methods=["GET", "POST"])
@login_required
def edit(vid=None, tid=None):
    row = or_404(q("SELECT * FROM tyre_sets WHERE id = ?", (tid,), one=True)) if tid else None
    vid = row["vehicle_id"] if row else vid
    vehicle = or_404(q("""SELECT v.*, c.display_name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                          WHERE v.id = ?""", (vid,), one=True))
    if request.method == "POST":
        f = {k: (request.form.get(k) or "").strip() or None for k in FIELDS}
        f["vehicle_id"] = vid
        f["season"] = choice("season", ["summer", "winter", "all-season"])
        f["rims"] = choice("rims", ["alloy", "steel", "none", ""], "") or None
        f["status"] = choice("status", STATUSES, "stored")
        for k in ("tread_fl", "tread_fr", "tread_rl", "tread_rr"):
            f[k] = to_num(f[k])
        f["fee"] = to_rappen(f["fee"], 0)
        f["stored_at"] = to_date(f["stored_at"]) or (today() if f["status"] == "stored" else None)
        if f["location"]:
            f["location"] = f["location"].upper()
        conn = get_db()
        if tid:
            conn.execute(f"UPDATE tyre_sets SET {', '.join(k + ' = ?' for k in FIELDS)} WHERE id = ?", (*f.values(), tid))
            audit("update", "tyres", tid, f["status"])
        else:
            tid = conn.execute(f"INSERT INTO tyre_sets ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
                               tuple(f.values())).lastrowid
            audit("create", "tyres", tid, f"{f['season']} {f['location'] or ''}")
        conn.commit()
        ok("Tyre set saved")
        return redirect(url_for("vehicles.view", vid=vid) + "#tyres")
    from core import setting_int
    return render_template("tyre_form.html", row=row, vehicle=vehicle, statuses=STATUSES,
                           default_fee=setting_int("tyre_storage_fee"))


@bp.route("/swap/<int:vid>", methods=["POST"])
@login_required
def swap(vid):
    """Seasonal change: the stored set goes on the car, the set on the car goes into storage."""
    stored = to_int(request.form.get("stored_id"))
    mounted = to_int(request.form.get("mounted_id"))
    location = (form("location") or "").upper() or None
    conn = get_db()
    if not stored:
        error("Choose the stored set that goes on the car")
        return redirect(url_for("vehicles.view", vid=vid) + "#tyres")
    old_place = q("SELECT location FROM tyre_sets WHERE id = ? AND vehicle_id = ?", (stored, vid), one=True)
    if not old_place:
        error("Tyre set not found")
        return redirect(url_for("vehicles.view", vid=vid))
    conn.execute("UPDATE tyre_sets SET status = 'on vehicle', location = NULL WHERE id = ?", (stored,))
    if mounted:
        conn.execute("UPDATE tyre_sets SET status = 'stored', location = ?, stored_at = ? WHERE id = ? AND vehicle_id = ?",
                     (location or old_place["location"], today(), mounted, vid))
    audit("swap", "tyres", stored, f"vehicle {vid}")
    conn.commit()
    ok("Tyres changed over")
    return redirect(url_for("vehicles.view", vid=vid) + "#tyres")


@bp.route("/<int:tid>/label")
@login_required
def label(tid):
    t = or_404(q("""SELECT t.*, v.plate, v.make, v.model AS car_model, c.display_name AS customer, c.mobile, c.phone
                    FROM tyre_sets t JOIN vehicles v ON v.id = t.vehicle_id JOIN customers c ON c.id = v.customer_id
                    WHERE t.id = ?""", (tid,), one=True))
    return render_template("tyre_label.html", t=t)
