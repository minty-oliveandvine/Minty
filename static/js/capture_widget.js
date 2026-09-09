/*
 * The AI Hub bubble, for a page that is NOT Minty.
 *
 * Loaded by Module 2's module-selection page with one script tag:
 *
 *   <script
 *     src="http://localhost:5001/static/js/capture_widget.js"
 *     data-minty="http://localhost:5001"
 *     data-token="<the JWT this page already holds>"
 *     data-entity="<the entity_id already in this page's URL>"
 *     defer></script>
 *
 * WHY A SCRIPT AND NOT A REBUILD
 *
 * The bubble on Minty's own pages is a Jinja partial. This is the same bubble
 * for a React application on another origin. Both load the SAME stylesheet
 * (static/css/capture_hub.css) and call the SAME endpoints, so there is one
 * look and one API to keep working, not two.
 *
 * The markup is built here rather than fetched because fetching HTML to inject
 * into another application's DOM is a worse trade: it needs its own CORS
 * surface, and it puts a network round trip in front of a button.
 *
 * AUTHENTICATION
 *
 * A browser will not send Minty's session cookie on a request made from port
 * 3000, so this uses the JWT the host page already has:
 * `Authorization: Bearer <token>`. That token lasts 30 minutes. When it runs
 * out every call answers 401 and the widget says so plainly rather than
 * failing quietly — see `handleUnauthorised`.
 *
 * TWO RULES CARRIED OVER FROM THE MINTY BUBBLE
 *
 *   NOTHING FROM A DOCUMENT IS EVER innerHTML. Filenames came off files
 *   somebody else supplied. textContent only.
 *
 *   THE POLL ALWAYS STOPS. When nothing is processing, when the tab is hidden,
 *   and unconditionally after five minutes.
 */
