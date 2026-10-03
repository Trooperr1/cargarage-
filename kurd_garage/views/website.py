"""Manage the public website (cars for sale, shop parts, services, texts) and build / publish it."""
import io
import json
import os
import shutil
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, request, send_file, send_from_directory, url_for

import db
from core import (admin_required, audit, checkbox, choice, default_vat, error, form, get_db, login_required, ok, or_404,
                  q, q1, settings, to_int, to_rappen)

bp = Blueprint("website", __name__, url_prefix="/website")

TEMPLATE_DIR = os.path.normpath(os.path.join(db.BASE_DIR, "..", "website"))
BUILD_DIR = os.path.join(db.DATA_DIR, "website")
PART_CATEGORIES = [
    ["oil", "🛢️", "Oil & fluids"], ["filters", "🧰", "Filters"], ["brakes", "🛑", "Brakes"],
    ["battery", "🔋", "Batteries"], ["lights", "💡", "Lights & bulbs"], ["wipers", "🌧️", "Wipers"],
    ["tyres", "🛞", "Tyres & rims"], ["care", "✨", "Care & accessories"], ["engine", "⚙️", "Engine & ignition"],
    ["other", "📦", "Other parts"],
]
FUELS = ["Petrol", "Diesel", "Hybrid", "Plug-in hybrid", "Electric", "Gas"]
BODIES = ["Hatchback", "Saloon", "Estate", "SUV", "Coupé", "Convertible", "Van", "MPV", "Pick-up"]
CAR_STATUSES = ["available", "reserved", "sold", "hidden"]
DAYS = [(1, "Monday"), (2, "Tuesday"), (3, "Wednesday"), (4, "Thursday"), (5, "Friday"), (6, "Saturday"), (0, "Sunday")]
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


def save_photo(upload):
    """Save an uploaded photo, made smaller for the web when Pillow is installed."""
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in IMAGE_TYPES:
        raise ValueError(f"{upload.filename}: only JPG, PNG or WEBP photos")
    os.makedirs(db.UPLOAD_DIR, exist_ok=True)
    name = "web_" + uuid.uuid4().hex
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(upload.stream)).convert("RGB")
        img.thumbnail((1600, 1600))
        name += ".jpg"
        img.save(os.path.join(db.UPLOAD_DIR, name), "JPEG", quality=82, optimize=True)
    except ImportError:
        name += ext
        upload.save(os.path.join(db.UPLOAD_DIR, name))
    except OSError:
        raise ValueError(f"{upload.filename}: this photo cannot be read")
    return name


def lines(text):
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


# ---------------------------------------------------------------- overview

@bp.route("/")
@login_required
def index():
    counts = {
        "cars": q1("SELECT COUNT(*) FROM web_cars WHERE status IN ('available', 'reserved')"),
        "sold": q1("SELECT COUNT(*) FROM web_cars WHERE status = 'sold'"),
        "parts": q1("SELECT COUNT(*) FROM parts WHERE web_show = 1 AND active = 1"),
        "services": q1("SELECT COUNT(*) FROM web_services WHERE active = 1"),
    }
    built = os.path.exists(os.path.join(BUILD_DIR, "index.html"))
    return render_template("web_index.html", counts=counts, built=built, build_dir=BUILD_DIR,
                           template_ok=os.path.isdir(TEMPLATE_DIR))


# ---------------------------------------------------------------- cars for sale

CAR_FIELDS = ["make", "model", "year", "km", "price", "fuel", "gearbox", "power_ps", "body", "doors", "seats",
              "color_name", "color_hex", "first_reg", "mfk", "warranty", "status", "is_new", "features",
              "description", "cost"]


@bp.route("/cars")
@login_required
def cars():
    rows = q("""SELECT c.*, (SELECT stored_name FROM web_car_photos WHERE car_id = c.id ORDER BY sort, id LIMIT 1) AS photo,
                  (SELECT COUNT(*) FROM web_car_photos WHERE car_id = c.id) AS photos
                FROM web_cars c ORDER BY c.status = 'sold', c.status = 'hidden', c.created_at DESC""")
    return render_template("web_cars.html", rows=rows)


