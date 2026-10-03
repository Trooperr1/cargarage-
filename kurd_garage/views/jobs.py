from flask import Blueprint, redirect, render_template, request, session, url_for

from core import (JOB_STATUSES, UNITS, audit, checkbox, choice, default_vat, error, form, get_db, job_totals,
                  login_required, ok, or_404, plus_days, q, q1, setting_int, to_date, to_int, to_num, to_rappen)

bp = Blueprint("jobs", __name__, url_prefix="/jobs")

JOB_LIST_SQL = """
SELECT j.*, v.plate, v.make, v.model, v.customer_id, c.display_name AS customer, c.mobile, c.phone,
       e.full_name AS employee,
       (SELECT COALESCE(SUM(net), 0) FROM job_items WHERE job_id = j.id) AS net,
       (SELECT number FROM invoices WHERE job_id = j.id AND status = 'issued') AS invoice_number,
       (SELECT id FROM invoices WHERE job_id = j.id AND status = 'issued') AS invoice_id
FROM jobs j
JOIN vehicles v ON v.id = j.vehicle_id
JOIN customers c ON c.id = v.customer_id
LEFT JOIN employees e ON e.id = j.employee_id
"""


def load(jid):
    return or_404(q(JOB_LIST_SQL + " WHERE j.id = ?", (jid,), one=True))


def locked(job):
    if job["invoice_id"]:
        error("This job is invoiced. Cancel the invoice first if you need to change it.")
        return True
    return False


def job_redirect(jid, anchor=""):
    return redirect(url_for("jobs.view", jid=jid) + anchor)


@bp.route("/")
@login_required
def index():
    status = request.args.get("status", "")
    term = request.args.get("q", "").strip()
    where, args = [], []
    if status == "active":
        where.append("j.status IN ('open','in_progress','waiting_parts')")
    elif status == "uninvoiced":
        where.append("j.status IN ('done','delivered') AND NOT EXISTS "
                     "(SELECT 1 FROM invoices WHERE job_id = j.id AND status = 'issued')")
    elif status in JOB_STATUSES:
        where.append("j.status = ?")
        args.append(status)
    if term:
        where.append("(v.plate LIKE ? OR c.display_name LIKE ? OR j.complaint LIKE ? OR CAST(j.id AS TEXT) = ?)")
        args += [f"%{term}%", f"%{term}%", f"%{term}%", term.lstrip("#")]
    sql = JOB_LIST_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY j.id DESC LIMIT 500"
    return render_template("jobs.html", rows=q(sql, args), status=status)


