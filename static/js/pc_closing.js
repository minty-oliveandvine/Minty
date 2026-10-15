/**
 * The Daily Closing stages' shared behaviour (templates/petty_cash/closing_base.html).
 *
 * The stage form is <form data-pc-stage-form> with a hidden <input name="action_type">; its
 * buttons are [data-pc-save="save_next"] (Primary) and [data-pc-save="save_exit"] (Link).
 *
 * - Save & Next checks every rule, "still empty" included (pc_validate.js); Save & Exit only the
 *   format rules - it is never refused for a missing field (CLAUDE.md);
 * - a stage adds its own rules across fields with window.PcStage.check(action) -> [{control,
 *   message}], and may take over the save with PcStage.submit(action, button, form);
 * - money inputs are sent without their thousands separators;
 * - moving to another stage with unsaved changes is refused with a message (as the old stepper did);
 * - the clicked button shows its processing state ("Saving…") and the form cannot be sent twice;
 * - a page restored from the back/forward cache reloads, so it never shows a stale stage.
 */
(function () {
  "use strict";

  const form = document.querySelector("form[data-pc-stage-form]");
  if (!form) return;
  PcValidate.attach(form);

  function serialise() {
    const parts = [];
    new FormData(form).forEach((value, key) => {
      if (key === "csrf_token" || key === "action_type") return;
      parts.push(key + "=" + (typeof value === "string" ? value.replace(/,/g, "") : value.name));
    });
    return parts.join("&");
  }
  let initial = serialise();
  window.addEventListener("load", () => {
    initial = serialise(); // after currency.js has grouped the server's values
  });

  function hasChanges() {
    return serialise() !== initial;
  }

  document.addEventListener("click", function (event) {
    const step = event.target.closest(".pc-steps a");
    if (step && hasChanges()) {
      event.preventDefault();
      showWarningToast("Your changes on this stage aren't saved yet. Save them first, then move to another stage.");
    }
  });

  function cleanMoney() {
    form.querySelectorAll('input[inputmode="decimal"]').forEach((input) => {
      input.value = input.value.replace(/,/g, "").trim();
      if (input.value === "" && input.hasAttribute("data-pc-empty-zero")) input.value = "0";
    });
  }

  let sending = false;

  function save(action, button) {
    if (sending) return;
    const stage = window.PcStage || {};
    const extra = typeof stage.check === "function" ? stage.check(action) || [] : [];
    if (!PcValidate.check(form, { required: action === "save_next" }, extra)) return;
    sending = true;
    const restore = PcOverlay.busy(button, (button && button.dataset.pcBusy) || "Saving…");
    const done = function () {
      sending = false;
      restore();
    };
    form.elements.action_type.value = action;
    if (typeof stage.submit === "function") {
      Promise.resolve(stage.submit(action, button, form)).catch(function (error) {
        if (window.sendLogToDataDog) window.sendLogToDataDog("error", "Stage save failed", { message: error && error.message });
        showErrorToast("This stage could not be saved. Check your connection and try again.");
      }).finally(done);
      return;
    }
    cleanMoney();
    initial = serialise(); // leaving on purpose: no unsaved-changes warning
    form.submit();
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const button = event.submitter && event.submitter.matches("[data-pc-save]") ? event.submitter : form.querySelector('[data-pc-save="save_next"]');
    save(button ? button.getAttribute("data-pc-save") : "save_next", button);
  });
  form.querySelectorAll('[data-pc-save="save_exit"]').forEach((button) => {
    button.addEventListener("click", () => save("save_exit", button));
  });

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) window.location.reload();
  });

  window.PcClosing = { hasChanges: hasChanges, resetChanges: () => (initial = serialise()), cleanMoney: cleanMoney, form: form };
})();
