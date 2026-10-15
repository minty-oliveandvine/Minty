/**
 * Modal and Drawer for the redesigned Petty Cash pages (Part 14 Overlay; the behaviour of
 * @minty/shared's Overlay.tsx, in plain JS). Markup comes from templates/petty_cash/_ui.html's
 * `modal` / `drawer` macros: <div class="pc-overlay" id="…" hidden data-pc-overlay>.
 *
 *   PcOverlay.open(id, { opener, initialFocus, onRequestClose })
 *   PcOverlay.close(id)
 *   <button data-pc-open="id"> opens; <button data-pc-close> closes the overlay it sits in.
 *
 * - focus goes to `initialFocus`, else [data-pc-initial-focus], else the first control, else the
 *   panel; Tab and Shift+Tab wrap inside the panel;
 * - Escape is a CAPTURE-phase document listener, and only the TOP overlay of the stack answers it
 *   (and only while focus is inside it - a foreign dialog on top keeps its own Escape);
 * - a mousedown on the scrim asks onRequestClose (which may refuse, for unsaved input);
 *   `data-pc-locked` overlays never close on Escape or the scrim;
 * - the scroll lock is reference-counted, so two overlays never unlock the page early;
 * - on close, focus returns to the opener.
 */
(function () {
  "use strict";

  const FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const stack = [];
  let locks = 0;
  let savedOverflow = "";

  function lockScroll() {
    if (locks++ === 0) {
      savedOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
  }
  function unlockScroll() {
    if (locks > 0 && --locks === 0) document.body.style.overflow = savedOverflow;
  }

  function panelOf(root) {
    return root.querySelector(".pc-modal, .pc-drawer");
  }
  function focusables(panel) {
    return Array.from(panel.querySelectorAll(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement
    );
  }

  function requestClose(entry) {
    if (entry.root.hasAttribute("data-pc-locked")) return;
    if (entry.onRequestClose && entry.onRequestClose() === false) return;
    close(entry.root.id);
  }

  function open(id, options) {
    const root = document.getElementById(id);
    if (!root) throw new Error("PcOverlay: no overlay #" + id);
    if (stack.some((e) => e.root === root)) return;
    const opts = options || {};
    const entry = {
      root: root,
      opener: opts.opener || document.activeElement,
      onRequestClose: opts.onRequestClose || null,
    };
    stack.push(entry);
    root.hidden = false;
    root.setAttribute("data-open", "");
    lockScroll();
    const panel = panelOf(root);
    const target =
      (typeof opts.initialFocus === "string" ? root.querySelector(opts.initialFocus) : opts.initialFocus) ||
      root.querySelector("[data-pc-initial-focus]") ||
      focusables(panel)[0] ||
      panel;
    target.focus();
    root.dispatchEvent(new CustomEvent("pc:open"));
  }

  function close(id) {
    const index = stack.findIndex((e) => e.root.id === id);
    if (index === -1) return;
    const entry = stack.splice(index, 1)[0];
    entry.root.hidden = true;
    entry.root.removeAttribute("data-open");
    unlockScroll();
    entry.root.dispatchEvent(new CustomEvent("pc:close"));
    if (entry.opener && document.contains(entry.opener) && typeof entry.opener.focus === "function") {
      entry.opener.focus();
    }
  }

  function top() {
    return stack[stack.length - 1] || null;
  }

  document.addEventListener(
    "keydown",
    function (event) {
      const entry = top();
      if (!entry) return;
      // The full-screen receipt viewer sits over every overlay and answers its own Escape.
      const viewer = document.getElementById("receiptViewerModal");
      if (viewer && !viewer.classList.contains("hidden")) return;
      const panel = panelOf(entry.root);
      if (!panel.contains(document.activeElement) && document.activeElement !== panel) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        requestClose(entry);
      } else if (event.key === "Tab") {
        const items = focusables(panel);
        if (items.length === 0) {
          event.preventDefault();
          panel.focus();
          return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    },
    true
  );

  document.addEventListener("mousedown", function (event) {
    const entry = top();
    if (entry && event.target.matches("[data-pc-scrim]") && entry.root.contains(event.target)) {
      requestClose(entry);
    }
  });

  document.addEventListener("click", function (event) {
    const opener = event.target.closest("[data-pc-open]");
    if (opener) {
      event.preventDefault();
      open(opener.getAttribute("data-pc-open"), { opener: opener });
      return;
    }
    const closer = event.target.closest("[data-pc-close]");
    if (closer) {
      const root = closer.closest("[data-pc-overlay]");
      if (root) {
        const entry = stack.find((e) => e.root === root);
        if (entry) {
          if (entry.onRequestClose && entry.onRequestClose() === false) return;
          close(root.id);
        }
      }
    }
  });

  /** A button's processing state (Part 14): disabled, aria-busy, spinner + "Saving…" label. */
  function busy(button, label) {
    if (!button) return function () {};
    const html = button.innerHTML;
    const wasDisabled = button.disabled;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.innerHTML = '<span class="pc-spinner" aria-hidden="true"></span><span></span>';
    button.lastChild.textContent = label;
    return function restore() {
      button.innerHTML = html;
      button.disabled = wasDisabled;
      button.removeAttribute("aria-busy");
    };
  }

  /** Overflow menus: <div class="pc-menu-wrap"><button aria-haspopup="menu" aria-expanded>…
   *  <div class="pc-menu" role="menu" hidden>…[role=menuitem]</div></div>. */
  function closeMenus(except) {
    document.querySelectorAll(".pc-menu-wrap > [aria-haspopup='menu'][aria-expanded='true']").forEach((btn) => {
      if (btn === except) return;
      btn.setAttribute("aria-expanded", "false");
      btn.parentElement.querySelector(".pc-menu").hidden = true;
    });
  }
  document.addEventListener("click", function (event) {
    const toggle = event.target.closest(".pc-menu-wrap > [aria-haspopup='menu']");
    if (toggle) {
      const menu = toggle.parentElement.querySelector(".pc-menu");
      const opening = menu.hidden;
      closeMenus(toggle);
      menu.hidden = !opening;
      toggle.setAttribute("aria-expanded", String(opening));
      if (opening) {
        const first = menu.querySelector("[role='menuitem']");
        if (first) first.focus();
      }
      return;
    }
    if (!event.target.closest(".pc-menu")) closeMenus(null);
  });
  document.addEventListener("keydown", function (event) {
    const menu = event.target.closest && event.target.closest(".pc-menu");
    if (!menu) return;
    const items = Array.from(menu.querySelectorAll("[role='menuitem']"));
    const i = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(i + 1) % items.length].focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(i - 1 + items.length) % items.length].focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      const toggle = menu.parentElement.querySelector("[aria-haspopup='menu']");
      closeMenus(null);
      toggle.focus();
    }
  });

  // A message the previous page left for this one (it saved, then reloaded or moved on).
  document.addEventListener("DOMContentLoaded", function () {
    const read = (key) => {
      try {
        const value = sessionStorage.getItem(key);
        sessionStorage.removeItem(key);
        return value;
      } catch (e) {
        return null;
      }
    };
    const success = read("pcFlashSuccess");
    const warning = read("pcFlashWarning");
    if (success && window.showSuccessToast) window.showSuccessToast(success);
    if (warning && window.showWarningToast) window.showWarningToast(warning);
  });

  window.PcOverlay = { open: open, close: close, busy: busy };
})();
