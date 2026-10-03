from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from core import (EMPLOYEE_ROLES, admin_required, audit, checkbox, choice, error, form, get_db, login_required, ok,
                  or_404, q, to_date, to_num, to_rappen)

bp = Blueprint("staff", __name__, url_prefix="/staff")


@bp.route("/")
@login_required
def index():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    rows = q("""SELECT e.*,
                  (SELECT COUNT(*) FROM jobs WHERE employee_id = e.id AND status IN ('open','in_progress','waiting_parts')) AS active_jobs,
                  (SELECT COALESCE(SUM(hours),0) FROM time_entries WHERE employee_id = e.id AND substr(work_date,1,7) = ?) AS hours_month,
                  (SELECT COALESCE(SUM(i.quantity),0) FROM job_items i JOIN invoices n ON n.job_id = i.job_id AND n.status='issued'
                   WHERE i.employee_id = e.id AND i.unit = 'h' AND substr(n.issue_date,1,7) = ?) AS billed_month,
                  (SELECT COALESCE(SUM(i.net),0) FROM job_items i JOIN invoices n ON n.job_id = i.job_id AND n.status='issued'
                   WHERE i.employee_id = e.id AND i.kind = 'labour' AND substr(n.issue_date,1,7) = ?) AS labour_month
                FROM employees e ORDER BY e.active DESC, e.first_name""", (month, month, month))
    return render_template("staff.html", rows=rows, month=month)


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:eid>/edit", methods=["GET", "POST"])
@login_required
def edit(eid=None):
    row = or_404(q("SELECT * FROM employees WHERE id = ?", (eid,), one=True)) if eid else None
    if request.method == "POST":
        values = (form("first_name"), form("last_name"), choice("role", EMPLOYEE_ROLES, "mechanic"), form("phone"),
                  form("email"), to_rappen(request.form.get("hourly_cost"), 0), to_date(request.form.get("start_date")),
                  checkbox("active") if eid else 1, form("notes"))
        if not values[0]:
            error("First name is required")
        else:
            cols = "first_name, last_name, role, phone, email, hourly_cost, start_date, active, notes"
            if eid:
                get_db().execute(f"UPDATE employees SET {', '.join(c + ' = ?' for c in cols.split(', '))} WHERE id = ?",
                                 (*values, eid))
                audit("update", "employee", eid)
            else:
                eid = get_db().execute(f"INSERT INTO employees ({cols}) VALUES (?,?,?,?,?,?,?,?,?)", values).lastrowid
                audit("create", "employee", eid, values[0])
            get_db().commit()
            ok("Employee saved")
            return redirect(url_for("staff.view", eid=eid))
    return render_template("employee_form.html", row=row, roles=EMPLOYEE_ROLES)


@bp.route("/<int:eid>")
@login_required
def view(eid):
    row = or_404(q("SELECT * FROM employees WHERE id = ?", (eid,), one=True))
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    times = q("""SELECT t.*, j.complaint, v.plate FROM time_entries t LEFT JOIN jobs j ON j.id = t.job_id
                 LEFT JOIN vehicles v ON v.id = j.vehicle_id
                 WHERE t.employee_id = ? AND substr(t.work_date,1,7) = ? ORDER BY t.work_date, t.id""", (eid, month))
    jobs = q("""SELECT j.*, v.plate, v.make, v.model FROM jobs j JOIN vehicles v ON v.id = j.vehicle_id
                WHERE j.employee_id = ? AND j.status IN ('open','in_progress','waiting_parts') ORDER BY j.id""", (eid,))
    days = {}
    for t in times:
        days[t["work_date"]] = days.get(t["work_date"], 0) + t["hours"]
    return render_template("employee_view.html", row=row, times=times, jobs=jobs, month=month, days=days,
                           total=sum(t["hours"] for t in times))


@bp.route("/<int:eid>/time", methods=["POST"])
@login_required
def time_add(eid):
    """Time not linked to a job (cleaning, training, workshop work)."""
    hours = to_num(request.form.get("hours"), 0)
    if hours <= 0 or hours > 24:
        error("Enter the hours")
    else:
        get_db().execute("INSERT INTO time_entries (employee_id, work_date, hours, note) VALUES (?,?,?,?)",
                         (eid, to_date(request.form.get("work_date")) or date.today().isoformat(), hours, form("note")))
        get_db().commit()
    return redirect(url_for("staff.view", eid=eid))


@bp.route("/<int:eid>/delete", methods=["POST"])
@admin_required
def delete(eid):
    get_db().execute("DELETE FROM employees WHERE id = ?", (eid,))
    audit("delete", "employee", eid)
    get_db().commit()
    ok("Employee deleted")
    return redirect(url_for("staff.index"))
