/*
 * AI-assisted expense capture — the Add New Expense card (plan §7.4, §9.3).
 *
 * Loaded ONLY when EXPENSE_AI_ENABLED is on. With the flag off the page never
 * receives this file and behaves exactly as it did before the feature existed.
 *
 * The five states this implements:
 *
 *   Reading      receipt attached, model working  -> quiet indicator
 *   Suggested    value returned with confidence   -> field filled and marked
 *   Confirmed    user edits, tabs past, or Adds   -> marking disappears
 *   Blank        low confidence or unreadable     -> field left empty
 *   Unavailable  slow, rate limited, or down      -> nothing at all
 *
 * Two rules the rest of the file exists to keep:
 *
 *   NEVER OVERWRITE THE USER. If a field already holds a value when the reply
 *   arrives — because the user typed faster than the model — that field is
 *   left alone regardless of confidence.
 *
 *   ADD IS NEVER BLOCKED. The request runs beside the form, never inside it.
 *   A reply that arrives after the card closed, after the file changed, or
 *   after Add was pressed is discarded.
 */
(function () {
  'use strict';

  var CONFIG = window.EXPENSE_AI || {};
  var controller = null;   // AbortController for the in-flight request
  var requestToken = 0;    // guards against a stale reply being applied
  var markedFields = [];   // input ids currently showing a suggestion marking

  // Which form control each suggestion lands in.
  var TARGETS = {
    amount: 'expense_amount',
    description: 'expense_remarks',
    supplier: 'expense_contact',
    account: 'expense_account_code'
  };

  // ----------------------------------------------------------------- chrome
  function ensureChrome() {
    if (document.getElementById('aiLiveRegion')) return;

    var region = document.createElement('div');
    region.id = 'aiLiveRegion';
    region.className = 'sr-only';
    region.setAttribute('role', 'status');
    region.setAttribute('aria-live', 'polite');
    document.body.appendChild(region);

    var uploadArea = document.getElementById('uploadArea');
    if (!uploadArea || !uploadArea.parentNode) return;

    // QA: the first version of this was 12px grey text and people missed it.
    // The wait is 8 seconds or more, so it has to be obvious that something
    // is happening — otherwise the page looks broken.
    var indicator = document.createElement('div');
    indicator.id = 'aiReadingIndicator';
    indicator.className =
      'hidden mt-3 mb-1 flex items-center gap-3 rounded-xl border ' +
      'border-[#54D3DA] bg-[#54D3DA]/10 px-4 py-3';
    indicator.innerHTML =
      '<svg class="animate-spin h-5 w-5 text-[#31B6BD] shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
      '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>' +
      '</svg>' +
      '<div class="min-w-0">' +
      '<p class="text-sm font-medium text-[#31B6BD]">Reading the receipt&hellip;</p>' +
      '<p class="text-xs text-gray-500">This can take a few seconds. ' +
      'You can start typing now if you prefer.</p>' +
      '</div>';
    uploadArea.parentNode.insertBefore(indicator, uploadArea.nextSibling);
  }

  function announce(message) {
    var region = document.getElementById('aiLiveRegion');
    if (region) region.textContent = message;
  }

  function showReading(on) {
    ensureChrome();
    var indicator = document.getElementById('aiReadingIndicator');
    if (indicator) indicator.classList.toggle('hidden', !on);
  }

  // --------------------------------------------------------------- marking
  // A marked field has to be obvious at a glance. The first version was 12px
  // teal text on white and testers walked straight past it, which defeats the
  // point: an unnoticed suggestion is an unchecked suggestion.
  //
  // Marking never relies on colour alone (§7.4). Every marked field gets an
  // icon, a worded label and a real button, so it reads correctly in
  // greyscale and to a screen reader.

  // Where the badge goes, for every field, without depending on how that
  // particular field happens to be wrapped. Amount, Supplier and Account sit
  // inside a `.relative` positioning box (it holds the currency symbol or the
  // dropdown chevron); Description has no wrapper at all. Walking up to the
  // nearest labelled block treats all four the same.
  function fieldGroup(input) {
    var node = input.parentElement;
    while (node && node !== document.body) {
      if (node.querySelector && node.querySelector('label')) return node;
      node = node.parentElement;
    }
    return input.parentElement || input;
  }

  function markField(inputId, label) {
    var input = document.getElementById(inputId);
    if (!input) return;

    unmarkField(inputId);
    input.dataset.aiSuggested = 'true';
    input.classList.add('ring-2', 'ring-[#54D3DA]', 'ring-offset-1');

    // The original inline style, sized up: 14px text and a 16px icon instead
    // of 12px and 12px. Deliberately light-touch — the ring on the field is
    // the main signal and this is the label that explains it.
    var badge = document.createElement('div');
    badge.id = 'aiBadge_' + inputId;
    badge.className =
      'mt-1.5 flex items-center gap-1.5 text-sm text-[#31B6BD]';
    badge.innerHTML =
      '<svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="currentColor" ' +
      'aria-hidden="true">' +
      '<path d="M12 2l2.4 6.2L21 10l-6.6 1.8L12 18l-2.4-6.2L3 10l6.6-1.8L12 2z"/>' +
      '</svg>' +
      '<span>' + label + '</span>' +
      '<button type="button" class="underline hover:no-underline font-medium" ' +
      'aria-label="Clear the suggested value for this field">Clear</button>';

    badge.querySelector('button').addEventListener('click', function () {
      clearSuggestion(inputId);
      input.focus();
    });

    fieldGroup(input).appendChild(badge);

    // Confirmed: the moment the user touches the field it is theirs.
    input.addEventListener('input', onUserEdit);
    input.addEventListener('change', onUserEdit);
    markedFields.push(inputId);
  }

  function onUserEdit(event) {
    unmarkField(event.target.id);
  }

  function unmarkField(inputId) {
    var input = document.getElementById(inputId);
    if (input) {
      delete input.dataset.aiSuggested;
      input.classList.remove('ring-2', 'ring-offset-1',
                             'ring-[#54D3DA]', 'ring-amber-400');
      input.removeEventListener('input', onUserEdit);
      input.removeEventListener('change', onUserEdit);
    }
    var badge = document.getElementById('aiBadge_' + inputId);
    if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
    markedFields = markedFields.filter(function (id) { return id !== inputId; });
  }

  function clearAllMarkings() {
    markedFields.slice().forEach(unmarkField);
  }

  // Drop a suggestion's VALUE as well as its marking.
  //
  // The difference matters, and getting it wrong is what broke replacing a
  // receipt: clearing only the marking left the previous receipt's amount and
  // description sitting in the fields, and the never-overwrite rule then
  // refused to fill them from the new receipt — protecting the AI's own stale
  // output as if the user had typed it.
  //
  // Only ever called for fields still in `markedFields`, i.e. fields holding
  // an untouched suggestion. The moment the user edits a field it unmarks
  // itself, and from then on nothing here can clear it.
  function clearSuggestion(inputId) {
    var input = document.getElementById(inputId);
    if (input) {
      // Supplier and account carry a selected id behind the visible text.
      // Clearing the text without clearing the id would leave the form
      // holding a selection the user can no longer see.
      if (inputId === TARGETS.supplier && typeof window.selectContact === 'function') {
        try { window.selectContact(null, ''); } catch (e) { /* best effort */ }
      } else if (inputId === TARGETS.account && typeof window.selectAccount === 'function') {
        try { window.selectAccount(null, ''); } catch (e) { /* best effort */ }
      }
      input.value = '';
    }
    unmarkField(inputId);
  }

  // QA request: when the receipt names a supplier we do not have, offer it
  // rather than silently leaving the field blank. The model read the name;
  // making the user retype it is a waste.
  //
  // This does NOT create a contact. It fills in the New Contact box that
  // already exists and the user still presses Create. Creating a supplier
  // stays a deliberate human action.
  function showDetectedSupplier(name) {
    removeDetectedSupplier();
    var input = document.getElementById(TARGETS.supplier);
    if (!input) return;

    // The original quiet style, sized up: 14px instead of 12px. Same grey
    // panel, same underlined link.
    var prompt = document.createElement('div');
    prompt.id = 'aiDetectedSupplier';
    prompt.className =
      'mt-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm';

    var line = document.createElement('p');
    line.className = 'text-gray-600';
    // textContent, not innerHTML: this string came off a receipt image and is
    // untrusted. It is never parsed as markup.
    line.textContent = 'Receipt says "' + name + '", which is not in your '
      + 'supplier list.';

    var button = document.createElement('button');
    button.type = 'button';
    button.className =
      'mt-1 font-medium text-[#31B6BD] underline hover:no-underline text-left';
    button.textContent = 'Add "' + name + '" as a new supplier';
    button.addEventListener('click', function () {
      if (typeof window.showNewContactSection === 'function') {
        window.showNewContactSection(name);
      }
      removeDetectedSupplier();
    });

    prompt.appendChild(line);
    prompt.appendChild(button);
    fieldGroup(input).appendChild(prompt);

    announce('The receipt names a supplier that is not in your list: ' + name
             + '. You can add it as a new supplier.');

    // Once the user picks a supplier themselves, the offer is stale.
    input.addEventListener('input', removeDetectedSupplier);
  }

  function removeDetectedSupplier() {
    var prompt = document.getElementById('aiDetectedSupplier');
    if (prompt && prompt.parentNode) prompt.parentNode.removeChild(prompt);
    var input = document.getElementById(TARGETS.supplier);
    if (input) input.removeEventListener('input', removeDetectedSupplier);
  }

  function clearAllSuggestions() {
    removeDetectedSupplier();
    removeAllMismatches();
    markedFields.slice().forEach(clearSuggestion);
  }

  // -------------------------------------------------------------- applying
  function isEmpty(input) {
    return !input || !String(input.value || '').trim();
  }

  // ------------------------------------------------------- mismatch notices
  // The never-overwrite rule says we leave a filled field alone. Followed
  // literally that also means saying nothing when the receipt plainly
  // disagrees with what is in the box — which loses information the user
  // would want. A typo of 44.80 for 448.80 is exactly the kind of thing the
  // receipt could catch and we were staying quiet about.
  //
  // So: never change a filled field, but do offer. Nothing moves without a
  // click, which keeps the rule intact.
  function showMismatch(inputId, wording, apply) {
    removeMismatch(inputId);
    var input = document.getElementById(inputId);
    if (!input) return;

    var note = document.createElement('div');
    note.id = 'aiMismatch_' + inputId;
    note.className =
      'mt-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm';

    var line = document.createElement('p');
    line.className = 'text-gray-600';
    // textContent: this came off a receipt image and is not trusted markup.
    line.textContent = wording;

    var button = document.createElement('button');
    button.type = 'button';
    button.className =
      'mt-1 font-medium text-[#31B6BD] underline hover:no-underline text-left';
    button.textContent = 'Use the value from the receipt';
    button.addEventListener('click', function () {
      apply();
      removeMismatch(inputId);
    });

    note.appendChild(line);
    note.appendChild(button);
    fieldGroup(input).appendChild(note);

    // Once the user edits the field themselves, the comparison is stale.
    input.addEventListener('input', function () { removeMismatch(inputId); });
  }

  // The confidence cut-off decides whether we PUT a value in an empty box.
  // It should not decide whether we MENTION a disagreement, because a notice
  // changes nothing and costs the user only a glance. So notices are shown
  // whenever we read something, and the wording carries how sure we were.
  function hedge(field) {
    return field && field.band === 'low' ? 'might read' : 'reads';
  }

  function removeMismatch(inputId) {
    var note = document.getElementById('aiMismatch_' + inputId);
    if (note && note.parentNode) note.parentNode.removeChild(note);
  }

  function removeAllMismatches() {
    Object.keys(TARGETS).forEach(function (key) { removeMismatch(TARGETS[key]); });
  }

  function sameText(a, b) {
    return String(a || '').trim().toLowerCase() ===
           String(b || '').trim().toLowerCase();
  }

  function sameAmount(a, b) {
    var x = parseFloat(String(a || '').replace(/,/g, ''));
    var y = parseFloat(String(b || '').replace(/,/g, ''));
    if (isNaN(x) || isNaN(y)) return false;
    return Math.abs(x - y) < 0.005;
  }

  function applySuggestions(data) {
    var suggestions = data && data.suggestions;
    if (!suggestions) return;

    var filled = [];

    var amount = suggestions.amount;
    var amountInput = document.getElementById(TARGETS.amount);
    if (amount && amount.applied && isEmpty(amountInput)) {
      amountInput.value = amount.value;
      if (typeof window.formatWithCommas === 'function') {
        try { window.formatWithCommas(amountInput); } catch (e) { /* cosmetic */ }
      }
      markField(TARGETS.amount, bandLabel(amount.band, 'Amount'));
      filled.push('amount');
    } else if (amount && amount.value &&
               !sameAmount(amountInput.value, amount.value)) {
      showMismatch(TARGETS.amount,
        'The receipt ' + hedge(amount) + ' ' + amount.value + ', not ' +
        amountInput.value + '.',
        function () {
          amountInput.value = amount.value;
          if (typeof window.formatWithCommas === 'function') {
            try { window.formatWithCommas(amountInput); } catch (e) { /* cosmetic */ }
          }
          markField(TARGETS.amount, bandLabel(amount.band, 'Amount'));
        });
    }

    var description = suggestions.description;
    var descriptionInput = document.getElementById(TARGETS.description);
    if (description && description.applied && isEmpty(descriptionInput)) {
      descriptionInput.value = description.value;
      markField(TARGETS.description, bandLabel(description.band, 'Description'));
      filled.push('description');
    }

    // Supplier and account go through the page's own selection functions so
    // the hidden ids, the validation state and the visible text stay in step —
    // a suggestion must leave the form in exactly the state a click would.
    var supplier = suggestions.supplier;
    var supplierInput = document.getElementById(TARGETS.supplier);
    if (supplier && supplier.applied && supplier.contact_id && isEmpty(supplierInput)) {
      if (typeof window.selectContact === 'function') {
        window.selectContact(supplier.contact_id, supplier.value);
        markField(TARGETS.supplier, bandLabel(supplier.band, 'Supplier'));
        filled.push('supplier');
      }
    } else if (supplier && supplier.detected_name && isEmpty(supplierInput)) {
      // Read a name off the receipt, but it matches nothing in the contact
      // list. Offer it instead of leaving the user to retype it.
      showDetectedSupplier(supplier.detected_name);
    } else if (supplier && supplier.contact_id &&
               !isEmpty(supplierInput) &&
               !sameText(supplierInput.value, supplier.value)) {
      showMismatch(TARGETS.supplier,
        'The receipt ' + hedge(supplier) + ' like "' + supplier.value +
        '", not "' + supplierInput.value + '".',
        function () {
          window.selectContact(supplier.contact_id, supplier.value);
          markField(TARGETS.supplier, bandLabel(supplier.band, 'Supplier'));
        });
    }

    var account = suggestions.account;
    var accountInput = document.getElementById(TARGETS.account);
    if (account && account.applied && account.account_id && isEmpty(accountInput)) {
      if (typeof window.selectAccount === 'function') {
        window.selectAccount(account.account_id, account.name);
        markField(TARGETS.account, bandLabel(account.band, 'Account code'));
        filled.push('account');
      }
    } else if (account && account.account_id &&
               !isEmpty(accountInput) &&
               !sameText(accountInput.value, account.name)) {
      showMismatch(TARGETS.account,
        'The receipt ' + hedge(account) + ' more like "' + account.name +
        '" than "' + accountInput.value + '".',
        function () {
          window.selectAccount(account.account_id, account.name);
          markField(TARGETS.account, bandLabel(account.band, 'Account code'));
        });
    }

    var mismatches = Object.keys(TARGETS).filter(function (key) {
      return document.getElementById('aiMismatch_' + TARGETS[key]);
    });
    if (mismatches.length) {
      announce('The receipt disagrees with ' + mismatches.length +
               ' field' + (mismatches.length === 1 ? '' : 's') +
               ' you already filled in: ' + mismatches.join(', ') +
               '. Nothing has been changed.');
    }

    if (!filled.length) return;
    // One announcement, not two: a live region that is written twice in quick
    // succession may only ever be read out once.
    var message =
      'Suggestions from the receipt filled ' + filled.length +
      ' field' + (filled.length === 1 ? '' : 's') + ': ' + filled.join(', ') +
      '. Please check them before adding.';
    var dateNote = dateMismatchNote(suggestions);
    announce(dateNote ? message + ' ' + dateNote : message);
  }

  function bandLabel(band, fieldName) {
    // Medium confidence is marked more strongly for review than high (§6.2).
    // The wording carries it as well as the colour, so the distinction
    // survives greyscale and screen readers.
    return band === 'medium'
      ? fieldName + ' suggested — please check'
      : fieldName + ' suggested';
  }

  // §13.1 "extract and check": the date is read off the receipt and used only
  // to warn when it is a long way from the report being worked on. Nothing
  // new appears on the form, and nothing blocks Add.
  function dateMismatchNote(suggestions) {
    var date = suggestions.document_date;
    if (!date || !date.applied || !CONFIG.transactionDate) return '';
    var receipt = Date.parse(date.value);
    var report = Date.parse(CONFIG.transactionDate);
    if (isNaN(receipt) || isNaN(report)) return '';
    var days = Math.abs(receipt - report) / 86400000;
    if (days <= 7) return '';
    return (
      'Note: this receipt is dated ' + date.value +
      ', which is more than a week from the report date.'
    );
  }

  // ------------------------------------------------------------- the call
  function cancel() {
    requestToken += 1;
    if (controller) {
      try { controller.abort(); } catch (e) { /* already settled */ }
      controller = null;
    }
    showReading(false);
  }

  function formIsOpen() {
    var form = document.getElementById('addExpenseForm');
    return !!form && !form.classList.contains('hidden');
  }

  // ------------------------------------------------------- shrink to upload
  // Resize the photo in the browser before sending it for reading.
  //
  // A modern phone photo is 8-12 MB. Uploading that over mobile data is the
  // slowest part of the whole thing after Google itself, and the server then
  // spends ~600ms shrinking it anyway. Doing it here removes both.
  //
  // THIS COPY IS FOR THE AI ONLY. The file input still holds the untouched
  // original, and that is what gets uploaded and stored when the user presses
  // Add. We never degrade the receipt anyone actually keeps.
  //
  // 2000px on the long edge is well above what is needed to read a receipt,
  // and Gemini downscales to 3072px regardless — anything larger is pure
  // waste. PDFs pass through untouched; they cannot be resized here.
  var MAX_EDGE = 2000;
  var JPEG_QUALITY = 0.85;

  function shrinkForUpload(file) {
    var unchanged = Promise.resolve(file);
    if (!file || !/^image\/(jpe?g|png)$/i.test(file.type || '')) return unchanged;
    if (typeof createImageBitmap !== 'function' ||
        typeof document.createElement('canvas').toBlob !== 'function') {
      return unchanged;
    }

    return createImageBitmap(file)
      .then(function (bitmap) {
        var scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
        // Already small enough - re-encoding would only lose quality.
        if (scale === 1) {
          bitmap.close && bitmap.close();
          return file;
        }
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close && bitmap.close();

        return new Promise(function (resolve) {
          canvas.toBlob(function (blob) {
            // Only use it if it is actually smaller. A tiny detailed image can
            // re-encode larger than it started.
            resolve(blob && blob.size < file.size ? blob : file);
          }, 'image/jpeg', JPEG_QUALITY);
        });
      })
      .catch(function () {
        // Any failure - unsupported format, out of memory, a browser quirk -
        // falls back to the original. The server shrinks it as before.
        return file;
      });
  }

  function onFilesAttached(files) {
    // Stage 1 reads the FIRST attached file only; additional files are
    // ignored (§7.1). Anything more is a Stage 2 question.
    cancel();
    // A new receipt supersedes the previous one's suggestions entirely, so
    // their VALUES go too, not just their marking. Fields the user has since
    // typed in are already unmarked and are left untouched.
    clearAllSuggestions();
    if (!files || !files.length || !formIsOpen()) return;

    var file = files[0];
    var token = requestToken;

    var csrf = document.querySelector('input[name="csrf_token"]');
    var headers = csrf ? { 'X-CSRFToken': csrf.value } : {};

    controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    showReading(true);

    shrinkForUpload(file).then(function (payload) {
      // The user may have swapped or removed the receipt while we were
      // resizing. Do not send a request for a file that is no longer there.
      if (token !== requestToken || !formIsOpen()) return;

      var formData = new FormData();
      // Keep the original filename so the server sees a sensible name; the
      // bytes are the shrunk copy.
      formData.append('file', payload, file.name || 'receipt.jpg');
      if (CONFIG.entityId) formData.append('entity_id', CONFIG.entityId);
      if (CONFIG.reportId) formData.append('report_id', CONFIG.reportId);

      return fetch(CONFIG.url, {
        method: 'POST',
        body: formData,
        headers: headers,
        credentials: 'same-origin',
        signal: controller ? controller.signal : undefined
      })
        .then(function (response) {
          return response.ok ? response.json() : null;
        })
        .then(function (data) {
          // Apply only if this is still the current request, the card is
          // still open, and the file has not been swapped underneath us.
          if (token !== requestToken || !formIsOpen()) return;
          var input = document.getElementById('expense_files');
          var current = input && input.files && input.files[0];
          if (current && current.name !== file.name) return;
          applySuggestions(data);
        });
    })
      .catch(function () {
        // Unavailable means invisible: no toast, no banner, no error state.
        // The card is exactly as it is without the feature.
      })
      .then(function () {
        if (token === requestToken) showReading(false);
      });
  }

  window.mintyAi = {
    onFilesAttached: onFilesAttached,
    // The receipt is gone, so the suggestions that came from it go with it.
    cancel: function () { cancel(); clearAllSuggestions(); },
    clearMarkings: clearAllMarkings
  };
})();
