import calendar
import csv
import io
import json
from datetime import date

from flask import Blueprint, Response, render_template, request

from core import login_required, q, q1, today

bp = Blueprint("reports", __name__, url_prefix="/reports")


def period():
    t = date.today()
    preset = request.args.get("preset", "")
    if preset == "year":
        return f"{t.year}-01-01", today()
    if preset == "lastyear":
        return f"{t.year - 1}-01-01", f"{t.year - 1}-12-31"
    if preset in ("q1", "q2", "q3", "q4"):
        n = int(preset[1:])
        start_month = 3 * (n - 1) + 1
        last_day = calendar.monthrange(t.year, start_month + 2)[1]
        return f"{t.year}-{start_month:02d}-01", f"{t.year}-{start_month + 2:02d}-{last_day:02d}"
    start = request.args.get("start") or t.replace(day=1).isoformat()
    end = request.args.get("end") or today()
    return start, end


@bp.route("/")
@login_required
def index():
    start, end = period()
    rng = (start, end)
    inv_where = "status = 'issued' AND issue_date BETWEEN ? AND ?"
    revenue = q(f"SELECT COALESCE(SUM(subtotal),0) AS net, COALESCE(SUM(vat_total),0) AS vat, COALESCE(SUM(total),0) AS gross, "
                f"COUNT(*) AS n FROM invoices WHERE {inv_where}", rng, one=True)
    received = q1("SELECT COALESCE(SUM(amount),0) FROM payments WHERE paid_on BETWEEN ? AND ?", rng)
    split = q("""SELECT i.kind, COALESCE(SUM(i.net),0) AS net, COALESCE(SUM(round(i.quantity * i.unit_cost)),0) AS cost
                 FROM job_items i JOIN invoices n ON n.job_id = i.job_id
                 WHERE n.status = 'issued' AND n.issue_date BETWEEN ? AND ? GROUP BY i.kind""", rng)
    split = {r["kind"]: r for r in split}
    parts_cost = split["part"]["cost"] if "part" in split else 0
    expenses = q("""SELECT category, COALESCE(SUM(amount),0) AS gross, COALESCE(SUM(vat_amount),0) AS vat
                    FROM expenses WHERE spent_on BETWEEN ? AND ? GROUP BY category ORDER BY gross DESC""", rng)
    exp_net = sum(e["gross"] - e["vat"] for e in expenses)
    exp_net_no_parts = sum(e["gross"] - e["vat"] for e in expenses if e["category"] != "parts purchase")
    profit = revenue["net"] - parts_cost - exp_net_no_parts
    by_method = q("SELECT method, COUNT(*) AS n, SUM(amount) AS total FROM payments WHERE paid_on BETWEEN ? AND ? "
                  "GROUP BY method ORDER BY total DESC", rng)
    months = q("""SELECT substr(issue_date,1,7) AS month, COUNT(*) AS n, SUM(subtotal) AS net, SUM(vat_total) AS vat,
                    SUM(total) AS gross FROM invoices WHERE status = 'issued' AND issue_date BETWEEN ? AND ?
                  GROUP BY month ORDER BY month""", rng)
    employees = q("""SELECT COALESCE(e.full_name, '(not assigned)') AS name,
                       COALESCE(SUM(CASE WHEN i.unit = 'h' THEN i.quantity END),0) AS hours_billed,
                       COALESCE(SUM(i.net),0) AS labour
                     FROM job_items i JOIN invoices n ON n.job_id = i.job_id AND n.status = 'issued'
                     LEFT JOIN employees e ON e.id = i.employee_id
                     WHERE i.kind = 'labour' AND n.issue_date BETWEEN ? AND ?
                     GROUP BY i.employee_id ORDER BY labour DESC""", rng)
    worked = {r["name"]: r["hours"] for r in q("""SELECT e.full_name AS name, SUM(t.hours) AS hours FROM time_entries t
                                                    JOIN employees e ON e.id = t.employee_id
                                                    WHERE t.work_date BETWEEN ? AND ? GROUP BY e.id""", rng)}
    customers = q("""SELECT c.id, c.display_name, COUNT(*) AS n, SUM(n.subtotal) AS net FROM invoices n
                     JOIN customers c ON c.id = n.customer_id WHERE n.status = 'issued' AND n.issue_date BETWEEN ? AND ?
                     GROUP BY c.id ORDER BY net DESC LIMIT 15""", rng)
    parts = q("""SELECT i.part_id, i.description, SUM(i.quantity) AS qty, SUM(i.net) AS net,
                   SUM(round(i.quantity * i.unit_cost)) AS cost
                 FROM job_items i JOIN invoices n ON n.job_id = i.job_id AND n.status = 'issued'
                 WHERE i.kind = 'part' AND n.issue_date BETWEEN ? AND ?
                 GROUP BY i.part_id ORDER BY net DESC LIMIT 20""", rng)
    services = q("""SELECT i.description, COUNT(*) AS n, SUM(i.net) AS net FROM job_items i
                    JOIN invoices n ON n.job_id = i.job_id AND n.status = 'issued'
                    WHERE i.kind = 'labour' AND n.issue_date BETWEEN ? AND ?
                    GROUP BY i.description ORDER BY net DESC LIMIT 15""", rng)
    makes = q("""SELECT v.make, COUNT(DISTINCT j.id) AS jobs FROM jobs j JOIN vehicles v ON v.id = j.vehicle_id
                 WHERE j.status NOT IN ('quote','cancelled') AND date(j.opened_at) BETWEEN ? AND ?
                 GROUP BY v.make ORDER BY jobs DESC LIMIT 10""", rng)
    new_customers = q1("SELECT COUNT(*) FROM customers WHERE date(created_at) BETWEEN ? AND ?", rng)
    jobs_count = q1("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('quote','cancelled') AND date(opened_at) BETWEEN ? AND ?", rng)
    return render_template("reports.html", start=start, end=end, revenue=revenue, received=received, split=split,
                           parts_cost=parts_cost, expenses=expenses, exp_net=exp_net, profit=profit,
                           by_method=by_method, months=months, employees=employees, worked=worked, customers=customers,
                           parts=parts, services=services, makes=makes, new_customers=new_customers,
                           jobs_count=jobs_count)


