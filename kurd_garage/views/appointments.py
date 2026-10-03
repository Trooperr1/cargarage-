from datetime import date, datetime, timedelta

from flask import Blueprint, redirect, render_template, request, url_for

from core import audit, checkbox, choice, error, form, get_db, login_required, ok, or_404, q, to_int

bp = Blueprint("appointments", __name__, url_prefix="/appointments")

SQL = """SELECT a.*, c.display_name AS customer, COALESCE(c.mobile, a.contact_phone) AS mobile, c.phone, c.email,
                v.plate, v.make, v.model,
                e.full_name AS employee
         FROM appointments a LEFT JOIN customers c ON c.id = a.customer_id
         LEFT JOIN vehicles v ON v.id = a.vehicle_id LEFT JOIN employees e ON e.id = a.employee_id"""


@bp.route("/")
@login_required
def index():
    try:
        start = date.fromisoformat(request.args.get("week", ""))
    except ValueError:
        start = date.today()
    monday = start - timedelta(days=start.weekday())
    days = [monday + timedelta(days=i) for i in range(6)]
    rows = q(SQL + " WHERE date(a.starts_at) BETWEEN ? AND ? ORDER BY a.starts_at",
             (days[0].isoformat(), days[-1].isoformat()))
    by_day = {d.isoformat(): [r for r in rows if r["starts_at"][:10] == d.isoformat()] for d in days}
    return render_template("appointments.html", days=days, by_day=by_day,
                           prev=(monday - timedelta(days=7)).isoformat(), next=(monday + timedelta(days=7)).isoformat(),
                           this_week=date.today().isoformat())


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:aid>", methods=["GET", "POST"])
@login_required
def edit(aid=None):
    row = or_404(q(SQL + " WHERE a.id = ?", (aid,), one=True)) if aid else None
    if request.method == "POST":
        day = request.form.get("day", "")
        time = request.form.get("time", "")
        try:
            starts = datetime.fromisoformat(f"{day} {time}").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            error("Choose a valid date and time")
            return redirect(request.url)
        vehicle_id = to_int(request.form.get("vehicle_id"))
        customer_id = to_int(request.form.get("customer_id"))
        if vehicle_id and not customer_id:
            customer_id = q("SELECT customer_id FROM vehicles WHERE id = ?", (vehicle_id,), one=True)["customer_id"]
        title = form("title")
        if not title:
            error("Write what the appointment is for")
            return redirect(request.url)
        if not customer_id and not form("contact_name"):
            error("Choose a customer or write the caller's name")
            return redirect(request.url)
        values = (starts, to_int(request.form.get("minutes"), 60), customer_id, vehicle_id,
                  to_int(request.form.get("employee_id")), form("contact_name"), form("contact_phone"), title,
                  choice("status", ["booked", "arrived", "no_show", "cancelled"], "booked"), checkbox("courtesy_car"),
                  form("notes"))
        conn = get_db()
        if aid:
            conn.execute("""UPDATE appointments SET starts_at=?, minutes=?, customer_id=?, vehicle_id=?, employee_id=?,
                            contact_name=?, contact_phone=?, title=?, status=?, courtesy_car=?, notes=? WHERE id=?""",
                         (*values, aid))
            audit("update", "appointment", aid)
        else:
            aid = conn.execute("""INSERT INTO appointments (starts_at, minutes, customer_id, vehicle_id, employee_id,
                                  contact_name, contact_phone, title, status, courtesy_car, notes)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?)""", values).lastrowid
            audit("create", "appointment", aid, starts)
        conn.commit()
        ok("Appointment saved")
        return redirect(url_for("appointments.index", week=starts[:10]))
    preset_vehicle = to_int(request.args.get("vehicle"))
    customers = q("SELECT id, display_name, mobile, phone FROM customers ORDER BY display_name")
    vehicles = q("""SELECT v.id, v.plate, v.make, v.model, v.customer_id, c.display_name AS owner FROM vehicles v
                    JOIN customers c ON c.id = v.customer_id WHERE v.active = 1 AND COALESCE(v.body_type, '') <> 'counter' ORDER BY v.plate""")
    employees = q("SELECT * FROM employees WHERE active = 1 ORDER BY first_name")
    return render_template("appointment_form.html", row=row, customers=customers, vehicles=vehicles,
                           employees=employees, preset_vehicle=preset_vehicle,
                           day=request.args.get("day") or date.today().isoformat())


@bp.route("/<int:aid>/delete", methods=["POST"])
@login_required
def delete(aid):
    row = or_404(q("SELECT * FROM appointments WHERE id = ?", (aid,), one=True))
    get_db().execute("DELETE FROM appointments WHERE id = ?", (aid,))
    audit("delete", "appointment", aid, row["starts_at"])
    get_db().commit()
    ok("Appointment deleted")
    return redirect(url_for("appointments.index", week=row["starts_at"][:10]))
