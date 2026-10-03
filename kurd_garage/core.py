"""Shared helpers: database access, money/VAT maths, security, formatting."""
import json
import secrets
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

import db

JOB_STATUSES = ["quote", "open", "in_progress", "waiting_parts", "done", "delivered", "cancelled"]
ACTIVE_STATUSES = ("open", "in_progress", "waiting_parts")
PAYMENT_METHODS = ["cash", "card", "twint", "bank transfer", "other"]
CANTONS = ["AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW", "OW",
           "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH"]
FUELS = ["petrol", "diesel", "hybrid", "plug-in hybrid", "electric", "gas", "other"]
EXPENSE_CATEGORIES = ["parts purchase", "rent", "energy", "salaries", "insurance", "tools & equipment",
                      "vehicles", "marketing", "office", "disposal", "taxes & fees", "other"]
EMPLOYEE_ROLES = ["mechanic", "master mechanic", "apprentice", "service advisor", "office", "other"]
UNITS = ["pc", "set", "l", "kg", "m"]


# ---------------------------------------------------------------- database

def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


def q(sql, args=(), one=False):
    rows = get_db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def q1(sql, args=()):
    """First column of the first row."""
    row = get_db().execute(sql, args).fetchone()
    return row[0] if row else None


def settings():
    if "settings" not in g:
        g.settings = db.get_settings(get_db())
    return g.settings


def setting_int(key, default=0):
    try:
        return int(settings().get(key) or default)
    except ValueError:
        return default


def default_vat():
    s = settings()
    return float(s.get("vat_rate") or 0) if s.get("vat_registered") == "1" else 0.0


def audit(action, entity, entity_id=None, details=None):
    get_db().execute(
        "INSERT INTO audit_log (user_id, action, entity, entity_id, details) VALUES (?, ?, ?, ?, ?)",
        (session.get("user_id"), action, entity, entity_id, details),
    )


def or_404(row):
    if row is None:
        abort(404)
    return row


# ---------------------------------------------------------------- input parsing

def form(name):
    value = request.form.get(name, "").strip()
    return value or None


def _clean_number(value):
    return (value or "").strip().replace("'", "").replace("’", "").replace(" ", "").replace("CHF", "").replace(",", ".")


def to_int(value, default=None):
    value = _clean_number(value)
    if value == "":
        return default
    try:
        return int(Decimal(value))
    except InvalidOperation:
        raise ValueError(f"'{value}' is not a whole number")


def to_num(value, default=None):
    """Decimal number such as quantity, hours or a percentage."""
    value = _clean_number(value)
    if value == "":
        return default
    try:
        return float(Decimal(value).quantize(Decimal("0.001")))
    except InvalidOperation:
        raise ValueError(f"'{value}' is not a number")


def to_rappen(value, default=None):
    """'1'234.50' -> 123450"""
    value = _clean_number(value)
    if value == "":
        return default
    try:
        return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        raise ValueError(f"'{value}' is not an amount of money")


def to_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"'{value}' is not a valid date")


def checkbox(name):
    return 1 if request.form.get(name) else 0


def choice(name, options, default=None):
    value = request.form.get(name) or default
    if value is not None and value not in options:
        raise ValueError(f"Invalid value for {name}")
    return value


# ---------------------------------------------------------------- formatting

def chf(rappen, symbol=True):
    rappen = int(rappen or 0)
    sign = "-" if rappen < 0 else ""
    francs, cents = divmod(abs(rappen), 100)
    text = f"{sign}{francs:,}.{cents:02d}".replace(",", "'")
    return f"CHF {text}" if symbol else text


def rappen_input(rappen):
    """Value for an <input> field."""
    if rappen is None:
        return ""
    return f"{int(rappen) / 100:.2f}"


def qty(value):
    if value is None:
        return ""
    value = float(value)
    return f"{value:g}" if value != int(value) else str(int(value))


def local_ip():
    """This computer's address in the local Wi-Fi network (e.g. 192.168.1.20)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # no data is sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def phone_intl(value):
    """'079 123 45 67' -> '41791234567' (for WhatsApp / SMS links)."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if (value or "").strip().startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return "41" + digits[1:]
    return digits


def iban(value):
    value = (value or "").replace(" ", "")
    return " ".join(value[i:i + 4] for i in range(0, len(value), 4))


def km(value):
    if value is None or value == "":
        return ""
    return f"{int(value):,}".replace(",", "'") + " km"


def swiss_date(value):
    if not value:
        return ""
    try:
        d = datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return value
    text = d.strftime("%d.%m.%Y")
    if len(str(value)) > 10 and str(value)[11:16] != "00:00":
        text += d.strftime(" %H:%M")
    return text


def days_until(value):
    if not value:
        return None
    return (date.fromisoformat(str(value)[:10]) - date.today()).days


def today():
    return date.today().isoformat()


def plus_days(n, start=None):
    return ((start or date.today()) + timedelta(days=int(n))).isoformat()


# ---------------------------------------------------------------- totals

def job_totals(job_id):
    """Net per VAT rate, VAT, 5-Rappen rounding and total for a job."""
    rows = q("SELECT kind, net, vat_rate, quantity, unit_cost FROM job_items WHERE job_id = ?", (job_id,))
    by_rate = {}
    labour = parts = other = cost = 0
    for r in rows:
        by_rate[r["vat_rate"]] = by_rate.get(r["vat_rate"], 0) + r["net"]
        if r["kind"] == "labour":
            labour += r["net"]
        elif r["kind"] == "part":
            parts += r["net"]
            cost += round(r["quantity"] * r["unit_cost"])
        else:
            other += r["net"]
    breakdown = [[rate, net, int((Decimal(net) * Decimal(str(rate)) / 100).quantize(Decimal("1"), ROUND_HALF_UP))]
                 for rate, net in sorted(by_rate.items())]
    subtotal = sum(b[1] for b in breakdown)
    vat = sum(b[2] for b in breakdown)
    gross = subtotal + vat
    total = gross
    if settings().get("round_5_rappen") == "1":
        total = int((Decimal(gross) / 5).quantize(Decimal("1"), ROUND_HALF_UP) * 5)
    return {"labour": labour, "parts": parts, "other": other, "parts_cost": cost, "subtotal": subtotal,
            "vat": vat, "breakdown": breakdown, "rounding": total - gross, "total": total}


def vat_breakdown(invoice):
    return json.loads(invoice["vat_breakdown"] or "[]")


def address_lines(c):
    """Postal address of a customer row as a list of lines."""
    lines = []
    if c["company"]:
        lines.append(c["company"])
        if c["contact_person"]:
            lines.append(c["contact_person"])
    else:
        sal = {"Mr": "Mr", "Ms": "Ms", "Family": "Family"}.get(c["salutation"] or "", "")
        lines.append(" ".join(x for x in [sal, c["first_name"], c["last_name"]] if x))
    street = " ".join(x for x in [c["street"], c["house_number"]] if x)
    if street:
        lines.append(street)
    town = " ".join(x for x in [c["postcode"], c["city"]] if x)
    if town:
        lines.append(town if (c["country"] or "CH") == "CH" else f"{c['country']}-{town}")
    return lines


# ---------------------------------------------------------------- security

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def back(default_endpoint="dashboard.index", **kwargs):
    target = request.referrer
    if target and target.startswith(request.host_url):
        return redirect(target)
    return redirect(url_for(default_endpoint, **kwargs))


def ok(message):
    flash(message, "ok")


def error(message):
    flash(message, "error")
