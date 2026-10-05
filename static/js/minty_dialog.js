/**
 * minty-web's modal family on this app's Jinja pages (2026-10-01). The user, 2026-09-30: "use
 * modals designed in minty web. that should be how modals is going to be designed accross
 * repos". The sources are minty-web's components/ui/ModalFrame.tsx and ConfirmDialog.tsx and
 * features/subscription/components/InterruptedDialogs.tsx (LeaveDialog, Figma A-11);
 * minty-payment-request-web holds copies under features/subscription/components/. This is a PORT, not a copy - @minty/shared is TypeScript and cannot
 * serve Jinja - so change all three together (minty-web, billing-frontend, here). The look is
 * static/css/minty_dialog.css.
 *
 * Two things live here:
 *
 * - MintyDialog.confirm({...}) is ConfirmDialog: a small white card over the blurred page, the
 *   title with Minty beside it, the sentences, the secondary button (Go back; grey-edged, or teal
 *   for "Discard changes") and the confirming one in the tone the action calls for (teal, orange,
 *   red). It resolves "confirm", "back" or "dismiss" - Escape or the backdrop, the safe way out.
 *
 * - MintyLeaveGuard is "Leave without saving?" for a page with unsaved changes. watch(isDirty)
 *   arms it. A link that would leave the page asks first; "Discard changes" replays the click,
 *   so every link keeps its own behaviour. The browser's own prompt covers reload, closing the
 *   tab, a typed address and Back/Forward. saving() lets the page's own save go without a
 *   question; ask(proceed) is for exits that are not links.
 *
 * The dialog is built on first use as the page's last element, outside any fade or stacking
 * context a page wraps its content in, at z-index 250 (see the stylesheet). Load this in the
 * page's head, not deferred, so a page's own scripts can rely on it.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var IMAGES = new URL("../img/portal/", (script && script.src) || window.location.href).href;

  // ConfirmDialog's MODAL_IMAGE, trimmed to the pictures this app ships. The height is pinned and
  // the width follows, as there.
  var IMAGE = {
    dont: { file: "minty-dont.png", width: 100, height: 130 },
    surprised: { file: "minty-surprised.png", width: 113, height: 144 },
  };
  var CONFIRM_TONES = ["teal", "orange", "red"];
  var BACK_TONES = ["grey", "teal"];

  var root = null;
  var parts = null;
  var pending = null; // { resolve, returnFocus }

  function build() {
    if (root) return;
    root = document.createElement("div");
    root.id = "minty-dialog";
    root.setAttribute("aria-hidden", "true");
    root.inert = true;
    // Static markup only: every word put into it later goes in as text.
    root.innerHTML =
      '<button type="button" class="md-backdrop" tabindex="-1" aria-label="Go back"></button>' +
      '<div class="md-card" role="dialog" aria-modal="true" aria-labelledby="minty-dialog-title">' +
      '<div class="md-head">' +
      '<div class="md-title-col"><h2 class="md-title" id="minty-dialog-title"></h2></div>' +
      '<img class="md-image" alt="">' +
      "</div>" +
      '<div class="md-body"></div>' +
      '<div class="md-actions">' +
      '<button type="button" class="md-btn md-back"></button>' +
      '<button type="button" class="md-btn md-confirm"></button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(root);
    parts = {
      backdrop: root.querySelector(".md-backdrop"),
      title: root.querySelector(".md-title"),
      image: root.querySelector(".md-image"),
      body: root.querySelector(".md-body"),
      back: root.querySelector(".md-back"),
      confirm: root.querySelector(".md-confirm"),
    };
    parts.backdrop.addEventListener("click", function () {
      finish("dismiss");
    });
    parts.back.addEventListener("click", function () {
      finish("back");
    });
    parts.confirm.addEventListener("click", function () {
      finish("confirm");
    });
  }

  /** One sentence: a string, or a list of strings and { strong: "..." } pieces. Text only. */
  function paragraph(sentence) {
    var p = document.createElement("p");
    (Array.isArray(sentence) ? sentence : [sentence]).forEach(function (piece) {
      if (piece && typeof piece === "object" && "strong" in piece) {
        var strong = document.createElement("strong");
        strong.textContent = String(piece.strong);
        p.appendChild(strong);
      } else {
        p.appendChild(document.createTextNode(piece == null ? "" : String(piece)));
      }
    });
    return p;
  }

  function finish(choice) {
    if (!pending) return;
    var done = pending;
    pending = null;
    root.removeAttribute("data-open");
    root.removeAttribute("data-modal");
    root.setAttribute("aria-hidden", "true");
    root.inert = true;
    var back = done.returnFocus;
    if (back && back.isConnected && typeof back.focus === "function") back.focus();
    done.resolve(choice);
  }

  /**
   * Ask. Options: title, body (a list of sentences), image ("dont" | "surprised"), confirmLabel,
   * confirmTone ("teal" | "orange" | "red"), backLabel ("Go back"), backTone ("grey" | "teal"),
   * safe ("back" | "confirm": the button focused first - the one that changes nothing), name (on
   * the card as data-modal, for tests). Resolves "confirm", "back" or "dismiss".
   */
  function confirm(options) {
    var o = options || {};
    build();
    finish("dismiss"); // one question at a time: an open one is answered the safe way
    var art = IMAGE[o.image] || IMAGE.surprised;
    parts.title.textContent = o.title || "";
    parts.image.src = IMAGES + art.file;
    parts.image.width = art.width;
    parts.image.height = art.height;
    parts.image.style.height = art.height + "px";
    parts.image.setAttribute("data-image", IMAGE[o.image] ? o.image : "surprised");
    parts.body.replaceChildren.apply(parts.body, (o.body || []).map(paragraph));
    parts.back.textContent = o.backLabel || "Go back";
    parts.back.setAttribute("data-tone", BACK_TONES.indexOf(o.backTone) >= 0 ? o.backTone : "grey");
    parts.confirm.textContent = o.confirmLabel || "Confirm";
    parts.confirm.setAttribute(
      "data-tone",
      CONFIRM_TONES.indexOf(o.confirmTone) >= 0 ? o.confirmTone : "teal"
    );
    if (o.name) root.setAttribute("data-modal", o.name);
    return new Promise(function (resolve) {
      pending = { resolve: resolve, returnFocus: document.activeElement };
      root.inert = false;
      root.removeAttribute("aria-hidden");
      root.setAttribute("data-open", "");
      (o.safe === "confirm" ? parts.confirm : parts.back).focus();
    });
  }

  // Escape answers the open question the safe way and goes no further: caught on the way down,
  // before the sidebar's own Escape (on window, bubbling) closes the drawer under the dialog.
  // Tab stays on the card's two buttons while it is open.
  window.addEventListener(
    "keydown",
    function (event) {
      if (!pending) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        finish("dismiss");
        return;
      }
      if (event.key !== "Tab") return;
      var first = parts.back;
      var last = parts.confirm;
      var inside = root.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || !inside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
        event.preventDefault();
        first.focus();
      }
    },
    true
  );

  window.MintyDialog = { confirm: confirm };

  // --- "Leave without saving?" ----------------------------------------------------------------

  // minty-web's LeaveDialog words (InterruptedDialogs.tsx): LEAVE_TITLE, LEAVE_BODY_1/2,
  // DISCARD_CHANGES, GO_BACK_UPPER.
  var LEAVE = {
    title: "Leave without saving?",
    body: ["You have unsaved changes.", "Your changes will be lost if you leave this page."],
    discard: "Discard changes",
    stay: "Go Back",
  };

  var guard = { isDirty: null, disarmed: false, bypass: false, installed: false };

  function dirtyNow() {
    if (guard.disarmed || typeof guard.isDirty !== "function") return false;
    try {
      return Boolean(guard.isDirty());
    } catch (err) {
      // A check that breaks must not let the changes go unasked: say so, and ask.
      console.error("[leave guard] the unsaved-changes check failed", err);
      return true;
    }
  }

  /** Discard changes (true) or Go Back (false). */
  function askToLeave() {
    return confirm({
      name: "leave",
      title: LEAVE.title,
      body: LEAVE.body,
      image: "dont",
      backLabel: LEAVE.discard,
      backTone: "teal",
      confirmLabel: LEAVE.stay,
      confirmTone: "teal",
      safe: "confirm",
    }).then(function (choice) {
      return choice === "back";
    });
  }

  function withoutHash(href) {
    var i = href.indexOf("#");
    return i === -1 ? href : href.slice(0, i);
  }

  /** The link a click would leave the page by, or null when the click stays (or opens elsewhere). */
  function leavingLink(target) {
    var el = target instanceof Element ? target : target && target.parentElement;
    var link = el ? el.closest("a[href]") : null;
    if (!link) return null;
    if (root && root.contains(link)) return null;
    // The header's initials and menu open the sidebar; they never navigate.
    if (link.hasAttribute("data-sidebar-open") || link.hasAttribute("download")) return null;
    var opensIn = (link.getAttribute("target") || "").trim().toLowerCase();
    if (opensIn && opensIn !== "_self") return null;
    // The attribute, not link.href, which is always absolute.
    var raw = (link.getAttribute("href") || "").trim();
    if (!raw || raw.charAt(0) === "#" || /^javascript:/i.test(raw)) return null;
    var url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (err) {
      return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    // A jump within this page. A link to exactly this address is NOT one: it reloads, so it asks.
    if (url.hash && withoutHash(url.href) === withoutHash(window.location.href)) return null;
    return link;
  }

  function replay(link) {
    if (!link.isConnected) {
      window.location.assign(link.href);
      return;
    }
    guard.bypass = true;
    link.click(); // synchronous: the guard's own listener sees it first and lets it through
    guard.bypass = false;
  }

  function onClick(event) {
    if (guard.bypass) {
      guard.bypass = false;
      return;
    }
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = leavingLink(event.target);
    if (!link || !dirtyNow()) return;
    // Caught on the way down, before the page's own handlers (inline onclick, the sidebar's
    // close-on-link) run; the open drawer stays open under the dialog.
    event.preventDefault();
    event.stopImmediatePropagation();
    askToLeave().then(function (discard) {
      if (!discard) return;
      guard.disarmed = true; // no browser prompt behind ours
      replay(link);
    });
  }

  function onBeforeUnload(event) {
    if (!dirtyNow()) return undefined;
    event.preventDefault();
    event.returnValue = "";
    return "";
  }

  window.MintyLeaveGuard = {
    /** Arm the guard: isDirty() is asked at every way out. */
    watch: function (isDirty) {
      guard.isDirty = isDirty;
      guard.disarmed = false;
      if (guard.installed) return;
      window.addEventListener("click", onClick, true);
      window.addEventListener("beforeunload", onBeforeUnload);
      guard.installed = true;
    },
    /** An exit that is not a link: proceed() at once when nothing is unsaved, else ask first. */
    ask: function (proceed) {
      if (!dirtyNow()) {
        proceed();
        return;
      }
      askToLeave().then(function (discard) {
        if (!discard) return;
        guard.disarmed = true;
        proceed();
      });
    },
    /** The page's own save is about to navigate: no question and no browser prompt. */
    saving: function () {
      guard.disarmed = true;
    },
  };
})();
