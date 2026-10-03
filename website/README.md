# Kurd Garage — Website

A fast, modern website with separate pages:

| Page | File |
|---|---|
| Home | `index.html` |
| Services & prices | `services.html` |
| Cars for sale (with filters) | `cars.html` → each car on `car.html?id=...` |
| Parts shop (basket, order by WhatsApp / e-mail) | `parts.html` |
| Book appointment | `booking.html` |
| About us | `about.html` |
| Contact, opening hours, map | `contact.html` |
| Legal notice & privacy | `legal.html` |

No server, no database, no monthly software costs — just files. Orders, bookings and
questions arrive on your **WhatsApp** (or e-mail).

## Change the content

Open the files in the `data` folder with Notepad (right-click → Open with → Notepad):

- `data/config.js` — garage name, phone, WhatsApp, e-mail, address, map position, opening hours, reviews, social media
- `data/services.js` — services and starting prices
- `data/cars.js` — cars for sale (set `status: "sold"` when sold)
- `data/parts.js` — parts shop: products, prices, stock

**Photos:** put them in the `images` folder (e.g. `images/golf-1.jpg`) and write the name in the list,
e.g. `images: ["images/golf-1.jpg", "images/golf-2.jpg"]`. Use landscape photos (16:10), max. 300 KB each.

Colours: change `--red` and `--navy` at the top of `assets/style.css`.

## Put it online (free)

**Netlify (easiest):** go to https://app.netlify.com/drop, create a free account and drag the whole
`website` folder onto the page. Your site is online in 1 minute. To update it, drag the folder again.

**Own address (e.g. kurdgarage.ch):** buy the domain at a Swiss provider (Infomaniak, Hostpoint, ~CHF 15/year)
and connect it in Netlify under *Domain settings*.

## After it is online

1. Create your free **Google Business Profile** (business.google.com) with the website link — the most important step for new customers.
2. Add the link to Instagram / Facebook / TikTok and to `data/config.js`.
3. Register on Swiss directories: local.ch and search.ch.
4. Ask happy customers for Google reviews, and copy the best ones into `data/config.js`.