@bp.route("/vat")
@login_required
def vat():
    """Figures for the quarterly MWST/VAT return (agreed method: by invoice date)."""
    start, end = period()
    rng = (start, end)
    invoices = q("SELECT vat_breakdown FROM invoices WHERE status = 'issued' AND issue_date BETWEEN ? AND ?", rng)
    by_rate = {}
    for inv in invoices:
        for rate, net, vat in json.loads(inv["vat_breakdown"]):
            r = by_rate.setdefault(rate, [0, 0])
            r[0] += net
            r[1] += vat
    input_tax = q("""SELECT category, vat_rate, SUM(amount) AS gross, SUM(vat_amount) AS vat FROM expenses
                     WHERE spent_on BETWEEN ? AND ? AND vat_rate > 0 GROUP BY category, vat_rate ORDER BY category""", rng)
    out_vat = sum(v[1] for v in by_rate.values())
    in_vat = sum(r["vat"] for r in input_tax)
    return render_template("report_vat.html", start=start, end=end, by_rate=sorted(by_rate.items()), input_tax=input_tax,
                           out_vat=out_vat, in_vat=in_vat, turnover=sum(v[0] for v in by_rate.values()))


@bp.route("/receivables")
@login_required
def receivables():
    """Who owes money, with age of the debt."""
    rows = q("""SELECT b.*, c.display_name AS customer, c.mobile, c.phone, c.email,
                  CAST(julianday('now','localtime') - julianday(b.effective_due) AS INTEGER) AS days_late
                FROM invoice_balance b JOIN customers c ON c.id = b.customer_id
                WHERE b.status = 'issued' AND b.open_amount > 0 ORDER BY b.effective_due""")
    buckets = {"not due": 0, "1-30 days": 0, "31-60 days": 0, "61-90 days": 0, "over 90 days": 0}
    for r in rows:
        d = r["days_late"]
        key = ("not due" if d <= 0 else "1-30 days" if d <= 30 else "31-60 days" if d <= 60
               else "61-90 days" if d <= 90 else "over 90 days")
        buckets[key] += r["open_amount"]
    return render_template("report_receivables.html", rows=rows, buckets=buckets)


@bp.route("/stock")
@login_required
def stock():
    rows = q("""SELECT p.*, s.name AS supplier, p.quantity * p.cost_price AS value,
                  (SELECT COALESCE(-SUM(change),0) FROM stock_movements WHERE part_id = p.id AND reason IN ('job','job_return')
                   AND created_at >= date('now','localtime','-12 months')) AS used_12m
                FROM parts p LEFT JOIN suppliers s ON s.id = p.supplier_id WHERE p.active = 1 ORDER BY value DESC""")
    return render_template("report_stock.html", rows=rows, total=sum(r["value"] for r in rows))


@bp.route("/payments.csv")
@login_required
def payments_csv():
    start, end = period()
    rows = q("""SELECT p.paid_on, n.number, c.display_name, p.method, p.amount / 100.0 AS amount_chf, p.note
                FROM payments p JOIN invoices n ON n.id = p.invoice_id JOIN customers c ON c.id = n.customer_id
                WHERE p.paid_on BETWEEN ? AND ? ORDER BY p.paid_on""", (start, end))
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["date", "invoice", "customer", "method", "amount CHF", "note"])
    w.writerows([tuple(r) for r in rows])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=payments_{start}_{end}.csv"})
