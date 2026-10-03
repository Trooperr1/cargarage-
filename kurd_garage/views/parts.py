from flask import Blueprint, redirect, render_template, request, session, url_for

from core import (UNITS, audit, checkbox, choice, error, form, get_db, login_required, ok, or_404, q, q1, to_int,
                  to_num, to_rappen)

bp = Blueprint("parts", __name__, url_prefix="/parts")

FIELDS = ["part_number", "ean", "name", "brand", "category", "unit", "supplier_id", "supplier_ref", "cost_price",
          "sell_price", "reorder_level", "location", "active", "notes"]


@bp.route("/")
@login_required
def index():
    term = request.args.get("q", "").strip()
    like = f"%{term}%"
    cat = request.args.get("category", "")
    sql = """SELECT p.*, s.name AS supplier FROM parts p LEFT JOIN suppliers s ON s.id = p.supplier_id
             WHERE (p.name LIKE ? OR p.part_number LIKE ? OR p.brand LIKE ? OR p.ean = ?)"""
    args = [like, like, like, term]
    if request.args.get("low"):
        sql += " AND p.active = 1 AND p.quantity <= p.reorder_level"
    if cat:
        sql += " AND p.category = ?"
        args.append(cat)
    if not request.args.get("inactive"):
        sql += " AND p.active = 1"
    rows = q(sql + " ORDER BY p.name", args)
    value = q1("SELECT COALESCE(SUM(quantity * cost_price), 0) FROM parts WHERE active = 1")
    categories = [r[0] for r in q("SELECT DISTINCT category FROM parts WHERE category IS NOT NULL ORDER BY 1")]
    return render_template("parts.html", rows=rows, value=value, categories=categories)


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def edit(pid=None):
    row = or_404(q("SELECT * FROM parts WHERE id = ?", (pid,), one=True)) if pid else None
    if request.method == "POST":
        f = {k: (request.form.get(k) or "").strip() or None for k in FIELDS}
        f["unit"] = choice("unit", UNITS, "pc")
        f["supplier_id"] = to_int(f["supplier_id"])
        f["cost_price"] = to_rappen(f["cost_price"], 0)
        f["sell_price"] = to_rappen(f["sell_price"], 0)
        f["reorder_level"] = to_num(f["reorder_level"], 0)
        f["active"] = checkbox("active") if pid else 1
        if not f["part_number"] or not f["name"]:
            error("Part number and name are required")
            row = request.form
        else:
            conn = get_db()
            if pid:
                conn.execute(f"UPDATE parts SET {', '.join(k + ' = ?' for k in FIELDS)} WHERE id = ?", (*f.values(), pid))
                audit("update", "part", pid)
            else:
                pid = conn.execute(f"INSERT INTO parts ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
                                   tuple(f.values())).lastrowid
                start = to_num(request.form.get("quantity"), 0)
                if start > 0:
                    conn.execute("INSERT INTO stock_movements (part_id, change, reason, unit_cost, note, user_id) "
                                 "VALUES (?, ?, 'purchase', ?, 'Opening stock', ?)",
                                 (pid, start, f["cost_price"], session["user_id"]))
                audit("create", "part", pid, f["name"])
            conn.commit()
            ok("Part saved")
            return redirect(url_for("parts.view", pid=pid))
    suppliers = q("SELECT * FROM suppliers ORDER BY name")
    categories = [r[0] for r in q("SELECT DISTINCT category FROM parts WHERE category IS NOT NULL ORDER BY 1")]
    return render_template("part_form.html", row=row, pid=pid, suppliers=suppliers, units=UNITS, categories=categories)


@bp.route("/<int:pid>")
@login_required
def view(pid):
    row = or_404(q("""SELECT p.*, s.name AS supplier FROM parts p LEFT JOIN suppliers s ON s.id = p.supplier_id
                      WHERE p.id = ?""", (pid,), one=True))
    moves = q("""SELECT m.*, u.full_name AS who FROM stock_movements m LEFT JOIN users u ON u.id = m.user_id
                 WHERE part_id = ? ORDER BY m.id DESC LIMIT 300""", (pid,))
    used_12m = q1("""SELECT COALESCE(-SUM(change), 0) FROM stock_movements WHERE part_id = ? AND reason IN ('job','job_return')
                     AND created_at >= date('now','localtime','-12 months')""", (pid,))
    return render_template("part_view.html", row=row, moves=moves, used_12m=used_12m)


@bp.route("/<int:pid>/stock", methods=["POST"])
@login_required
def stock(pid):
    part = or_404(q("SELECT * FROM parts WHERE id = ?", (pid,), one=True))
    reason = choice("reason", ["purchase", "adjustment", "count"])
    conn = get_db()
    if reason == "count":
        counted = to_num(request.form.get("change"))
        if counted is None or counted < 0:
            error("Enter the counted quantity")
            return redirect(url_for("parts.view", pid=pid))
        change = round(counted - part["quantity"], 3)
        reason, note = "adjustment", f"Stock count: {counted:g}. " + (form("note") or "")
    else:
        change, note = to_num(request.form.get("change")), form("note")
    if not change:
        error("Nothing to change")
        return redirect(url_for("parts.view", pid=pid))
    cost = to_rappen(request.form.get("unit_cost"), part["cost_price"])
    conn.execute("INSERT INTO stock_movements (part_id, change, reason, unit_cost, note, user_id) VALUES (?,?,?,?,?,?)",
                 (pid, change, reason, cost, note, session["user_id"]))
    if reason == "purchase" and cost != part["cost_price"] and request.form.get("update_cost"):
        conn.execute("UPDATE parts SET cost_price = ? WHERE id = ?", (cost, pid))
    audit("stock", "part", pid, f"{change:+g} {reason}")
    conn.commit()
    ok("Stock updated")
    return redirect(url_for("parts.view", pid=pid))


@bp.route("/order-list")
@login_required
def order_list():
    rows = q("""SELECT p.*, s.name AS supplier, s.phone AS supplier_phone, s.email AS supplier_email,
                  s.customer_number FROM low_stock p LEFT JOIN suppliers s ON s.id = p.supplier_id
                ORDER BY s.name, p.name""")
    return render_template("order_list.html", rows=rows)


@bp.route("/suppliers", methods=["GET", "POST"])
@bp.route("/suppliers/<int:sid>", methods=["GET", "POST"])
@login_required
def suppliers(sid=None):
    fields = ["name", "contact_person", "phone", "email", "website", "street", "postcode", "city", "customer_number", "notes"]
    row = or_404(q("SELECT * FROM suppliers WHERE id = ?", (sid,), one=True)) if sid else None
    if request.method == "POST":
        f = [form(k) for k in fields]
        if not f[0]:
            error("Name is required")
        else:
            if sid:
                get_db().execute(f"UPDATE suppliers SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", (*f, sid))
                audit("update", "supplier", sid)
            else:
                sid = get_db().execute(f"INSERT INTO suppliers ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                                       f).lastrowid
                audit("create", "supplier", sid, f[0])
            get_db().commit()
            ok("Supplier saved")
            return redirect(url_for("parts.suppliers"))
    rows = q("""SELECT s.*, (SELECT COUNT(*) FROM parts WHERE supplier_id = s.id) AS parts,
                  (SELECT COALESCE(SUM(amount),0) FROM expenses WHERE supplier_id = s.id
                   AND spent_on >= date('now','localtime','start of year')) AS spent_year
                FROM suppliers s ORDER BY s.name""")
    return render_template("suppliers.html", rows=rows, row=row)
