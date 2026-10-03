/* Kurd Garage website — shared layout and page logic. Content lives in /data/*.js */
(function () {
  "use strict";
  var G = window.GARAGE || {};
  var page = document.body.getAttribute("data-page") || "";

  // ------------------------------------------------------------ helpers
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function chf(n) {
    var v = Number(n || 0);
    var parts = v.toFixed(2).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, "'");
    return "CHF " + (parts[1] === "00" ? parts[0] + ".–" : parts.join("."));
  }
  function km(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "'") + " km"; }
  function intl(phone) {
    var d = String(phone || "").replace(/\D/g, "");
    if (String(phone || "").trim().charAt(0) === "+") return d;
    if (d.indexOf("00") === 0) return d.slice(2);
    if (d.charAt(0) === "0") return "41" + d.slice(1);
    return d;
  }
  function waLink(text) { return "https://wa.me/" + intl(G.whatsapp || G.phone) + "?text=" + encodeURIComponent(text); }
  function mailLink(subject, text) {
    return "mailto:" + G.email + "?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(text);
  }
  function telLink() { return "tel:+" + intl(G.phone); }
  function param(name) { return new URLSearchParams(location.search).get(name); }
  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { return null; }
  }
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  function openNow() {
    var now = new Date(), slots = (G.hours || {})[now.getDay()] || [];
    var t = ("0" + now.getHours()).slice(-2) + ":" + ("0" + now.getMinutes()).slice(-2);
    for (var i = 0; i < slots.length; i++) if (t >= slots[i][0] && t < slots[i][1]) return true;
    return false;
  }
  function hoursText(day) {
    var s = (G.hours || {})[day] || [];
    return s.length ? s.map(function (x) { return x[0] + " – " + x[1]; }).join(", ") : "closed";
  }
  var ICON = {
    phone: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z"/></svg>',
    wa: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm5.5 14.2c-.2.6-1.3 1.2-1.8 1.3-.5.1-1 .1-1.7-.1-.4-.1-.9-.3-1.5-.6-2.7-1.2-4.4-3.9-4.5-4-.1-.2-1.1-1.5-1.1-2.8s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.1.1.3 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.7 1.2 1.6 1.9 1.1 1 2 1.3 2.3 1.4.3.1.5.1.6-.1l.9-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.7-.1 1.3z"/></svg>',
    mail: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4-8 5-8-5V6l8 5 8-5z"/></svg>',
    pin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/></svg>',
    cart: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm10 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7.2 14h9.9a2 2 0 0 0 1.8-1.1l3.6-6.5A1 1 0 0 0 21.6 5H5.2L4.3 3H1v2h2l3.6 7.6L5.2 15A2 2 0 0 0 7 18h12v-2H7.4z"/></svg>',
    clock: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 11h-5v-2h3V6h2z"/></svg>'
  };

  // Simple car drawing used when a car has no photos yet.
  function carDrawing(color) {
    return '<svg class="car-draw" viewBox="0 0 400 200" role="img" aria-label="car">' +
      '<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#eef2f7"/><stop offset="1" stop-color="#dfe5ee"/></linearGradient></defs>' +
      '<rect width="400" height="200" fill="url(#sky)"/><rect y="160" width="400" height="40" fill="#cfd6e0"/>' +
      '<path d="M40 140 Q42 112 70 106 L120 98 Q150 66 190 62 L250 62 Q285 64 312 96 L350 104 Q372 110 370 140 Z" fill="' + esc(color || "#64748b") + '"/>' +
      '<path d="M138 98 Q160 74 190 72 L218 72 L218 98 Z M228 72 L250 72 Q276 74 296 98 L228 98 Z" fill="#cbd5e1" opacity=".9"/>' +
      '<rect x="44" y="124" width="22" height="8" rx="3" fill="#fde68a"/><rect x="346" y="122" width="18" height="8" rx="3" fill="#fca5a5"/>' +
      '<circle cx="110" cy="142" r="26" fill="#1f2937"/><circle cx="110" cy="142" r="12" fill="#9ca3af"/>' +
      '<circle cx="300" cy="142" r="26" fill="#1f2937"/><circle cx="300" cy="142" r="12" fill="#9ca3af"/></svg>';
  }
  function carImage(car, index) {
    var img = (car.images || [])[index || 0];
    return img ? '<img src="' + esc(img) + '" alt="' + esc(car.make + " " + car.model) + '" loading="lazy">' : carDrawing(car.color);
  }
  function catOf(id) {
    var c = (window.PART_CATEGORIES || []).filter(function (x) { return x[0] === id; })[0];
    return c || [id, "📦", id];
  }

  // ------------------------------------------------------------ layout (header / footer)
  var NAV = [
    ["index.html", "Home", "home"], ["services.html", "Services", "services"], ["cars.html", "Cars for sale", "cars"],
    ["parts.html", "Parts shop", "parts"], ["booking.html", "Book appointment", "booking"],
    ["about.html", "About us", "about"], ["contact.html", "Contact", "contact"]
  ];
  function header() {
    var active = page === "car" ? "cars" : page;
    var links = NAV.map(function (n) {
      return '<a href="' + n[0] + '"' + (n[2] === active ? ' class="active" aria-current="page"' : "") + ">" + n[1] + "</a>";
    }).join("");
    var open = openNow();
    return '<div class="topbar"><div class="wrap">' +
      (G.street ? '<span>' + ICON.pin + esc(G.street) + ", " + esc(G.postcode) + " " + esc(G.city) + "</span>" : "<span></span>") +
      '<span class="' + (open ? "open" : "closed") + '">' + ICON.clock + (open ? "Open now" : "Closed now") + " · today " + hoursText(new Date().getDay()) + "</span>" +
      (G.phone ? '<a href="' + telLink() + '">' + ICON.phone + esc(G.phone) + "</a>" : "<span></span>") + "</div></div>" +
      '<header class="site-header"><div class="wrap">' +
      '<a class="logo" href="index.html"><span class="logo-mark">KG</span><span><b>' + esc(G.name) + "</b><small>" + esc(G.slogan) + "</small></span></a>" +
      '<button class="burger" aria-label="Menu" aria-expanded="false"><span></span><span></span><span></span></button>' +
      '<nav class="main-nav">' + links + "</nav>" +
      '<a class="cart-btn" href="parts.html#basket" aria-label="Parts basket">' + ICON.cart + '<span class="cart-count">0</span></a>' +
      "</div></header>";
  }
  function footer() {
    var social = [["instagram", "Instagram"], ["facebook", "Facebook"], ["tiktok", "TikTok"], ["googleReviews", "Google reviews"]]
      .filter(function (s) { return G[s[0]]; })
      .map(function (s) { return '<a href="' + esc(G[s[0]]) + '" target="_blank" rel="noopener">' + s[1] + "</a>"; }).join(" · ");
    var hours = [1, 2, 3, 4, 5, 6, 0].map(function (d) {
      return "<tr><td>" + DAYS[d] + "</td><td>" + hoursText(d) + "</td></tr>";
    }).join("");
    return '<footer class="site-footer"><div class="wrap grid4">' +
      "<div><h3>" + esc(G.name) + "</h3><p>" + esc(G.intro) + "</p>" + (social ? "<p>" + social + "</p>" : "") + "</div>" +
      "<div><h3>Contact</h3><p>" + esc(G.street) + "<br>" + esc(G.postcode) + " " + esc(G.city) + "</p>" +
      '<p><a href="' + telLink() + '">' + esc(G.phone) + '</a><br><a href="' + waLink("Hello " + G.name + ", ") + '" target="_blank" rel="noopener">WhatsApp ' + esc(G.whatsapp) + "</a>" +
      (G.email ? '<br><a href="mailto:' + esc(G.email) + '">' + esc(G.email) + "</a>" : "") + "</p></div>" +
      '<div><h3>Opening hours</h3><table class="hours">' + hours + "</table></div>" +
      "<div><h3>Links</h3><p>" + NAV.map(function (n) { return '<a href="' + n[0] + '">' + n[1] + "</a>"; }).join("<br>") +
      '<br><a href="legal.html">Legal notice & privacy</a></p></div>' +
      '</div><div class="wrap copy">© ' + new Date().getFullYear() + " " + esc(G.name) + " · " + esc(G.city) + ", " + esc(G.country) + "</div></footer>" +
      '<a class="wa-float" href="' + waLink("Hello " + G.name + ", ") + '" target="_blank" rel="noopener" aria-label="WhatsApp">' + ICON.wa + "</a>";
  }
  function layout() {
    var h = document.getElementById("site-header"), f = document.getElementById("site-footer");
    if (h) h.outerHTML = header();
    if (f) f.outerHTML = footer();
    var burger = $(".burger"), nav = $(".main-nav");
    if (burger) burger.addEventListener("click", function () {
      var openState = nav.classList.toggle("show");
      burger.setAttribute("aria-expanded", openState ? "true" : "false");
    });
    $all("[data-g]").forEach(function (el) { el.textContent = G[el.getAttribute("data-g")] || ""; });
    $all("[data-tel]").forEach(function (el) { el.href = telLink(); });
    $all("[data-wa]").forEach(function (el) { el.href = waLink(el.getAttribute("data-wa") || ("Hello " + G.name + ", ")); el.target = "_blank"; el.rel = "noopener"; });
    $all("[data-mail]").forEach(function (el) { if (G.email) el.href = "mailto:" + G.email; else el.style.display = "none"; });
    if (!G.email) $all('button[value="mail"]').forEach(function (b) { b.style.display = "none"; });
    document.title = document.title.replace("{name}", G.name || "");
    updateCartCount();
  }

  // ------------------------------------------------------------ parts basket (saved in this browser)
  function cart() { return store("kg_cart") || {}; }
  function saveCart(c) { store("kg_cart", c); updateCartCount(); }
  function updateCartCount() {
    var c = cart(), n = 0;
    Object.keys(c).forEach(function (k) { n += c[k]; });
    $all(".cart-count").forEach(function (el) { el.textContent = n; el.style.display = n ? "" : "none"; });
  }
  function partById(id) { return (window.PARTS || []).filter(function (p) { return p.id === id; })[0]; }
  function addToCart(id) {
    var c = cart();
    c[id] = (c[id] || 0) + 1;
    saveCart(c);
    toast("Added to basket ✔");
    renderBasket();
  }
  function toast(text) {
    var t = document.createElement("div");
    t.className = "toast";
    t.textContent = text;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add("show"); }, 10);
    setTimeout(function () { t.classList.remove("show"); setTimeout(function () { t.remove(); }, 300); }, 1800);
  }
  function orderText(c, form) {
    var lines = [], total = 0;
    Object.keys(c).forEach(function (id) {
      var p = partById(id);
      if (!p) return;
      total += p.price * c[id];
      lines.push(c[id] + " × " + p.name + " (" + p.brand + ") — " + chf(p.price * c[id]));
    });
    return "Hello " + G.name + ",\n\nI would like to order:\n" + lines.join("\n") + "\n\nTotal: " + chf(total) +
      "\nDelivery: " + form.delivery + "\nCar: " + (form.car || "-") + "\nName: " + form.name + "\nPhone: " + form.phone +
      (form.note ? "\nNote: " + form.note : "") + "\n\nThank you!";
  }
  function renderBasket() {
    var box = $("#basket-items");
    if (!box) return;
    var c = cart(), ids = Object.keys(c).filter(partById), total = 0;
    if (!ids.length) {
      box.innerHTML = '<p class="muted">Your basket is empty. Add parts with the “Add” button.</p>';
      $("#basket-total").textContent = chf(0);
      $("#basket-form").hidden = true;
      return;
    }
    box.innerHTML = ids.map(function (id) {
      var p = partById(id), sum = p.price * c[id];
      total += sum;
      return '<div class="basket-line"><span>' + catOf(p.cat)[1] + " " + esc(p.name) + "</span>" +
        '<span class="qty"><button data-dec="' + p.id + '" aria-label="less">−</button><b>' + c[id] + '</b><button data-inc="' + p.id + '" aria-label="more">+</button></span>' +
        '<span class="sum">' + chf(sum) + "</span></div>";
    }).join("");
    $("#basket-total").textContent = chf(total);
    $("#basket-form").hidden = false;
  }

  // ------------------------------------------------------------ pages
  function homePage() {
    var statBox = $("#stats");
    if (statBox) statBox.innerHTML = (G.stats || []).map(function (s) {
      return '<div class="stat"><b>' + esc(s[0]) + "</b><span>" + esc(s[1]) + "</span></div>";
    }).join("");
    var svc = $("#home-services");
    if (svc) svc.innerHTML = (window.SERVICES || []).slice(0, 6).map(serviceCard).join("");
    var cars = $("#home-cars");
    if (cars) cars.innerHTML = (window.CARS || []).filter(function (c) { return c.status !== "sold"; }).slice(0, 3).map(carCard).join("");
    var parts = $("#home-cats");
    if (parts) parts.innerHTML = (window.PART_CATEGORIES || []).map(function (c) {
      return '<a class="cat-tile" href="parts.html?cat=' + c[0] + '"><span>' + c[1] + "</span>" + esc(c[2]) + "</a>";
    }).join("");
    var brands = $("#brands");
    if (brands) brands.innerHTML = (G.brands || []).map(function (b) { return "<span>" + esc(b) + "</span>"; }).join("");
    reviews();
  }
  function reviews() {
    var box = $("#reviews");
    if (!box) return;
    box.innerHTML = (G.reviews || []).map(function (r) {
      return '<figure class="review"><div class="stars">' + "★★★★★".slice(0, r.stars) + "</div><blockquote>“" + esc(r.text) +
        "”</blockquote><figcaption>— " + esc(r.name) + "</figcaption></figure>";
    }).join("");
  }
  function serviceCard(s) {
    return '<article class="card service" id="' + esc(s.id) + '"><div class="svc-icon">' + s.icon + "</div><h3>" + esc(s.name) + "</h3><p>" + esc(s.text) + "</p>" +
      (s.points ? '<ul class="ticks">' + s.points.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul>" : "") +
      '<div class="svc-foot"><span class="price">' + (s.price ? "from " + chf(s.price) : "price on request") + '</span><span class="muted">⏱ ' + esc(s.time) + "</span></div>" +
      '<a class="btn btn-small" href="booking.html?service=' + encodeURIComponent(s.id) + '">Book this service</a></article>';
  }
  function servicesPage() {
    var box = $("#services");
    if (box) box.innerHTML = (window.SERVICES || []).map(serviceCard).join("");
  }

  function carCard(c) {
    var badge = c.status === "sold" ? '<span class="badge sold">Sold</span>' : c.status === "reserved" ? '<span class="badge reserved">Reserved</span>' : c.isNew ? '<span class="badge new">New in stock</span>' : "";
    return '<a class="card car-card' + (c.status === "sold" ? " is-sold" : "") + '" href="car.html?id=' + encodeURIComponent(c.id) + '">' +
      '<div class="car-img">' + carImage(c) + badge + "</div>" +
      '<div class="car-body"><h3>' + esc(c.make) + " " + esc(c.model) + "</h3>" +
      '<ul class="specs"><li>📅 ' + c.year + "</li><li>🛣️ " + km(c.km) + "</li><li>⛽ " + esc(c.fuel) + "</li><li>⚙️ " + esc(c.gearbox) + "</li></ul>" +
      '<div class="car-foot"><span class="price big">' + chf(c.price) + '</span>' + (c.mfk ? '<span class="mfk">' + esc(c.mfk) + "</span>" : "") + "</div></div></a>";
  }
  function carsPage() {
    var all = window.CARS || [];
    var makes = {}, fuels = {};
    all.forEach(function (c) { makes[c.make] = 1; fuels[c.fuel] = 1; });
    $("#f-make").innerHTML = '<option value="">All makes</option>' + Object.keys(makes).sort().map(function (m) { return "<option>" + esc(m) + "</option>"; }).join("");
    $("#f-fuel").innerHTML = '<option value="">All fuels</option>' + Object.keys(fuels).sort().map(function (m) { return "<option>" + esc(m) + "</option>"; }).join("");
    function draw() {
      var q = $("#f-q").value.toLowerCase(), make = $("#f-make").value, fuel = $("#f-fuel").value,
        gear = $("#f-gear").value, maxP = Number($("#f-price").value || 0), maxK = Number($("#f-km").value || 0),
        sold = $("#f-sold").checked, sort = $("#f-sort").value;
      var list = all.filter(function (c) {
        return (!q || (c.make + " " + c.model + " " + (c.features || []).join(" ")).toLowerCase().indexOf(q) >= 0) &&
          (!make || c.make === make) && (!fuel || c.fuel === fuel) && (!gear || c.gearbox === gear) &&
          (!maxP || c.price <= maxP) && (!maxK || c.km <= maxK) && (sold || c.status !== "sold");
      });
      list.sort(function (a, b) {
        if (sort === "price-asc") return a.price - b.price;
        if (sort === "price-desc") return b.price - a.price;
        if (sort === "km") return a.km - b.km;
        if (sort === "year") return b.year - a.year;
        return (b.isNew ? 1 : 0) - (a.isNew ? 1 : 0);
      });
      $("#car-count").textContent = list.length + (list.length === 1 ? " car" : " cars");
      $("#car-list").innerHTML = list.length ? list.map(carCard).join("") : '<p class="muted">No car matches your search. Tell us what you are looking for — we find it for you!</p>';
    }
    $all("#car-filters input, #car-filters select").forEach(function (el) { el.addEventListener("input", draw); });
    $("#f-reset").addEventListener("click", function () { $("#car-filters").reset(); draw(); });
    draw();
  }
  function carPage() {
    var c = (window.CARS || []).filter(function (x) { return x.id === param("id"); })[0];
    var box = $("#car");
    if (!c) { box.innerHTML = '<h1>Car not found</h1><p>This car is no longer online. <a href="cars.html">See all cars for sale</a>.</p>'; return; }
    document.title = c.make + " " + c.model + " — " + G.name;
    var title = c.make + " " + c.model + " (" + c.year + ", " + km(c.km) + ", " + chf(c.price) + ")";
    var enquiry = "Hello " + G.name + ",\n\nI am interested in the " + title + ".\nIs it still available? When can I see it / make a test drive?\n\nThank you!";
    var thumbs = (c.images || []).map(function (img, i) {
      return '<button class="thumb" data-i="' + i + '"><img src="' + esc(img) + '" alt=""></button>';
    }).join("");
    var specs = [["Price", chf(c.price)], ["First registration", c.firstReg || c.year], ["Mileage", km(c.km)], ["Fuel", c.fuel],
      ["Gearbox", c.gearbox], ["Power", c.power ? c.power + " PS / " + Math.round(c.power * 0.7355) + " kW" : ""], ["Body", c.body],
      ["Doors / seats", (c.doors || "") + " / " + (c.seats || "")], ["Colour", c.colorName], ["MFK", c.mfk], ["Warranty", c.warranty]]
      .filter(function (s) { return s[1]; })
      .map(function (s) { return "<tr><th>" + s[0] + "</th><td>" + esc(s[1]) + "</td></tr>"; }).join("");
    var status = c.status === "sold" ? '<p class="alert">This car is sold. <a href="cars.html">See other cars</a></p>' :
      c.status === "reserved" ? '<p class="alert warn">This car is reserved. Call us — maybe it becomes free again.</p>' : "";
    box.innerHTML = '<p class="crumbs"><a href="cars.html">← All cars for sale</a></p>' +
      '<div class="car-detail"><div><div class="gallery-main">' + carImage(c, 0) + "</div>" + (thumbs ? '<div class="thumbs">' + thumbs + "</div>" : "") + "</div>" +
      '<div class="car-side"><h1>' + esc(c.make) + " " + esc(c.model) + "</h1>" + status +
      '<div class="price huge">' + chf(c.price) + '</div><p class="muted">' + ["incl. VAT", c.mfk, c.warranty ? c.warranty + " warranty" : ""].filter(Boolean).map(esc).join(" · ") + "</p>" +
      '<div class="cta-stack"><a class="btn btn-wa" href="' + waLink(enquiry) + '" target="_blank" rel="noopener">' + ICON.wa + " Ask on WhatsApp</a>" +
      '<a class="btn" href="' + telLink() + '">' + ICON.phone + " Call " + esc(G.phone) + "</a>" +
      (G.email ? '<a class="btn btn-ghost" href="' + mailLink("Enquiry: " + c.make + " " + c.model, enquiry) + '">' + ICON.mail + " E-mail</a>" : "") +
      '<a class="btn btn-ghost" href="booking.html?service=testdrive&car=' + encodeURIComponent(c.make + " " + c.model) + '">Book a test drive</a></div>' +
      '<ul class="ticks small"><li>Trade-in of your old car possible</li><li>Financing & leasing on request</li><li>Delivered serviced and cleaned</li></ul></div></div>' +
      '<div class="grid2 top-gap"><div class="card"><h2>Specifications</h2><table class="spec-table">' + specs + "</table></div>" +
      '<div class="card"><h2>Equipment</h2><ul class="ticks cols">' + (c.features || []).map(function (f) { return "<li>" + esc(f) + "</li>"; }).join("") + "</ul>" +
      "<h2>Description</h2><p>" + esc(c.text || "") + "</p></div></div>";
    $all(".thumb").forEach(function (b) {
      b.addEventListener("click", function () { $(".gallery-main").innerHTML = carImage(c, Number(b.getAttribute("data-i"))); });
    });
  }

  function partsPage() {
    var cats = window.PART_CATEGORIES || [], all = window.PARTS || [];
    var current = param("cat") || "";
    function catList() {
      $("#part-cats").innerHTML = '<button data-cat="" class="' + (current ? "" : "on") + '">📦 All parts</button>' + cats.map(function (c) {
        return '<button data-cat="' + c[0] + '" class="' + (current === c[0] ? "on" : "") + '">' + c[1] + " " + esc(c[2]) + "</button>";
      }).join("");
    }
    function draw() {
      var q = $("#p-q").value.toLowerCase(), stockOnly = $("#p-stock").checked;
      var list = all.filter(function (p) {
        return (!current || p.cat === current) && (!stockOnly || p.stock > 0) &&
          (!q || (p.name + " " + p.brand + " " + p.fits).toLowerCase().indexOf(q) >= 0);
      });
      $("#part-count").textContent = list.length + " products";
      $("#part-list").innerHTML = list.length ? list.map(function (p) {
        var img = p.image ? '<img src="' + esc(p.image) + '" alt="" loading="lazy">' : '<span class="part-icon">' + catOf(p.cat)[1] + "</span>";
        return '<article class="card part"><div class="part-img">' + img + '</div><div class="part-body"><small class="muted">' + esc(p.brand) + " · " + esc(catOf(p.cat)[2]) + "</small>" +
          "<h3>" + esc(p.name) + '</h3><p class="fits">Fits: ' + esc(p.fits) + "</p>" +
          '<p class="stock ' + (p.stock > 0 ? "in" : "out") + '">' + (p.stock > 0 ? "● In stock" : "● On order — 1–2 days") + "</p>" +
          '<div class="part-foot"><span class="price">' + chf(p.price) + '</span><button class="btn btn-small" data-add="' + p.id + '">' + ICON.cart + " Add</button></div></div></article>";
      }).join("") : '<p class="muted">Nothing found. Ask us — we can order almost every part within 1–2 days.</p>';
    }
    catList();
    draw();
    $("#part-cats").addEventListener("click", function (e) {
      var b = e.target.closest("[data-cat]");
      if (!b) return;
      current = b.getAttribute("data-cat");
      catList();
      draw();
    });
    $("#p-q").addEventListener("input", draw);
    $("#p-stock").addEventListener("change", draw);
    document.addEventListener("click", function (e) {
      var add = e.target.closest("[data-add]"), inc = e.target.closest("[data-inc]"), dec = e.target.closest("[data-dec]");
      if (add) addToCart(add.getAttribute("data-add"));
      if (inc || dec) {
        var id = (inc || dec).getAttribute(inc ? "data-inc" : "data-dec"), c = cart();
        c[id] = (c[id] || 0) + (inc ? 1 : -1);
        if (c[id] <= 0) delete c[id];
        saveCart(c);
        renderBasket();
      }
    });
    renderBasket();
    $("#basket-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var f = e.target, data = { name: f.name.value.trim(), phone: f.phone.value.trim(), car: f.car.value.trim(),
        delivery: f.delivery.value, note: f.note.value.trim() };
      var text = orderText(cart(), data);
      var how = e.submitter && e.submitter.value === "mail" ? "mail" : "wa";
      window.open(how === "mail" ? mailLink("Parts order", text) : waLink(text), "_blank");
      $("#basket-done").hidden = false;
    });
    $("#basket-clear").addEventListener("click", function () { saveCart({}); renderBasket(); });
  }

  function bookingPage() {
    var sel = $("#b-service");
    sel.innerHTML = (window.SERVICES || []).map(function (s) { return '<option value="' + esc(s.id) + '">' + esc(s.name) + "</option>"; }).join("") +
      '<option value="testdrive">Test drive (car for sale)</option><option value="other">Other / not sure</option>';
    if (param("service")) sel.value = param("service");
    if (param("car")) $("#b-car").value = param("car");
    var d = new Date();
    d.setDate(d.getDate() + 1);
    $("#b-date").min = new Date().toISOString().slice(0, 10);
    $("#b-date").value = d.toISOString().slice(0, 10);
    $("#booking-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var f = e.target;
      var day = new Date(f.date.value + "T12:00:00");
      if ((((G.hours || {})[day.getDay()]) || []).length === 0) {
        alert("We are closed on " + DAYS[day.getDay()] + ". Please choose another day.");
        return;
      }
      var service = sel.options[sel.selectedIndex].text;
      var text = "Hello " + G.name + ",\n\nI would like an appointment:\n\nService: " + service +
        "\nDate: " + day.toLocaleDateString("de-CH") + ", " + f.time.value +
        "\nCar: " + (f.car.value || "-") + (f.plate.value ? " (" + f.plate.value + ")" : "") +
        "\nName: " + f.name.value + "\nPhone: " + f.phone.value + (f.email.value ? "\nE-mail: " + f.email.value : "") +
        (f.courtesy.checked ? "\nI need a courtesy car." : "") + (f.message.value ? "\n\n" + f.message.value : "") + "\n\nThank you!";
      var how = e.submitter && e.submitter.value === "mail" ? "mail" : "wa";
      window.open(how === "mail" ? mailLink("Appointment request", text) : waLink(text), "_blank");
      $("#booking-done").hidden = false;
    });
  }

  function contactPage() {
    var rows = [1, 2, 3, 4, 5, 6, 0].map(function (d) {
      return "<tr" + (d === new Date().getDay() ? ' class="today"' : "") + "><td>" + DAYS[d] + "</td><td>" + hoursText(d) + "</td></tr>";
    }).join("");
    $("#contact-hours").innerHTML = rows;
    $("#open-state").textContent = openNow() ? "We are open now" : "We are closed now";
    $("#open-state").className = "pill " + (openNow() ? "open" : "closed");
    var lat = Number(G.mapLat), lon = Number(G.mapLon), d = 0.006;
    $("#map").innerHTML = '<iframe title="Map" loading="lazy" src="https://www.openstreetmap.org/export/embed.html?bbox=' +
      (lon - d) + "%2C" + (lat - d / 2) + "%2C" + (lon + d) + "%2C" + (lat + d / 2) + "&layer=mapnik&marker=" + lat + "%2C" + lon + '"></iframe>';
    $("#route").href = "https://www.google.com/maps/dir/?api=1&destination=" + encodeURIComponent(G.street + ", " + G.postcode + " " + G.city);
    $("#contact-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var f = e.target;
      var text = "Hello " + G.name + ",\n\n" + f.message.value + "\n\n" + f.name.value + "\n" + f.phone.value + (f.email.value ? "\n" + f.email.value : "");
      var how = e.submitter && e.submitter.value === "mail" ? "mail" : "wa";
      window.open(how === "mail" ? mailLink("Question from the website", text) : waLink(text), "_blank");
    });
  }

  function aboutPage() {
    $all("[data-years]").forEach(function (el) { el.textContent = Math.max(1, new Date().getFullYear() - Number(G.founded || new Date().getFullYear())); });
    var statBox = $("#stats");
    if (statBox) statBox.innerHTML = (G.stats || []).map(function (s) {
      return '<div class="stat"><b>' + esc(s[0]) + "</b><span>" + esc(s[1]) + "</span></div>";
    }).join("");
    reviews();
  }

  function seo() {
    // Tells Google the business details (address, phone, opening hours).
    var spec = [];
    Object.keys(G.hours || {}).forEach(function (d) {
      (G.hours[d] || []).forEach(function (s) {
        spec.push({ "@type": "OpeningHoursSpecification", dayOfWeek: DAYS[d], opens: s[0], closes: s[1] });
      });
    });
    var data = { "@context": "https://schema.org", "@type": "AutoRepair", name: G.name, telephone: "+" + intl(G.phone), email: G.email,
      address: { "@type": "PostalAddress", streetAddress: G.street, postalCode: G.postcode, addressLocality: G.city, addressCountry: "CH" },
      geo: { "@type": "GeoCoordinates", latitude: G.mapLat, longitude: G.mapLon }, openingHoursSpecification: spec,
      url: location.origin + "/" };
    var s = document.createElement("script");
    s.type = "application/ld+json";
    s.textContent = JSON.stringify(data);
    document.head.appendChild(s);
  }

  document.addEventListener("DOMContentLoaded", function () {
    layout();
    var run = { home: homePage, services: servicesPage, cars: carsPage, car: carPage, parts: partsPage, booking: bookingPage,
      contact: contactPage, about: aboutPage }[page];
    if (run) run();
    if (page === "home" || page === "contact") seo();
  });
})();
