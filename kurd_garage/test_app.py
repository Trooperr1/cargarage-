"""End-to-end tests. Run: python -m unittest test_app"""
import io
import os
import re
import tempfile
import unittest

os.environ["KURD_GARAGE_DATA"] = tempfile.mkdtemp()

import app as garage  # noqa: E402
import core  # noqa: E402
import db  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.c = garage.app.test_client()
        self.c.get("/login")
        self.post("/login", username="admin", password="admin123")
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()

    def token(self):
        with self.c.session_transaction() as s:
            return s["csrf"]

    def post(self, url, files=None, **data):
        data["csrf"] = self.token()
        if files:
            data.update(files)
            return self.c.post(url, data=data, follow_redirects=True, content_type="multipart/form-data")
        return self.c.post(url, data=data, follow_redirects=True)

    def get(self, url):
        r = self.c.get(url)
        self.assertEqual(r.status_code, 200, f"{url}: {r.data[-800:]}")
        return r

    def one(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    @staticmethod
    def new_id(resp):
        return int(re.search(r"/(\d+)(?:/[a-z]*)?$", resp.request.path).group(1))


class FullWorkflow(Base):
    def test_full_workflow(self):
        self.post("/admin/settings", garage_name="Kurd Garage", street="Bahnhofstrasse", house_number="12",
                  postcode="8001", city="Zürich", canton="ZH", country="CH", phone="044 123 45 67",
                  iban="CH93 0076 2011 6238 5295 7", uid="CHE-123.456.789 MWST", vat_registered="1", vat_rate="8.1",
                  round_5_rappen="1", hourly_rate="135.00", payment_days="30", quote_valid_days="30",
                  tyre_storage_fee="90", reminder_fee_2="20", reminder_fee_3="30", reminder_days="10",
                  mfk_warn_days="60", invoice_footer="Thanks", backup_dir="")
        self.assertEqual(self.one("SELECT value FROM settings WHERE key='hourly_rate'"), "13500")

        # customer + vehicle
        r = self.post("/customers/new", kind="private", salutation="Mr", first_name="Hans", last_name="Muster",
                      street="Dorfstrasse", house_number="5", postcode="3000", city="Bern", country="CH",
                      mobile="079 123 45 67", email="Hans@Example.ch", reminders_ok="1")
        cid = self.new_id(r)
        self.assertEqual(self.one("SELECT display_name FROM customers WHERE id=?", cid), "Hans Muster")
        r = self.post(f"/vehicles/new/{cid}", plate="zh123456", make="Volkswagen", model="Golf",
                      vin="WVWZZZ1KZAW000001", first_registration="2019-03-15", fuel="diesel", mileage="85000",
                      mfk_next=core.plus_days(20), power_kw="110")
        vid = self.new_id(r)
        self.assertIn(b"ZH 123456", r.data)
        self.assertEqual(self.one("SELECT year FROM vehicles WHERE id=?", vid), 2019)

        # stock + staff
        r = self.post("/parts/new", part_number="OC-1", name="Oil filter", unit="pc", cost_price="8.50",
                      sell_price="18.90", quantity="10", reorder_level="3")
        pid = self.new_id(r)
        r = self.post("/parts/new", part_number="OIL-5W30", name="Engine oil 5W-30", unit="l", cost_price="6",
                      sell_price="14.50", quantity="40", reorder_level="10")
        oil = self.new_id(r)
        r = self.post("/staff/new", first_name="Hemn", last_name="Ali", role="mechanic", hourly_cost="45")
        eid = self.new_id(r)

        # quote does NOT take parts from stock
        r = self.post(f"/jobs/new/{vid}", kind="quote", complaint="Service", mileage_in="90000")
        quote = self.new_id(r)
        self.post(f"/jobs/{quote}/items", kind="part", part_id=str(pid), quantity="1")
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 9 + 1)
        # turning it into a job does
        self.post(f"/jobs/{quote}/update", status="open", complaint="Service")
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 9)
        # cancelling it gives the part back
        self.post(f"/jobs/{quote}/update", status="cancelled", complaint="Service")
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 10)
        self.assertEqual(self.one("SELECT mileage FROM vehicles WHERE id=?", vid), 90000)

        # real job
        r = self.post(f"/jobs/new/{vid}", kind="job", complaint="Oil service + brakes", mileage_in="90500",
                      employee_id=str(eid), fuel_level="1/2", damages="Scratch rear bumper")
        jid = self.new_id(r)
        oil_service = self.one("SELECT id FROM services WHERE code='OIL'")
        self.post(f"/jobs/{jid}/items", kind="service", service_id=str(oil_service))
        self.post(f"/jobs/{jid}/items", kind="part", part_id=str(pid), quantity="1")
        self.post(f"/jobs/{jid}/items", kind="part", part_code="OIL-5W30", quantity="4.5")
        self.post(f"/jobs/{jid}/items", kind="labour", description="Brake pads front", quantity="1.5", unit_price="")
        self.post(f"/jobs/{jid}/items", kind="other", description="Disposal fee", quantity="1", unit_price="9.50")
        self.post(f"/jobs/{jid}/time", employee_id=str(eid), hours="2.5", work_date=core.today())
        self.assertAlmostEqual(self.one("SELECT quantity FROM parts WHERE id=?", oil), 35.5)

        # too many parts -> refused, stock unchanged
        r = self.post(f"/jobs/{jid}/items", kind="part", part_id=str(pid), quantity="99")
        self.assertIn(b"Not enough parts", r.data)
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 9)

        # edit a line (quantity change moves stock)
        iid = self.one("SELECT id FROM job_items WHERE job_id=? AND part_id=?", jid, pid)
        self.post(f"/jobs/{jid}/items/{iid}", description="Oil filter", quantity="2", unit_price="18.90",
                  discount_pct="0", vat_rate="8.1")
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 8)

        with garage.app.test_request_context():
            t = core.job_totals(jid)
        # 1h*135 + 2*18.90 + 4.5*14.50 + 1.5*135 + 9.50 = 135 + 37.80 + 65.25 + 202.50 + 9.50 = 450.05
        self.assertEqual(t["subtotal"], 45005)
        self.assertEqual(t["vat"], 3645)               # 8.1 % of 450.05 = 36.454
        self.assertEqual(t["total"] % 5, 0)            # rounded to 5 Rappen
        self.assertEqual(t["total"], 48650)

        for url in [f"/jobs/{jid}", f"/jobs/{jid}/print/card", f"/jobs/{jid}/print/quote", f"/vehicles/{vid}",
                    f"/vehicles/{vid}/history", f"/customers/{cid}", f"/invoices/create/{jid}", "/",
                    f"/staff/{eid}", "/staff/", "/jobs/?status=active"]:
            self.get(url)

        # invoice
        r = self.post(f"/invoices/create/{jid}", issue_date=core.today(), due_date=core.plus_days(30))
        inv = self.new_id(r)
        number = self.one("SELECT number FROM invoices WHERE id=?", inv)
        self.assertRegex(number, r"^\d{4}-0001$")
        self.assertEqual(self.one("SELECT total FROM invoices WHERE id=?", inv), 48650)
        self.assertEqual(self.one("SELECT status FROM jobs WHERE id=?", jid), "done")

        # invoiced job is frozen
        r = self.post(f"/jobs/{jid}/items", kind="other", description="x", unit_price="1")
        self.assertIn(b"invoiced", r.data)
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM job_items WHERE job_id=?", (jid,))
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE invoices SET total = 1 WHERE id=?", (inv,))
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM invoices WHERE id=?", (inv,))
        self.conn.rollback()

        # print with QR bill
        r = self.get(f"/invoices/{inv}/print")
        self.assertIn(b"<svg", r.data)
        self.assertIn(b"486.50", r.data)

        # reminders
        self.post(f"/invoices/{inv}/remind", fee="0")
        self.post(f"/invoices/{inv}/remind", fee="20")
        self.assertEqual(self.one("SELECT open_amount FROM invoice_balance WHERE id=?", inv), 48650 + 2000)
        r = self.get(f"/invoices/{inv}/print?reminder=2")
        self.assertIn(b"PAYMENT REMINDER 2", r.data)

        # overpay refused, part pay, full pay
        r = self.post(f"/invoices/{inv}/pay", amount="9999", method="cash")
        self.assertIn(b"larger than the amount", r.data)
        self.post(f"/invoices/{inv}/pay", amount="100", method="twint")
        self.post(f"/invoices/{inv}/pay", amount="406.50", method="card", deliver="1")
        self.assertEqual(self.one("SELECT open_amount FROM invoice_balance WHERE id=?", inv), 0)
        self.assertEqual(self.one("SELECT status FROM jobs WHERE id=?", jid), "delivered")

        # paid invoice cannot be cancelled
        r = self.post(f"/invoices/{inv}/cancel", reason="test")
        self.assertIn(b"has payments", r.data)

        # tyre hotel: store winter set, then swap
        r = self.post(f"/tyres/new/{vid}", season="winter", brand="Michelin", size="205/55 R16", location="a-1",
                      status="stored", tread_fl="5", tread_fr="5", tread_rl="3.5", tread_rr="5", fee="90")
        winter = self.one("SELECT id FROM tyre_sets WHERE vehicle_id=? AND season='winter'", vid)
        self.post(f"/tyres/new/{vid}", season="summer", brand="Conti", status="on vehicle")
        summer = self.one("SELECT id FROM tyre_sets WHERE vehicle_id=? AND season='summer'", vid)
        r = self.post(f"/tyres/new/{vid}", season="summer", status="stored", location="A-1")
        self.assertIn(b"already used", r.data)
        self.post(f"/tyres/swap/{vid}", stored_id=str(winter), mounted_id=str(summer))
        self.assertEqual(self.one("SELECT status FROM tyre_sets WHERE id=?", winter), "on vehicle")
        self.assertEqual(self.one("SELECT location FROM tyre_sets WHERE id=?", summer), "A-1")
        self.get("/tyres/")

        # appointment -> job
        r = self.post("/appointments/new", day=core.today(), time="09:30", minutes="60", vehicle_id=str(vid),
                      title="MFK preparation", status="booked")
        aid = self.one("SELECT MAX(id) FROM appointments")
        self.assertEqual(self.one("SELECT customer_id FROM appointments WHERE id=?", aid), cid)
        self.get("/appointments/")
        self.get(f"/appointments/{aid}")
        r = self.post(f"/jobs/new/{vid}?appointment={aid}", complaint="MFK preparation")
        self.assertEqual(self.one("SELECT status FROM appointments WHERE id=?", aid), "arrived")

        # expense with VAT
        self.post("/expenses/", spent_on=core.today(), category="rent", description="Workshop rent",
                  amount="2500", vat_rate="8.1")
        self.assertEqual(self.one("SELECT vat_amount FROM expenses"), 18733)   # 2500 * 8.1 / 108.1 = 187.33

        # uploads
        r = self.post(f"/admin/files/job/{jid}", files={"files": (io.BytesIO(b"\x89PNG fake"), "damage.png")},
                      caption="rear bumper")
        self.assertEqual(self.one("SELECT COUNT(*) FROM attachments"), 1)
        fid = self.one("SELECT id FROM attachments")
        self.get(f"/admin/files/{fid}")
        r = self.post(f"/admin/files/job/{jid}", files={"files": (io.BytesIO(b"MZ"), "virus.exe")})
        self.assertIn(b"not allowed", r.data)

        # reports
        for url in ["/reports/", "/reports/?preset=year", "/reports/?preset=q4", "/reports/vat?preset=year",
                    "/reports/receivables", "/reports/stock", "/reports/payments.csv", "/invoices/?filter=paid",
                    f"/invoices/{inv}", "/admin/", "/admin/log", "/admin/export/invoices.csv", "/parts/order-list",
                    f"/parts/{pid}", "/search?q=zh123", "/search?q=Muster", f"/search?q={number}", "/search?q=%23" + str(jid)]:
            self.get(url)
        r = self.get("/search?q=zh123")
        self.assertIn(b"ZH 123456", r.data)

        # stock count
        self.post(f"/parts/{pid}/stock", reason="count", change="7", note="yearly count")
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 7)

        # delete protection
        r = self.post(f"/customers/{cid}/delete")
        self.assertIn(b"still used", r.data)

        # backup + restore
        r = self.post("/admin/backup")
        self.assertEqual(r.status_code, 200)
        path, backups = db.list_backups()
        newest = os.path.join(path, backups[0][0])
        self.post("/customers/new", first_name="Temp", last_name="Person", mobile="078 000 00 00")
        before = self.one("SELECT COUNT(*) FROM customers")
        with open(newest, "rb") as f:
            self.post("/admin/restore", files={"file": (io.BytesIO(f.read()), "backup.zip")}, confirm="RESTORE")
        conn = db.connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], before - 1)
        conn.close()
        self.assertTrue(db.check_integrity()[0])