@bp.route("/cars/new", methods=["GET", "POST"])
@bp.route("/cars/<int:car_id>", methods=["GET", "POST"])
@login_required
def car_edit(car_id=None):
    row = or_404(q("SELECT * FROM web_cars WHERE id = ?", (car_id,), one=True)) if car_id else None
    if request.method == "POST":
        f = {k: (request.form.get(k) or "").strip() or None for k in CAR_FIELDS}
        for k in ("year", "km", "power_ps", "doors", "seats"):
            f[k] = to_int(f[k])
        f["price"] = to_rappen(f["price"])
        f["cost"] = to_rappen(f["cost"])
        f["status"] = choice("status", CAR_STATUSES, "available")
        f["is_new"] = checkbox("is_new")
        f["color_hex"] = f["color_hex"] or "#64748b"
        if not f["make"] or not f["model"] or f["price"] is None:
            error("Make, model and price are required")
            return render_template("web_car_form.html", row=request.form, car_id=car_id, photos=[],
                                   fuels=FUELS, bodies=BODIES, statuses=CAR_STATUSES)
        conn = get_db()
        if car_id:
            sold_at = row["sold_at"] or (datetime.now().strftime("%Y-%m-%d") if f["status"] == "sold" else None)
            conn.execute(f"UPDATE web_cars SET {', '.join(k + ' = ?' for k in CAR_FIELDS)}, sold_at = ? WHERE id = ?",
                         (*f.values(), sold_at if f["status"] == "sold" else None, car_id))
            audit("update", "web_car", car_id, f["status"])
        else:
            car_id = conn.execute(f"INSERT INTO web_cars ({', '.join(CAR_FIELDS)}) VALUES ({', '.join('?' * len(CAR_FIELDS))})",
                                  tuple(f.values())).lastrowid
            audit("create", "web_car", car_id, f"{f['make']} {f['model']}")
        start = (q1("SELECT MAX(sort) FROM web_car_photos WHERE car_id = ?", (car_id,)) or 0) + 1
        added = 0
        for n, upload in enumerate(request.files.getlist("photos")):
            if upload and upload.filename:
                conn.execute("INSERT INTO web_car_photos (car_id, stored_name, sort) VALUES (?,?,?)",
                             (car_id, save_photo(upload), start + n))
                added += 1
        conn.commit()
        auto_build()
        ok("Car saved" + (f" with {added} new photo(s)" if added else "") + ". The website preview is updated.")
        return redirect(url_for("website.car_edit", car_id=car_id))
    photos = q("SELECT * FROM web_car_photos WHERE car_id = ? ORDER BY sort, id", (car_id,)) if car_id else []
    return render_template("web_car_form.html", row=row, car_id=car_id, photos=photos, fuels=FUELS, bodies=BODIES,
                           statuses=CAR_STATUSES)


@bp.route("/cars/<int:car_id>/photos/<int:pid>/<action>", methods=["POST"])
@login_required
def car_photo(car_id, pid, action):
    photo = or_404(q("SELECT * FROM web_car_photos WHERE id = ? AND car_id = ?", (pid, car_id), one=True))
    conn = get_db()
    if action == "delete":
        conn.execute("DELETE FROM web_car_photos WHERE id = ?", (pid,))
        try:
            os.remove(os.path.join(db.UPLOAD_DIR, photo["stored_name"]))
        except OSError:
            pass
    elif action == "main":
        low = q1("SELECT MIN(sort) FROM web_car_photos WHERE car_id = ?", (car_id,)) or 0
        conn.execute("UPDATE web_car_photos SET sort = ? WHERE id = ?", (low - 1, pid))
    else:
        abort(404)
    conn.commit()
    auto_build()
    return redirect(url_for("website.car_edit", car_id=car_id) + "#photos")


@bp.route("/cars/<int:car_id>/delete", methods=["POST"])
@login_required
def car_delete(car_id):
    for p in q("SELECT stored_name FROM web_car_photos WHERE car_id = ?", (car_id,)):
        try:
            os.remove(os.path.join(db.UPLOAD_DIR, p["stored_name"]))
        except OSError:
            pass
    get_db().execute("DELETE FROM web_cars WHERE id = ?", (car_id,))
    audit("delete", "web_car", car_id)
    get_db().commit()
    auto_build()
    ok("Car deleted")
    return redirect(url_for("website.cars"))


@bp.route("/photo/<name>")
@login_required
def photo(name):
    if not name.startswith("web_") or "/" in name or "\\" in name:
        abort(404)
    return send_from_directory(db.UPLOAD_DIR, name)


# ---------------------------------------------------------------- parts in the online shop

