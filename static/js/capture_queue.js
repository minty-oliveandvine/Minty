/*
 * The Draft Queue page.
 *
 * Cards are built here rather than server-rendered, so confirming one does not
 * reload the page and lose the user's place in a list of twenty.
 *
 * THE RULES, same as the bubble's:
 *
 *   NOTHING FROM A DOCUMENT IS EVER innerHTML. Supplier names, descriptions,
 *   filenames and locators all came off a file somebody else supplied.
 *
 *   A SUGGESTION IS MARKED UNTIL THE USER TOUCHES IT, then the marking goes.
 *   Same language as the expense form, so the two read as one feature.
 *
 *   A LOW-CONFIDENCE FIELD IS LEFT BLANK. It is not a suggestion the user
 *   should have to notice and delete.
 */
(function () {
  'use strict';

  var CONFIG = window.CAPTURE_QUEUE || {};
  if (!CONFIG.draftsUrl) { return; }

  var list = document.getElementById('capList');
  var empty = document.getElementById('capEmpty');
  var count = document.getElementById('capCount');
  var filters = document.getElementById('capFilters');
  var live = document.getElementById('capQueueLive');

  var status = '';
  var openReports = [];

  // ------------------------------------------------------------- utilities
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function suggested(draft, name) {
    var field = draft.suggested && draft.suggested[name];
    return (field && typeof field === 'object') ? field : null;
  }

  /* The value to prefill. Empty when the model was not confident enough:
     `applied` is the server's instruction and it already accounts for the
     confidence bands. */
  function prefill(draft, name) {
    var field = suggested(draft, name);
    if (!field || !field.applied) { return ''; }
    return field.value == null ? '' : String(field.value);
  }

  /* Read from the hidden input the page renders, matching
     static/js/expense_ai.js. These are session-authenticated writes and are
     CSRF-protected like any other; without the header the POST redirects to
     the login page and the browser parses an HTML 200 as JSON. */
  function csrfToken() {
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : null;
  }

  function post(url, body) {
    var headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
    var token = csrfToken();
    if (token) { headers['X-CSRFToken'] = token; }
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: headers,
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; })
        .then(function (data) { return { ok: response.ok, data: data }; });
    });
  }

  // ---------------------------------------------------------------- fields
  function field(labelText, name, value, isSuggestion, extraNote) {
    var wrap = el('div', 'cap-field');
    wrap.appendChild(el('label', null, labelText));

    var input = el('input');
    input.type = 'text';
    input.name = name;
    input.value = value || '';
    if (isSuggestion && value) {
      input.classList.add('is-suggested');
      // The marking disappears the moment the user takes ownership of the
      // field — the same behaviour the expense form already taught them.
      input.addEventListener('input', function () {
        input.classList.remove('is-suggested');
        if (note) { note.remove(); note = null; }
      }, { once: true });
    }
    wrap.appendChild(input);

    var note = null;
    if (extraNote) {
      note = el('div', 'cap-why', extraNote);
      wrap.appendChild(note);
    }
    return wrap;
  }

  function reportPicker(draft) {
    var wrap = el('div', 'cap-field');
    wrap.appendChild(el('label', null, 'Add to report'));

    var select = el('select');
    select.name = 'report_id';

    if (!openReports.length) {
      // ShopExpense.report_id is NOT NULL, so without an open report there is
      // genuinely nothing to attach this to. Say so plainly rather than
      // failing on Confirm.
      var none = el('option', null, 'No open report');
      none.value = '';
      select.appendChild(none);
      select.disabled = true;
    } else {
      openReports.forEach(function (report, index) {
        var option = el('option', null, report.label);
        option.value = report.id;
        if (index === 0) { option.selected = true; }
        select.appendChild(option);
      });
    }
    wrap.appendChild(select);
    return wrap;
  }

  // ----------------------------------------------------------------- cards
  function card(draft) {
    var root = el('div', 'cap-card');
    root.dataset.draftId = draft.id;

    root.appendChild(thumb(draft));

    var fields = el('div', 'cap-fields');
    fields.appendChild(tags(draft));

    var grid = el('div', 'cap-grid');
    var isInvoice = draft.doc_type === 'invoice';

    var supplier = suggested(draft, 'supplier') || {};
    grid.appendChild(field(
      'Supplier',
      'contact_name',
      prefill(draft, 'supplier') || supplier.detected_name || '',
      true,
      // The model read a name off the document but it matched no contact. Say
      // so, rather than letting the user assume it is linked.
      (!supplier.contact_id && supplier.detected_name)
        ? 'Read from the document — not a saved supplier yet'
        : null
    ));
    if (supplier.contact_id) {
      var hidden = el('input');
      hidden.type = 'hidden';
      hidden.name = 'contact_id';
      hidden.value = supplier.contact_id;
      grid.appendChild(hidden);
    }

    grid.appendChild(field('Amount', 'amount', prefill(draft, 'amount'), true));
    grid.appendChild(field('Currency', 'currency', (draft.suggested && draft.suggested.currency) || '', true));
    grid.appendChild(field('Date', 'document_date', prefill(draft, 'document_date'), true));
    grid.appendChild(field('Description', 'description', prefill(draft, 'description'), true));

    var account = suggested(draft, 'account') || {};
    grid.appendChild(field('Account code', 'account_code', prefill(draft, 'account'), true));
    if (account.account_id) {
      var accountId = el('input');
      accountId.type = 'hidden';
      accountId.name = 'account_id';
      accountId.value = account.account_id;
      grid.appendChild(accountId);
    }

    if (isInvoice) {
      grid.appendChild(field('Invoice number', 'invoice_number', prefill(draft, 'invoice_number'), true));
      grid.appendChild(field('Due date', 'due_date', prefill(draft, 'due_date'), true));
      grid.appendChild(field('Tax', 'tax_amount', prefill(draft, 'tax_amount'), true));
    }

    if (draft.destination === 'petty_cash') {
      grid.appendChild(reportPicker(draft));
    }

    fields.appendChild(grid);

    if (draft.destination === 'hold') {
      fields.appendChild(el('div', 'cap-note hold',
        isInvoice
          ? "This looks like a supplier invoice. Payment Submission isn't switched on for this company, so there's nowhere to send it yet."
          : "This looks like a receipt. Petty Cash isn't switched on for this company, so there's nowhere to send it yet."));
    }

    if (draft.last_error) {
      fields.appendChild(el('div', 'cap-note err', draft.last_error));
    }

    fields.appendChild(actions(draft));
    root.appendChild(fields);
    return root;
  }

  function thumb(draft) {
    var wrap = el('div', 'cap-thumb');
    var frame = el('iframe', 'cap-frame');
    frame.src = draft.file_url;
    frame.title = 'Document ' + draft.sequence;
    frame.loading = 'lazy';
    wrap.appendChild(frame);

    var parts = [];
    if (draft.of > 1) { parts.push('Document ' + draft.sequence + ' of ' + draft.of); }
    if (draft.page_start === draft.page_end) {
      parts.push('page ' + draft.page_start);
    } else {
      parts.push('pages ' + draft.page_start + '–' + draft.page_end);
    }
    var origin = el('div', 'cap-origin');
    // textContent, twice over: a filename and a locator both came off a file.
    origin.textContent = draft.original_filename + ' · ' + parts.join(' · ');
    wrap.appendChild(origin);

    if (draft.locator) {
      var locator = el('div', 'cap-origin', draft.locator);
      wrap.appendChild(locator);
    }
    return wrap;
  }

  function tags(draft) {
    var wrap = el('div', 'cap-tags');
    wrap.appendChild(el('span', 'cap-tag ' + draft.doc_type,
      draft.doc_type === 'invoice' ? 'Invoice' : 'Receipt'));
    wrap.appendChild(el('span', 'cap-tag ' + draft.status, statusLabel(draft.status)));
    wrap.appendChild(el('span', 'cap-tag',
      draft.destination === 'payment' ? 'Payment Submission'
        : draft.destination === 'petty_cash' ? 'Petty Cash' : 'On hold'));
    return wrap;
  }

  function statusLabel(value) {
    switch (value) {
      case 'ready': return 'Ready';
      case 'needs_clarification': return 'Needs a look';
      case 'hold': return 'On hold';
      case 'confirming': return 'Sending';
      case 'send_failed': return "Didn't send";
      case 'posted': return 'Added';
      case 'archived': return 'Archived';
      default: return value;
    }
  }

  function actions(draft) {
    var wrap = el('div', 'cap-actions');

    if (draft.status === 'posted' || draft.status === 'archived') {
      wrap.appendChild(el('span', 'text-sm text-slate-500',
        draft.status === 'posted' ? 'Already added.' : 'Archived.'));
      return wrap;
    }

    if (draft.destination !== 'hold') {
      var confirm = el('button', 'cap-btn primary',
        draft.status === 'send_failed' ? 'Try again' : 'Confirm');
      confirm.type = 'button';

      var blocked = draft.destination === 'petty_cash' && !openReports.length;
      if (blocked) {
        confirm.disabled = true;
        confirm.title = 'You need an open petty cash report first.';
      }
      confirm.addEventListener('click', function () { submit(draft, confirm); });
      wrap.appendChild(confirm);

      if (blocked) {
        wrap.appendChild(el('span', 'text-sm text-slate-500',
          'You need an open petty cash report first.'));
      }
    }

    var archive = el('button', 'cap-btn ghost', 'Archive');
    archive.type = 'button';
    archive.addEventListener('click', function () { archiveDraft(draft, archive); });
    wrap.appendChild(archive);

    return wrap;
  }

  // -------------------------------------------------------------- actions
  function collect(root) {
    var values = {};
    root.querySelectorAll('input[name], select[name]').forEach(function (node) {
      values[node.name] = node.value;
    });
    return values;
  }

  function submit(draft, button) {
    var root = list.querySelector('[data-draft-id="' + draft.id + '"]');
    var url = draft.status === 'send_failed'
      ? '/capture/draft/' + draft.id + '/retry'
      : '/capture/draft/' + draft.id + '/confirm';

    root.classList.add('is-busy');
    post(url, collect(root)).then(function (result) {
      root.classList.remove('is-busy');
      if (!result.ok) {
        flash(root, (result.data && result.data.message) || 'That did not work.');
        return;
      }
      announce(result.data.message || 'Done.');
      if (result.data.status === 'posted') {
        root.remove();
        refreshCount();
      } else {
        load();
      }
    }).catch(function () {
      root.classList.remove('is-busy');
      flash(root, 'We could not reach the server. Please try again.');
    });
  }

  function archiveDraft(draft, button) {
    var root = list.querySelector('[data-draft-id="' + draft.id + '"]');
    root.classList.add('is-busy');
    post('/capture/draft/' + draft.id + '/reject', {}).then(function (result) {
      root.classList.remove('is-busy');
      if (!result.ok) {
        flash(root, (result.data && result.data.message) || 'That did not work.');
        return;
      }
      root.remove();
      refreshCount();
      announce('Archived.');
    });
  }

  function flash(root, text) {
    var existing = root.querySelector('.cap-note.err');
    if (existing) { existing.remove(); }
    var note = el('div', 'cap-note err', text);
    root.querySelector('.cap-fields').appendChild(note);
  }

  function announce(text) { if (live) { live.textContent = text; } }

  // --------------------------------------------------------------- loading
  function refreshCount() {
    var showing = list.children.length;
    count.textContent = showing ? showing + (showing === 1 ? ' draft' : ' drafts') : '';
    empty.hidden = showing > 0;
  }

  function load() {
    var url = CONFIG.draftsUrl +
      '?entity_id=' + encodeURIComponent(CONFIG.entityId) +
      (status ? '&status=' + encodeURIComponent(status) : '');

    fetch(url, { credentials: 'same-origin' })
      .then(function (response) { return response.ok ? response.json() : { drafts: [] }; })
      .then(function (data) {
        list.textContent = '';
        (data.drafts || []).forEach(function (draft) { list.appendChild(card(draft)); });
        refreshCount();
      })
      .catch(function () { announce('Could not load the queue.'); });
  }

  filters.addEventListener('click', function (event) {
    var button = event.target.closest('.cap-filter');
    if (!button) { return; }
    filters.querySelectorAll('.cap-filter').forEach(function (node) {
      node.classList.toggle('is-on', node === button);
    });
    status = button.dataset.status || '';
    load();
  });

  // Open reports first: the Confirm button's availability depends on whether
  // there is one, so loading the cards before this answer would render every
  // petty cash card enabled and then disable it a moment later.
  fetch(CONFIG.reportsUrl + '?entity_id=' + encodeURIComponent(CONFIG.entityId),
        { credentials: 'same-origin' })
    .then(function (response) { return response.ok ? response.json() : { reports: [] }; })
    .then(function (data) { openReports = data.reports || []; })
    .catch(function () { openReports = []; })
    .then(load);
})();
