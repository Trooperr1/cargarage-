# Kurd Garage — Garage Management System (Switzerland)

A complete system to run a Swiss car garage: customers, vehicles, appointments, quotes, work orders,
parts stock, invoices with **Swiss QR-bill**, payments, payment reminders, tyre hotel, staff time,
expenses, VAT (MWST) and business reports. It runs on your own computer and you use it in the browser.

## Features

| Area | What you get |
|---|---|
| **Dashboard** | Vehicles in work, ready for pickup, today's appointments, money received, open/overdue invoices, reminders for MFK, service, low stock and tyre season |
| **Customers** | Private or company, salutation, Swiss address (street, no., postcode, city, canton), mobile, phone, e-mail, UID, payment terms, standard discount, source, notes, files, revenue and open balance |
| **Vehicles** | Plate (auto-formatted `ZH 123456`), VIN (17-char check), master number (Stammnummer), type approval, 1st registration, fuel, gearbox, drive, ccm, kW/PS, oil spec, tyre sizes, key/radio code, **MFK last/next**, next service date/km, mileage history with tampering warning, owner change, printable service history |
| **Calendar** | Week view, appointments for customers or new callers, mechanic, duration, courtesy car, "vehicle arrived → open job" |
| **Jobs & quotes** | Quote → job, check-in (km, fuel level, existing damage), promised time, customer waiting, mechanic, standard services, labour hours, parts (by list, part number or barcode), other items, per-line discount and VAT, findings, recommendations, internal notes, time tracking, photos, copy job, printable job card and quote |
| **Invoices** | Sequential numbers (2026-0001), frozen after issue (can only be cancelled), 5-Rappen rounding, VAT breakdown, **QR-bill (IBAN or QR-IBAN)**, partial payments (cash, card, TWINT, bank transfer), payment reminders 1–3 with fees, print/PDF |
| **Parts & stock** | Part no., EAN, brand, category, unit (pc/l/kg/m/set), supplier, cost/sell price and margin, stock with automatic movements, deliveries, corrections, stock counts, order list per supplier, stock value report |
| **Tyre hotel** | Sets per vehicle (summer/winter), brand, size, DOT, rims, tread depth ×4 with legal-minimum warning, storage place (no double use), one-click seasonal change, printable labels for the 4 wheels |
| **Staff** | Mechanics with role and hourly cost, time per job, hours worked vs billed (efficiency), monthly view |
| **Expenses** | Categories, supplier, VAT included, receipts as photo/PDF |
| **Reports** | Revenue, labour/parts split, profit estimate, per month, per mechanic, best customers, top services/parts, makes, **VAT/MWST report per quarter**, receivables with ageing, **cash book (Kassenbuch)**, stock value, payments CSV |
| **Messages** | One-click **WhatsApp / SMS / e-mail** with ready text: car ready, quote, ask for approval, MFK and service reminders, appointment confirmation, payment reminder |
| **Admin** | Garage settings (address, IBAN, UID, VAT rate, hourly rate, fees), logins (admin/staff), standard services, activity log, backup/restore, Excel export, **import customers & vehicles from Excel** |

## Data safety

- **SQLite database with strict rules**: required fields, no negative amounts, unique plate / VIN / part number / invoice number / storage place.
- **History is protected**: a customer with vehicles, or a vehicle with jobs, cannot be deleted.
- **Invoices cannot be changed or deleted** — only cancelled with a reason (the number stays used). An invoiced job is locked.
- **Stock is automatic**: parts leave stock when added to a job (not for quotes), and come back when removed or cancelled. Stock can never go below zero.
- **Money is exact**: stored in Rappen, never rounded wrong. Payments larger than the open amount are refused.
- **Crash safe** (WAL journal, full sync) — a power cut does not corrupt data.
- **Activity log**: every change records who did it and when.
- **Automatic backups**: every start and every day, as a ZIP (database + photos), last 60 kept.
- Login is blocked for 15 minutes after 5 wrong passwords; automatic logout after 12 hours.
- Passwords are hashed; all forms are protected against CSRF; staff logins cannot open Admin.

## Install & run (Windows)

1. Install **Python 3.10+** from https://www.python.org/downloads/ (answer **y** to the PATH and install questions).
2. Download this project as ZIP and extract it.
3. Double-click `kurd_garage/start_windows.bat` (the first start installs everything, about 1–2 minutes).
4. The browser opens **http://127.0.0.1:5000**. Keep the black window open while working.
5. Log in with **admin / admin123** and change the password right away (top right → *password*).
6. Go to **Admin → Garage settings** and enter your address, phone, IBAN, UID/VAT number and hourly rate.

Linux / Mac: run `./kurd_garage/start.sh`.

To use it from other computers or phones in the garage (same Wi-Fi), start it with `HOST=0.0.0.0`
(Windows: `set HOST=0.0.0.0` before running) and open `http://<this-computer-IP>:5000`.

## Where the data lives

The data is stored **outside** the program folder, so you can download a newer version without losing anything:

- Windows: `%LOCALAPPDATA%\KurdGarage\garage.db` (photos in `uploads\`)
- Linux/Mac: `~/.local/share/kurd_garage/`
- Backups: `Documents\Kurd Garage Backups\` (change it under Admin → Garage settings, e.g. to a OneDrive folder)

Restore: Admin → *Restore from a backup*, or `python db.py restore <file.zip>`.

Command-line tools (inside `kurd_garage/`):

```
python db.py          # show where data and backups are
python db.py backup   # make a backup now
python db.py check    # check the database is healthy
```

## Tests

```
cd kurd_garage
python -m unittest test_app
```