(function () {
  'use strict';

  var script = document.currentScript ||
    (function () {
      var all = document.getElementsByTagName('script');
      return all[all.length - 1];
    })();
  if (!script) { return; }

  var CONFIG = {
    // Where Minty is. Falls back to the origin this script was served from,
    // which is the right answer in every deployment and saves the host page
    // having to know it twice.
    base: (script.getAttribute('data-minty') ||
           new URL(script.src, window.location.href).origin).replace(/\/$/, ''),
    token: script.getAttribute('data-token') || '',
    entityId: script.getAttribute('data-entity') || ''
  };

  // Without a company or a token there is nothing this can safely do. Render
  // nothing at all rather than a button that fails when pressed.
  if (!CONFIG.token || !CONFIG.entityId) { return; }
  if (document.getElementById('capBubbleBtn')) { return; }  // already present

  var POLL_MS = 2000;
  var POLL_CEILING_MS = 5 * 60 * 1000;
  var EXPIRED_MESSAGE = "Your session's expired, refresh the page.";

  var SPARKLE = '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M9.5 2.5 11 7l4.5 1.5L11 10l-1.5 4.5L8 10l-4.5-1.5L8 7z"/>' +
    '<path d="M17.5 12.5 18.4 15l2.6.9-2.6.9-.9 2.6-.9-2.6L14 15l2.6-.9z"/>' +
    '<path d="M16 3l.6 1.7 1.7.6-1.7.6L16 7.6l-.6-1.7-1.7-.6 1.7-.6z"/>' +
    '</svg>';
  var UPLOAD_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M12 3 7 8h3v6h4V8h3zM5 17h14v3H5z"/></svg>';

  var expired = false;
  var queue = [];
  var busy = false;
  var pollTimer = null;
  var pollStarted = 0;
  var lastAttention = null;
  var lastTriedToken = '';

  // ------------------------------------------------------------------ chrome
  function stylesheet() {
    var href = CONFIG.base + '/static/css/capture_hub.css';
    if (document.querySelector('link[href="' + href + '"]')) { return; }
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text) { node.textContent = text; }
    return node;
  }

  var btn, panel, drop, input, badge, message, recentWrap, recent, live, cta;

  function build() {
    btn = el('button', 'cap-bubble-btn');
    btn.type = 'button';
    btn.id = 'capBubbleBtn';
    btn.setAttribute('aria-label', 'AI Hub — upload a receipt or invoice');
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = SPARKLE;                      // our own markup, not a document's
    badge = el('span', 'cap-badge');
    badge.hidden = true;
    btn.appendChild(badge);

    panel = el('div', 'cap-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'AI Hub');
    panel.hidden = true;

    var head = el('div', 'cap-panel-head');
    head.appendChild(el('span', null, 'AI Hub'));
    var close = el('button', 'cap-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close');
    close.addEventListener('click', hide);
    head.appendChild(close);

    var body = el('div', 'cap-panel-body');
    body.appendChild(el('p', 'cap-intro',
      'Drop a receipt or invoice here and the AI will read it, split it if ' +
      'there is more than one, and create a draft for you to check — in Petty ' +
      'Cash or Payment Submission, whichever it belongs in. Nothing is saved ' +
      'until you confirm it.'));

    drop = el('div', 'cap-drop');
    drop.tabIndex = 0;
    drop.setAttribute('role', 'button');
    drop.setAttribute('aria-label', 'Drop a file here, or click to choose one');
    var icon = el('span', 'cap-drop-icon');
    icon.innerHTML = UPLOAD_ICON;
    drop.appendChild(icon);
    var strong = el('div');
    strong.appendChild(el('strong', null, 'Drop a file here'));
    drop.appendChild(strong);
    drop.appendChild(el('div', null, 'or click to choose one'));
    drop.appendChild(el('div', 'cap-hint', 'PDF, JPG or PNG · up to 3 pages · 10 MB'));
    body.appendChild(drop);

    input = document.createElement('input');
    input.type = 'file';
    input.hidden = true;
    input.accept = '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png';
    body.appendChild(input);

    message = el('div');
    body.appendChild(message);

    recentWrap = el('div', 'cap-recent');
    recentWrap.hidden = true;
    recentWrap.appendChild(el('h4', null, 'Recent'));
    recent = el('div');
    recentWrap.appendChild(recent);
    body.appendChild(recentWrap);

    cta = el('a', 'cap-go', 'Review drafts');
    cta.href = CONFIG.base + '/capture?entity_id=' + encodeURIComponent(CONFIG.entityId);
    // Opens Minty. The review queue lives there and is not duplicated here —
    // the bubble is the part worth having in two places, the queue is not.
    cta.target = '_blank';
    cta.rel = 'noopener';
    body.appendChild(cta);

    panel.appendChild(head);
    panel.appendChild(body);

    live = el('div');
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    live.style.cssText =
      'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);';

    document.body.appendChild(btn);
    document.body.appendChild(panel);
    document.body.appendChild(live);
  }

  function show() {
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    refresh();
  }

  function hide() {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    btn.focus();
  }

  // -------------------------------------------------------------------- auth
  /* The token, read fresh on EVERY request rather than captured once at load.
     The host application rotates it — billing-frontend has its own
     refreshToken() and re-writes the cookie — and a widget holding the value it
     saw at startup would start failing the moment that happened, on a page that
     was otherwise perfectly signed in.

     A host that wants this sets `window.captureHubToken` to a function
     returning the current token. Without one, the data-token attribute stands. */
  function currentToken() {
    var getter = window.captureHubToken;
    if (typeof getter === 'function') {
      try {
        var live = getter();
        if (live) { return live; }
      } catch (err) { /* fall through to the snapshot */ }
    }
    return CONFIG.token;
  }

  function headers(extra) {
    var base = { 'Authorization': 'Bearer ' + currentToken() };
    if (extra) {
      Object.keys(extra).forEach(function (k) { base[k] = extra[k]; });
    }
    return base;
  }

  /* The token lasts 30 minutes. When it runs out, say so once and stop —
     rather than a button that silently does nothing, or a poll that keeps
     asking a question already answered. */
  function handleUnauthorised(data) {
    // One retry with a freshly-read token before giving up: the host may have
    // rotated it between this request being sent and the answer coming back.
    var live = currentToken();
    if (live && live !== lastTriedToken) {
      lastTriedToken = live;
      refresh();
      return;
    }
    expired = true;
    stopPolling();
    note((data && data.message) || EXPIRED_MESSAGE, 'err');
    drop.classList.add('is-busy');
    if (panel.hidden) { show(); }
    announce(EXPIRED_MESSAGE);
  }

  // --------------------------------------------------------------- uploading
  function accept(files) {
    if (expired || !files || !files.length) { return; }
    for (var i = 0; i < files.length; i++) { queue.push(files[i]); }
    pump();
  }

  function pump() {
    if (expired || busy || !queue.length) { return; }
    var file = queue.shift();

    var problem = quickCheck(file);
    if (problem) { note(problem, 'err'); pump(); return; }

    busy = true;
    drop.classList.add('is-busy');
    note('Reading ' + file.name + '…', 'ok');

    var body = new FormData();
    body.append('file', file);
    body.append('entity_id', CONFIG.entityId);

    fetch(CONFIG.base + '/capture/upload', {
      method: 'POST',
      body: body,
      headers: headers()          // no Content-Type: the browser sets the boundary
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; })
          .then(function (data) { return { status: response.status, ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (result.status === 401) { handleUnauthorised(result.data); return; }
        if (result.data && result.data.duplicate) {
          note(result.data.message || 'You already uploaded this file.', 'ok');
        } else if (!result.ok) {
          note((result.data && result.data.message) || 'That file could not be read.', 'err');
        } else {
          note('Reading it now…', 'ok');
          announce('Upload accepted. Reading the document.');
          startPolling();
        }
      })
      .catch(function () {
        note('We could not reach Minty. Please try again.', 'err');
      })
      .then(function () {
        busy = false;
        if (!expired) { drop.classList.remove('is-busy'); }
        refresh();
        pump();
      });
  }

  function quickCheck(file) {
    var name = (file.name || '').toLowerCase();
    var okType = /\.(pdf|jpe?g|png)$/.test(name) ||
      ['application/pdf', 'image/jpeg', 'image/png'].indexOf(file.type) !== -1;
    if (!okType) { return 'Only PDF, JPG and PNG files can be read.'; }
    if (file.size > 10 * 1024 * 1024) { return 'That file is larger than 10 MB.'; }
    if (file.size === 0) { return 'That file is empty.'; }
    return null;
  }

  // ----------------------------------------------------------------- polling
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

  function refresh() {
    if (expired) { return; }
    fetch(CONFIG.base + '/capture/status?entity_id=' + encodeURIComponent(CONFIG.entityId),
          { headers: headers() })
      .then(function (response) {
        if (response.status === 401) {
          return response.json().catch(function () { return {}; })
            .then(function (data) { handleUnauthorised(data); return null; });
        }
        return response.ok ? response.json() : null;
      })
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
      var line = el('div', 'cap-row');
      // textContent: this is a filename somebody else chose.
      line.appendChild(el('span', 'cap-name', row.filename));
      line.appendChild(el('span', 'cap-state' + (isBad(row.status) ? ' bad' : ''),
                          describe(row)));
      recent.appendChild(line);
    });
  }

  function isBad(status) {
    return status === 'failed' || status === 'rejected_not_supported' ||
      status === 'rejected_too_many';
  }

  function describe(row) {
    switch (row.status) {
      case 'queued': return 'waiting…';
      case 'processing': return 'reading…';
      case 'done':
        return (row.document_count || 1) === 1 ? '1 draft' : row.document_count + ' drafts';
      case 'rejected_not_supported': return 'not a receipt';
      case 'rejected_too_many': return 'too many items';
      case 'failed': return 'could not read';
      default: return row.status;
    }
  }

  function note(text, kind) {
    message.textContent = '';
    if (!text) { return; }
    message.appendChild(el('div', 'cap-msg ' + (kind || 'ok'), text));
  }

  function announce(text) { if (live) { live.textContent = text; } }

  // ------------------------------------------------------------------- wire
  function start() {
    stylesheet();
    build();

    btn.addEventListener('click', function () {
      if (panel.hidden) { show(); } else { hide(); }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) { hide(); }
    });

    drop.addEventListener('click', function () { if (!busy && !expired) { input.click(); } });
    drop.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (!busy && !expired) { input.click(); }
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

    window.addEventListener('dragover', function (event) {
      if (!event.dataTransfer) { return; }
      var types = event.dataTransfer.types || [];
      if (Array.prototype.indexOf.call(types, 'Files') === -1) { return; }
      event.preventDefault();
      if (panel.hidden && !expired) { show(); }
    });
    window.addEventListener('drop', function (event) {
      // Without this the browser navigates away to display the dropped file.
      if (event.target && !drop.contains(event.target)) { event.preventDefault(); }
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && pollTimer) { refresh(); }
    });

    refresh();
  }

  /* Teardown, for a single-page application that unmounts the page this was
     added to. Without it the bubble outlives its host route and keeps polling
     a company the user has navigated away from. */
  window.CaptureHubWidget = {
    destroy: function () {
      stopPolling();
      [btn, panel, live].forEach(function (node) {
        if (node && node.parentNode) { node.parentNode.removeChild(node); }
      });
      btn = panel = live = null;
      delete window.CaptureHubWidget;
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
