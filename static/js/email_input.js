/**
 * Email fields take English only: printable ASCII, nothing else (the user's call, 2026-10-01).
 * Flask's twin of minty-web lib/emailInput.ts (also copied into billing-frontend, onboarding and
 * the landing page) - change all of them together. The server says the same thing loudly:
 * blueprints/shared/email_rules.py answers 400 with HINT.
 *
 * Markup - every editable email field:
 *
 *   <input type="text" inputmode="email" autocomplete="email" autocapitalize="none"
 *          spellcheck="false" data-email-ascii="<hint classes>"
 *          [data-email-ascii-anchor="<closest() selector>"]>
 *
 * Why `type="text" inputmode="email"` and not `type="email"`: the browser's email input refuses
 * Hangul before the "@" but accepts it after, as an international domain, and then hands
 * `.value` back as punycode (`xn--...`) - ASCII to every check here, Korean on screen. It also
 * hides the caret position, so a strip could not keep it. `inputmode` keeps the phone's email
 * keyboard.
 *
 * Anything else is stripped as it is typed, the caret kept where it was, and the hint (a
 * `div.email-ascii-hint[role=status]`, made on first need right after the input - or after
 * `closest(data-email-ascii-anchor)` when the input sits in a row - with the attribute's
 * classes) says why. The strip waits for an IME composition to finish: rewriting the value
 * mid-composition makes the Korean IME duplicate characters, so a syllable shows for a moment,
 * then goes.
 *
 * The listeners are on `document` in the CAPTURE phase, so a page's own `input` handler on the
 * field runs after the strip and reads the clean value. A strip at `compositionend` happens
 * after the browser's last `input`, so it fires one more `input` for those handlers.
 */
(function () {
  "use strict";

  // Loaded by the sidebar and by the page itself on some screens: the first copy wins.
  if (window.MintyEmail) return;

  var HINT = "Email can only contain English letters, numbers and symbols.";
  var NOT_EMAIL_CHAR = /[^\x21-\x7E]/g;
  var NON_ASCII = /[^\x00-\x7F]/;
  // One "@", something either side, a dot in the domain - printable ASCII only. Deliberately
  // shallow (`a+b@sub.domain.museum` must pass); the same rule as minty-web's and the API's.
  var EMAIL_RE = /^[\x21-\x3F\x41-\x7E]+@[\x21-\x3F\x41-\x7E]+\.[\x21-\x3F\x41-\x7E]+$/;
  var SELECTOR = "input[data-email-ascii]";
  var HINT_CLASS = "email-ascii-hint";

  var redispatching = false;

  function text(value) {
    return value == null ? "" : String(value);
  }

  /** Drops everything but printable ASCII - whitespace included, which no address contains. */
  function sanitize(value) {
    return text(value).replace(NOT_EMAIL_CHAR, "");
  }

  function isEmail(value) {
    return EMAIL_RE.test(text(value).trim());
  }

  function hintFor(input, create) {
    var anchorSelector = input.getAttribute("data-email-ascii-anchor");
    var anchor = (anchorSelector && input.closest(anchorSelector)) || input;
    var next = anchor.nextElementSibling;
    if (next && next.classList.contains(HINT_CLASS)) return next;
    if (!create) return null;
    var hint = document.createElement("div");
    hint.className = (text(input.getAttribute("data-email-ascii")) + " " + HINT_CLASS).trim();
    hint.setAttribute("role", "status");
    hint.hidden = true;
    hint.textContent = HINT;
    anchor.insertAdjacentElement("afterend", hint);
    return hint;
  }

  function setHint(input, show) {
    var hint = hintFor(input, show);
    if (hint) hint.hidden = !show;
  }

  /** Hides a field's hint - for a form that is reset or put away without an input event. */
  function hideHint(input) {
    if (input) setHint(input, false);
  }

  /** Strips the field, keeps the caret, shows or hides the hint. True when the value changed. */
  function settle(input) {
    var raw = input.value;
    var clean = sanitize(raw);
    var changed = clean !== raw;
    if (changed) {
      var start = input.selectionStart == null ? raw.length : input.selectionStart;
      var caret = sanitize(raw.slice(0, start)).length;
      input.value = clean;
      input.setSelectionRange(caret, caret);
    }
    setHint(input, NON_ASCII.test(raw));
    return changed;
  }

  function emailField(event) {
    var el = event.target;
    return el && el.matches && el.matches(SELECTOR) ? el : null;
  }

  document.addEventListener(
    "input",
    function (event) {
      if (redispatching || event.isComposing) return;
      var el = emailField(event);
      if (el) settle(el);
    },
    true
  );

  document.addEventListener(
    "compositionend",
    function (event) {
      var el = emailField(event);
      if (!el || !settle(el)) return;
      redispatching = true;
      try {
        el.dispatchEvent(new Event("input", { bubbles: true }));
      } finally {
        redispatching = false;
      }
    },
    true
  );

  window.MintyEmail = {
    HINT: HINT,
    EMAIL_RE: EMAIL_RE,
    isEmail: isEmail,
    sanitize: sanitize,
    hideHint: hideHint,
  };
})();
