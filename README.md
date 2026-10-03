# Kurd Garage — Garage Management System

A complete, safe data system for **Kurd Garage**: customers, cars, repair jobs,
parts stock, payments, invoices and reports — all in one place, running on your own computer.

## What it does

| Area | Features |
|---|---|
| **Customers** | Name, 2 phones, address, notes, full history, how much they owe |
| **Cars** | Plate (unique), make, model, year, color, VIN, mileage, service history per car |
| **Jobs (work orders)** | Status (open → in progress → waiting parts → done → delivered), mechanic, problem, diagnosis, labour + parts lines, discount |
| **Parts / stock** | Part number, cost & sell price, stock count, low-stock warning, shelf location, supplier, full stock history |
| **Payments** | Cash / card / transfer, partial payments, who took the money |
| **Invoices** | Printable invoice for every job |
| **Reports** | Income per day, work per mechanic, most used parts, cost of parts |
| **Users** | Admin and staff logins, password change, activity log of who did what |
| **Backup** | Automatic backup on every start (last 30 kept), one-click backup download, export any table to Excel (CSV) |

## Why the data is strong and safe

- **SQLite database with strict rules**: required fields, no negative prices or stock, unique plate, VIN and part number.
- **Links are protected**: you cannot delete a customer that has cars, or a car that has jobs — no lost history.
- **Stock is automatic**: adding a part to a job removes it from stock, removing it puts it back. Stock can never go below zero.
- **Money is exact**: stored as whole Dinars (IQD), never rounded wrong. A payment larger than what is owed is refused.
- **Crash safe**: WAL journal + full sync, so a power cut does not corrupt the data.
- **Audit log**: every create / change / payment / delete is recorded with the user and time.
- **Integrity check** shown on the Admin page.
- Passwords are hashed; all forms are protected against CSRF.

## Install & run

You need **Python 3.10+** (https://www.python.org/downloads/ — tick "Add Python to PATH" on Windows).

- **Windows:** double-click `kurd_garage/start_windows.bat`
- **Linux / Mac:** run `./kurd_garage/start.sh`

Then open **http://127.0.0.1:5000** in your browser.

First login: **username `admin`, password `admin123`** — change it right away (top right → *password*).

To use it from other computers or phones in the garage on the same Wi-Fi, start it with `HOST=0.0.0.0`
(Windows: `set HOST=0.0.0.0` before running) and open `http://<this-computer-IP>:5000`.

## Where the data lives

- Database: `kurd_garage/data/kurd_garage.db`
- Backups: `kurd_garage/data/backups/`

**Copy the backups folder to a USB stick or Google Drive every week.**
To restore, stop the program and copy a backup file over `data/kurd_garage.db`.

Command-line tools (run inside `kurd_garage/`):

```
python db.py backup   # make a backup now
python db.py check    # check the database is healthy
```

## Tests

```
cd kurd_garage
python -m unittest test_app
```

## Settings

Edit the top of `kurd_garage/app.py` to change the garage name (`GARAGE_NAME`) or currency (`CURRENCY`).
