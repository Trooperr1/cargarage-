"""End-to-end tests. Run: python -m unittest test_app"""
import os
import re
import tempfile
import unittest

os.environ["KURD_GARAGE_DATA"] = tempfile.mkdtemp()

import app as garage  # noqa: E402
import db  # noqa: E402


class GarageTest(unittest.TestCase):
    def setUp(self):
        self.c = garage.app.test_client()
        self.post("/login", username="admin", password="admin123")

    def token(self):
        with self.c.session_transaction() as s:
            if "csrf" not in s:
                self.c.get("/login")
        with self.c.session_transaction() as s:
            return s["csrf"]

    def post(self, url, **data):
        self.c.get("/login") if url == "/login" else None
        data["csrf"] = self.token()
        return self.c.post(url, data=data, follow_redirects=True)

    def new_id(self, resp):
        return int(re.search(r"/(\d+)$", resp.request.path).group(1))

    def test_full_workflow(self):
        r = self.post("/customers/new", name="Karwan Ahmed", phone="0750 123 4567")
        cid = self.new_id(r)
        r = self.post(f"/vehicles/new/{cid}", plate="22 b 12345", make="Toyota", model="Corolla", year="2018")
        vid = self.new_id(r)
        self.assertIn(b"22 B 12345", r.data)
        r = self.post("/parts/new", part_number="OF-1", name="Oil filter", cost_price="5,000",
                      sell_price="8000", quantity="10", reorder_level="3")
        pid = self.new_id(r)
        self.post("/mechanics", name="Hemn")
        r = self.post(f"/jobs/new/{vid}", complaint="Oil change", mileage_in="85000", mechanic_id="1")
        jid = self.new_id(r)

        self.post(f"/jobs/{jid}/items", kind="labour", description="Oil change", quantity="1", unit_price="15000")
        self.post(f"/jobs/{jid}/items", kind="part", part_id=str(pid), quantity="2")
        conn = db.connect()
        self.assertEqual(conn.execute("SELECT quantity FROM parts WHERE id=?", (pid,)).fetchone()[0], 8)
        t = conn.execute("SELECT * FROM job_totals WHERE job_id=?", (jid,)).fetchone()
        self.assertEqual((t["labour"], t["parts"], t["total"]), (15000, 16000, 31000))

        # Too many parts is refused, stock stays correct
        r = self.post(f"/jobs/{jid}/items", kind="part", part_id=str(pid), quantity="50")
        self.assertIn(b"Not enough parts", r.data)
        self.assertEqual(conn.execute("SELECT quantity FROM parts WHERE id=?", (pid,)).fetchone()[0], 8)

        # Overpaying is refused
        r = self.post(f"/jobs/{jid}/pay", amount="99999", method="cash")
        self.assertIn(b"larger than the amount", r.data)
        self.post(f"/jobs/{jid}/pay", amount="31000", method="cash")
        t = conn.execute("SELECT * FROM job_totals WHERE job_id=?", (jid,)).fetchone()
        self.assertEqual(t["paid"], 31000)

        # Removing a part returns it to stock
        iid = conn.execute("SELECT id FROM job_items WHERE kind='part' AND job_id=?", (jid,)).fetchone()[0]
        self.post(f"/jobs/{jid}/items/{iid}/delete")
        self.assertEqual(conn.execute("SELECT quantity FROM parts WHERE id=?", (pid,)).fetchone()[0], 10)

        # Customer with cars cannot be deleted
        r = self.post(f"/customers/{cid}/delete")
        self.assertIn(b"still used", r.data)

        # Duplicate plate refused
        r = self.post(f"/vehicles/new/{cid}", plate="22 B 12345", make="Kia", model="Rio")
        self.assertIn(b"already exists", r.data)

        for url in ["/", "/jobs", "/jobs?status=unpaid", "/customers", f"/customers/{cid}", "/vehicles",
                    f"/vehicles/{vid}", f"/jobs/{jid}", f"/jobs/{jid}/invoice", "/parts", f"/parts/{pid}",
                    "/mechanics", "/suppliers", "/reports", "/admin", "/search?q=Karwan",
                    "/admin/export/jobs.csv", "/password"]:
            self.assertEqual(self.c.get(url).status_code, 200, url)

        self.assertEqual(self.post("/admin/backup").status_code, 200)
        self.assertTrue(db.check_integrity()[0])
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 5)
        conn.close()

    def test_login_and_csrf_required(self):
        anon = garage.app.test_client()
        self.assertEqual(anon.get("/").status_code, 302)
        self.assertEqual(self.c.post("/mechanics", data={"name": "x"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
