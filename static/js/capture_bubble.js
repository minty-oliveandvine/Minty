/*
 * The AI Hub bubble — upload, badge, and a short recent list.
 *
 * Loaded ONLY when the context processor decided the bubble should render, so
 * this file never runs for a signed-out visitor or a company without the
 * module. With the kill switch off the page never receives it at all.
 *
 * FOUR RULES THIS FILE EXISTS TO KEEP
 *
 *   NOTHING FROM A DOCUMENT IS EVER innerHTML. Filenames, locators and
 *   supplier names came off a file somebody else supplied. textContent only.
 *
 *   THE POLL ALWAYS STOPS. When nothing is processing, when the tab is
 *   hidden, and unconditionally after five minutes. A poll loop that outlives
 *   its reason is a bug that only shows up in production, in aggregate.
 *
 *   ONE UPLOAD AT A TIME. Several files go one after another. Firing five
 *   concurrent uploads would put five model calls in flight from one click.
 *
 *   THE SERVER'S MESSAGE IS THE MESSAGE. A 4xx body was written in plain
 *   English for the user; show it rather than inventing something vaguer.
 */
(function () {
  'use strict';

  var CONFIG = window.CAPTURE_HUB || {};
  if (!CONFIG.uploadUrl) { return; }

  var POLL_MS = 2000;
  var POLL_CEILING_MS = 5 * 60 * 1000;

  var btn = document.getElementById('capBubbleBtn');
  var panel = document.getElementById('capBubblePanel');
  var closeBtn = document.getElementById('capCloseBtn');
  var drop = document.getElementById('capDrop');
  var input = document.getElementById('capFile');
  var badge = document.getElementById('capBadge');
  var message = document.getElementById('capMessage');
  var recentWrap = document.getElementById('capRecentWrap');
  var recent = document.getElementById('capRecent');
  var live = document.getElementById('capLiveRegion');

  /* The CSRF token, read from the hidden input the partial renders. These
     endpoints are session-authenticated and therefore CSRF-protected like any
     other write in this app. Without the header the POST is redirected to the
     login page and the browser parses an HTML 200 as JSON — which looks like a
     mysterious upload failure rather than a missing token. */
  function csrfHeader() {
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? { 'X-CSRFToken': input.value } : {};
  }

  var queue = [];        // files waiting their turn
  var busy = false;      // an upload is in flight
  var pollTimer = null;
  var pollStarted = 0;

  // ------------------------------------------------------------ open/close
  function open() {
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    refresh();
  }

  function close() {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    btn.focus();
  }

  btn.addEventListener('click', function () {
    if (panel.hidden) { open(); } else { close(); }
  });
  closeBtn.addEventListener('click', close);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !panel.hidden) { close(); }
  });

  // Dragging anything over the window opens the panel, so the user does not
  // have to click first and then drag a second time.
  window.addEventListener('dragover', function (event) {
    if (!event.dataTransfer) { return; }
    var types = event.dataTransfer.types || [];
    if (Array.prototype.indexOf.call(types, 'Files') === -1) { return; }
    event.preventDefault();
    if (panel.hidden) { open(); }
  });
  window.addEventListener('drop', function (event) {
    // Without this the browser navigates away to display the dropped file,
    // which loses whatever the user was in the middle of.
    if (event.target && !drop.contains(event.target)) { event.preventDefault(); }
  });

  // ---------------------------------------------------------------- picking
  drop.addEventListener('click', function () { if (!busy) { input.click(); } });
  drop.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!busy) { input.click(); }
    }
  });

  drop.addEventListener('dragover', function (event) {
    event.preventDefault();
    drop.classList.add('is-over');
  });
  drop.addEventListener('dragleave', function () { drop.classList.remove('is-over'); });
  drop.addEventListener('drop', function (event) {
    event.preventDefault();
    drop.classList.remove('is-over');
    accept(event.dataTransfer && event.dataTransfer.files);
  });

  input.addEventListener('change', function () {
    accept(input.value ? input.files : null);
    input.value = '';
  });

  function accept(files) {
    if (!files || !files.length) { return; }
    for (var i = 0; i < files.length; i++) { queue.push(files[i]); }
    pump();
  }

  // ------------------------------------------------------------- uploading
  function pump() {
    if (busy || !queue.length) { return; }
    var file = queue.shift();

    // A courtesy check, NOT security — the server re-checks everything from
    // the bytes. It just saves a 10 MB round trip to be told no.
    var problem = quickCheck(file);
    if (problem) {
      show(problem, 'err');
      pump();
      return;
    }

    busy = true;
    drop.classList.add('is-busy');
    show('Reading ' + file.name + '…', 'ok');

    var body = new FormData();
    body.append('file', file);
    body.append('entity_id', CONFIG.entityId);

    fetch(CONFIG.uploadUrl, {
      method: 'POST',
      body: body,
      credentials: 'same-origin',
      headers: Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, csrfHeader())
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (result.data && result.data.duplicate) {
          show(result.data.message || 'You already uploaded this file.', 'ok');
        } else if (!result.ok) {
          // The server wrote this sentence for the user. Show it.
          show((result.data && result.data.message) || 'That file could not be read.', 'err');
        } else {
          show('Reading it now…', 'ok');
          announce('Upload accepted. Reading the document.');
          startPolling();
        }
      })
      .catch(function () {
        show('We could not reach the server. Please try again.', 'err');
      })
      .then(function () {
        busy = false;
        drop.classList.remove('is-busy');
        refresh();
        pump();
      });
  }

  function quickCheck(file) {
    var name = (file.name || '').toLowerCase();
    var okType = /\.(pdf|jpe?g|png)$/.test(name) ||
      ['application/pdf', 'image/jpeg', 'image/png'].indexOf(file.type) !== -1;
    if (!okType) { return 'Only PDF, JPG and PNG files can be read.'; }
    if (CONFIG.maxMb && file.size > CONFIG.maxMb * 1024 * 1024) {
      return 'That file is larger than ' + CONFIG.maxMb + ' MB.';
    }
    if (file.size === 0) { return 'That file is empty.'; }
    // Page count is a SERVER check only. Counting PDF pages in the browser
    // means shipping a PDF library, and the server answers in well under a
    // second.
    return null;
  }

  // --------------------------------------------------------------- polling
  function startPolling() {
    pollStarted = Date.now();
    if (pollTimer) { return; }
    pollTimer = setInterval(tick, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function tick() {
    if (document.visibilityState === 'hidden') { return; }
    if (Date.now() - pollStarted > POLL_CEILING_MS) { stopPolling(); return; }
    refresh();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && pollTimer) { refresh(); }
  });

  var lastAttention = null;

  function refresh() {
    var url = CONFIG.statusUrl + '?entity_id=' + encodeURIComponent(CONFIG.entityId);
    fetch(url, { credentials: 'same-origin' })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) { return; }
        paintBadge(data.attention || 0);
        paintRecent(data.recent || []);
        if (!data.processing) { stopPolling(); }
        if (lastAttention !== null && data.attention > lastAttention) {
          announce(data.attention + ' drafts ready for review.');
        }
        lastAttention = data.attention;
      })
      .catch(function () { /* a failed poll is not worth telling anyone about */ });
  }

  function paintBadge(count) {
    if (!count) { badge.hidden = true; return; }
    badge.hidden = false;
    badge.textContent = count > 99 ? '99+' : String(count);
  }

  function paintRecent(rows) {
    recent.textContent = '';
    if (!rows.length) { recentWrap.hidden = true; return; }
    recentWrap.hidden = false;

    rows.forEach(function (row) {
      var line = document.createElement('div');
      line.className = 'cap-row';

      var name = document.createElement('span');
      name.className = 'cap-name';
      // textContent: this is a filename somebody else chose.
      name.textContent = row.filename;

      var state = document.createElement('span');
      state.className = 'cap-state' + (isBad(row.status) ? ' bad' : '');
      state.textContent = describe(row);

      line.appendChild(name);
      line.appendChild(state);
      recent.appendChild(line);
    });
  }

  function isBad(status) {
    return status === 'failed' ||
      status === 'rejected_not_supported' ||
      status === 'rejected_too_many';
  }

  function describe(row) {
    switch (row.status) {
      case 'queued': return 'waiting…';
      case 'processing': return 'reading…';
      case 'done':
        return (row.document_count || 1) === 1
          ? '1 draft'
          : row.document_count + ' drafts';
      case 'rejected_not_supported': return 'not a receipt';
      case 'rejected_too_many': return 'too many items';
      case 'failed': return 'could not read';
      default: return row.status;
    }
  }

  function show(text, kind) {
    message.textContent = '';
    if (!text) { return; }
    var box = document.createElement('div');
    box.className = 'cap-msg ' + (kind || 'ok');
    box.textContent = text;
    message.appendChild(box);
  }

  function announce(text) {
    if (live) { live.textContent = text; }
  }

  // One quiet check on load, so a user who left drafts behind yesterday sees
  // the badge without opening anything.
  refresh();
})();
