/**
 * Validation for the redesigned Petty Cash forms - CLAUDE.md's "Validation while typing" rules,
 * written once (as minty-payment-request-web's Field / ErrorSummary do it):
 *
 * - every field checks its own rules (format, length, range) AS THE USER TYPES, and its message
 *   appears and clears inline at once;
 * - a message that only means "not finished yet" waits until the field is left;
 * - an EMPTY required field is never painted red by typing - only after a refused submit (then it
 *   clears live as it is filled);
 * - a refused submit with one problem moves focus to that field; two or more show the error summary
 *   at the top, which takes focus and links to each field;
 * - Save & Exit / Save as draft skips the "still empty" checks (never disabled for missing fields),
 *   but a malformed value still stops it;
 * - the server re-checks everything: this is a convenience, never the gate.
 *
 * Rules are attributes on the control (the message is Part 11 wording - issue, then action):
 *   data-pc-required="The amount is still empty. Add the amount to continue."
 *   data-pc-amount="…"          a money value: digits, at most 11 whole digits and 2 decimals
 *   data-pc-min="0" data-pc-min-msg="…"     data-pc-max="1000" data-pc-max-msg="…"
 *   data-pc-maxlength="255" data-pc-maxlength-msg="…"
 * and PcValidate.rule(control, fn) adds one: fn(value, control) -> "" | "message" |
 * {message, unfinished: true}.
 *
 *   PcValidate.attach(form)                       wire live checks (once per form)
 *   PcValidate.check(form, {required: true})      -> true when clean; draws the problems
 */