class Rules(Base):
    def test_login_and_csrf_required(self):
        anon = garage.app.test_client()
        self.assertEqual(anon.get("/").status_code, 302)
        self.assertEqual(self.c.post("/staff/new", data={"first_name": "x"}).status_code, 400)

    def test_customer_needs_name_and_contact(self):
        r = self.post("/customers/new", first_name="", last_name="", mobile="079")
        self.assertIn(b"Enter a name", r.data)
        r = self.post("/customers/new", last_name="Nobody")
        self.assertIn(b"at least one phone", r.data)

    def test_vin_and_plate_validation(self):
        r = self.post("/customers/new", company="Muster AG", kind="company", phone="044 000 00 00")
        cid = self.new_id(r)
        r = self.post(f"/vehicles/new/{cid}", make="BMW", model="X1", vin="TOOSHORT")
        self.assertIn(b"17 characters", r.data)
        self.post(f"/vehicles/new/{cid}", make="BMW", model="X1", plate="BE 1")
        r = self.post(f"/vehicles/new/{cid}", make="Audi", model="A3", plate="be1")
        self.assertIn(b"plate number already exists", r.data)

    def test_money_parsing(self):
        self.assertEqual(core.to_rappen("1'234.50"), 123450)
        self.assertEqual(core.to_rappen("12,3"), 1230)
        self.assertEqual(core.to_rappen("CHF 9.95"), 995)
        self.assertEqual(core.chf(123450), "CHF 1'234.50")
        self.assertEqual(core.chf(-5), "CHF -0.05")
        from views.invoices import qr_reference
        self.assertEqual(qr_reference("2026-0001"), "000000000000000000202600013")

    def test_staff_cannot_open_admin(self):
        self.post("/admin/users", username="worker", full_name="Worker", password="secret1", role="staff")
        c = garage.app.test_client()
        c.get("/login")
        with c.session_transaction() as s:
            tok = s["csrf"]
        c.post("/login", data={"username": "worker", "password": "secret1", "csrf": tok})
        self.assertEqual(c.get("/admin/").status_code, 403)
        self.assertEqual(c.get("/").status_code, 200)


