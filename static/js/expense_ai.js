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

    var indicator = document.createElement('p');
    indicator.id = 'aiReadingIndicator';
    indicator.className = 'hidden mt-2 text-xs text-gray-500 flex items-center gap-2';
    indicator.innerHTML =
      '<svg class="animate-spin h-3 w-3 text-gray-400" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>' +
      '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>' +
      '</svg><span>Reading the receipt&hellip;</span>';
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
  // Marking must not rely on colour alone (§7.4): every marked field gets a
  // visible text label as well as the ring, and the arrival is announced.
  function markField(inputId, label) {
    var input = document.getElementById(inputId);
    if (!input) return;

    unmarkField(inputId);
    input.dataset.aiSuggested = 'true';
    input.classList.add('ring-2', 'ring-[#54D3DA]', 'ring-offset-1');

    var badge = document.createElement('div');
    badge.id = 'aiBadge_' + inputId;
    badge.className =
      'mt-1 flex items-center gap-1 text-xs text-[#31B6BD]';
    badge.innerHTML =
      '<svg class="h-3 w-3" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
      '<path d="M12 2l2.4 6.2L21 10l-6.6 1.8L12 18l-2.4-6.2L3 10l6.6-1.8L12 2z"/></svg>' +
      '<span>' + label + '</span>' +
      '<button type="button" class="underline hover:no-underline" ' +
      'aria-label="Clear this suggestion">Clear</button>';

    badge.querySelector('button').addEventListener('click', function () {
      clearSuggestion(inputId);
      input.focus();
    });

    // Sit the badge directly under the control. Amount, supplier and account
    // are each wrapped in a `.relative` positioning box (it holds the currency
    // symbol / dropdown chevron); the badge goes after that box rather than
    // inside it. Description has no wrapper, so it goes after the input.
    var anchor =
      input.parentElement && input.parentElement.classList.contains('relative')
        ? input.parentElement
        : input;
    anchor.insertAdjacentElement('afterend', badge);

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
      input.classList.remove('ring-2', 'ring-[#54D3DA]', 'ring-offset-1');
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

  function clearAllSuggestions() {
    markedFields.slice().forEach(clearSuggestion);
  }

  // -------------------------------------------------------------- applying
  function isEmpty(input) {
    return !input || !String(input.value || '').trim();
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
    }

    var account = suggestions.account;
    var accountInput = document.getElementById(TARGETS.account);
    if (account && account.applied && account.account_id && isEmpty(accountInput)) {
      if (typeof window.selectAccount === 'function') {
        window.selectAccount(account.account_id, account.name);
        markField(TARGETS.account, bandLabel(account.band, 'Account code'));
        filled.push('account');
      }
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
    var formData = new FormData();
    formData.append('file', file);
    if (CONFIG.entityId) formData.append('entity_id', CONFIG.entityId);
    if (CONFIG.reportId) formData.append('report_id', CONFIG.reportId);

    var csrf = document.querySelector('input[name="csrf_token"]');
    var headers = csrf ? { 'X-CSRFToken': csrf.value } : {};

    controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    showReading(true);

    fetch(CONFIG.url, {
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
        // Apply only if this is still the current request, the card is still
        // open, and the file has not been swapped underneath us.
        if (token !== requestToken || !formIsOpen()) return;
        var input = document.getElementById('expense_files');
        var current = input && input.files && input.files[0];
        if (current && current.name !== file.name) return;
        showReading(false);
        applySuggestions(data);
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
