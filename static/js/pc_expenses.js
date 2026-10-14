/**
 * The Expenses stage (templates/report/expense.html; Part 15.15c, 15.13 receipts).
 *
 * One entry at a time, in the Drawer #expenseDrawer:
 *   add          a draft's new entry: receipt required -> POST /report/expense/add
 *   edit         a draft's entry: a new receipt replaces the kept one -> POST /report/expense/update/<id>
 *   report edit  a SUBMITTED report's entry (?report_edit=true): the amount stays locked
 *                -> POST /report/expense/edit/<id>
 *   view         a submitted report's entry, read-only
 * Delete asks first (#deleteExpenseModal) -> DELETE /report/expense/delete/<id>.
 *
 * Every save goes to the server at once and the page reloads from it, so the list and the total
 * are always the server's (nothing is kept in the browser between visits). The supplier and
 * account pickers are comboboxes over the company's Xero contacts and accounts; a supplier the
 * list lacks is added to Xero (POST /entity/contact/create). Suggestions from a receipt
 * (static/js/expense_ai.js, EXPENSE_AI_ENABLED only) land in the same fields through
 * window.selectContact / selectAccount / showNewContactSection.
 */
(function () {
  "use strict";

  const CFG = window.PC_EXPENSES;
  const MAX_BYTES = 10 * 1024 * 1024;
  const TYPES = /\.(pdf|jpe?g|png)$/i;
  const stageForm = document.getElementById("expense-form");
  const csrf = stageForm.elements.csrf_token.value;
  const form = document.getElementById("addExpenseForm");
  const drawerTitle = document.getElementById("expenseDrawer-title");
  const drawerDesc = document.querySelector("#expenseDrawer .pc-drawer__desc");
  const saveBtn = document.getElementById("saveExpenseBtn");
  const amount = document.getElementById("expense_amount");
  const contact = document.getElementById("expense_contact");
  const account = document.getElementById("expense_account_code");
  const remarks = document.getElementById("expense_remarks");
  const fileInput = document.getElementById("expense_files");
  const cameraInput = document.getElementById("expense_camera");
  const errorSlot = document.getElementById("expenseFormError");
  const readOnly = document.getElementById("expenseReadOnly");

  let mode = "add"; // add | edit | report_edit | view
  let editingId = null;
  let deleting = null;
  let pendingFile = null;
  let initialState = "";

  // ------------------------------------------------------------------ helpers

  function money(value) {
    return CFG.code + " " + Currency.formatMoney(value);
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon(name) {
    const span = el("span", "pc-icon", name);
    span.setAttribute("aria-hidden", "true");
    return span;
  }

  function showFormError(message) {
    errorSlot.replaceChildren();
    const box = el("div", "pc-alert pc-alert--danger");
    box.setAttribute("role", "alert");
    box.append(icon("error"), el("p", "pc-alert__body", message));
    errorSlot.appendChild(box);
    errorSlot.hidden = false;
    errorSlot.scrollIntoView({ block: "nearest" });
  }

  function reloadWith(message) {
    sessionStorage.setItem("pcFlashSuccess", message);
    window.location.reload();
  }

  async function send(url, init, fallback) {
    const response = await fetch(url, init);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status !== "success") {
      throw Object.assign(new Error(data.message || fallback), { shown: Boolean(data.message) });
    }
    return data;
  }

  // ---------------------------------------------------------------- comboboxes

  /**
   * A list-only combobox (Part 14 Select with search): typing filters, arrows move, Enter picks,
   * Escape closes the list (never the drawer). `extra(query, exact)` may add a last option.
   */
  function combobox(input, list, options, onPick, extra) {
    let active = -1;
    let shown = [];
    const state = { id: null, label: null };

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    }

    function render(query) {
      const q = (query || "").trim().toLowerCase();
      shown = options().filter((o) => !q || o.label.toLowerCase().includes(q) || (o.sub || "").toLowerCase().includes(q));
      const exact = shown.some((o) => o.label.toLowerCase() === q);
      const more = extra ? extra(query.trim(), exact) : null;
      list.replaceChildren();
      shown.slice(0, 50).forEach((o, i) => {
        const item = el("li", "pc-option");
        item.id = list.id + "-" + i;
        item.setAttribute("role", "option");
        item.append(el("span", "", o.label));
        if (o.sub) item.append(el("span", "pc-option__sub", o.sub));
        item.addEventListener("mousedown", (e) => {
          e.preventDefault();
          pick(o);
        });
        list.appendChild(item);
      });
      if (more) {
        const item = el("li", "pc-option pc-option--action");
        item.id = list.id + "-more";
        item.setAttribute("role", "option");
        item.append(icon("add"), el("span", "", more.label));
        item.addEventListener("mousedown", (e) => {
          e.preventDefault();
          close();
          more.run();
        });
        list.appendChild(item);
      }
      if (!list.children.length) list.appendChild(el("li", "pc-option pc-option--empty", "Nothing matches. Try another name."));
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      active = -1;
    }

    function move(step) {
      const items = Array.from(list.querySelectorAll('[role="option"]'));
      if (!items.length) return;
      active = (active + step + items.length) % items.length;
      items.forEach((item, i) => item.setAttribute("aria-selected", String(i === active)));
      input.setAttribute("aria-activedescendant", items[active].id);
      items[active].scrollIntoView({ block: "nearest" });
    }

    function pick(o) {
      state.id = o.id;
      state.label = o.label;
      input.value = o.label;
      close();
      PcValidate.refresh(input, true);
      onPick(o);
    }

    input.addEventListener("focus", () => render(state.id ? "" : input.value));
    input.addEventListener("click", () => render(state.id ? "" : input.value));
    input.addEventListener("input", () => {
      if (state.label !== input.value) {
        state.id = null;
        state.label = null;
      }
      render(input.value);
    });
    input.addEventListener("blur", () => setTimeout(close, 120));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (list.hidden) render(input.value);
        move(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        move(-1);
      } else if (e.key === "Enter" && !list.hidden && active >= 0) {
        e.preventDefault();
        list.querySelectorAll('[role="option"]')[active].dispatchEvent(new MouseEvent("mousedown"));
      } else if (e.key === "Escape" && !list.hidden) {
        e.preventDefault();
        e.stopPropagation(); // the list closes; the drawer stays
        close();
      }
    });

    return {
      state: state,
      set(id, label) {
        state.id = id || null;
        state.label = id ? label : null;
        input.value = label || "";
      },
      clear() {
        state.id = null;
        state.label = null;
        input.value = "";
        close();
      },
    };
  }

  const contacts = (CFG.contacts || []).map((c) => ({ id: c.ContactID, label: c.Name }));
  const accounts = (CFG.accounts || []).map((a) => ({
    id: a.AccountID,
    label: a.Code ? a.Code + " — " + a.Name : a.Name,
    name: a.Name,
    code: a.Code || "",
    itemCode: a.ItemCode || "",
  }));
  const accountById = (id) => accounts.find((a) => a.id === id) || null;

  const contactBox = combobox(contact, document.getElementById("expenseContactSuggestions"), () => contacts, () => {}, (query, exact) =>
    query && !exact ? { label: 'Add "' + query + '" as a new supplier', run: () => showNewContactSection(query) } : null
  );
  const accountBox = combobox(account, document.getElementById("expenseAccountSuggestions"), () => accounts, () => {});

  // A typed name that was never picked is "not finished yet" until the field is left.
  PcValidate.rule(contact, () => (contactBox.state.id ? "" : { message: "Choose a supplier from the list, or add a new one.", unfinished: true }));
  PcValidate.rule(account, () => (accountBox.state.id ? "" : { message: "Choose an account from the list.", unfinished: true }));

  // The hooks expense_ai.js calls to fill a suggestion in.
  window.selectContact = function (id, name) {
    contactBox.set(id, name);
    PcValidate.refresh(contact, true);
  };
  window.selectAccount = function (id) {
    const a = accountById(id);
    accountBox.set(id, a ? a.label : "");
    PcValidate.refresh(account, true);
  };

  // ------------------------------------------------------------- new supplier

  const newSection = document.getElementById("newContactSection");
  const newName = document.getElementById("newContactName");

  function showNewContactSection(name) {
    newSection.hidden = false;
    newName.value = name || "";
    newName.focus();
  }
  window.showNewContactSection = showNewContactSection;

  document.getElementById("cancelNewContact").addEventListener("click", () => {
    newSection.hidden = true;
    PcValidate.clear(newName);
    contact.focus();
  });

  document.getElementById("createContactBtn").addEventListener("click", async function () {
    const name = newName.value.trim();
    if (!name) {
      PcValidate.show(newName, "The supplier's name is still empty. Add it to continue.");
      newName.focus();
      return;
    }
    const restore = PcOverlay.busy(this, "Adding…");
    const body = new FormData();
    body.append("name", name);
    body.append("entity_id", CFG.entityId);
    body.append("csrf_token", csrf);
    try {
      const data = await send(
        "/entity/contact/create",
        { method: "POST", headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf }, body: body },
        "The supplier could not be added. Try again in a moment."
      );
      const id = data.contact_id;
      const label = data.name || name;
      contacts.push({ id: id, label: label });
      contactBox.set(id, label);
      newSection.hidden = true;
      PcValidate.refresh(contact, true);
      showSuccessToast(label + " is added to your suppliers.");
    } catch (error) {
      PcValidate.show(newName, error.shown ? error.message : "The supplier could not be added. Check your connection and try again.");
    } finally {
      restore();
    }
  });

  // ------------------------------------------------------------------ receipts

  const newReceipts = document.getElementById("newReceipts");
  const existingReceipts = document.getElementById("existingReceipts");

  function sizeText(bytes) {
    return bytes >= 1024 * 1024 ? (bytes / 1024 / 1024).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function fileCard(name, meta, actions) {
    const card = el("div", "pc-filecard");
    card.append(icon(/\.pdf$/i.test(name) ? "picture_as_pdf" : "image"));
    const text = el("div", "");
    text.style.minWidth = "0";
    text.style.flex = "1";
    const title = el("p", "pc-filecard__name pc-t-body-m", name);
    text.append(title);
    if (meta) text.append(el("p", "pc-filecard__meta", meta));
    card.append(text);
    actions.forEach((a) => card.append(a));
    return card;
  }

  function actionButton(label, handler, attrs) {
    const button = el("button", "pc-btn pc-btn--ghost pc-btn--compact", label);
    button.type = "button";
    Object.entries(attrs || {}).forEach(([k, v]) => button.setAttribute(k, v));
    if (handler) button.addEventListener("click", handler);
    return button;
  }

  function drawPending() {
    newReceipts.replaceChildren();
    if (!pendingFile) return;
    const view = actionButton("View", () => {
      const url = URL.createObjectURL(pendingFile);
      openReceiptViewer(url, window.ReceiptPreview ? ReceiptPreview.kind(pendingFile.name) : "", pendingFile.name);
    });
    const remove = actionButton("Remove", () => {
      pendingFile = null;
      fileInput.value = "";
      cameraInput.value = "";
      drawPending();
      if (window.mintyAi) window.mintyAi.cancel();
      fileInput.focus();
    });
    remove.setAttribute("aria-label", "Remove " + pendingFile.name);
    newReceipts.append(fileCard(pendingFile.name, sizeText(pendingFile.size) + (mode === "add" ? "" : " · replaces the receipt kept"), [view, remove]));
  }

  function takeFile(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    if (file.size > MAX_BYTES) {
      PcValidate.show(fileInput, "That file is " + sizeText(file.size) + ". Files up to 10 MB. Add a smaller one.");
      input.value = "";
      return;
    }
    if (!TYPES.test(file.name) && !/^image\/(jpeg|png)$|^application\/pdf$/.test(file.type)) {
      PcValidate.show(fileInput, "That file type can't be used. Add a PDF, JPG or PNG.");
      input.value = "";
      return;
    }
    PcValidate.clear(fileInput);
    pendingFile = file;
    drawPending();
    if (window.mintyAi) window.mintyAi.onFilesAttached([file]);
  }
  fileInput.addEventListener("change", () => takeFile(fileInput));
  cameraInput.addEventListener("change", () => takeFile(cameraInput));

  function drawExisting(files) {
    existingReceipts.replaceChildren();
    files.forEach((f) => {
      const view = actionButton("View", null, { "data-receipt-key": f.s3_key, "data-receipt-name": f.display_name });
      view.setAttribute("aria-label", "View " + f.display_name);
      existingReceipts.append(fileCard(f.display_name, null, [view]));
    });
  }

  function parseFiles(raw) {
    try {
      const parsed = JSON.parse(raw || "[]");
      return (Array.isArray(parsed) ? parsed : [parsed])
        .map((e) => (typeof e === "string" ? { s3_key: e, display_name: e.split("/").pop() } : e && { s3_key: e.s3_key || e.file_path || e.path || "", display_name: e.display_name || e.original_filename || e.name || "" }))
        .filter((e) => e && e.s3_key)
        .map((e) => ({ s3_key: e.s3_key, display_name: e.display_name || e.s3_key.split("/").pop() }));
    } catch (e) {
      return [];
    }
  }

  // ------------------------------------------------------------------- drawer

  function snapshot() {
    return [amount.value, contactBox.state.id, accountBox.state.id, remarks.value, pendingFile ? pendingFile.name : ""].join("|");
  }

  function setMode(next, row) {
    mode = next;
    editingId = row ? row.dataset.expenseId : null;
    pendingFile = null;
    fileInput.value = "";
    cameraInput.value = "";
    newSection.hidden = true;
    errorSlot.hidden = true;
    delete form.dataset.pcRefused;
    [amount, contact, account, remarks, fileInput, newName].forEach((c) => PcValidate.clear(c));
    const summary = form.querySelector("[data-pc-summary]");
    summary.hidden = true;

    // The entry's own fields - not the New supplier box, which opens only on request.
    const fields = Array.from(form.querySelectorAll(".pc-field")).filter((f) => !newSection.contains(f));
    const required = form.querySelectorAll("[data-pc-receipt-required]");
    readOnly.hidden = true;
    fields.forEach((f) => (f.hidden = false));
    saveBtn.hidden = false;
    amount.readOnly = false;

    if (row) {
      amount.value = Currency.group(String(row.dataset.expenseAmount || ""));
      contactBox.set(row.dataset.expenseContactId, row.dataset.expenseContactName);
      const a = accountById(row.dataset.expenseAccountId);
      accountBox.set(row.dataset.expenseAccountId, a ? a.label : row.dataset.expenseItem);
      remarks.value = row.dataset.expenseDescription || "";
      drawExisting(parseFiles(row.dataset.expenseFiles));
    } else {
      amount.value = "";
      contactBox.clear();
      accountBox.clear();
      remarks.value = "";
      drawExisting([]);
    }
    drawPending();
    required.forEach((r) => (r.hidden = next !== "add"));

    if (next === "add") {
      drawerTitle.textContent = "Add expense";
      drawerDesc.textContent = "Attach the receipt, then the amount, supplier and account.";
      saveBtn.textContent = "Add expense";
    } else if (next === "edit") {
      drawerTitle.textContent = "Edit expense";
      drawerDesc.textContent = "A new receipt replaces the one kept.";
      saveBtn.textContent = "Save changes";
    } else if (next === "report_edit") {
      drawerTitle.textContent = "Edit expense";
      drawerDesc.textContent = "The report is submitted, so the amount stays as it is.";
      saveBtn.textContent = "Save changes";
      amount.readOnly = true;
    } else {
      drawerTitle.textContent = "Expense";
      drawerDesc.textContent = "This report is submitted.";
      fields.forEach((f) => {
        if (!f.contains(existingReceipts)) f.hidden = true;
      });
      document.getElementById("uploadArea").hidden = true;
      document.querySelector(".pc-camera").hidden = true;
      saveBtn.hidden = true;
      readOnly.replaceChildren(readOnlyRows(row));
      readOnly.hidden = false;
    }
    if (next !== "view") {
      document.getElementById("uploadArea").hidden = false;
      document.querySelector(".pc-camera").hidden = false;
    }
    initialState = snapshot();
  }

  function readOnlyRows(row) {
    const dl = el("dl", "pc-dl");
    [
      ["Amount", money(parseFloat(row.dataset.expenseAmount) || 0)],
      ["Supplier", row.dataset.expenseContactName],
      ["Account", row.dataset.expenseItem],
      ["Description", row.dataset.expenseDescription],
    ].forEach(([term, value]) => {
      const div = el("div");
      div.append(el("dt", "", term));
      const dd = el("dd", value ? "" : "pc-dl__empty", value || "Not set yet");
      div.append(dd);
      dl.append(div);
    });
    return dl;
  }

  function open(next, row, opener) {
    setMode(next, row);
    PcOverlay.open("expenseDrawer", {
      opener: opener,
      initialFocus: next === "view" ? ".pc-close" : next === "report_edit" ? "#expense_contact" : "#expense_files",
      onRequestClose: confirmDiscard,
    });
  }

  // Closing with typed input asks first (Part 14 Drawer: Escape never discards silently).
  let discardAsked = false;
  function confirmDiscard() {
    if (discardAsked || mode === "view" || snapshot() === initialState) return true;
    PcOverlay.open("discardExpenseModal");
    return false;
  }
  const discard = document.getElementById("discardExpenseModal");
  if (discard) {
    document.getElementById("confirmDiscardExpense").addEventListener("click", () => {
      PcOverlay.close("discardExpenseModal");
      discardAsked = true;
      PcOverlay.close("expenseDrawer");
      discardAsked = false;
      if (window.mintyAi) window.mintyAi.cancel();
    });
  }

  document.addEventListener("click", (event) => {
    const add = event.target.closest("[data-pc-add-expense]");
    if (add) {
      open("add", null, add);
      return;
    }
    const opener = event.target.closest("[data-pc-open-expense]");
    if (opener) {
      const row = opener.closest("[data-expense-id]");
      open(CFG.canChange ? "edit" : CFG.reportEdit ? "report_edit" : "view", row, opener);
      return;
    }
    const remove = event.target.closest("[data-pc-delete-expense]");
    if (remove) {
      deleting = remove.closest("[data-expense-id]").dataset.expenseId;
      PcOverlay.open("deleteExpenseModal", { opener: remove });
    }
  });

  // -------------------------------------------------------------------- saving

  function payload() {
    const body = new FormData();
    const a = accountById(accountBox.state.id);
    body.append("csrf_token", csrf);
    body.append("entity_id", CFG.entityId);
    if (CFG.transactionDate) body.append("transaction_date", CFG.transactionDate);
    body.append("item", a ? a.name : "");
    body.append("amount", amount.value.replace(/,/g, ""));
    body.append("remarks", remarks.value.trim());
    body.append("contactId", contactBox.state.id || "");
    body.append("contactName", contactBox.state.label || "");
    body.append("accountId", accountBox.state.id || "");
    body.append("account_code", a ? a.code : "");
    body.append("item_code", a ? a.itemCode : "");
    if (pendingFile) body.append("files[0][0]", pendingFile);
    return body;
  }

  PcValidate.attach(form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (mode === "view") return;
    const extra = [];
    if (mode === "add" && !pendingFile) {
      extra.push({ control: fileInput, message: "The receipt is still missing. Add a photo or file of it to continue." });
    }
    if (!PcValidate.check(form, { required: true }, extra)) return;
    const restore = PcOverlay.busy(saveBtn, mode === "add" ? "Adding…" : "Saving…");
    errorSlot.hidden = true;
    const headers = { "X-CSRFToken": csrf };
    try {
      if (mode === "add") {
        await send(CFG.addUrl, { method: "POST", headers: headers, body: payload() }, "The expense could not be added.");
        initialState = snapshot();
        reloadWith("The expense is added.");
      } else if (mode === "edit") {
        await send("/report/expense/update/" + encodeURIComponent(editingId), { method: "POST", headers: headers, body: payload() }, "The expense could not be saved.");
        initialState = snapshot();
        reloadWith("The expense is saved.");
      } else {
        const body = payload();
        body.delete("amount"); // never sent: a submitted report's cash stays locked
        await send("/report/expense/edit/" + encodeURIComponent(editingId), { method: "POST", headers: headers, body: body, credentials: "include" }, "The expense could not be saved.");
        initialState = snapshot();
        reloadWith("The expense is saved.");
      }
    } catch (error) {
      restore();
      if (window.sendLogToDataDog) window.sendLogToDataDog("error", "Expense save failed", { mode: mode, message: error && error.message });
      showFormError(error.shown ? error.message : "The expense could not be saved. Check your connection and try again.");
    }
  });

  // ------------------------------------------------------------------- delete

  const confirmDelete = document.getElementById("confirmDeleteExpense");
  if (confirmDelete) {
    confirmDelete.addEventListener("click", async function () {
      if (!deleting) return;
      const restore = PcOverlay.busy(this, "Deleting…");
      try {
        await send(
          "/report/expense/delete/" + encodeURIComponent(deleting),
          { method: "DELETE", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf } },
          "The expense could not be deleted."
        );
        reloadWith("The expense is deleted.");
      } catch (error) {
        restore();
        PcOverlay.close("deleteExpenseModal");
        showErrorToast(error.shown ? error.message : "The expense could not be deleted. Check your connection and try again.");
      }
    });
  }
})();
