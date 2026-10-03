"""Kurd Garage - garage management system for Switzerland (Flask + SQLite)."""
import mimetypes
import os
import sqlite3
from datetime import timedelta

from flask import Flask, abort, flash, g, render_template, request, session
from werkzeug.exceptions import HTTPException

import core
import db
from views import (admin, appointments, auth, customers, dashboard, expenses, invoices, jobs, parts,
                   reports, staff, tyres, vehicles, website)

# Some Windows computers report wrong file types for these, then the browser ignores the design.
for _ext, _type in ((".css", "text/css"), (".js", "text/javascript"), (".svg", "image/svg+xml"),
                    (".html", "text/html"), (".json", "application/json"), (".webp", "image/webp")):
    mimetypes.add_type(_type, _ext)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("KURD_GARAGE_SECRET") or db.secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024   # uploads up to 25 MB
app.config["PHONE_MODE"] = os.environ.get("HOST") == "0.0.0.0"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)   # log out automatically after 12 hours

for module in (auth, dashboard, customers, vehicles, jobs, invoices, parts, appointments, tyres, staff,
               expenses, reports, admin, website):
    app.register_blueprint(module.bp)

app.jinja_env.filters.update(chf=core.chf, money_in=core.rappen_input, qty=core.qty, d=core.swiss_date, km=core.km, iban=core.iban, intl=core.phone_intl,
                             days_until=core.days_until)


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@app.before_request
def before():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf"):
            abort(400, "This form expired. Please go back, reload the page and try again.")


@app.context_processor
def inject_globals():
    return {"csrf": core.csrf_token(), "S": core.settings(), "statuses": core.JOB_STATUSES,
            "today": core.today(), "payment_methods": core.PAYMENT_METHODS, "cantons": core.CANTONS}


@app.errorhandler(sqlite3.IntegrityError)
def integrity_error(err):
    core.get_db().rollback()
    msg = str(err)
    if "FOREIGN KEY" in msg:
        msg = "This record is still used by other records (for example a customer with cars, or a car with jobs)."
    elif "UNIQUE" in msg:
        field = msg.split(":")[-1].strip()
        msg = {"vehicles.plate": "A car with this plate number already exists.",
               "vehicles.vin": "A car with this VIN / chassis number already exists.",
               "parts.part_number": "A part with this part number already exists.",
               "tyre_sets.location": "This storage place is already used by another tyre set.",
               "users.username": "This username is already taken.",
               "services.code": "A service with this code already exists.",
               "suppliers.name": "A supplier with this name already exists."}.get(field, "This value already exists: " + field)
    elif "CHECK" in msg and "quantity" in msg:
        msg = "Not enough parts in stock. Book the delivery under Parts first (or correct the stock)."
    elif "CHECK" in msg:
        msg = "Some values are not allowed (for example a negative number or a missing name/phone)."
    flash(msg, "error")
    return core.back()


@app.errorhandler(sqlite3.DatabaseError)
def database_error(err):
    core.get_db().rollback()
    flash(str(err), "error")
    return core.back()


@app.errorhandler(HTTPException)
def http_error(err):
    if err.code == 413:
        flash("The file is too big (maximum 25 MB).", "error")
        return core.back()
    return render_template("error.html", code=err.code, message=err.description), err.code


@app.errorhandler(Exception)
def unexpected_error(err):
    app.logger.exception("Unexpected error")
    return render_template("error.html", code=500, message=f"{type(err).__name__}: {err}"), 500


@app.errorhandler(ValueError)
def value_error(err):
    flash(str(err), "error")
    return core.back()


db.init_db()

if __name__ == "__main__":
    import threading
    import webbrowser

    db.backup()  # automatic backup every time the program starts
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Kurd Garage is running at http://127.0.0.1:{port}")
    print(f"  Data:    {db.DB_PATH}")
    print(f"  Backups: {db.backup_dir()}")
    print("  Keep this window open while you use the program.\n")
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, webbrowser.open, (f"http://127.0.0.1:{port}",)).start()
    host = os.environ.get("HOST", "127.0.0.1")
    if host == "0.0.0.0":
        print(f"  PHONE: open  http://{core.local_ip()}:{port}  on a phone in the same Wi-Fi")
        print("  (or log in on this computer and click the phone icon to scan a QR code)\n")
    try:
        import logging

        from waitress import serve   # stable multi-user server
        logging.getLogger("waitress.queue").setLevel(logging.ERROR)
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        app.run(host=host, port=port)
