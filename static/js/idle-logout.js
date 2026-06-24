/*
 * Idle auto-logout.
 *
 * Logs the user out after a period of no real activity (mouse / keyboard /
 * touch / scroll). On timeout the browser is sent to /logout?reason=idle,
 * which clears the Minty session AND ends the user's Xero SSO session
 * (Xero end-session endpoint). A warning toast appears shortly before logout
 * with a button to stay signed in.
 *
 * Activity is shared across tabs via localStorage, so using any tab keeps the
 * others alive, and a logout in one effectively logs out all.
 *
 * Config injected by base/layout.html:
 *   window.IDLE_TIMEOUT_SECONDS  - inactivity allowed before logout (default 1800)
 *   window.IDLE_LOGOUT_URL       - URL to navigate to on timeout
 */
(function () {
  "use strict";

  var TIMEOUT_MS = (Number(window.IDLE_TIMEOUT_SECONDS) || 1800) * 1000;
  var LOGOUT_URL = window.IDLE_LOGOUT_URL || "/logout?reason=idle";
  // Warn 60s before logout (or 10% of a very short timeout, for testing).
  var WARN_MS = Math.min(60 * 1000, Math.floor(TIMEOUT_MS * 0.1));
  var STORAGE_KEY = "minty_last_activity";
  var ACTIVITY_WRITE_THROTTLE_MS = 5000;

  var idleTimer = null;
  var warnTimer = null;
  var lastWrite = 0;
  var loggingOut = false;

  function nowMs() {
    return new Date().getTime();
  }

  function readLastActivity() {
    var v = null;
    try {
      v = window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      /* localStorage unavailable (private mode) — fall back to per-tab */
    }
    var parsed = parseInt(v, 10);
    return isNaN(parsed) ? nowMs() : parsed;
  }

  function writeLastActivity(ts) {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(ts));
    } catch (e) {
      /* ignore */
    }
  }

  function doLogout() {
    if (loggingOut) return;
    loggingOut = true;
    window.location.href = LOGOUT_URL;
  }

  function removeWarning() {
    var el = document.getElementById("idle-warning-toast");
    if (el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
  }

  function showWarning(secondsLeft) {
    if (document.getElementById("idle-warning-toast")) return;
    var box = document.createElement("div");
    box.id = "idle-warning-toast";
    box.setAttribute("role", "alertdialog");
    box.style.cssText = [
      "position:fixed",
      "top:16px",
      "right:16px",
      "z-index:99999",
      "max-width:320px",
      "padding:14px 16px",
      "background:#FFF7ED",
      "border:1px solid #F97316",
      "border-radius:12px",
      "box-shadow:0 6px 20px rgba(0,0,0,0.12)",
      "font-family:'Plus Jakarta Sans',system-ui,sans-serif",
      "color:#9A3412",
      "font-size:14px",
    ].join(";");

    var msg = document.createElement("div");
    msg.style.cssText = "margin-bottom:10px;line-height:1.4;";
    msg.textContent =
      "You will be logged out soon due to inactivity. Xero will also be " +
      "signed out.";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Stay signed in";
    btn.style.cssText = [
      "background:#294882",
      "color:#fff",
      "border:none",
      "border-radius:9999px",
      "padding:6px 14px",
      "font-size:13px",
      "cursor:pointer",
    ].join(";");
    btn.addEventListener("click", function () {
      recordActivity(true);
    });

    box.appendChild(msg);
    box.appendChild(btn);
    document.body.appendChild(box);
  }

  function schedule() {
    if (idleTimer) clearTimeout(idleTimer);
    if (warnTimer) clearTimeout(warnTimer);

    var elapsed = nowMs() - readLastActivity();
    var remaining = TIMEOUT_MS - elapsed;

    if (remaining <= 0) {
      doLogout();
      return;
    }

    removeWarning();
    var warnIn = remaining - WARN_MS;
    if (warnIn <= 0) {
      showWarning(Math.ceil(remaining / 1000));
    } else {
      warnTimer = setTimeout(function () {
        showWarning(Math.ceil(WARN_MS / 1000));
      }, warnIn);
    }
    idleTimer = setTimeout(doLogout, remaining);
  }

  function recordActivity(force) {
    var ts = nowMs();
    // Throttle localStorage writes, but always write when forced (e.g. the
    // "Stay signed in" button) so other tabs reset immediately.
    if (force || ts - lastWrite > ACTIVITY_WRITE_THROTTLE_MS) {
      lastWrite = ts;
      writeLastActivity(ts);
    }
    removeWarning();
    schedule();
  }

  // User activity in THIS tab.
  var events = [
    "mousemove",
    "mousedown",
    "keydown",
    "scroll",
    "touchstart",
    "click",
    "wheel",
  ];
  events.forEach(function (evt) {
    window.addEventListener(
      evt,
      function () {
        recordActivity(false);
      },
      { passive: true }
    );
  });

  // Activity (or logout) in ANOTHER tab.
  window.addEventListener("storage", function (e) {
    if (e.key === STORAGE_KEY) {
      schedule();
    }
  });

  // Re-evaluate when a backgrounded tab becomes visible again.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      schedule();
    }
  });

  // Initialise.
  writeLastActivity(nowMs());
  schedule();
})();
