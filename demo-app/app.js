/* DemoShop - Hotel Booking Demo
   Client-side application logic. Multi-page static site: every page is a
   standalone HTML document; state (users, bookings, defects) lives in
   localStorage so it survives navigation. Synthetic data only. */

(function () {
  "use strict";

  const STORAGE = {
    USERS: "demo_users",
    BOOKINGS: "demo_bookings",
    DEFECTS: "demo_defects",
    CURRENT_USER: "demo_current_user",
    LAST_SEARCH: "demo_last_search",
    LAST_HOTEL: "demo_last_hotel",
    LAST_BOOKING: "demo_last_booking",
  };

  const DEFAULT_USER = {
    name: "Demo User",
    email: "demo@example.com",
    password: "Password123!",
  };

  const HOTELS = [
    {
      id: "lakeview",
      name: "Lakeview Resort",
      price: 120,
      location: "Lakeside",
      rating: 4.7,
      rooms: [
        { id: "std-1", type: "Standard", price: 120, capacity: 2 },
        { id: "del-1", type: "Deluxe", price: 180, capacity: 3 },
        { id: "sup-1", type: "Suite", price: 280, capacity: 4 },
      ],
    },
    {
      id: "central",
      name: "Central Plaza Hotel",
      price: 95,
      location: "City Center",
      rating: 4.3,
      rooms: [
        { id: "std-2", type: "Standard", price: 95, capacity: 2 },
        { id: "exe-2", type: "Executive", price: 150, capacity: 2 },
      ],
    },
    {
      id: "greenleaf",
      name: "Greenleaf Inn",
      price: 70,
      location: "Old Town",
      rating: 4.0,
      rooms: [{ id: "std-3", type: "Standard", price: 70, capacity: 2 }],
    },
  ];

  const DEFECT_KEYS = [
    "invalid_email_accepted",
    "incorrect_login_error",
    "filter_ignored",
    "invalid_date_range_accepted",
    "no_confirmation",
  ];

  // ------------------------------------------------------------------ //
  // Storage helpers
  // ------------------------------------------------------------------ //

  function readJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }

  function writeJson(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  let DEFECTS_CACHE = null;

  async function loadDefectsFromServer() {
    try {
      const res = await fetch("/__demo/defects", { cache: "no-store" });
      if (res.ok) {
        const arr = await res.json();
        if (Array.isArray(arr)) {
          DEFECTS_CACHE = arr;
          return;
        }
      }
    } catch (e) {
      // Demo control endpoint not available; fall back to localStorage.
    }
  }

  function getDefects() {
    if (DEFECTS_CACHE !== null) return DEFECTS_CACHE;
    const raw = localStorage.getItem(STORAGE.DEFECTS);
    if (!raw) {
      localStorage.setItem(STORAGE.DEFECTS, JSON.stringify([]));
      return [];
    }
    try {
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }

  function hasDefect(key) {
    return getDefects().includes(key);
  }

  function getUsers() {
    let users = readJson(STORAGE.USERS, null);
    if (!users) {
      users = [DEFAULT_USER];
      writeJson(STORAGE.USERS, users);
    }
    return users;
  }

  function saveUsers(users) {
    writeJson(STORAGE.USERS, users);
  }

  function getBookings() {
    return readJson(STORAGE.BOOKINGS, []);
  }

  function saveBookings(bookings) {
    writeJson(STORAGE.BOOKINGS, bookings);
  }

  function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  function showToast(message, type) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.className = "status status-" + (type || "info");
    el.style.display = "block";
    setTimeout(function () {
      el.style.display = "none";
    }, 3500);
  }

  function showStatus(id, text) {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = text;
      el.style.display = "block";
    }
  }

  function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return "";
    return String(unsafe)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function escapeAttr(unsafe) {
    return escapeHtml(unsafe).replace(/&#039;/g, "&#39;");
  }

  function queryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name);
  }

  // ------------------------------------------------------------------ //
  // Defect controls (used by home.html and config.html)
  // ------------------------------------------------------------------ //

  function renderDefectControls() {
    const container = document.getElementById("defect-list");
    if (!container) return;
    const defects = getDefects();
    container.innerHTML = DEFECT_KEYS.map(
      function (key) {
        const checked = defects.includes(key) ? "checked" : "";
        const labels = {
          invalid_email_accepted: "Registration accepts invalid email",
          incorrect_login_error: "Login shows incorrect error message",
          filter_ignored: "Search ignores selected filter",
          invalid_date_range_accepted: "Booking accepts invalid date range",
          no_confirmation: "Submit works but shows no confirmation",
        };
        return (
          '<li><input type="checkbox" id="defect-' +
          key +
          '" ' +
          checked +
          ' data-defect="' +
          key +
          '"><label for="defect-' +
          key +
          '">' +
          (labels[key] || key) +
          "</label></li>"
        );
      }
    ).join("");
    container.querySelectorAll("input[data-defect]").forEach(function (input) {
      input.addEventListener("change", function () {
        const key = input.getAttribute("data-defect");
        let defects = getDefects();
        if (input.checked) {
          if (!defects.includes(key)) defects.push(key);
        } else {
          defects = defects.filter(function (k) {
            return k !== key;
          });
        }
        localStorage.setItem(STORAGE.DEFECTS, JSON.stringify(defects));
        DEFECTS_CACHE = defects;
        showToast(
          input.checked ? "Defect enabled: " + key : "Defect disabled: " + key,
          "info"
        );
      });
    });
  }

  // ------------------------------------------------------------------ //
  // Registration page
  // ------------------------------------------------------------------ //

  function setupRegister() {
    const form = document.getElementById("register-form");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const name = document.getElementById("reg-name").value.trim();
      const email = document.getElementById("reg-email").value.trim();
      const password = document.getElementById("reg-password").value;
      const confirm = document.getElementById("reg-confirm").value;

      document.getElementById("register-error").textContent = "";
      document.getElementById("register-success").textContent = "";
      ["reg-name", "reg-email", "reg-password", "reg-confirm"].forEach(function (id) {
        document.getElementById(id).classList.remove("invalid");
        const box = document.getElementById(id + "-error");
        box.textContent = "";
        box.style.display = "none";
      });

      let valid = true;
      if (!name) { markInvalid("reg-name", "Full name is required"); valid = false; }
      if (!email) { markInvalid("reg-email", "Email is required"); valid = false; }
      else if (!isValidEmail(email) && !hasDefect("invalid_email_accepted")) {
        markInvalid("reg-email", "Please enter a valid email address"); valid = false;
      }
      if (!password) { markInvalid("reg-password", "Password is required"); valid = false; }
      else if (password.length < 8) {
        markInvalid("reg-password", "Password must be at least 8 characters"); valid = false;
      }
      if (password !== confirm) { markInvalid("reg-confirm", "Passwords do not match"); valid = false; }
      if (!valid) return;

      const users = getUsers();
      if (users.some(function (u) {
        return u.email.toLowerCase() === email.toLowerCase();
      })) {
        document.getElementById("register-error").textContent =
          "An account with this email already exists.";
        return;
      }

      users.push({ name: name, email: email, password: password });
      saveUsers(users);
      showStatus("register-success", "Account created successfully. You can now sign in.");
      form.reset();
      showToast("Registration successful", "success");
    });
  }

  function markInvalid(id, message) {
    const input = document.getElementById(id);
    const box = document.getElementById(id + "-error");
    input.classList.add("invalid");
    input.addEventListener(
      "input",
      function () { input.classList.remove("invalid"); },
      { once: true }
    );
    showStatus(id + "-error", message);
  }

  // ------------------------------------------------------------------ //
  // Login page
  // ------------------------------------------------------------------ //

  function setupLogin() {
    const form = document.getElementById("login-form");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const email = document.getElementById("log-email").value.trim();
      const password = document.getElementById("log-password").value;
      const errorBox = document.getElementById("login-error");
      errorBox.textContent = "";

      const users = getUsers();
      const user = users.find(function (u) {
        return u.email.toLowerCase() === email.toLowerCase();
      });

      if (!user || user.password !== password) {
        if (hasDefect("incorrect_login_error")) {
          showStatus("login-error", "Your account has been locked due to suspicious activity.");
        } else {
          showStatus("login-error", "Invalid email or password.");
        }
        document.getElementById("log-password").classList.add("invalid");
        return;
      }

      writeJson(STORAGE.CURRENT_USER, JSON.stringify(user));
      showToast("Signed in successfully", "success");
      window.location.href = "search.html";
    });
  }

  // ------------------------------------------------------------------ //
  // Search page
  // ------------------------------------------------------------------ //

  function setupSearch() {
    const form = document.getElementById("search-form");
    if (!form) return;
    const today = new Date();
    const tomorrow = new Date(Date.now() + 86400000);
    const dayAfter = new Date(Date.now() + 172800000);
    const toISO = function (d) { return d.toISOString().slice(0, 10); };
    document.getElementById("search-checkin").value = toISO(tomorrow);
    document.getElementById("search-checkout").value = toISO(dayAfter);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const search = {
        destination: document.getElementById("search-destination").value.trim(),
        checkIn: document.getElementById("search-checkin").value,
        checkOut: document.getElementById("search-checkout").value,
        guests: document.getElementById("search-guests").value,
        filter: document.getElementById("search-filter").value,
      };
      writeJson(STORAGE.LAST_SEARCH, search);
      const qs = new URLSearchParams(search).toString();
      window.location.href = "results.html?" + qs;
    });
  }

  // ------------------------------------------------------------------ //
  // Results page
  // ------------------------------------------------------------------ //

  function renderResults() {
    const container = document.getElementById("results-list");
    const summary = document.getElementById("results-summary");
    if (!container) return;
    const search = readJson(STORAGE.LAST_SEARCH, {});
    const filter = search.filter;
    const hotels = HOTELS.filter(function (hotel) {
      if (search.destination) {
        const match =
          hotel.name.toLowerCase().includes(search.destination.toLowerCase()) ||
          hotel.location.toLowerCase().includes(search.destination.toLowerCase());
        if (!match) return false;
      }
      if (hasDefect("filter_ignored")) return true;
      if (!filter || filter === "any") return true;
      if (filter === "under100") return hotel.price < 100;
      if (filter === "under150") return hotel.price < 150;
      return true;
    });

    if (summary) {
      summary.textContent =
        hotels.length +
        " result" +
        (hotels.length === 1 ? "" : "s") +
        (hasDefect("filter_ignored") ? " (filter not applied)" : "");
    }

    container.innerHTML = hotels
      .map(
        function (hotel) {
          return (
            '<div class="hotel" data-testid="hotel-card"><img class="demo-hotel" alt="' +
            escapeHtml(hotel.name) +
            '"><div><h3>' +
            escapeHtml(hotel.name) +
            '</h3><div class="meta">' +
            escapeHtml(hotel.location) +
            " \u00b7 " +
            escapeHtml(hotel.price) +
            "/night \u00b7 \u2605 " +
            hotel.rating +
            '</div></div><div class="hotel-actions"><a class="primary" href="booking.html?hotel=' +
            hotel.id +
            '">Select room</a></div></div>'
          );
      }
    ).join("");
  }

  // ------------------------------------------------------------------ //
  // Booking page
  // ------------------------------------------------------------------ //

  function renderBooking() {
    const container = document.getElementById("booking-form-box");
    const hotelId = queryParam("hotel");
    const hotel = HOTELS.find(function (h) { return h.id === hotelId; });
    if (!container || !hotel) {
      if (container) container.textContent = "No hotel selected.";
      return;
    }

    const user = readJson(STORAGE.CURRENT_USER, null);
    const roomsHtml = hotel.rooms
      .map(
        function (room) {
          return (
            '<label class="room"><input type="radio" name="room" value="' +
            room.id +
            '" data-price="' +
            room.price +
            '">' +
            escapeHtml(room.type) +
            " - $" +
            room.price +
            "/night (capacity " +
            room.capacity +
            ")</label>"
          );
      }
    ).join("");

    container.innerHTML =
      '<div class="booking-summary"><strong>' +
      escapeHtml(hotel.name) +
      "</strong> \u00b7 " +
      escapeHtml(hotel.location) +
      "</div>" +
      '<form id="booking-form" novalidate>' +
      '<label>Guest name<input type="text" id="book-name" value="' +
      escapeAttr(user ? user.name : "") +
      '" required></label>' +
      '<label>Email<input type="email" id="book-email" value="' +
      escapeAttr(user ? user.email : "") +
      '" required></label>' +
      '<label>Check-in date<input type="date" id="book-checkin" required></label>' +
      '<label>Check-out date<input type="date" id="book-checkout" required></label>' +
      '<label>Room type<div id="book-rooms">' +
      roomsHtml +
      "</div></label>" +
      '<button type="submit" class="primary" id="book-submit">Book now</button>' +
      "</form>";

    const form = document.getElementById("booking-form");
    const errorBox = document.getElementById("booking-error");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const checkIn = document.getElementById("book-checkin").value;
      const checkOut = document.getElementById("book-checkout").value;
      if (errorBox) errorBox.textContent = "";

      if (!checkIn || !checkOut) {
        showStatus("booking-error", "Please select both dates.");
        return;
      }
      if (checkOut < checkIn && !hasDefect("invalid_date_range_accepted")) {
        showStatus("booking-error", "Check-out date must be on or after the check-in date.");
        return;
      }

      const btn = document.getElementById("book-submit");
      if (errorBox) errorBox.style.display = "none";
      const booking = {
          id: "BK-" + Math.random().toString(36).slice(2, 9).toUpperCase(),
          hotelId: hotel.id,
          hotelName: hotel.name,
          name: document.getElementById("book-name").value.trim(),
          email: document.getElementById("book-email").value.trim(),
          checkIn: checkIn,
          checkOut: checkOut,
          room: document.querySelector('input[name="room"]:checked')
            ? document.querySelector('input[name="room"]:checked').value
            : hotel.rooms[0].id,
          createdAt: new Date().toISOString(),
        };
        const bookings = getBookings();
        bookings.push(booking);
        saveBookings(bookings);
        writeJson(STORAGE.LAST_BOOKING, booking);

        if (hasDefect("no_confirmation")) {
          btn.disabled = false;
          btn.textContent = "Book now";
          showStatus("booking-error", "Your request was received. We will confirm shortly.");
          showToast("Request submitted (no confirmation)", "info");
          return;
        }
        window.location.href = "confirmation.html";
    });
  }

  // ------------------------------------------------------------------ //
  // Confirmation page
  // ------------------------------------------------------------------ //

  function renderConfirmation() {
    const container = document.getElementById("confirmation-detail");
    if (!container) return;
    const booking = readJson(STORAGE.LAST_BOOKING, null);
    if (!booking) {
      container.innerHTML = '<p>No recent booking found.</p>';
      return;
    }
    container.innerHTML =
      '<h2>Booking Confirmed</h2>' +
      '<p><strong>Reference:</strong> <span class="reference">' +
      escapeHtml(booking.id) +
      "</span></p>" +
      '<p><strong>Hotel:</strong> ' +
      escapeHtml(booking.hotelName) +
      "</p>" +
      '<p><strong>Guest:</strong> ' +
      escapeHtml(booking.name) +
      " (" +
      escapeHtml(booking.email) +
      ")</p>" +
      '<p><strong>Check-in:</strong> ' +
      escapeHtml(booking.checkIn) +
      "</p>" +
      '<p><strong>Check-out:</strong> ' +
      escapeHtml(booking.checkOut) +
      "</p>" +
      '<p><strong>Room:</strong> ' +
      escapeHtml(booking.room) +
      "</p>" +
      '<p class="status success">Your booking is confirmed.</p>';
  }

  // ------------------------------------------------------------------ //
  // Initialization
  // ------------------------------------------------------------------ //

  async function init() {
    await loadDefectsFromServer();
    renderDefectControls();

    const page = window.location.pathname.split("/").pop() || "index.html";
    if (page === "index.html" || page === "") setupHomeStub();
    if (page === "register.html") setupRegister();
    if (page === "login.html") setupLogin();
    if (page === "search.html") setupSearch();
    if (page === "results.html") renderResults();
    if (page === "booking.html") renderBooking();
    if (page === "confirmation.html") renderConfirmation();
    if (page === "config.html") renderDefectControls();
  }

  function setupHomeStub() {
    // Home page has no form; defect controls rendered by renderDefectControls.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(); });
  } else {
    init();
  }
})();
