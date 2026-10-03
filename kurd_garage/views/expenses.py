from datetime import date

from flask import Blueprint, redirect, render_template, request, session, url_for

from core import (EXPENSE_CATEGORIES, PAYMENT_METHODS, admin_required, audit, choice, default_vat, error, form, get_db,
                  login_required, ok, or_404, q, to_date, to_int, to_num, to_rappen, today)

bp = Blueprint("expenses", __name__, url_prefix="/expenses")


@bp.route("/", methods=["GET", "POST"])
@bp.route("/<int:xid>", methods=["GET", "POST"])
@login_required
def index(xid=None):
    row = or_404(q("SELECT * FROM expenses WHERE id = ?", (xid,), one=True)) if xid else None
    if request.method == "POST":
        values = (to_date(request.form.get("spent_on")) or today(), choice("category", EXPENSE_CATEGORIES),
                  to_int(request.form.get("supplier_id")), form("description"), to_rappen(request.form.get("amount")),
                  to_num(request.form.get("vat_rate"), 0), choice("method", PAYMENT_METHODS + [""], "") or None,
                  form("reference"))
        if not values[3] or not values[4]:
            error("Description and amount are required")
        else:
            cols = "spent_on, category, supplier_id, description, amount, vat_rate, method, reference"
            if xid:
                get_db().execute(f"UPDATE expenses SET {', '.join(c + ' = ?' for c in cols.split(', '))} WHERE id = ?",
                                 (*values, xid))
                audit("update", "expense", xid)
            else:
                xid = get_db().execute(f"INSERT INTO expenses ({cols}, user_id) VALUES (?,?,?,?,?,?,?,?,?)",
                                       (*values, session["user_id"])).lastrowid
                audit("create", "expense", xid, values[3])
            get_db().commit()
            ok("Expense saved")
            return redirect(url_for("expenses.index", month=values[0][:7]))
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    rows = q("""SELECT x.*, s.name AS supplier,
                  (SELECT COUNT(*) FROM attachments WHERE entity = 'expense' AND entity_id = x.id) AS files
                FROM expenses x LEFT JOIN suppliers s ON s.id = x.supplier_id
                WHERE substr(x.spent_on,1,7) = ? ORDER BY x.spent_on DESC, x.id DESC""", (month,))
    by_cat = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]
    suppliers = q("SELECT id, name FROM suppliers ORDER BY name")
    files = q("SELECT * FROM attachments WHERE entity = 'expense' AND entity_id = ?", (xid,)) if xid else []
    return render_template("expenses.html", rows=rows, row=row, month=month, by_cat=by_cat, suppliers=suppliers,
                           categories=EXPENSE_CATEGORIES, default_vat=default_vat(), files=files,
                           total=sum(r["amount"] for r in rows), vat=sum(r["vat_amount"] for r in rows))


@bp.route("/<int:xid>/delete", methods=["POST"])
@admin_required
def delete(xid):
    get_db().execute("DELETE FROM expenses WHERE id = ?", (xid,))
    audit("delete", "expense", xid)
    get_db().commit()
    ok("Expense deleted")
    return redirect(url_for("expenses.index"))
