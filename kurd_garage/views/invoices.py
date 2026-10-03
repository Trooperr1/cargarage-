import io
import json
import re
from datetime import date

from flask import Blueprint, redirect, render_template, request, session, url_for
from markupsafe import Markup

from core import (PAYMENT_METHODS, address_lines, admin_required, audit, choice, error, form, get_db, job_totals,
                  login_required, ok, or_404, plus_days, q, q1, setting_int, settings, to_date, to_rappen, today,
                  vat_breakdown)
from views.jobs import load as load_job

bp = Blueprint("invoices", __name__, url_prefix="/invoices")

LIST_SQL = """SELECT b.*, c.display_name AS customer, v.plate FROM invoice_balance b
              JOIN customers c ON c.id = b.customer_id JOIN jobs j ON j.id = b.job_id
              JOIN vehicles v ON v.id = j.vehicle_id"""


def next_number(conn):
    year = date.today().year
    last = conn.execute("SELECT MAX(CAST(substr(number, 6) AS INTEGER)) FROM invoices WHERE number LIKE ?",
                        (f"{year}-%",)).fetchone()[0] or 0
    return f"{year}-{last + 1:04d}"


@bp.route("/")
@login_required
def index():
    f = request.args.get("filter", "open")
    t = today()
    where = {
        "open": "b.status = 'issued' AND b.open_amount > 0",
        "overdue": f"b.status = 'issued' AND b.open_amount > 0 AND b.effective_due < '{t}'",
        "paid": "b.status = 'issued' AND b.open_amount <= 0",
        "cancelled": "b.status = 'cancelled'",
        "all": "1 = 1",
    }.get(f, "1 = 1")
    rows = q(LIST_SQL + f" WHERE {where} ORDER BY b.id DESC LIMIT 1000")
    return render_template("invoices.html", rows=rows, filter=f)