class NewFeatures(Base):
    def test_messages_cash_labels_import_errors(self):
        r = self.post("/customers/new", salutation="Ms", first_name="Sara", last_name="Ahmed", mobile="079 555 66 77",
                      email="sara@example.ch", reminders_ok="1")
        cid = self.new_id(r)
        r = self.post(f"/vehicles/new/{cid}", make="Toyota", model="Yaris", plate="LU 777", mfk_next=core.plus_days(10))
        vid = self.new_id(r)
        # WhatsApp links with Swiss number converted to +41
        r = self.get(f"/vehicles/{vid}")
        self.assertIn(b"https://wa.me/41795556677", r.data)
        self.assertIn(b"MFK reminder", r.data)
        self.assertIn(b"wa.me/41795556677", self.get("/").data)
        r = self.post(f"/jobs/new/{vid}", complaint="Check engine light")
        jid = self.new_id(r)
        self.post(f"/jobs/{jid}/items", kind="other", description="Diagnosis", unit_price="80")
        self.post(f"/jobs/{jid}/update", status="done", complaint="Check engine light")
        self.assertIn(b"Car ready", self.get(f"/jobs/{jid}").data)
        self.assertIn(b"Finished, not invoiced", self.get("/").data)
        r = self.post(f"/invoices/create/{jid}")
        inv = self.new_id(r)
        self.assertIn(b"Payment reminder", self.get(f"/invoices/{inv}").data)
        self.post(f"/invoices/{inv}/pay", amount="50", method="cash")
        self.post("/expenses/", spent_on=core.today(), category="office", description="Coffee", amount="12.50",
                  vat_rate="0", method="cash")
        r = self.get("/reports/cash")
        self.assertIn(b"Sara Ahmed</td><td class=\"num\">50.00", r.data)
        self.assertIn(b"office: Coffee</td><td class=\"num\"></td>\n<td class=\"num\">12.50", r.data)
        # tyre label
        self.post(f"/tyres/new/{vid}", season="winter", status="stored", location="C-3")
        tid = self.one("SELECT id FROM tyre_sets WHERE vehicle_id=?", vid)
        self.assertIn(b"C-3", self.get(f"/tyres/{tid}/label").data)
        # appointment confirmation
        self.post("/appointments/new", day=core.today(), time="10:00", vehicle_id=str(vid), title="Service")
        aid = self.one("SELECT MAX(id) FROM appointments")
        self.assertIn(b"Send confirmation", self.get(f"/appointments/{aid}").data)
        # import from Excel CSV (semicolon, Windows encoding)
        csv_text = ("first_name;last_name;mobile;plate;make;model;year;mfk_next\n"
                    "Jürg;Müller;078 111 22 33;zg 4455;Škoda;Octavia;2017;2027-04-30\n"
                    "Jürg;Müller;078 111 22 33;ZG 4456;Audi;A4;2015;\n"
                    ";;;;;;;\n"
                    "Nophone;Person;;;;;;\n").encode("cp1252", errors="replace")
        r = self.post("/admin/import", files={"file": (io.BytesIO(csv_text), "customers.csv")})
        self.assertIn(b"<b>1</b> new customers", r.data)
        self.assertIn(b"<b>2</b> new vehicles", r.data)
        self.assertEqual(self.one("SELECT plate FROM vehicles WHERE make='Audi'"), "ZG 4456")
        self.get("/admin/import/template.csv")
        # friendly errors
        r = self.c.get("/customers/99999")
        self.assertEqual(r.status_code, 404)
        self.assertIn(b"Page not found", r.data)
        r = self.post("/admin/restore", files={"file": (io.BytesIO(b"junk"), "x.zip")}, confirm="RESTORE")
        self.assertIn(b"not a Kurd Garage backup", r.data)

    def test_counter_sale(self):
        r = self.post("/customers/new", first_name="Walk", last_name="In", mobile="076 000 11 22")
        cid = self.new_id(r)
        r = self.post("/parts/new", part_number="WB-1", name="Wiper blade", sell_price="19.90", quantity="5")
        pid = self.new_id(r)
        r = self.post(f"/jobs/counter/{cid}")
        jid = self.new_id(r)
        self.assertIn(b"Counter sale", r.data)
        self.post(f"/jobs/{jid}/items", kind="part", part_id=str(pid), quantity="2")
        self.assertEqual(self.one("SELECT quantity FROM parts WHERE id=?", pid), 3)
        with garage.app.test_request_context():
            total = core.job_totals(jid)["total"]
        r = self.post(f"/invoices/create/{jid}", paid_now=core.rappen_input(total), method="cash")
        inv = self.new_id(r)
        self.assertEqual(self.one("SELECT open_amount FROM invoice_balance WHERE id=?", inv), 0)
        r = self.get(f"/invoices/{inv}/print")
        self.assertNotIn(b"Vehicle:", r.data)
        # the placeholder never shows up as a vehicle, and is reused
        self.assertNotIn(b"Counter sale", self.get("/vehicles/").data)
        self.assertNotIn(b"Counter sale", self.get(f"/customers/{cid}").data.split(b"<h2>Vehicles</h2>")[1].split(b"<h2>")[0])
        self.post(f"/jobs/counter/{cid}")
        self.assertEqual(self.one("SELECT COUNT(*) FROM vehicles WHERE customer_id=?", cid), 1)

    def test_login_lockout(self):
        c = garage.app.test_client()
        c.get("/login")
        with c.session_transaction() as s:
            tok = s["csrf"]
        for _ in range(5):
            c.post("/login", data={"username": "admin", "password": "wrong", "csrf": tok})
        r = c.post("/login", data={"username": "admin", "password": "admin123", "csrf": tok}, follow_redirects=True)
        self.assertIn(b"Too many wrong passwords", r.data)
        self.conn.execute("DELETE FROM audit_log WHERE action = 'login_failed'")
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
