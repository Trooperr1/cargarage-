from datetime import date

from flask import Blueprint, render_template, request

import db
from core import ACTIVE_STATUSES, login_required, q, q1, setting_int, today
from views.jobs import JOB_LIST_SQL

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    try:
        db.backup_if_due()
    except OSError:
        pass
    t = today()
    month = t[:7]
    warn = setting_int("mfk_warn_days", 60)
    active = "('" + "','".join(ACTIVE_STATUSES) + "')"
    stats = {
        "in_work": q1(f"SELECT COUNT(*) FROM jobs WHERE status IN {active}"),
        "ready": q1("SELECT COUNT(*) FROM jobs WHERE status = 'done'"),
        "quotes": q1("SELECT COUNT(*) FROM jobs WHERE status = 'quote'"),
        "today_in": q1("SELECT COALESCE(SUM(amount),0) FROM payments WHERE paid_on = ?", (t,)),
        "month_in": q1("SELECT COALESCE(SUM(amount),0) FROM payments WHERE substr(paid_on,1,7) = ?", (month,)),
        "month_invoiced": q1("SELECT COALESCE(SUM(subtotal),0) FROM invoices WHERE status='issued' AND substr(issue_date,1,7) = ?", (month,)),
        "open": q1("SELECT COALESCE(SUM(open_amount),0) FROM invoice_balance WHERE status='issued'"),
        "overdue": q1("SELECT COALESCE(SUM(open_amount),0) FROM invoice_balance WHERE status='issued' AND open_amount > 0 AND effective_due < ?", (t,)),
        "uninvoiced": q1("SELECT COUNT(*) FROM jobs j WHERE j.status IN ('done','delivered') AND NOT EXISTS "
                         "(SELECT 1 FROM invoices WHERE job_id = j.id AND status = 'issued') "
                         "AND EXISTS (SELECT 1 FROM job_items WHERE job_id = j.id)"),
        "tyres": q1("SELECT COUNT(*) FROM tyre_sets WHERE status = 'stored'"),
    }
    appts = q("""SELECT a.*, c.display_name AS customer, v.plate, e.full_name AS employee FROM appointments a
                 LEFT JOIN customers c ON c.id = a.customer_id LEFT JOIN vehicles v ON v.id = a.vehicle_id
                 LEFT JOIN employees e ON e.id = a.employee_id
                 WHERE date(a.starts_at) = ? AND a.status <> 'cancelled' ORDER BY a.starts_at""", (t,))
    jobs = q(JOB_LIST_SQL + f" WHERE j.status IN {active[:-1]},'done') ORDER BY j.promised_at IS NULL, j.promised_at, j.id")
    mfk = q("""SELECT v.*, c.display_name AS customer, c.mobile, c.phone, c.email FROM vehicles v
               JOIN customers c ON c.id = v.customer_id
               WHERE v.active = 1 AND c.reminders_ok = 1 AND v.mfk_next IS NOT NULL AND v.mfk_next <= date('now','localtime', ?)
               ORDER BY v.mfk_next LIMIT 15""", (f"+{warn} days",))
    service = q("""SELECT v.*, c.display_name AS customer, c.mobile, c.phone FROM vehicles v
                   JOIN customers c ON c.id = v.customer_id
                   WHERE v.active = 1 AND c.reminders_ok = 1 AND v.service_next_date IS NOT NULL AND v.service_next_date <= date('now','localtime','+30 days')
                   ORDER BY v.service_next_date LIMIT 15""")
    overdue = q("""SELECT b.*, c.display_name AS customer FROM invoice_balance b JOIN customers c ON c.id = b.customer_id
                   WHERE b.status = 'issued' AND b.open_amount > 0 AND b.effective_due < ? ORDER BY b.effective_due LIMIT 15""", (t,))
    low = q("SELECT * FROM low_stock ORDER BY quantity LIMIT 10")
    month_now = date.today().month
    tyre_season = month_now in (3, 4, 10, 11)
    return render_template("dashboard.html", stats=stats, appts=appts, jobs=jobs, mfk=mfk, service=service,
                           overdue=overdue, low=low, tyre_season=tyre_season)


@bp.route("/search")
@login_required
def search():
    term = request.args.get("q", "").strip()
    like = f"%{term}%"
    res = {}
    if term:
        res["customers"] = q("""SELECT * FROM customers WHERE display_name LIKE ? OR phone LIKE ? OR mobile LIKE ?
                                OR email LIKE ? OR city LIKE ? ORDER BY display_name LIMIT 50""", (like,) * 5)
        compact = term.replace(" ", "")
        res["vehicles"] = q("""SELECT v.*, c.display_name AS owner FROM vehicles v JOIN customers c ON c.id = v.customer_id
                               WHERE COALESCE(v.body_type, '') <> 'counter' AND (replace(v.plate,' ','') LIKE ? OR v.vin LIKE ? OR v.master_number LIKE ?
                               OR v.make LIKE ? OR v.model LIKE ?) LIMIT 50""", (f"%{compact}%", like, like, like, like))
        res["invoices"] = q("""SELECT b.*, c.display_name AS customer FROM invoice_balance b JOIN customers c ON c.id = b.customer_id
                               WHERE b.number LIKE ? LIMIT 20""", (like,))
        res["parts"] = q("SELECT * FROM parts WHERE name LIKE ? OR part_number LIKE ? OR ean = ? LIMIT 20", (like, like, term))
        if term.lstrip("#").isdigit():
            res["jobs"] = q(JOB_LIST_SQL + " WHERE j.id = ?", (int(term.lstrip("#")),))
    return render_template("search.html", term=term, res=res)