@bp.route("/parts", methods=["GET", "POST"])
@login_required
def parts():
    if request.method == "POST":
        conn = get_db()
        pid = to_int(request.form.get("id"))
        or_404(q("SELECT id FROM parts WHERE id = ?", (pid,), one=True))
        image = q1("SELECT web_image FROM parts WHERE id = ?", (pid,))
        upload = request.files.get("image")
        if upload and upload.filename:
            image = save_photo(upload)
        conn.execute("UPDATE parts SET web_show = ?, web_category = ?, web_fits = ?, web_image = ? WHERE id = ?",
                     (checkbox("web_show"), choice("web_category", [c[0] for c in PART_CATEGORIES], "other"),
                      form("web_fits"), image, pid))
        conn.commit()
        auto_build()
        ok("Saved")
        return redirect(url_for("website.parts", show=request.args.get("show", "")) + f"#p{pid}")
    show = request.args.get("show", "")
    sql = "SELECT * FROM parts WHERE active = 1"
    if show == "online":
        sql += " AND web_show = 1"
    elif show == "offline":
        sql += " AND web_show = 0"
    rows = q(sql + " ORDER BY web_show DESC, name")
    return render_template("web_parts.html", rows=rows, cats=PART_CATEGORIES, vat=default_vat(), show=show)


@bp.route("/parts/all", methods=["POST"])
@login_required
def parts_all():
    value = 1 if request.form.get("value") == "1" else 0
    get_db().execute("UPDATE parts SET web_show = ? WHERE active = 1", (value,))
    get_db().execute("UPDATE parts SET web_category = 'other' WHERE web_category IS NULL")
    get_db().commit()
    auto_build()
    ok("All parts are now " + ("shown in" if value else "hidden from") + " the online shop")
    return redirect(url_for("website.parts"))


# ---------------------------------------------------------------- services

@bp.route("/services", methods=["GET", "POST"])
@login_required
def services():
    if request.method == "POST":
        sid = to_int(request.form.get("id"))
        values = (to_int(request.form.get("sort"), 0), form("icon") or "🔧", form("name"), to_rappen(request.form.get("price"), 0),
                  form("time"), form("text"), request.form.get("points", "").strip(), checkbox("active") if sid else 1)
        if not values[2]:
            error("Name is required")
        elif sid:
            get_db().execute("UPDATE web_services SET sort=?, icon=?, name=?, price=?, time=?, text=?, points=?, active=? "
                             "WHERE id=?", (*values, sid))
        else:
            get_db().execute("INSERT INTO web_services (sort, icon, name, price, time, text, points, active) "
                             "VALUES (?,?,?,?,?,?,?,?)", values)
        get_db().commit()
        auto_build()
        ok("Service saved")
        return redirect(url_for("website.services"))
    return render_template("web_services.html", rows=q("SELECT * FROM web_services ORDER BY active DESC, sort, id"))


# ---------------------------------------------------------------- texts, hours, links

TEXT_KEYS = ["web_slogan", "web_intro", "web_whatsapp", "web_map_lat", "web_map_lon", "web_owner", "web_founded",
             "web_instagram", "web_facebook", "web_tiktok", "web_google_reviews", "web_stats", "web_brands",
             "web_reviews"]


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def site_settings():
    if request.method == "POST":
        conn = get_db()
        hours = {}
        for d, _ in DAYS:
            slots = []
            for n in (1, 2):
                a, b = request.form.get(f"h{d}_{n}_from", "").strip(), request.form.get(f"h{d}_{n}_to", "").strip()
                if a and b:
                    if a >= b:
                        raise ValueError("Opening hours: the start time must be before the end time")
                    slots.append([a, b])
            hours[str(d)] = slots
        values = {k: request.form.get(k, "").strip() for k in TEXT_KEYS}
        values["web_hours"] = json.dumps(hours)
        for k, v in values.items():
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (k, v))
        audit("update", "website settings")
        conn.commit()
        auto_build()
        ok("Website settings saved")
        return redirect(url_for("website.site_settings"))
    hours = json.loads(settings().get("web_hours") or "{}")
    return render_template("web_settings.html", hours=hours, days=DAYS)


# ---------------------------------------------------------------- build

