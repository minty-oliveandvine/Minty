/**
 * Petty Cash Settings (templates/entity/settings_entity.html): everything the page does but the
 * Xero mapping pickers (partials/xero_mapping_classic_script_fragment.html). One Save Changes
 * saves every card:
 *
 *   1. the mapping check (validateMappingBeforeSave, the fragment's) and the account-code rule
 *      below - both before anything is written;
 *   2. the pending sales-method changes, each through its own API call - any that fails stops
 *      the save and says which, and nothing else is posted;
 *   3. the form: country and currency, the mapping, and the ticked account codes - which a
 *      `formdata` listener adds (sorted, never blank) from the page's own set, so a search that
 *      hides a ticked row, an Enter in a text box or a row never drawn cannot drop one.
 *
 * At least one account code must stay ticked when the company has any: a save with none would
 * switch every code off, and a petty cash expense can only use the codes ticked here. Save is
 * greyed while none is (the hint says why), and the server refuses it too
 * (entity_settings_entity).
 *
 * minty-web's modal design (static/js/minty_dialog.js): "Leave without saving?" guards the page
 * once it has loaded, and deleting a method asks first.
 */
(function () {
  "use strict";

  var form = document.getElementById("entitySettingsForm");
  var config = readConfig();
  if (!form || !config) return;

  var saveButton = document.getElementById("saveChangesBtn");
  var viewOnly = !saveButton || saveButton.hasAttribute("data-view-only");
  var methodsUrl = "/api/entities/" + encodeURIComponent(config.entityId) + "/payment-methods";
  var saving = false;

  function readConfig() {
    var el = document.getElementById("pcs-config");
    if (!el) {
      console.error("[petty cash settings] the page config is missing; the page cannot run");
      return null;
    }
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      console.error("[petty cash settings] the page config does not parse", err);
      return null;
    }
  }

  function toast(message, type) {
    if (typeof window.showFlashMessages === "function") {
      window.showFlashMessages(message, type || "error", type === "success" ? 4000 : 12000);
    } else {
      console.error(message);
    }
  }

  function csrfToken() {
    var el = form.querySelector('input[name="csrf_token"]');
    return el ? el.value : "";
  }

  function clip(text, max) {
    var s = String(text == null ? "" : text);
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // --- collapsible cards ----------------------------------------------------------------------

  function setCardOpen(toggle, open) {
    var body = document.getElementById(toggle.getAttribute("aria-controls"));
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (body) body.hidden = !open;
  }

  /** Open the card a field sits in, so a field the save points at can be seen. */
  function revealCardOf(node) {
    var card = node && node.closest(".pcs-card");
    var toggle = card && card.querySelector("[data-card-toggle]");
    if (toggle && toggle.getAttribute("aria-expanded") === "false") setCardOpen(toggle, true);
  }

  document.querySelectorAll("#pc-settings [data-card-toggle]").forEach(function (toggle) {
    toggle.addEventListener("click", function () {
      setCardOpen(toggle, toggle.getAttribute("aria-expanded") === "false");
    });
  });

  // --- a searchable picker in ThemedSelect's look (country, currency, the method catalogue) ----

  /**
   * options(query) gives the rows to list ({ value, label, ...}); onPick(row) applies one.
   * extras(query) may add trailing rows ({ value, label, info } - info rows are not pickable).
   * label() gives what the box shows when the list closes (the current choice).
   */
  function picker(spec) {
    var input = spec.input;
    var list = spec.list;
    var icon = spec.icon;
    var rows = [];
    var active = -1;
    if (!input || !list) return null;

    function isOpen() {
      return !list.hidden && !list.classList.contains("hidden");
    }

    function setOpen(open) {
      list.hidden = !open;
      list.classList.toggle("hidden", !open);
      input.setAttribute("aria-expanded", open ? "true" : "false");
      if (icon) icon.classList.toggle("rotate-180", open);
    }

    function highlight(index) {
      var items = list.querySelectorAll("[data-index]");
      active = index;
      items.forEach(function (item, i) {
        item.toggleAttribute("data-active", i === index);
        if (i === index && item.scrollIntoView) item.scrollIntoView({ block: "nearest" });
      });
    }

    function render(query) {
      rows = spec.options(query || "");
      var extra = spec.extras ? spec.extras(query || "") : [];
      list.replaceChildren();
      active = -1;
      var pickable = 0;
      rows.concat(extra).forEach(function (row) {
        var item = el("div", "", row.label);
        if (row.info) {
          list.appendChild(item);
          return;
        }
        item.setAttribute("data-index", String(pickable));
        item.setAttribute("data-value", row.value);
        item.setAttribute("role", "option");
        if (spec.isSelected && spec.isSelected(row)) item.setAttribute("aria-selected", "true");
        item.addEventListener("mousedown", function (event) {
          // mousedown, so the box's blur cannot close the list first
          event.preventDefault();
          choose(row);
        });
        list.appendChild(item);
        pickable += 1;
      });
      rows = rows.concat(extra.filter(function (row) { return !row.info; }));
      setOpen(list.childElementCount > 0);
    }

    function choose(row) {
      setOpen(false);
      spec.onPick(row);
    }

    function close() {
      setOpen(false);
      if (spec.label) input.value = spec.label();
    }

    input.addEventListener("focus", function () {
      render("");
    });
    input.addEventListener("click", function () {
      if (!isOpen()) render("");
    });
    input.addEventListener("input", function () {
      if (spec.onType) spec.onType();
      render(input.value.trim());
    });
    input.addEventListener("blur", function () {
      close();
    });
    input.addEventListener("keydown", function (event) {
      if (!isOpen()) return;
      var count = list.querySelectorAll("[data-index]").length;
      if (event.key === "ArrowDown" && count) {
        event.preventDefault();
        highlight((active + 1) % count);
      } else if (event.key === "ArrowUp" && count) {
        event.preventDefault();
        highlight(active <= 0 ? count - 1 : active - 1);
      } else if (event.key === "Enter") {
        if (active >= 0 && rows[active]) {
          event.preventDefault();
          choose(rows[active]);
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });
    return { open: function () { input.focus(); }, close: close, render: render };
  }

  // --- 1. country and currency ----------------------------------------------------------------

  function wireRegistryPicker(inputId, listId, hiddenId, rows, valueKey, labelKey) {
    var input = document.getElementById(inputId);
    var hidden = document.getElementById(hiddenId);
    var all = (Array.isArray(rows) ? rows : []).map(function (row) {
      return { value: String(row[valueKey] == null ? "" : row[valueKey]), label: String(row[labelKey] || "") };
    });
    function current() {
      var value = hidden ? hidden.value : "";
      for (var i = 0; i < all.length; i += 1) if (all[i].value === value) return all[i];
      return null;
    }
    var initial = current();
    picker({
      input: input,
      list: document.getElementById(listId),
      options: function (query) {
        var q = query.toLowerCase();
        var picked = current();
        // Opened on the current choice: the whole list; typing filters it.
        if (!q || (picked && picked.label.toLowerCase() === q)) return all;
        return all.filter(function (row) { return row.label.toLowerCase().indexOf(q) !== -1; });
      },
      extras: function (query) {
        return query && !all.some(function (row) { return row.label.toLowerCase().indexOf(query.toLowerCase()) !== -1; })
          ? [{ info: true, label: "No matches" }]
          : [];
      },
      isSelected: function (row) {
        return Boolean(hidden) && row.value === hidden.value;
      },
      onPick: function (row) {
        if (hidden) hidden.value = row.value;
        input.value = row.label;
      },
      label: function () {
        var picked = current();
        return picked ? picked.label : initial ? initial.label : "";
      },
    });
  }

  if (!viewOnly) {
    wireRegistryPicker("ci_country_display", "ci_country_suggestions", "ci_country_code_hidden",
      config.countries, "country_code", "country_name");
    wireRegistryPicker("ci_currency_display", "ci_currency_suggestions", "ci_currency_id_hidden",
      config.currencies, "currency_id", "currency_name");
  }

  // --- 4. account codes: Payment Settings' checklist --------------------------------------------

  var codes = (Array.isArray(config.codes) ? config.codes : [])
    .map(function (row) {
      return { code: String(row.code == null ? "" : row.code).trim(), name: String(row.name || "").trim(), selected: Boolean(row.selected) };
    })
    // A row without a code can never be saved (the save keys on the code), so it is not offered.
    .filter(function (row) { return row.code !== ""; })
    .map(function (row) {
      row.label = row.name ? row.code + " - " + row.name : row.code;
      return row;
    });
  var ticked = new Set(codes.filter(function (row) { return row.selected; }).map(function (row) { return row.code; }));
  var hasCodes = codes.length > 0;
  var codesEditable = Boolean(config.canEditCodes) && !viewOnly;
  var codeList = document.getElementById("accountCodeList");
  var codeSearch = document.getElementById("accountCodeInput");

  function tickedCodes() {
    return Array.from(ticked).filter(function (code) { return code !== ""; }).sort();
  }

  function shownCodes() {
    var q = codeSearch ? codeSearch.value.trim().toLowerCase() : "";
    if (!q) return codes;
    return codes.filter(function (row) { return row.label.toLowerCase().indexOf(q) !== -1; });
  }

  function selectAllRow(rows) {
    var all = rows.length > 0 && rows.every(function (row) { return ticked.has(row.code); });
    var some = !all && rows.some(function (row) { return ticked.has(row.code); });
    var li = el("li", "pcs-select-all");
    var label = el("label");
    var box = el("input", "pcs-tick");
    box.type = "checkbox";
    box.checked = all;
    box.indeterminate = some;
    box.disabled = !codesEditable || rows.length === 0;
    box.setAttribute("aria-label", "Select all visible account codes");
    box.addEventListener("change", function () {
      rows.forEach(function (row) {
        if (box.checked) ticked.add(row.code);
        else ticked.delete(row.code);
      });
      renderCodes();
      codesChanged();
    });
    label.appendChild(el("span", "pcs-select-all-label", "Select all"));
    label.appendChild(box);
    li.appendChild(label);
    return li;
  }

  function renderCodes() {
    if (!codeList) return;
    codeList.replaceChildren();
    if (!hasCodes) {
      codeList.appendChild(el("p", "pcs-codes-empty", "No account codes yet - I'll show them here once Xero's connected."));
      return;
    }
    var rows = shownCodes();
    var ul = el("ul", "pcs-codes");
    ul.setAttribute("aria-label", "Account codes");
    ul.appendChild(selectAllRow(rows));
    rows.forEach(function (row) {
      var li = el("li", "pcs-code-row");
      var label = el("label");
      var box = el("input", "pcs-tick");
      box.type = "checkbox";
      box.value = row.code;
      box.checked = ticked.has(row.code);
      box.disabled = !codesEditable;
      box.addEventListener("change", function () {
        if (box.checked) ticked.add(row.code);
        else ticked.delete(row.code);
        var all = ul.querySelector(".pcs-select-all");
        if (all) ul.replaceChild(selectAllRow(rows), all);
        codesChanged();
      });
      label.appendChild(el("span", "pcs-code-label", row.label));
      label.appendChild(box);
      li.appendChild(label);
      ul.appendChild(li);
    });
    codeList.appendChild(ul);
    if (rows.length === 0) codeList.appendChild(el("p", "pcs-codes-nomatch", "No codes match your search."));
  }

  function noCodesTicked() {
    return hasCodes && tickedCodes().length === 0;
  }

  function codesChanged() {
    var missing = codesEditable && noCodesTicked();
    var saveHint = document.getElementById("saveHint");
    if (saveHint) saveHint.hidden = !missing;
    updatePettyCashSave();
  }

  if (codeSearch) codeSearch.addEventListener("input", renderCodes);
  renderCodes();

  // The ticks are posted from the set, never by the boxes (which have no name): every way the
  // form is turned into a request - form.submit(), an Enter, new FormData(form) - fires this.
  form.addEventListener("formdata", function (event) {
    event.formData.delete("account_codes[]");
    tickedCodes().forEach(function (code) {
      event.formData.append("account_codes[]", code);
    });
  });

  // --- Save: one gate ---------------------------------------------------------------------------

  /**
   * Whether Save may be pressed - the only place that turns it on or off. Off with nothing to
   * save: the page's changes are measured the way "Leave without saving?" measures them (isDirty).
   */
  function updatePettyCashSave() {
    if (!saveButton || viewOnly) return; // the view-only button never comes on
    var loading = window.xeroDataReady !== true;
    saveButton.disabled = saving || loading || noCodesTicked() || !isDirty();
  }
  // The mapping script calls this when its Xero lists start and finish loading.
  window.updatePettyCashSave = updatePettyCashSave;

  function busy(text) {
    var overlay = document.getElementById("xeroLoadingOverlay");
    var label = document.getElementById("xeroLoadingText");
    if (!overlay) return;
    if (text) {
      if (label) label.textContent = text;
      overlay.classList.remove("hidden");
    } else {
      overlay.classList.add("hidden");
    }
  }

  function showSaving(on) {
    var text = document.getElementById("saveBtnText");
    var spinner = document.getElementById("saveBtnSpinner");
    if (text) text.hidden = on;
    if (spinner) spinner.hidden = !on;
  }

  // An Enter in a text box no longer submits the whole page. keypress, not keydown: the boxes'
  // own Enter (add a method, pick a suggestion, finish a rename) runs on keydown or on the box.
  form.addEventListener("keypress", function (event) {
    if (event.key !== "Enter") return;
    var target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (["checkbox", "radio", "submit", "button", "reset", "image"].indexOf(target.type) !== -1) return;
    event.preventDefault();
  });

  // --- 3. sales methods ------------------------------------------------------------------------

  var KINDS = {
    electronic: {
      label: "Electronic",
      list: "paymentMethodsList",
      add: "addMethodBtn",
      form: "addMethodForm",
      catalog: "methodCatalog",
      nameWrap: "methodNameWrapper",
      name: "methodName",
      cancel: "cancelMethodBtn",
      save: "saveMethodBtn",
      noun: "payment method",
    },
    delivery: {
      label: "Delivery",
      list: "deliveryMethodsList",
      add: "addDeliveryMethodBtn",
      form: "addDeliveryMethodForm",
      catalog: "deliveryCatalog",
      nameWrap: "deliveryMethodNameWrapper",
      name: "deliveryMethodName",
      cancel: "cancelDeliveryMethodBtn",
      save: "saveDeliveryMethodBtn",
      noun: "delivery method",
    },
  };
  var TYPES = ["electronic", "delivery"];
  var salesEditable = Boolean(config.canEditSalesMethods);
  var methods = { electronic: [], delivery: [] };
  var savedOrder = { electronic: [], delivery: [] };
  var deletions = []; // { id, name, type } - switched off on Save
  var methodsState = "loading";
  var catalogue = { electronic: [], delivery: [] };
  var catalogueFailed = false;
  var newId = 0;

  function valueNameOf(name) {
    return name.toLowerCase() + "_sales";
  }

  function nameTaken(name, except) {
    var wanted = name.trim().toLowerCase();
    return TYPES.some(function (type) {
      return methods[type].some(function (m) {
        return m !== except && m.name.trim().toLowerCase() === wanted;
      });
    });
  }

  function setMethodsNote(type, text, tone) {
    var note = document.querySelector('[data-methods-note="' + type + '"]');
    if (!note) return;
    note.textContent = text || "";
    note.hidden = !text;
    if (tone) note.setAttribute("data-tone", tone);
    else note.removeAttribute("data-tone");
  }

  function closeRowMenus(except) {
    document.querySelectorAll("#pc-settings .pcs-row-menu-list").forEach(function (menu) {
      if (menu === except) return;
      menu.hidden = true;
      var button = menu.parentElement && menu.parentElement.querySelector(".pcs-row-menu-btn");
      if (button) button.setAttribute("aria-expanded", "false");
    });
  }

  document.addEventListener("click", function (event) {
    if (!(event.target instanceof Element) || !event.target.closest(".pcs-row-menu")) closeRowMenus(null);
  });

  function renderMethods(type) {
    var kind = KINDS[type];
    var list = document.getElementById(kind.list);
    if (!list) return;
    list.replaceChildren();
    var rows = methods[type];
    rows.forEach(function (method, index) {
      var li = el("li", type + "-method-item pcs-method");
      li.setAttribute("data-id", method.id);
      li.setAttribute("data-method", method.name);
      if (!salesEditable) {
        li.appendChild(el("span", "pcs-method-name", method.name));
        list.appendChild(li);
        return;
      }
      var name = el("button", "pcs-method-name", method.name);
      name.type = "button";
      name.title = "Rename";
      name.addEventListener("click", function () {
        startRename(type, method, name);
      });
      li.appendChild(name);
      li.appendChild(rowMenu(type, method, index, rows.length));
      list.appendChild(li);
    });
    if (methodsState === "ready") {
      setMethodsNote(type, rows.length ? "" : "No " + kind.label.toLowerCase() + " methods yet.");
    }
    updatePettyCashSave(); // every add, rename, move and delete draws the list again
  }

  function rowMenu(type, method, index, count) {
    var wrap = el("div", "pcs-row-menu");
    var button = el("button", "pcs-row-menu-btn", "⋮");
    button.type = "button";
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", "Actions for " + method.name);
    var menu = el("ul", "pcs-row-menu-list");
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    [
      { label: "Move up", disabled: index === 0, run: function () { move(type, index, -1); } },
      { label: "Move down", disabled: index === count - 1, run: function () { move(type, index, 1); } },
      { label: "Delete", disabled: false, run: function () { askDelete(type, method); } },
    ].forEach(function (action) {
      var li = el("li");
      li.setAttribute("role", "none");
      var item = el("button", "", action.label);
      item.type = "button";
      item.setAttribute("role", "menuitem");
      item.disabled = action.disabled;
      item.addEventListener("click", function () {
        closeRowMenus(null);
        action.run();
      });
      li.appendChild(item);
      menu.appendChild(li);
    });
    button.addEventListener("click", function () {
      var opening = menu.hidden;
      closeRowMenus(menu);
      menu.hidden = !opening;
      button.setAttribute("aria-expanded", opening ? "true" : "false");
    });
    menu.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRowMenus(null);
        button.focus();
      }
    });
    wrap.appendChild(button);
    wrap.appendChild(menu);
    return wrap;
  }

  function move(type, index, step) {
    var rows = methods[type];
    var to = index + step;
    if (to < 0 || to >= rows.length) return;
    var moved = rows.splice(index, 1)[0];
    rows.splice(to, 0, moved);
    renderMethods(type);
  }

  function startRename(type, method, nameButton) {
    var input = el("input", "pcs-method-rename");
    input.type = "text";
    input.value = method.name;
    input.setAttribute("aria-label", "Rename " + method.name);
    var done = false;
    function finish(commit) {
      if (done) return;
      done = true;
      var next = input.value.trim();
      if (commit && next && next !== method.name) {
        if (nameTaken(next, method)) {
          toast("That method is already on the list.", "error");
        } else {
          method.name = next;
          if (method.isNew) method.valueName = valueNameOf(next);
        }
      }
      renderMethods(type);
    }
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", function () {
      finish(true);
    });
    nameButton.replaceWith(input);
    input.focus();
    input.select();
  }

  function askDelete(type, method) {
    if (!window.MintyDialog) {
      console.error("[petty cash settings] the dialog script is missing; nothing was deleted");
      return;
    }
    window.MintyDialog.confirm({
      name: "delete-method",
      title: "Delete " + KINDS[type].label + " Method",
      body: [['Are you sure you want to delete "', { strong: method.name }, '"? This action cannot be undone.']],
      image: "surprised",
      backLabel: "Go back",
      backTone: "grey",
      confirmLabel: "Delete",
      confirmTone: "red",
      safe: "back",
    }).then(function (choice) {
      if (choice !== "confirm") return;
      methods[type] = methods[type].filter(function (m) { return m !== method; });
      if (!method.isNew) deletions.push({ id: method.id, name: method.savedName || method.name, type: type });
      renderMethods(type);
    });
  }

  function wireAddForm(type) {
    var kind = KINDS[type];
    var addButton = document.getElementById(kind.add);
    var addForm = document.getElementById(kind.form);
    var nameWrap = document.getElementById(kind.nameWrap);
    var nameInput = document.getElementById(kind.name);
    var catalogInput = document.getElementById(kind.catalog + "Input");
    var choice = null; // { name, valueName } from the catalogue, or { other: true }

    function reset() {
      choice = null;
      if (catalogInput) catalogInput.value = "";
      if (nameInput) nameInput.value = "";
      if (nameWrap) nameWrap.classList.add("hidden");
    }

    function closeForm() {
      reset();
      if (addForm) addForm.classList.add("hidden");
      if (addButton) addButton.classList.remove("hidden");
    }

    var catalogPicker = picker({
      input: catalogInput,
      list: document.getElementById(kind.catalog + "Suggestions"),
      icon: document.getElementById(kind.catalog + "DropdownIcon"),
      options: function (query) {
        var q = query.toLowerCase();
        return catalogue[type]
          .filter(function (item) { return !nameTaken(item.name); })
          .filter(function (item) { return !q || item.name.toLowerCase().indexOf(q) !== -1; })
          .map(function (item) { return { value: item.id, label: item.name, item: item }; });
      },
      extras: function (query) {
        var rows = [];
        var q = query.toLowerCase();
        var any = catalogue[type].some(function (item) {
          return !nameTaken(item.name) && (!q || item.name.toLowerCase().indexOf(q) !== -1);
        });
        if (catalogueFailed) rows.push({ info: true, label: "I couldn't load the method list - pick Other to type a name." });
        else if (!any) rows.push({ info: true, label: "No matching " + kind.noun + " found" });
        // "Other" always stays reachable: it reveals the Name box for a brand new method.
        rows.push({ value: "__other__", label: "+ Other (type a new name)", other: true });
        return rows;
      },
      onType: function () {
        // Typing filters the list; nothing is chosen until a row is picked.
        choice = null;
        if (nameWrap) nameWrap.classList.add("hidden");
      },
      onPick: function (row) {
        if (row.other) {
          choice = { other: true };
          catalogInput.value = "Other";
          if (nameWrap) nameWrap.classList.remove("hidden");
          if (nameInput) {
            nameInput.value = "";
            nameInput.focus();
          }
          return;
        }
        choice = { name: row.item.name, valueName: row.item.value_name || valueNameOf(row.item.name) };
        catalogInput.value = row.item.name;
        if (nameWrap) nameWrap.classList.add("hidden");
      },
      label: function () {
        if (!choice) return catalogInput.value;
        return choice.other ? "Other" : choice.name;
      },
    });

    function commit() {
      var name;
      var valueName;
      if (choice && choice.other) {
        name = nameInput ? nameInput.value.trim() : "";
        valueName = name ? valueNameOf(name) : "";
      } else if (choice) {
        name = choice.name;
        valueName = choice.valueName;
      }
      if (!name) {
        toast(choice && choice.other ? "Type a name for the new method." : "Pick a method from the list, or Other.", "error");
        return;
      }
      if (nameTaken(name)) {
        toast("That method is already on the list.", "error");
        return;
      }
      newId += 1;
      methods[type].push({ id: type + "_new_" + newId, name: name, valueName: valueName, isNew: true, type: type });
      renderMethods(type);
      closeForm();
    }

    if (addButton) {
      addButton.addEventListener("click", function () {
        if (!addForm) return;
        addForm.classList.remove("hidden");
        addButton.classList.add("hidden");
        if (catalogInput) catalogInput.focus();
      });
    }
    var cancel = document.getElementById(kind.cancel);
    if (cancel) cancel.addEventListener("click", closeForm);
    var save = document.getElementById(kind.save);
    if (save) save.addEventListener("click", commit);
    if (nameInput) {
      nameInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        }
      });
    }
    return catalogPicker;
  }

  function setMethodsState(state) {
    methodsState = state;
    TYPES.forEach(function (type) {
      var addButton = document.getElementById(KINDS[type].add);
      if (addButton) addButton.disabled = !(state === "ready" && salesEditable);
      if (state === "loading") setMethodsNote(type, "Loading…");
      if (state === "failed") {
        setMethodsNote(type, "I couldn't load your sales methods. Reload the page to try again - the rest of this page still saves.", "error");
      }
      if (state === "ready") renderMethods(type);
    });
  }

  function loadMethods() {
    setMethodsState("loading");
    return fetch(methodsUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("the payment-methods list answered " + res.status);
        return res.json();
      })
      .then(function (data) {
        var list = data && Array.isArray(data.payment_methods) ? data.payment_methods : null;
        if (!list) throw new Error("the payment-methods answer has no list");
        list.forEach(function (m) {
          var type = m.type === "electronic" || m.type === "delivery" ? m.type : null;
          if (!type || !m.id) return;
          methods[type].push({ id: String(m.id), name: String(m.name || ""), savedName: String(m.name || ""), type: type });
        });
        TYPES.forEach(function (type) {
          savedOrder[type] = methods[type].map(function (m) { return m.id; });
        });
        setMethodsState("ready");
        if (salesEditable) loadCatalogue();
      })
      .catch(function (err) {
        console.error("[petty cash settings] the sales methods did not load", err);
        setMethodsState("failed");
      });
  }

  function loadCatalogue() {
    fetch(methodsUrl + "/available", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("the method catalogue answered " + res.status);
        return res.json();
      })
      .then(function (data) {
        TYPES.forEach(function (type) {
          catalogue[type] = (data && Array.isArray(data[type]) ? data[type] : []).filter(function (item) {
            return item && item.id && item.name;
          });
        });
      })
      .catch(function (err) {
        // The picker still works through Other, and says the list did not come.
        catalogueFailed = true;
        console.error("[petty cash settings] the method catalogue did not load", err);
      });
  }

  /** One API call; never rejects. */
  function send(method, url, body) {
    return fetch(url, {
      method: method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrfToken() },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(
      function (res) {
        return res
          .json()
          .catch(function () {
            return null;
          })
          .then(function (data) {
            return { ok: res.ok, data: data, reason: (data && (data.error || data.message)) || "" };
          });
      },
      function (err) {
        return { ok: false, data: null, reason: "", network: err };
      }
    );
  }

  /**
   * Write the pending sales-method changes. Resolves null when all went through, else the
   * sentence to show. What did go through is remembered, so the next Save redoes only the rest.
   */
  function saveSalesMethods() {
    if (!salesEditable || methodsState !== "ready") return Promise.resolve(null);
    var failures = [];
    var touched = { electronic: false, delivery: false };

    function failed(what, result) {
      if (result.network) console.error("[petty cash settings] " + what + " did not reach the server", result.network);
      failures.push({ what: what, reason: result.network ? "" : result.reason });
    }

    var deleting = deletions.slice();
    return Promise.all(
      deleting.map(function (gone) {
        return send("DELETE", methodsUrl + "/" + encodeURIComponent(gone.id)).then(function (result) {
          if (result.ok) deletions.splice(deletions.indexOf(gone), 1);
          else failed('delete "' + clip(gone.name, 30) + '"', result);
        });
      })
    )
      .then(function () {
        var adding = [];
        TYPES.forEach(function (type) {
          methods[type].forEach(function (m) {
            if (m.isNew) adding.push(m);
          });
        });
        return Promise.all(
          adding.map(function (m) {
            return send("POST", methodsUrl, { name: m.name, type: m.type, value_name: m.valueName, enabled: true }).then(function (result) {
              var saved = result.data && result.data.payment_method;
              if (result.ok && saved && saved.id) {
                m.id = String(saved.id);
                m.isNew = false;
                m.savedName = m.name;
                touched[m.type] = true;
              } else {
                failed('add "' + clip(m.name, 30) + '"', result);
              }
            });
          })
        );
      })
      .then(function () {
        var renaming = [];
        TYPES.forEach(function (type) {
          methods[type].forEach(function (m) {
            if (!m.isNew && m.savedName !== m.name) renaming.push(m);
          });
        });
        return Promise.all(
          renaming.map(function (m) {
            return send("PUT", methodsUrl + "/" + encodeURIComponent(m.id), { name: m.name }).then(function (result) {
              if (result.ok) m.savedName = m.name;
              else failed('rename "' + clip(m.savedName, 30) + '"', result);
            });
          })
        );
      })
      .then(function () {
        return Promise.all(
          TYPES.map(function (type) {
            var ids = methods[type].map(function (m) { return m.id; });
            var unsaved = methods[type].some(function (m) { return m.isNew; });
            var same = ids.join("\n") === savedOrder[type].join("\n");
            // The API refuses an empty list; an add that failed has no id to place yet.
            if (!ids.length || unsaved || (same && !touched[type])) return null;
            return send("PUT", methodsUrl + "/reorder", { method_ids: ids }).then(function (result) {
              if (result.ok) savedOrder[type] = ids;
              else failed("put the " + KINDS[type].label + " methods in order", result);
            });
          })
        );
      })
      .then(function () {
        TYPES.forEach(renderMethods);
        if (!failures.length) return null;
        // Kept under the toast's 200 characters: a longer sentence is shown as the house fallback.
        var first = failures[0];
        var more = failures.length > 1 ? " (and " + (failures.length - 1) + " more)" : "";
        var reason = first.reason ? ": " + clip(first.reason, 100) : " - the server didn't answer";
        return "I couldn't " + first.what + reason + more + ". Nothing else was saved.";
      });
  }

  if (TYPES.every(function (type) { return document.getElementById(KINDS[type].list); })) {
    if (salesEditable) TYPES.forEach(wireAddForm);
  }
  var methodsLoaded = loadMethods();

  // --- 2 + the save ----------------------------------------------------------------------------

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (saving || viewOnly) return;

    // The mapping check: every mapping field, once any is set (the fragment's rule).
    if (typeof window.validateMappingBeforeSave !== "function") {
      console.error("[petty cash settings] the mapping check is missing; nothing was saved");
      toast("Something went wrong on my end. Mind trying again?", "error");
      return;
    }
    if (!window.validateMappingBeforeSave()) {
      var missing = document.querySelector("#pc-settings .pcs-combo-input.border-red-500");
      if (missing) {
        revealCardOf(missing);
        missing.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return;
    }

    // The account-code rule, before any sales method is written.
    if (noCodesTicked()) {
      codesChanged();
      revealCardOf(codeList);
      if (codeList) codeList.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    saving = true;
    updatePettyCashSave();
    showSaving(true);
    busy("Saving changes…");
    saveSalesMethods().then(
      function (problem) {
        if (problem) {
          saving = false;
          showSaving(false);
          busy(null);
          updatePettyCashSave();
          toast(problem, "error");
          return;
        }
        if (window.MintyLeaveGuard) window.MintyLeaveGuard.saving();
        form.submit();
      },
      function (err) {
        console.error("[petty cash settings] the save stopped", err);
        saving = false;
        showSaving(false);
        busy(null);
        updatePettyCashSave();
        toast("Something went wrong on my end. Mind trying again?", "error");
      }
    );
  });

  // --- "Leave without saving?" -------------------------------------------------------------------

  // What the page holds, in three parts measured against what it loaded: the form's own fields
  // (the mapping, country and currency - known once the Xero lists have loaded), the ticks
  // (known now) and the sales methods (once loaded). A part not yet loaded is not "changed".
  function formPart() {
    var pairs = [];
    new FormData(form).forEach(function (value, key) {
      if (key === "csrf_token" || key === "account_codes[]") return;
      pairs.push(key + "=" + (typeof value === "string" ? value : ""));
    });
    return pairs.join("\n");
  }

  function codesPart() {
    return tickedCodes().join("\n");
  }

  function methodsPart() {
    return JSON.stringify([
      TYPES.map(function (type) {
        return methods[type].map(function (m) { return [m.id, m.name]; });
      }),
      deletions.map(function (gone) { return gone.id; }),
    ]);
  }

  var baseline = { form: null, codes: codesPart(), methods: null };

  function isDirty() {
    if (!baseline) return false; // asked before this script reached its own measure
    if (baseline.form !== null && formPart() !== baseline.form) return true;
    if (codesPart() !== baseline.codes) return true;
    return baseline.methods !== null && methodsPart() !== baseline.methods;
  }

  document.addEventListener("DOMContentLoaded", function () {
    // The mapping script has started its Xero load by now (its DOMContentLoaded ran first).
    Promise.allSettled([window.xeroDataLoad || Promise.resolve()]).then(function () {
      baseline.form = formPart();
      updatePettyCashSave();
    });
    Promise.allSettled([methodsLoaded]).then(function () {
      baseline.methods = methodsPart();
      updatePettyCashSave();
    });
    // Save follows every edit. The mapping pickers write their hidden <select>s from script,
    // which fires no event, so any click, key or blur re-checks too - after its handlers ran.
    ["input", "change", "click", "mousedown", "keyup", "focusout"].forEach(function (type) {
      document.addEventListener(type, function () { setTimeout(updatePettyCashSave, 0); }, true);
    });
    if (window.MintyLeaveGuard) window.MintyLeaveGuard.watch(isDirty);
    else console.error("[petty cash settings] the leave guard is missing; unsaved changes are not guarded");
    codesChanged();
  });
})();
