/*
 * The sidebar on this app's pages (templates/components/minty_sidebar.html, decided in
 * blueprints/shared/sidebar.py) - minty-web's one drawer with two views, ported from
 * components/ui/Sidebar.tsx and features/profile:
 *
 * - the MENU (Figma 02), opened by a header's ≡ (data-sidebar-open="menu"), drawn by the server;
 * - MY PROFILE (Figma 10-A), opened by the header's initials (data-sidebar-open="profile") or
 *   from the menu by the person's name; its ‹ goes back to the menu. Drawn here, over the SAME
 *   reads minty-web makes: this app's GET/PATCH /api/me/profile and minty-billing-api's
 *   GET /api/me/subscriptions, with the bearer token GET /me/sidebar-token hands the page.
 *
 * Nothing navigates to open it: it slides over the page and closes back onto it (Escape, a click
 * beside it, a link inside it). The profile view is read when it is opened, never before, and
 * forgotten when the view goes back to the menu - as minty-web mounts and unmounts it.
 *
 * Failures say so: a read that fails shows its sentence (or the house one) with Try again, and
 * the console carries the detail. Nothing is swallowed.
 */
(function () {
  "use strict";

  const root = document.getElementById("minty-sidebar");
  if (!root || root.dataset.ready) return;
  root.dataset.ready = "1";
  // Out of whatever ancestor the include sat in (a transform or overflow there would clip a
  // fixed drawer) - minty-web's portal to document.body.
  document.body.appendChild(root);

  const panel = root.querySelector(".msb-panel");
  const backdrop = root.querySelector(".msb-backdrop");
  const views = {
    menu: root.querySelector('[data-sidebar-view="menu"]'),
    profile: root.querySelector('[data-sidebar-view="profile"]'),
  };
  const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled])";

  // --- copy (minty-web features/profile/lib/profileView.ts, lib/apiClient.ts) -----------------
  const LOAD_FAILED = "Your profile didn't come through. Mind trying again?";
  const SAVE_FAILED = "That didn't quite save. Mind trying again?";
  const EMAIL_REQUIRED = "We'll need an email here.";
  const SAVED = "Your profile is saved.";
  const HOUSE_FALLBACK = "Something went wrong on my end. Mind trying again?";
  const SESSION_ENDED = "Your session has ended. Sign in again to keep going.";
  const TRIAL_ENDING_DAYS = 30; // minty-web features/subscription/lib/billing.ts
  const MAX_PER_PAGE = 100;

  // --- the drawer (Sidebar.tsx) ----------------------------------------------------------------

  const state = { open: false, view: "menu", profileMounted: false };
  let opener = null;
  let previousOverflow = "";

  function openers() {
    return document.querySelectorAll("[data-sidebar-open]");
  }

  function paintOpeners() {
    openers().forEach((el) => {
      const mine = el.getAttribute("data-sidebar-open") === state.view;
      el.setAttribute("aria-expanded", state.open && mine ? "true" : "false");
    });
  }

  function focusFirst() {
    const first = views[state.view] && views[state.view].querySelector(FOCUSABLE);
    if (first) first.focus();
  }

  function show(view) {
    state.view = view === "profile" ? "profile" : "menu";
    panel.setAttribute("data-view", state.view);
    views.menu.hidden = state.view !== "menu";
    views.profile.hidden = state.view !== "profile";
    backdrop.setAttribute("aria-label", state.view === "profile" ? "Close My Profile" : "Close menu");
    if (state.view === "profile" && !state.profileMounted) {
      state.profileMounted = true;
      Profile.mount();
    } else if (state.view === "menu") {
      state.profileMounted = false;
      Profile.unmount();
    }
    paintOpeners();
    if (state.open) focusFirst();
  }

  function open(view, from) {
    opener = from || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    if (!state.open) {
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    state.open = true;
    root.setAttribute("data-open", "");
    root.removeAttribute("aria-hidden");
    root.inert = false;
    backdrop.tabIndex = 0;
    show(view);
  }

  function close({ restoreFocus = true } = {}) {
    if (!state.open) return;
    state.open = false;
    root.removeAttribute("data-open");
    root.setAttribute("aria-hidden", "true");
    root.inert = true;
    backdrop.tabIndex = -1;
    document.body.style.overflow = previousOverflow;
    paintOpeners();
    if (restoreFocus && opener && typeof opener.focus === "function") opener.focus();
  }

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const trigger = target.closest("[data-sidebar-open]");
    if (trigger) {
      event.preventDefault(); // the initials' href is the no-script way in
      open(trigger.getAttribute("data-sidebar-open"), trigger);
      return;
    }
    if (!root.contains(target)) return;
    if (target.closest("[data-sidebar-close]")) {
      close();
      return;
    }
    const switcher = target.closest("[data-sidebar-show]");
    if (switcher) {
      show(switcher.getAttribute("data-sidebar-show"));
      return;
    }
    // A link inside moves this page somewhere else: close behind it, so a back button's
    // restored page is not left under an open sidebar (minty-web closes on the route change).
    const link = target.closest("a[href]");
    if (link && link.target !== "_blank") close({ restoreFocus: false });
  });

  window.addEventListener("keydown", (event) => {
    if (state.open && event.key === "Escape") close();
  });

  // Restored from the back/forward cache: always closed.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) close({ restoreFocus: false });
  });

  // The pages' own words for the ≡ - kept so any caller of the old drawers still works.
  window.toggleMenu = () => (state.open && state.view === "menu" ? close() : open("menu"));
  window.closeSidePanel = () => close();
  window.openNavDrawer = () => open("menu");
  window.closeNavDrawer = () => close();

  const viewerName = root.dataset.viewerName || "";
  openers().forEach((el) => {
    el.setAttribute("aria-controls", "minty-sidebar-panel");
    el.setAttribute("aria-expanded", "false");
    if (el.getAttribute("data-sidebar-open") === "profile" && viewerName) {
      el.setAttribute("aria-label", `${viewerName}, My Profile`);
    }
  });

  // --- the reads: a bearer token from this app, then the same routes minty-web calls ---------

  class ReadError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  let token = null; // { value, expiresAt }

  async function bearer(force) {
    if (!force && token && Date.now() < token.expiresAt - 60000) return token.value;
    const res = await fetch(root.dataset.tokenUrl, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
    });
    if (res.status === 401) throw new ReadError(401, SESSION_ENDED);
    const body = await readBody(res);
    if (!res.ok || !body || typeof body.token !== "string") {
      throw new ReadError(res.status, sentence(body) || HOUSE_FALLBACK);
    }
    token = { value: body.token, expiresAt: Date.now() + Number(body.valid_for_seconds || 0) * 1000 };
    return token.value;
  }

  async function readBody(res) {
    const text = await res.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch (_) {
      return null;
    }
  }

  function sentence(body) {
    return body && typeof body.error === "string" ? body.error : null;
  }

  /**
   * A bearer call without this app's cookie (as minty-web's cross-origin calls are): one fresh
   * token on a 401, then the 401 stands. Resolves the parsed JSON; rejects with a ReadError
   * carrying the answer's sentence.
   */
  async function call(url, init = {}, retried = false) {
    const value = await bearer(retried);
    const headers = Object.assign({ Accept: "application/json", Authorization: `Bearer ${value}` }, init.headers || {});
    const res = await fetch(url, Object.assign({}, init, { headers, credentials: "omit", cache: "no-store" }));
    if (res.status === 401 && !retried) return call(url, init, true);
    const body = await readBody(res);
    if (res.status === 401) throw new ReadError(401, SESSION_ENDED);
    if (!res.ok) throw new ReadError(res.status, sentence(body) || HOUSE_FALLBACK);
    return body;
  }

  // --- My Profile (features/profile: useProfile, ProfileParts, DetailsCard) -------------------

  const Profile = (() => {
    const pane = views.profile;
    const $ = (selector) => pane.querySelector(selector);
    const entityId = root.dataset.entityId || "";
    const profileUrl = root.dataset.profileUrl + (entityId ? `?entity=${encodeURIComponent(entityId)}` : "");
    const form = $("[data-profile-form]");
    const editButton = $("[data-profile-edit]");
    const saveButton = $("[data-profile-save]");
    const saveError = $("[data-profile-save-error]");
    const FIELDS = ["first_name", "last_name", "email"];
    let generation = 0;
    let profile = null;
    let editing = false;
    let saving = false;

    function setState(name, message) {
      pane.querySelectorAll("[data-profile-state]").forEach((el) => {
        el.hidden = el.getAttribute("data-profile-state") !== name;
      });
      if (name === "error") $("[data-profile-error]").textContent = message || LOAD_FAILED;
    }

    /** The line under the company: SuperMinty (both, with the caped cat), else the one module. */
    function planLabel(company) {
      if (!company) return null;
      const modules = company.modules || [];
      const petty = modules.includes("PETTY_CASH");
      const payments = modules.includes("PAYMENT_REQUEST");
      if (petty && payments) return { text: "SuperMinty", key: "superminty", cat: true };
      if (payments) return { text: "Payment Request", key: "payments", cat: false };
      if (petty) return { text: "Petty Cash", key: "petty", cat: false };
      return null;
    }

    function render() {
      const company = profile.entity;
      const plan = planLabel(company);
      const companyBlock = $("[data-profile-company]");
      companyBlock.hidden = !company;
      companyBlock.toggleAttribute("data-cat", Boolean(plan && plan.cat));
      $("[data-profile-company-name]").textContent = company ? company.name : "";
      const planLine = $("[data-profile-plan]");
      planLine.hidden = !plan;
      planLine.textContent = plan ? plan.text : "";
      planLine.setAttribute("data-plan", plan ? plan.key : "");
      $("[data-profile-plan-cat]").hidden = !(plan && plan.cat);
      $("[data-profile-initials]").textContent = profile.user.initials;
      $("[data-profile-name]").textContent = profile.user.name;
      const role = $("[data-profile-role]");
      role.hidden = !(company && company.role_label);
      role.textContent = company && company.role_label ? company.role_label : "";
      FIELDS.forEach((field) => {
        $(`[data-profile-value="${field}"]`).textContent = profile.user[field] || "";
      });
      paintEditing();
    }

    function paintEditing() {
      FIELDS.forEach((field) => {
        $(`[data-profile-value="${field}"]`).hidden = editing;
        $(`[data-profile-field="${field}"]`).hidden = !editing;
      });
      // the email's line keeps its hidden "Email " label with the value
      $('[data-profile-value="email"]').parentElement.hidden = editing;
      $('[data-profile-value="email"]').hidden = false;
      $("[data-profile-editing]").hidden = !editing;
      editButton.textContent = editing ? "Cancel" : "Edit";
      editButton.disabled = saving;
      saveButton.disabled = saving;
      saveButton.textContent = saving ? "Saving…" : "Save";
    }

    function showSaveError(message) {
      saveError.hidden = !message;
      saveError.textContent = message || "";
    }

    function startEditing() {
      if (!profile) return;
      FIELDS.forEach((field) => {
        $(`[data-profile-field="${field}"]`).value = profile.user[field] || "";
      });
      editing = true;
      showSaveError(null);
      paintEditing();
    }

    function stopEditing() {
      editing = false;
      showSaveError(null);
      paintEditing();
    }

    /** Only what changed is sent; an emptied email is refused here (profileView.changesFrom). */
    function changesFrom() {
      const draft = {};
      FIELDS.forEach((field) => {
        draft[field] = $(`[data-profile-field="${field}"]`).value;
      });
      if (!draft.email.trim()) return { changes: {}, error: EMAIL_REQUIRED };
      const changes = {};
      FIELDS.forEach((field) => {
        if (draft[field].trim() !== (profile.user[field] || "")) changes[field] = draft[field];
      });
      return { changes, error: null };
    }

    /** After a save: every badge and the menu's name show the new person at once (primeViewer). */
    function primeViewer(user) {
      root.dataset.viewerName = user.name;
      root.querySelectorAll("[data-viewer-initials]").forEach((el) => (el.textContent = user.initials));
      root.querySelectorAll("[data-viewer-name]").forEach((el) => (el.textContent = user.name));
      const person = root.querySelector(".msb-person");
      if (person) person.setAttribute("aria-label", `${user.name}, My Profile`);
      document.querySelectorAll('[data-sidebar-open="profile"]').forEach((el) => {
        const letters = el.querySelector("span") || el;
        letters.textContent = user.initials;
        el.setAttribute("title", user.name);
        el.setAttribute("aria-label", `${user.name}, My Profile`);
      });
    }

    async function save() {
      if (!profile || !editing || saving) return;
      const { changes, error } = changesFrom();
      if (error) {
        showSaveError(error);
        return;
      }
      if (Object.keys(changes).length === 0) {
        stopEditing();
        return;
      }
      saving = true;
      showSaveError(null);
      paintEditing();
      const mine = generation;
      try {
        const fresh = await call(profileUrl, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(changes),
        });
        if (mine !== generation) return;
        profile = fresh;
        editing = false;
        render();
        primeViewer(fresh.user);
        if (typeof window.showSuccessToast === "function") window.showSuccessToast(SAVED);
      } catch (err) {
        if (mine !== generation) return;
        console.error("[sidebar] profile save failed", err);
        showSaveError(err instanceof ReadError ? err.message : SAVE_FAILED);
      } finally {
        if (mine === generation) {
          saving = false;
          paintEditing();
        }
      }
    }

    async function load() {
      const mine = ++generation;
      profile = null;
      editing = false;
      saving = false;
      showSaveError(null);
      setState("loading");
      Subs.unmount();
      try {
        const body = await call(profileUrl);
        if (mine !== generation) return;
        if (!body || !body.user) throw new ReadError(502, LOAD_FAILED);
        profile = body;
        render();
        setState("ready");
        Subs.mount();
      } catch (err) {
        if (mine !== generation) return;
        console.error("[sidebar] profile read failed", err);
        setState("error", err instanceof ReadError ? err.message : LOAD_FAILED);
      }
    }

    editButton.addEventListener("click", () => (editing ? stopEditing() : startEditing()));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      save();
    });
    $("[data-profile-retry]").addEventListener("click", () => load());

    return {
      mount: load,
      unmount() {
        generation += 1; // an answer still on its way is for a view no longer shown
        profile = null;
        editing = false;
        saving = false;
        Subs.unmount();
      },
    };
  })();

  // --- Subscriptions Overview (features/subscription SubscriptionsOverviewCard) ---------------

  const Subs = (() => {
    // Not drawn at all while subscriptions are dark (the template leaves it out).
    const section = views.profile.querySelector("[data-subs]");
    if (!section) return { mount() {}, unmount() {} };
    const $ = (selector) => section.querySelector(selector);
    const base = (root.dataset.billingApi || "").replace(/\/+$/, "");
    let generation = 0;

    function setState(name) {
      section.querySelectorAll("[data-subs-state]").forEach((el) => {
        el.hidden = el.getAttribute("data-subs-state") !== name;
      });
    }

    /** An ISO day, or any date Date.parse reads (the portal's RFC 822), as a UTC midnight. */
    function utcDay(value) {
      if (!value) return null;
      const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
      if (m) return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
      const parsed = Date.parse(value);
      if (Number.isNaN(parsed)) return null;
      const d = new Date(parsed);
      return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
    }

    function daysUntil(value, today) {
      const day = utcDay(value);
      const from = utcDay(today.toISOString());
      if (day === null || from === null) return null;
      return Math.round((day - from) / 86400000);
    }

    /** 08-A's two figures (billing.ts overview): companies paid for, companies with a trial ending. */
    function overview(entities, today) {
      let active = 0;
      let trialEnding = 0;
      entities.forEach((entity) => {
        const modules = entity.modules || [];
        if (modules.some((m) => m.status === "active" || m.status === "cancelled")) active += 1;
        const ending = modules.some((m) => {
          if (m.status !== "trialing") return false;
          const left = daysUntil(m.date_iso, today);
          return left !== null && left <= TRIAL_ENDING_DAYS;
        });
        if (ending) trialEnding += 1;
      });
      return { active, trialEnding };
    }

    const entityUnit = (n) => (n === 1 ? "entity" : "entities");

    async function page(n) {
      const data = await call(`${base}/api/me/subscriptions?page=${n}&per_page=${MAX_PER_PAGE}`);
      if (!data || !Array.isArray(data.entities)) throw new ReadError(502, HOUSE_FALLBACK);
      return data;
    }

    async function load() {
      const mine = ++generation;
      section.hidden = false;
      setState("loading");
      try {
        const first = await page(1);
        const entities = first.entities.slice();
        for (let n = 2; n <= Number(first.pages || 1); n += 1) {
          const next = await page(n);
          entities.push(...next.entities);
        }
        if (mine !== generation) return;
        if (entities.length === 0) {
          setState("empty");
          return;
        }
        const figures = overview(entities, new Date());
        $("[data-subs-active]").textContent = String(figures.active);
        $("[data-subs-active-unit]").textContent = entityUnit(figures.active);
        $("[data-subs-trial]").textContent = String(figures.trialEnding);
        $("[data-subs-trial-unit]").textContent = entityUnit(figures.trialEnding);
        setState("ready");
      } catch (err) {
        if (mine !== generation) return;
        // A 404 is the feature dark at the API: then the card is not there at all.
        if (err instanceof ReadError && err.status === 404) {
          section.hidden = true;
          return;
        }
        console.error("[sidebar] subscriptions read failed", err);
        setState("error");
      }
    }

    $("[data-subs-retry]").addEventListener("click", () => load());

    return {
      mount() {
        if (base) load();
        else section.hidden = true;
      },
      unmount() {
        generation += 1;
        section.hidden = true;
      },
    };
  })();
})();