@bp.route("/new/<int:vid>", methods=["GET", "POST"])
@login_required
def new(vid):
    vehicle = or_404(q("""SELECT v.*, c.display_name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                          WHERE v.id = ?""", (vid,), one=True))
    appointment_id = to_int(request.args.get("appointment"))
    appt = q("SELECT * FROM appointments WHERE id = ?", (appointment_id,), one=True) if appointment_id else None
    if request.method == "POST":
        complaint = form("complaint")
        if not complaint:
            error("Write what the customer wants done")
        else:
            mileage = to_int(request.form.get("mileage_in"))
            if mileage is not None and vehicle["mileage"] and mileage < vehicle["mileage"]:
                error(f"Warning: mileage {mileage:,} km is lower than the last known {vehicle['mileage']:,} km. Saved anyway.")
            quote = request.form.get("kind") == "quote"
            conn = get_db()
            jid = conn.execute(
                """INSERT INTO jobs (vehicle_id, employee_id, status, complaint, mileage_in, fuel_level, damages,
                   customer_waiting, promised_at, quote_valid_until, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (vid, to_int(request.form.get("employee_id")), "quote" if quote else "open", complaint, mileage,
                 choice("fuel_level", ["empty", "1/4", "1/2", "3/4", "full", ""], "") or None, form("damages"),
                 checkbox("customer_waiting"), form("promised_at"),
                 plus_days(setting_int("quote_valid_days", 30)) if quote else None, session["user_id"])).lastrowid
            if appt:
                conn.execute("UPDATE appointments SET job_id = ?, status = 'arrived' WHERE id = ?", (jid, appt["id"]))
            audit("create", "job", jid, ("quote " if quote else "") + (vehicle["plate"] or ""))
            conn.commit()
            return job_redirect(jid)
    employees = q("SELECT * FROM employees WHERE active = 1 ORDER BY first_name")
    return render_template("job_new.html", vehicle=vehicle, employees=employees, appt=appt,
                           kind=request.args.get("kind", "job"))


@bp.route("/<int:jid>")
@login_required
def view(jid):
    job = load(jid)
    items = q("""SELECT i.*, e.full_name AS employee, p.quantity AS stock FROM job_items i
                 LEFT JOIN employees e ON e.id = i.employee_id LEFT JOIN parts p ON p.id = i.part_id
                 WHERE i.job_id = ? ORDER BY i.id""", (jid,))
    times = q("""SELECT t.*, e.full_name AS employee FROM time_entries t JOIN employees e ON e.id = t.employee_id
                 WHERE t.job_id = ? ORDER BY t.work_date, t.id""", (jid,))
    invoices = q("SELECT * FROM invoice_balance WHERE job_id = ? ORDER BY id DESC", (jid,))
    vehicle = q("SELECT * FROM vehicles WHERE id = ?", (job["vehicle_id"],), one=True)
    customer = q("SELECT * FROM customers WHERE id = ?", (job["customer_id"],), one=True)
    parts = q("SELECT * FROM parts WHERE active = 1 ORDER BY name")
    services = q("SELECT * FROM services WHERE active = 1 ORDER BY name")
    employees = q("SELECT * FROM employees WHERE active = 1 OR id = ? ORDER BY first_name", (job["employee_id"],))
    files = q("SELECT * FROM attachments WHERE entity = 'job' AND entity_id = ? ORDER BY id DESC", (jid,))
    history = q("SELECT id, opened_at, complaint, status FROM jobs WHERE vehicle_id = ? AND id <> ? ORDER BY id DESC LIMIT 5",
                (job["vehicle_id"], jid))
    worked = sum(t["hours"] for t in times)
    billed = sum(i["quantity"] for i in items if i["kind"] == "labour")
    return render_template("job_view.html", job=job, items=items, times=times, invoices=invoices, vehicle=vehicle,
                           customer=customer, parts=parts, services=services, employees=employees, files=files,
                           history=history, totals=job_totals(jid), worked=worked, billed=billed,
                           default_vat=default_vat())


@bp.route("/<int:jid>/update", methods=["POST"])
@login_required
def update(jid):
    job = load(jid)
    status = choice("status", JOB_STATUSES)
    if job["invoice_id"] and status in ("quote", "cancelled"):
        error("This job is invoiced. Cancel the invoice first.")
        return job_redirect(jid)
    finished = "finished_at"
    if status in ("done", "delivered") and not job["finished_at"]:
        finished = "datetime('now','localtime')"
    elif status not in ("done", "delivered"):
        finished = "NULL"
    closed = "datetime('now','localtime')" if status in ("delivered", "cancelled") and not job["closed_at"] else (
        "closed_at" if status in ("delivered", "cancelled") else "NULL")
    get_db().execute(
        f"""UPDATE jobs SET status = ?, employee_id = ?, complaint = ?, diagnosis = ?, recommendations = ?,
            internal_notes = ?, damages = ?, promised_at = ?, quote_valid_until = ?, customer_waiting = ?,
            finished_at = {finished}, closed_at = {closed} WHERE id = ?""",
        (status, to_int(request.form.get("employee_id")), form("complaint") or job["complaint"], form("diagnosis"),
         form("recommendations"), form("internal_notes"), form("damages"), form("promised_at"),
         to_date(request.form.get("quote_valid_until")), checkbox("customer_waiting"), jid))
    if status != job["status"]:
        audit("status", "job", jid, f"{job['status']} -> {status}")
    get_db().commit()
    ok("Job saved")
    return job_redirect(jid)


@bp.route("/<int:jid>/items", methods=["POST"])
@login_required
def item_add(jid):
    job = load(jid)
    if locked(job):
        return job_redirect(jid)
    customer_discount = q1("SELECT discount_pct FROM customers WHERE id = ?", (job["customer_id"],)) or 0
    kind = choice("kind", ["labour", "part", "other", "service"])
    qty = to_num(request.form.get("quantity"), 1)
    discount = to_num(request.form.get("discount_pct"), customer_discount)
    vat = to_num(request.form.get("vat_rate"), default_vat())
    employee = to_int(request.form.get("employee_id")) or job["employee_id"]
    rate = setting_int("hourly_rate")
    conn = get_db()
    sql = """INSERT INTO job_items (job_id, kind, part_id, service_id, employee_id, description, quantity, unit,
             unit_price, unit_cost, discount_pct, vat_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""
    if kind == "service":
        s = or_404(q("SELECT * FROM services WHERE id = ?", (to_int(request.form.get("service_id")),), one=True))
        if s["fixed_price"] is not None:
            conn.execute(sql, (jid, "labour", None, s["id"], employee, s["name"], 1, "flat", s["fixed_price"], 0,
                               discount, vat))
        else:
            conn.execute(sql, (jid, "labour", None, s["id"], employee, s["name"], s["hours"], "h", rate, 0,
                               discount, vat))
    elif kind == "part":
        part_id = to_int(request.form.get("part_id"))
        code = form("part_code")
        part = None
        if part_id:
            part = q("SELECT * FROM parts WHERE id = ?", (part_id,), one=True)
        elif code:
            part = q("SELECT * FROM parts WHERE part_number = ? OR ean = ?", (code, code), one=True)
        if not part:
            error("Part not found. Create it under Parts first.")
            return job_redirect(jid, "#add")
        price = to_rappen(request.form.get("unit_price"), part["sell_price"])
        conn.execute(sql, (jid, "part", part["id"], None, None, f"{part['name']} ({part['part_number']})", qty,
                           part["unit"], price, part["cost_price"], discount, vat))
    else:
        desc = form("description")
        if not desc:
            error("Enter a description")
            return job_redirect(jid, "#add")
        default_price = rate if kind == "labour" else None
        price = to_rappen(request.form.get("unit_price"), default_price)
        if price is None:
            error("Enter a price")
            return job_redirect(jid, "#add")
        conn.execute(sql, (jid, kind, None, None, employee if kind == "labour" else None, desc, qty,
                           "h" if kind == "labour" else (form("unit") or "pc"), price, to_rappen(request.form.get("unit_cost"), 0),
                           discount, vat))
    audit("add_item", "job", jid, kind)
    conn.commit()
    return job_redirect(jid, "#items")


@bp.route("/<int:jid>/items/<int:iid>", methods=["POST"])
@login_required
def item_edit(jid, iid):
    if locked(load(jid)):
        return job_redirect(jid)
    item = or_404(q("SELECT * FROM job_items WHERE id = ? AND job_id = ?", (iid, jid), one=True))
    get_db().execute("""UPDATE job_items SET description = ?, quantity = ?, unit_price = ?, discount_pct = ?, vat_rate = ?
                        WHERE id = ?""",
                     (form("description") or item["description"], to_num(request.form.get("quantity"), item["quantity"]),
                      to_rappen(request.form.get("unit_price"), item["unit_price"]),
                      to_num(request.form.get("discount_pct"), 0), to_num(request.form.get("vat_rate"), item["vat_rate"]),
                      iid))
    audit("edit_item", "job", jid, str(iid))
    get_db().commit()
    return job_redirect(jid, "#items")


@bp.route("/<int:jid>/items/<int:iid>/delete", methods=["POST"])
@login_required
def item_delete(jid, iid):
    if locked(load(jid)):
        return job_redirect(jid)
    get_db().execute("DELETE FROM job_items WHERE id = ? AND job_id = ?", (iid, jid))
    audit("remove_item", "job", jid, str(iid))
    get_db().commit()
    return job_redirect(jid, "#items")


@bp.route("/<int:jid>/time", methods=["POST"])
@login_required
def time_add(jid):
    load(jid)
    employee = to_int(request.form.get("employee_id"))
    hours = to_num(request.form.get("hours"))
    if not employee or not hours:
        error("Choose the employee and enter the hours")
    else:
        get_db().execute("INSERT INTO time_entries (job_id, employee_id, work_date, hours, note) VALUES (?,?,?,?,?)",
                         (jid, employee, to_date(request.form.get("work_date")) or plus_days(0), hours, form("note")))
        audit("time", "job", jid, str(hours))
        get_db().commit()
    return job_redirect(jid, "#time")


@bp.route("/<int:jid>/time/<int:tid>/delete", methods=["POST"])
@login_required
def time_delete(jid, tid):
    get_db().execute("DELETE FROM time_entries WHERE id = ? AND job_id = ?", (tid, jid))
    audit("time_delete", "job", jid, str(tid))
    get_db().commit()
    return job_redirect(jid, "#time")


@bp.route("/<int:jid>/copy", methods=["POST"])
@login_required
def copy(jid):
    """Copy a job (for example to repeat last year's service) as a new quote or job."""
    job = load(jid)
    conn = get_db()
    status = "quote" if request.form.get("as") == "quote" else "open"
    new_id = conn.execute("INSERT INTO jobs (vehicle_id, employee_id, status, complaint, created_by) VALUES (?,?,?,?,?)",
                          (job["vehicle_id"], job["employee_id"], status, job["complaint"], session["user_id"])).lastrowid
    conn.execute("""INSERT INTO job_items (job_id, kind, part_id, service_id, employee_id, description, quantity, unit,
                    unit_price, unit_cost, discount_pct, vat_rate)
                    SELECT ?, i.kind, i.part_id, i.service_id, i.employee_id, i.description, i.quantity, i.unit,
                           COALESCE(p.sell_price, i.unit_price), COALESCE(p.cost_price, i.unit_cost), i.discount_pct, ?
                    FROM job_items i LEFT JOIN parts p ON p.id = i.part_id WHERE i.job_id = ? ORDER BY i.id""",
                 (new_id, default_vat(), jid))
    audit("copy", "job", new_id, f"from #{jid}")
    conn.commit()
    ok(f"Copied from job #{jid}")
    return job_redirect(new_id)


@bp.route("/<int:jid>/print/<kind>")
@login_required
def printout(jid, kind):
    if kind not in ("card", "quote"):
        return redirect(url_for("jobs.view", jid=jid))
    job = load(jid)
    items = q("SELECT * FROM job_items WHERE job_id = ? ORDER BY CASE kind WHEN 'labour' THEN 0 WHEN 'part' THEN 1 ELSE 2 END, id", (jid,))
    vehicle = q("SELECT * FROM vehicles WHERE id = ?", (job["vehicle_id"],), one=True)
    customer = q("SELECT * FROM customers WHERE id = ?", (job["customer_id"],), one=True)
    from core import address_lines
    return render_template(f"print_{kind}.html", job=job, items=items, vehicle=vehicle, customer=customer,
                           address=address_lines(customer), totals=job_totals(jid), units=UNITS)
