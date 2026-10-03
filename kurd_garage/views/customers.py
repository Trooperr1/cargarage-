from flask import Blueprint, redirect, render_template, request, url_for

from core import (CANTONS, admin_required, audit, checkbox, choice, error, get_db, login_required, ok, or_404, q,
                  to_date, to_int, to_num)
from views.jobs import JOB_LIST_SQL

bp = Blueprint("customers", __name__, url_prefix="/customers")

FIELDS = ["kind", "salutation", "first_name", "last_name", "company", "contact_person", "street", "house_number",
          "postcode", "city", "canton", "country", "phone", "mobile", "email", "birth_date", "vat_number",
          "payment_days", "discount_pct", "reminders_ok", "source", "notes"]


def read_form():
    f = {k: (request.form.get(k) or "").strip() or None for k in FIELDS}
    f["kind"] = choice("kind", ["private", "company"], "private")
    f["salutation"] = choice("salutation", ["Mr", "Ms", "Family", "Company", ""], "") or None
    f["canton"] = choice("canton", CANTONS + [""], "") or None
    f["country"] = (f["country"] or "CH").upper()[:2]
    f["birth_date"] = to_date(f["birth_date"])
    f["payment_days"] = to_int(f["payment_days"])
    f["discount_pct"] = to_num(f["discount_pct"], 0)
    f["reminders_ok"] = checkbox("reminders_ok")
    if f["email"]:
        f["email"] = f["email"].lower()
    return f


@bp.route("/")
@login_required
def index():
    term = request.args.get("q", "").strip()
    like = f"%{term}%"
    rows = q("""SELECT c.*,
                  (SELECT COUNT(*) FROM vehicles WHERE customer_id = c.id AND COALESCE(body_type, '') <> 'counter') AS cars,
                  (SELECT COALESCE(SUM(open_amount),0) FROM invoice_balance WHERE customer_id = c.id AND status='issued') AS open_amount,
                  (SELECT MAX(opened_at) FROM jobs j JOIN vehicles v ON v.id = j.vehicle_id WHERE v.customer_id = c.id) AS last_visit
                FROM customers c
                WHERE c.display_name LIKE ? OR c.phone LIKE ? OR c.mobile LIKE ? OR c.email LIKE ? OR c.city LIKE ?
                ORDER BY c.display_name""", (like,) * 5)
    return render_template("customers.html", rows=rows)


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def edit(cid=None):
    row = or_404(q("SELECT * FROM customers WHERE id = ?", (cid,), one=True)) if cid else None
    if request.method == "POST":
        f = read_form()
        if not (f["company"] or f["last_name"] or f["first_name"]):
            error("Enter a name or a company name")
        elif not (f["phone"] or f["mobile"] or f["email"]):
            error("Enter at least one phone number or e-mail")
        else:
            conn = get_db()
            if cid:
                conn.execute(f"UPDATE customers SET {', '.join(k + ' = ?' for k in FIELDS)} WHERE id = ?",
                             (*f.values(), cid))
                audit("update", "customer", cid)
            else:
                cid = conn.execute(f"INSERT INTO customers ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
                                   tuple(f.values())).lastrowid
                audit("create", "customer", cid, f["company"] or f["last_name"])
            conn.commit()
            ok("Customer saved")
            if request.form.get("then") == "vehicle":
                return redirect(url_for("vehicles.edit", cid=cid))
            return redirect(url_for("customers.view", cid=cid))
        row = request.form
    return render_template("customer_form.html", row=row, cid=cid)


@bp.route("/<int:cid>")
@login_required
def view(cid):
    row = or_404(q("SELECT * FROM customers WHERE id = ?", (cid,), one=True))
    vehicles = q("SELECT * FROM vehicles WHERE customer_id = ? AND COALESCE(body_type, '') <> 'counter' "
                 "ORDER BY active DESC, plate", (cid,))
    jobs = q(JOB_LIST_SQL + " WHERE v.customer_id = ? ORDER BY j.id DESC", (cid,))
    invoices = q("SELECT * FROM invoice_balance WHERE customer_id = ? ORDER BY id DESC", (cid,))
    stats = {
        "revenue": sum(i["subtotal"] for i in invoices if i["status"] == "issued"),
        "open": sum(i["open_amount"] for i in invoices if i["status"] == "issued"),
        "visits": len([j for j in jobs if j["status"] not in ("quote", "cancelled")]),
    }
    appts = q("SELECT * FROM appointments WHERE customer_id = ? AND starts_at >= date('now','localtime') "
              "AND status = 'booked' ORDER BY starts_at", (cid,))
    files = q("SELECT * FROM attachments WHERE entity = 'customer' AND entity_id = ? ORDER BY id DESC", (cid,))
    return render_template("customer_view.html", row=row, vehicles=vehicles, jobs=jobs, invoices=invoices,
                           stats=stats, appts=appts, files=files)


@bp.route("/<int:cid>/delete", methods=["POST"])
@admin_required
def delete(cid):
    get_db().execute("DELETE FROM customers WHERE id = ?", (cid,))
    audit("delete", "customer", cid)
    get_db().commit()
    ok("Customer deleted")
    return redirect(url_for("customers.index"))