def site_data():
    """Everything the website shows, taken from the garage database."""
    s = settings()
    hours = json.loads(s.get("web_hours") or "{}")
    stats = [[x.strip() for x in line.split("|", 1)] for line in lines(s.get("web_stats")) if "|" in line]
    reviews = []
    for line in lines(s.get("web_reviews")):
        parts = [x.strip() for x in line.split("|", 2)]
        if len(parts) == 3:
            stars = max(1, min(5, int(parts[1]) if parts[1].isdigit() else 5))
            reviews.append({"name": parts[0], "stars": stars, "text": parts[2]})
    try:
        lat, lon = float(s.get("web_map_lat") or 47.3769), float(s.get("web_map_lon") or 8.5417)
    except ValueError:
        lat, lon = 47.3769, 8.5417
    garage = {
        "name": s.get("garage_name") or "Kurd Garage", "slogan": s.get("web_slogan"), "intro": s.get("web_intro"),
        "phone": s.get("phone"), "whatsapp": s.get("web_whatsapp") or s.get("phone"), "email": s.get("email"),
        "street": f"{s.get('street', '')} {s.get('house_number', '')}".strip(), "postcode": s.get("postcode"),
        "city": s.get("city"), "country": "Switzerland" if (s.get("country") or "CH") == "CH" else s.get("country"),
        "mapLat": lat, "mapLon": lon, "hours": {k: v for k, v in hours.items()},
        "owner": s.get("web_owner"), "uid": s.get("uid"), "founded": to_int(s.get("web_founded")) or datetime.now().year,
        "instagram": s.get("web_instagram"), "facebook": s.get("web_facebook"), "tiktok": s.get("web_tiktok"),
        "googleReviews": s.get("web_google_reviews"), "stats": stats,
        "brands": [b.strip() for b in (s.get("web_brands") or "").split(",") if b.strip()], "reviews": reviews,
    }
    def service_id(r):
        word = "".join(ch for ch in (r["name"] or "").split(" ")[0].lower() if ch.isalnum())
        return word or f"s{r['id']}"
    services = [{"id": service_id(r), "icon": r["icon"], "name": r["name"], "price": r["price"] / 100, "time": r["time"] or "",
                 "text": r["text"] or "", "points": lines(r["points"])}
                for r in q("SELECT * FROM web_services WHERE active = 1 ORDER BY sort, id")]
    cars, images = [], []
    for c in q("SELECT * FROM web_cars WHERE status <> 'hidden' ORDER BY status = 'sold', created_at DESC"):
        photos = [p["stored_name"] for p in q("SELECT stored_name FROM web_car_photos WHERE car_id = ? ORDER BY sort, id", (c["id"],))]
        images += photos
        slug = "-".join(x for x in f"{c['make']} {c['model']} {c['year'] or ''}".lower().replace("/", " ").split() if x)
        cars.append({"id": f"{c['id']}-{''.join(ch for ch in slug if ch.isalnum() or ch == '-')[:60]}",
                     "make": c["make"], "model": c["model"], "year": c["year"] or "", "km": c["km"] or 0,
                     "price": c["price"] / 100, "fuel": c["fuel"] or "", "gearbox": c["gearbox"] or "",
                     "power": c["power_ps"] or 0, "body": c["body"] or "", "doors": c["doors"] or "", "seats": c["seats"] or "",
                     "color": c["color_hex"], "colorName": c["color_name"] or "", "firstReg": c["first_reg"] or "",
                     "mfk": c["mfk"] or "", "warranty": c["warranty"] or "", "status": c["status"],
                     "isNew": bool(c["is_new"]), "images": ["images/" + p for p in photos],
                     "features": lines(c["features"]), "text": c["description"] or ""})
    vat = default_vat()
    parts = []
    for p in q("SELECT * FROM parts WHERE web_show = 1 AND active = 1 ORDER BY name"):
        if p["web_image"]:
            images.append(p["web_image"])
        parts.append({"id": f"p{p['id']}", "cat": p["web_category"] or "other", "name": p["name"], "brand": p["brand"] or "",
                      "price": round(p["sell_price"] * (100 + vat) / 100 / 5) * 5 / 100, "stock": int(p["quantity"]),
                      "fits": p["web_fits"] or "", "image": ("images/" + p["web_image"]) if p["web_image"] else ""})
    return garage, services, cars, parts, images