(function () {
  "use strict";

  const custom = new WeakMap();
  const AMOUNT = /^-?\d{0,11}(\.\d{0,2})?$/;

  function plain(value) {
    return String(value == null ? "" : value).replace(/,/g, "").trim();
  }

  function controls(form) {
    return Array.from(
      form.querySelectorAll("[data-pc-required],[data-pc-amount],[data-pc-min],[data-pc-max],[data-pc-maxlength],[data-pc-rule]")
    ).filter((el) => !el.disabled && !el.closest("[hidden]"));
  }

  function isEmpty(control) {
    if (control.type === "checkbox" || control.type === "radio") {
      const group = control.form ? control.form.querySelectorAll('[name="' + control.name + '"]') : [control];
      return !Array.from(group).some((el) => el.checked);
    }
    return plain(control.value) === "";
  }

  /** The control's format problem (not the "still empty" one): {message, unfinished} or null. */
  function formatProblem(control) {
    const raw = control.value;
    if (plain(raw) === "") return null;
    if (control.hasAttribute("data-pc-amount")) {
      const v = plain(raw);
      if (v === "-" || v === "." || !AMOUNT.test(v)) {
        return { message: control.getAttribute("data-pc-amount") || "Enter the amount in numbers, with up to 2 decimals." };
      }
    }
    const number = parseFloat(plain(raw));
    if (control.hasAttribute("data-pc-min") && !isNaN(number) && number < parseFloat(control.getAttribute("data-pc-min"))) {
      return { message: control.getAttribute("data-pc-min-msg") };
    }
    if (control.hasAttribute("data-pc-max") && !isNaN(number) && number > parseFloat(control.getAttribute("data-pc-max"))) {
      return { message: control.getAttribute("data-pc-max-msg") };
    }
    if (control.hasAttribute("data-pc-maxlength") && raw.length > parseInt(control.getAttribute("data-pc-maxlength"), 10)) {
      return { message: control.getAttribute("data-pc-maxlength-msg") };
    }
    const fns = custom.get(control) || [];
    for (const fn of fns) {
      const result = fn(raw, control);
      if (!result) continue;
      return typeof result === "string" ? { message: result } : result;
    }
    return null;
  }

  function noteOf(control) {
    return document.getElementById(control.id + "-note");
  }

  function show(control, message) {
    const note = noteOf(control);
    control.setAttribute("aria-invalid", "true");
    if (note) {
      note.textContent = message;
      note.hidden = false;
      note.classList.add("pc-note--error");
      note.setAttribute("role", "alert");
    }
  }

  function clear(control) {
    const note = noteOf(control);
    control.removeAttribute("aria-invalid");
    if (note) {
      const helper = note.getAttribute("data-pc-helper") || "";
      note.textContent = helper;
      note.hidden = helper === "";
      note.classList.remove("pc-note--error");
      note.removeAttribute("role");
    }
  }

  /** What the control says now. `required` = the form has been refused once (or is being submitted). */
  function problemFor(control, required, leaving) {
    if (required && control.hasAttribute("data-pc-required") && isEmpty(control)) {
      return { message: control.getAttribute("data-pc-required") };
    }
    const problem = formatProblem(control);
    if (problem && problem.unfinished && !leaving) return null;
    return problem;
  }

  function refresh(control, leaving) {
    const form = control.form || control.closest("form") || document;
    const refused = form.dataset && form.dataset.pcRefused === "true";
    const problem = problemFor(control, refused, leaving);
    if (problem) show(control, problem.message);
    else clear(control);
  }

  function attach(form) {
    if (!form || form.dataset.pcAttached) return;
    form.dataset.pcAttached = "true";
    form.addEventListener("input", (e) => {
      if (e.target.matches && controls(form).includes(e.target)) refresh(e.target, false);
    });
    form.addEventListener("change", (e) => {
      if (e.target.matches && controls(form).includes(e.target)) refresh(e.target, true);
    });
    form.addEventListener(
      "blur",
      (e) => {
        if (e.target.matches && controls(form).includes(e.target)) refresh(e.target, true);
      },
      true
    );
  }

  function summaryFor(form) {
    return form.querySelector("[data-pc-summary]") || document.querySelector("[data-pc-summary]");
  }

  function labelText(control) {
    const label = document.querySelector('label[for="' + control.id + '"]');
    if (!label) return "";
    const copy = label.cloneNode(true);
    copy.querySelectorAll(".pc-req, .sr-only").forEach((el) => el.remove());
    return copy.textContent.trim();
  }

  /**
   * Check the whole form. options.required (default true) = include the "still empty" checks.
   * extra = [{control, message}] the page found itself (a rule across fields). Returns true when
   * there is nothing to fix; otherwise draws every problem and moves focus.
   */
  function check(form, options, extra) {
    const required = !options || options.required !== false;
    const problems = [];
    controls(form).forEach((control) => {
      const problem = problemFor(control, required, true);
      if (problem) {
        show(control, problem.message);
        problems.push({ control: control, message: problem.message });
      } else {
        clear(control);
      }
    });
    (extra || []).forEach((p) => {
      if (p.control) show(p.control, p.message);
      problems.push(p);
    });
    const summary = summaryFor(form);
    if (problems.length === 0) {
      if (summary) {
        summary.hidden = true;
        summary.innerHTML = "";
      }
      return true;
    }
    if (required) form.dataset.pcRefused = "true";
    if (problems.length === 1 || !summary) {
      if (summary) summary.hidden = true;
      const target = problems[0].control || summary;
      if (target) target.focus();
      return false;
    }
    summary.innerHTML = "";
    const heading = document.createElement("p");
    heading.className = "pc-strong";
    heading.textContent = problems.length + " details need a look before this can be saved.";
    const list = document.createElement("ul");
    problems.forEach((p) => {
      const item = document.createElement("li");
      if (p.control && p.control.id) {
        const link = document.createElement("a");
        link.href = "#" + p.control.id;
        const name = labelText(p.control);
        link.textContent = name ? name + ": " + p.message : p.message;
        link.addEventListener("click", (e) => {
          e.preventDefault();
          p.control.focus();
        });
        item.appendChild(link);
      } else {
        item.textContent = p.message;
      }
      list.appendChild(item);
    });
    summary.appendChild(heading);
    summary.appendChild(list);
    summary.hidden = false;
    summary.focus();
    return false;
  }

  function rule(control, fn) {
    if (!control) return;
    const list = custom.get(control) || [];
    list.push(fn);
    custom.set(control, list);
    control.setAttribute("data-pc-rule", "");
  }

  window.PcValidate = { attach: attach, check: check, rule: rule, show: show, clear: clear, refresh: refresh };
})();
