from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core import audit, error, get_db, login_required, ok, q

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = q("SELECT * FROM users WHERE username = ? AND active = 1", (request.form.get("username", ""),), one=True)
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            csrf = session.get("csrf")
            session.clear()
            session.update(user_id=user["id"], name=user["full_name"], role=user["role"], csrf=csrf)
            get_db().execute("UPDATE users SET last_login = datetime('now','localtime') WHERE id = ?", (user["id"],))
            get_db().commit()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard.index"))
        error("Wrong username or password")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    if request.method == "POST":
        user = q("SELECT * FROM users WHERE id = ?", (session["user_id"],), one=True)
        new = request.form.get("new", "")
        if not check_password_hash(user["password_hash"], request.form.get("old", "")):
            error("Current password is wrong")
        elif len(new) < 6:
            error("New password must be at least 6 characters")
        elif new != request.form.get("new2"):
            error("The two new passwords are not the same")
        else:
            get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), user["id"]))
            audit("password_change", "user", user["id"])
            get_db().commit()
            ok("Password changed")
            return redirect(url_for("dashboard.index"))
    return render_template("password.html")