@bp.route("/create/<int:jid>", methods=["GET", "POST"])
@login_required
def create(jid):
    job = load_job(jid)
    if job["invoice_id"]:
        return redirect(url_for("invoices.view", iid=job["invoice_id"]))
    customer = q("SELECT * FROM customers WHERE id = ?", (job["customer_id"],), one=True)
    totals = job_totals(jid)
    days = customer["payment_days"] if customer["payment_days"] is not None else setting_int("payment_days", 30)
    if request.method == "POST":
        if not q1("SELECT COUNT(*) FROM job_items WHERE job_id = ?", (jid,)):
            error("This job has no lines. Add work or parts first.")
            return redirect(url_for("jobs.view", jid=jid))
        issue = to_date(request.form.get("issue_date")) or today()
        due = to_date(request.form.get("due_date")) or plus_days(days, date.fromisoformat(issue))
        conn = get_db()
        number = next_number(conn)
        iid = conn.execute(
            """INSERT INTO invoices (number, job_id, customer_id, issue_date, due_date, bill_to, subtotal, vat_total,
               rounding, total, vat_breakdown, notes, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (number, jid, customer["id"], issue, due, "\n".join(address_lines(customer)), totals["subtotal"],
             totals["vat"], totals["rounding"], totals["total"], json.dumps(totals["breakdown"]), form("notes"),
             session["user_id"])).lastrowid
        if job["status"] in ("quote", "open", "in_progress", "waiting_parts"):
            conn.execute("UPDATE jobs SET status = 'done', finished_at = COALESCE(finished_at, datetime('now','localtime')) "
                         "WHERE id = ?", (jid,))
        paid_now = to_rappen(request.form.get("paid_now"))
        if paid_now:
            conn.execute("INSERT INTO payments (invoice_id, amount, method, user_id) VALUES (?,?,?,?)",
                         (iid, paid_now, choice("method", PAYMENT_METHODS, "cash"), session["user_id"]))
        audit("create", "invoice", iid, number)
        conn.commit()
        ok(f"Invoice {number} created")
        return redirect(url_for("invoices.view", iid=iid))
    return render_template("invoice_create.html", job=job, customer=customer, totals=totals,
                           due=plus_days(days))


def load(iid):
    return or_404(q(LIST_SQL + " WHERE b.id = ?", (iid,), one=True))


@bp.route("/<int:iid>")
@login_required
def view(iid):
    inv = load(iid)
    payments = q("""SELECT p.*, u.full_name AS taken_by FROM payments p LEFT JOIN users u ON u.id = p.user_id
                    WHERE invoice_id = ? ORDER BY p.paid_on, p.id""", (iid,))
    dunning = q("SELECT * FROM dunning WHERE invoice_id = ? ORDER BY level", (iid,))
    next_level = (dunning[-1]["level"] + 1) if dunning else 1
    fee = setting_int(f"reminder_fee_{next_level}", 0) if next_level > 1 else 0
    customer = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
    return render_template("invoice_view.html", inv=inv, payments=payments, dunning=dunning, next_level=next_level,
                           next_fee=fee, breakdown=vat_breakdown(inv), customer=customer)


@bp.route("/<int:iid>/pay", methods=["POST"])
@login_required
def pay(iid):
    inv = load(iid)
    amount = to_rappen(request.form.get("amount"))
    if not amount or amount <= 0:
        error("Enter the amount")
    else:
        get_db().execute("INSERT INTO payments (invoice_id, amount, method, paid_on, note, user_id) VALUES (?,?,?,?,?,?)",
                         (iid, amount, choice("method", PAYMENT_METHODS, "cash"),
                          to_date(request.form.get("paid_on")) or today(), form("note"), session["user_id"]))
        audit("payment", "invoice", iid, str(amount))
        if amount >= inv["open_amount"] and request.form.get("deliver"):
            get_db().execute("UPDATE jobs SET status = 'delivered', closed_at = COALESCE(closed_at, datetime('now','localtime')) "
                             "WHERE id = ? AND status = 'done'", (inv["job_id"],))
        get_db().commit()
        ok("Payment saved")
    return redirect(url_for("invoices.view", iid=iid))


@bp.route("/<int:iid>/payments/<int:pid>/delete", methods=["POST"])
@admin_required
def payment_delete(iid, pid):
    get_db().execute("DELETE FROM payments WHERE id = ? AND invoice_id = ?", (pid, iid))
    audit("payment_delete", "invoice", iid, str(pid))
    get_db().commit()
    ok("Payment removed")
    return redirect(url_for("invoices.view", iid=iid))


@bp.route("/<int:iid>/cancel", methods=["POST"])
@login_required
def cancel(iid):
    reason = form("reason")
    if not reason:
        error("Write why the invoice is cancelled")
        return redirect(url_for("invoices.view", iid=iid))
    get_db().execute("UPDATE invoices SET status = 'cancelled', cancelled_at = datetime('now','localtime'), "
                     "cancel_reason = ? WHERE id = ? AND status = 'issued'", (reason, iid))
    audit("cancel", "invoice", iid, reason)
    get_db().commit()
    ok("Invoice cancelled. You can now change the job and make a new invoice.")
    return redirect(url_for("invoices.view", iid=iid))


@bp.route("/<int:iid>/remind", methods=["POST"])
@login_required
def remind(iid):
    inv = load(iid)
    if inv["status"] != "issued" or inv["open_amount"] <= 0:
        error("Nothing open on this invoice")
        return redirect(url_for("invoices.view", iid=iid))
    level = (inv["dunning_level"] or 0) + 1
    if level > 3:
        error("Already 3 reminders sent. Next step: debt collection (Betreibung).")
        return redirect(url_for("invoices.view", iid=iid))
    fee = to_rappen(request.form.get("fee"), 0)
    get_db().execute("INSERT INTO dunning (invoice_id, level, fee, new_due, user_id) VALUES (?,?,?,?,?)",
                     (iid, level, fee, plus_days(setting_int("reminder_days", 10)), session["user_id"]))
    audit("reminder", "invoice", iid, f"level {level}")
    get_db().commit()
    ok(f"Reminder {level} created")
    return redirect(url_for("invoices.printout", iid=iid, reminder=level))


# ---------------------------------------------------------------- printing & QR-bill

def is_qr_iban(iban):
    iid = re.sub(r"\s", "", iban)[4:9]
    return iid.isdigit() and 30000 <= int(iid) <= 31999


def qr_reference(number):
    digits = re.sub(r"\D", "", number).zfill(26)[-26:]
    table = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
    carry = 0
    for d in digits:
        carry = table[(carry + int(d)) % 10]
    return digits + str((10 - carry) % 10)


def split_street(street, number):
    return {"street": street or "", "house_num": number or ""}


def qr_bill_svg(inv, amount, customer, label):
    s = settings()
    if not s.get("iban") or not s.get("postcode") or not s.get("city"):
        return None, "Add your IBAN and address under Admin → Settings to print a QR-bill."
    try:
        from qrbill import QRBill
    except ImportError:
        return None, "QR-bill module missing. Run start_windows.bat again to install it."
    creditor = {"name": s.get("garage_name"), "pcode": s["postcode"], "city": s["city"], "country": s.get("country") or "CH",
                **split_street(s.get("street"), s.get("house_number"))}
    debtor = None
    if customer["postcode"] and customer["city"]:
        debtor = {"name": (customer["display_name"] or "")[:70], "pcode": customer["postcode"], "city": customer["city"],
                  "country": customer["country"] or "CH", **split_street(customer["street"], customer["house_number"])}
    try:
        bill = QRBill(account=s["iban"], creditor=creditor, debtor=debtor, amount=f"{amount / 100:.2f}",
                      reference_number=qr_reference(inv["number"]) if is_qr_iban(s["iban"]) else None,
                      additional_information=label, language="en")
        out = io.StringIO()
        bill.as_svg(out, full_page=False)
        svg = out.getvalue()
        svg = svg[svg.index("<svg"):]
        return Markup(svg), None
    except Exception as err:  # noqa: BLE001 - show any QR problem to the user instead of failing the page
        return None, f"QR-bill could not be made: {err}"


@bp.route("/<int:iid>/print")
@login_required
def printout(iid):
    inv = load(iid)
    reminder = request.args.get("reminder", type=int)
    customer = q("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],), one=True)
    job = load_job(inv["job_id"])
    vehicle = q("SELECT * FROM vehicles WHERE id = ?", (job["vehicle_id"],), one=True)
    items = q("SELECT * FROM job_items WHERE job_id = ? ORDER BY CASE kind WHEN 'labour' THEN 0 WHEN 'part' THEN 1 ELSE 2 END, id", (inv["job_id"],))
    dunning = q("SELECT * FROM dunning WHERE invoice_id = ? ORDER BY level", (iid,))
    payments = q("SELECT * FROM payments WHERE invoice_id = ? ORDER BY paid_on", (iid,))
    rem = next((d for d in dunning if d["level"] == reminder), None) if reminder else None
    amount = inv["open_amount"] if (rem or payments) else inv["total"]
    qr, qr_error = (None, None)
    if inv["status"] == "issued" and amount > 0:
        label = f"Invoice {inv['number']}" + (f" / reminder {rem['level']}" if rem else "")
        qr, qr_error = qr_bill_svg(inv, amount, customer, label)
    return render_template("print_invoice.html", inv=inv, customer=customer, job=job, vehicle=vehicle, items=items,
                           breakdown=vat_breakdown(inv), payments=payments, dunning=dunning, rem=rem, amount=amount,
                           qr=qr, qr_error=qr_error, bill_to=inv["bill_to"].split("\n"))