def build():
    if not os.path.isdir(TEMPLATE_DIR):
        raise ValueError("The 'website' folder is missing next to the 'kurd_garage' folder. Download the program again.")
    garage, services, cars, parts, images = site_data()
    # Pages, styles and data are written fresh; photos are only copied when new (fast to rebuild often).
    os.makedirs(BUILD_DIR, exist_ok=True)
    for entry in os.listdir(BUILD_DIR):
        if entry != "images":
            full = os.path.join(BUILD_DIR, entry)
            shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
    for entry in os.listdir(TEMPLATE_DIR):
        if entry in ("data", "images", "README.md"):
            continue
        src = os.path.join(TEMPLATE_DIR, entry)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(BUILD_DIR, entry))
        else:
            shutil.copy2(src, os.path.join(BUILD_DIR, entry))
    os.makedirs(os.path.join(BUILD_DIR, "data"))
    image_dir = os.path.join(BUILD_DIR, "images")
    os.makedirs(image_dir, exist_ok=True)

    def write(name, body):
        with open(os.path.join(BUILD_DIR, "data", name), "w", encoding="utf-8") as fh:
            fh.write("/* Made by the Kurd Garage program — do not edit, change it in the program instead. */\n" + body)
    dump = lambda v: json.dumps(v, ensure_ascii=False, indent=1)  # noqa: E731
    write("config.js", f"window.GARAGE = {dump(garage)};\n")
    write("services.js", f"window.SERVICES = {dump(services)};\n")
    write("cars.js", f"window.CARS = {dump(cars)};\n")
    write("parts.js", f"window.PART_CATEGORIES = {dump(PART_CATEGORIES)};\nwindow.PARTS = {dump(parts)};\n")
    wanted = set(images)
    for name in os.listdir(image_dir):
        if name not in wanted:
            os.remove(os.path.join(image_dir, name))
    for name in wanted:
        src, dst = os.path.join(db.UPLOAD_DIR, name), os.path.join(image_dir, name)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    name = settings().get("garage_name") or "Kurd Garage"
    for html in os.listdir(BUILD_DIR):
        if html.endswith(".html"):
            path = os.path.join(BUILD_DIR, html)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace("Kurd Garage", name))
    conn = get_db()
    conn.execute("UPDATE settings SET value = ? WHERE key = 'web_last_build'", (datetime.now().strftime("%Y-%m-%d %H:%M"),))
    conn.commit()
    return len(cars), len(parts)


def auto_build():
    """Keep the preview up to date after every change. Shows a message if it cannot be built."""
    try:
        build()
        return True
    except (ValueError, OSError) as err:
        error(f"The website could not be updated: {err}")
        return False


def zip_bytes():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(BUILD_DIR):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, BUILD_DIR).replace("\\", "/"))
    return out.getvalue()


@bp.route("/build", methods=["POST"])
@login_required
def build_site():
    n_cars, n_parts = build()
    audit("build", "website", None, f"{n_cars} cars, {n_parts} parts")
    get_db().commit()
    ok(f"Website built: {n_cars} cars, {n_parts} parts. Check the preview, then publish it.")
    return redirect(url_for("website.index"))


@bp.route("/preview/")
@bp.route("/preview/<path:filename>")
@login_required
def preview(filename="index.html"):
    if filename.endswith(".html") and not auto_build():   # every preview page shows the newest data
        return redirect(url_for("website.index"))
    if not os.path.isdir(BUILD_DIR):
        error("Build the website first")
        return redirect(url_for("website.index"))
    resp = send_from_directory(BUILD_DIR, filename)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/download")
@login_required
def download():
    if not os.path.isdir(BUILD_DIR):
        error("Build the website first")
        return redirect(url_for("website.index"))
    return send_file(io.BytesIO(zip_bytes()), mimetype="application/zip", as_attachment=True,
                     download_name=f"website_{datetime.now():%Y-%m-%d}.zip")


@bp.route("/publish", methods=["GET", "POST"])
@admin_required
def publish():
    conn = get_db()
    if request.method == "POST" and request.form.get("save_keys"):
        for k in ("web_netlify_token", "web_netlify_site"):
            conn.execute("UPDATE settings SET value = ? WHERE key = ?", ((request.form.get(k) or "").strip(), k))
        conn.commit()
        ok("Saved")
        return redirect(url_for("website.publish"))
    if request.method == "POST":
        s = settings()
        if not s.get("web_netlify_token") or not s.get("web_netlify_site"):
            error("Enter your Netlify token and site ID first (see the steps below)")
            return redirect(url_for("website.publish"))
        build()
        req = urllib.request.Request(
            f"https://api.netlify.com/api/v1/sites/{s['web_netlify_site']}/deploys", data=zip_bytes(), method="POST",
            headers={"Content-Type": "application/zip", "Authorization": f"Bearer {s['web_netlify_token']}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as err:
            error(f"Netlify refused the upload ({err.code}). Check the token and site ID." if err.code in (401, 403, 404)
                  else f"Netlify error {err.code}. Try again later.")
            return redirect(url_for("website.publish"))
        except (urllib.error.URLError, OSError):
            error("No internet connection to Netlify. Check the internet and try again.")
            return redirect(url_for("website.publish"))
        conn.execute("UPDATE settings SET value = ? WHERE key = 'web_last_publish'", (datetime.now().strftime("%Y-%m-%d %H:%M"),))
        audit("publish", "website", None, result.get("ssl_url") or result.get("url"))
        conn.commit()
        ok(f"Website is online! {result.get('ssl_url') or result.get('url') or ''}")
        return redirect(url_for("website.index"))
    return render_template("web_publish.html")
