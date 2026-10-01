# Error & warning message audit

How user-facing error copy works in this app, what was fixed, and what is left.

**Status: the leak classes below are closed.** This document previously tracked
an open backlog; that backlog has been worked. Keep it updated — an earlier
version of this file sat stale for months and sent the next reader chasing
issues that had already been fixed.

---

## The mechanism: one scrubber, because there is no API client

There is **no shared API client** in this app. Every call site does a bare
`fetch()` with its own hand-rolled `.then/.catch`, so there is no natural place
to turn a failure into human copy.

`templates/components/flash_messages.html` is therefore the chokepoint. It is
included by 39 templates and installs two globals:

```js
window.mintyErrorCopy(message, fallback)   // scrub a string
window.mintyApiError(error, fallback)      // scrub a caught Error
```

`mintyErrorCopy` replaces anything matching `RAW_ERROR_PATTERNS` (`Failed to
fetch`, `Unexpected token '<'`, `HTTP 500`, `Server error (502): …`,
`Traceback`, `[object Object]`, anything over 200 chars, non-strings) with the
caller's fallback. It also joins string arrays and drops non-string members, so
a validation payload can be passed straight in.

`showFlashMessages` runs error and warning copy through it automatically.
Success and info pass through untouched.

### The `fromServer` convention

`mintyApiError` only shows `error.message` when the error is tagged
`fromServer` — i.e. the server actually authored the text:

```js
const err = new Error(data.error || 'Request failed');
err.fromServer = Boolean(data.error);   // 'Request failed' is OURS, not the server's
throw err;
```

Anything reaching a `.catch()` without that flag is a JS/network/parse failure
and must never be surfaced. **When you add a `fetch()`, tag its throw.**

### No page keeps its own toast

Until 2026-10-01 `templates/entity/settings.html` and
`templates/entity/settings_users_scripts.html` redefined `showErrorToast` over their own DOM
(`#settingsNotification` / `#errorToast`), and eight other pages had toast copies of their
own, some putting server text in with `innerHTML`. All of them now call the shared
`showFlashMessages`, so every error and warning toast goes through `mintyErrorCopy` and is set
as text. **Never add a page-level toast function**: a top-level `function showErrorToast`
silently replaces the shared one. See [toasts.md](toasts.md).

---

## The other repos

This standard is shared across the product. Each repo has its own `ERROR_COPY.md`
describing its mechanism; this file is the canonical statement of the standard
itself.

| Repo | Mechanism | Talks to |
|---|---|---|
| Minty (here) | `mintyErrorCopy` / `mintyApiError` in `templates/components/flash_messages.html` | itself |
| billing-frontend | `normalizeApiErrorDetail` + `readsAsProse` in `lib/api.ts`; `lib/payerPortal.ts` | Django billing backend, and Minty |
| onboarding | `friendlyError` / `errorCopy` in `lib/errorCopy.js` | Minty only |
| billing-backend | `core/exceptions.py` handlers | serves billing-frontend |

The cross-repo bug worth remembering: django-ninja answers a schema failure with
`detail: [{type, loc, msg}, ...]`, and billing-frontend used to `JSON.stringify`
that into a toast. Neither side was unreasonable alone. Both ends are guarded now.

## The copy standard

> `I couldn't <do the specific thing>. <Short next step>?`

1. Under two sentences. One clause naming what failed, one short offer to retry.
2. First person, Minty speaking — not `Error:`, not `Failed to`.
3. Name the specific thing — *"that invitation"*, not *"the operation"*.
4. Warm close, no blame. Drop the apology when retrying won't help (validation,
   a hard limit) and state the requirement instead: `Files need to be under 10MB.`
5. No error codes or stack text in the visible string. That goes to the log.
6. Sentence case, no `Error:` prefix, no exclamation marks on failures.

House fallback for unknown causes: `Something went wrong on my end. Mind trying again?`
Defaults must be **cause-neutral** — `settings.html` used to default to
"Please connect to Xero and set up Entity Settings", which lied for every caller
that passed nothing.

---

## Backend

### Content negotiation — `pettycash/core/hooks.py`

Handlers exist for **500**, **CSRF**, and **`HTTPException`** (the last added in
this pass). Before that, nothing handled 400/401/403/404/405, so `abort(404)`
and every `@login_required` rejection returned Werkzeug's **HTML** page — which
a `fetch()` then died on inside `response.json()` as `Unexpected token '<'`.
That string was the app's most common unreadable toast, and it was produced
here, not in the browser.

`_wants_json()` is the shared negotiation helper. Two things to preserve:

- The handler **must not** rewrite anything under 400. Werkzeug's trailing-slash
  `RequestRedirect` is an `HTTPException` with code 308; returning JSON for it
  breaks the redirect.
- `handle_500_error` still special-cases the literal path
  `/report/expense/submit_all`. Don't expand that pattern.

### Response envelopes are inconsistent — still true

Two competing shapes, split by blueprint, not by route:

| Shape | Count | Where |
|---|---|---|
| `{"status": "error", "message": …}` | ~235 | `report/`, `auth/`, `xero/`, `legal/`, the global handlers |
| `{"error": …}` | ~131 | `entity/routes/create.py` (71), `entity/routes/settings.py` (33), `subscription/routes/portal.py` (13) |

`entity/routes/settings.py` uses **both** — `{"error": …}` for billing routes,
`{"status": "error", "message": …}` for the Xero-contact routes below them. The
frontend reads `data.message` at ~51 sites and `data.error` at ~17. Unifying
these is worthwhile but was out of scope here.

There is **no machine-readable error code**. Four string codes exist
(`session_expired`, `csrf_expired`, `terms_acceptance_required`,
`version_changed`) and **no template or JS reads `.code`** — they are dead
weight on the wire. Any future friendly-message mapping layer has nothing to map
against; copy is authored at each raise site.

### Not leaks, despite appearances

- `services/auth/token_service.py` — `token_expired()` returns a **tuple** on
  failure as a sentinel. Both callers (`hooks.py`, the refresh flow) branch on
  `isinstance(..., tuple)`. It never reaches a response body. Keep the shape.
- `blueprints/subscription/routes/portal.py` — `_MissingField` text is authored
  by `_required()` and names the field **on purpose**;
  `test_payer_portal_api.py::test_initiating_a_handover_needs_an_entity`
  asserts it. Do not genericise it.
- `blueprints/xero/services/publish_errors.py` — the `<= 120` char passthrough
  is deliberate: a real Xero validation sentence ("Account code 'X' is not a
  valid code for this document") is exactly what the user needs to fix their
  mapping. It is now gated on `_reads_as_prose()`, which rejects serialised
  bodies, markup, stack text and bare GUIDs.
- The six duplicated create-contact blocks in `settings.html` and
  `xero_mapping_classic_script_fragment.html` throw jargon
  (`'Network response was not ok'`, `'Server returned non-JSON response.'`) but
  every one of their `.catch()` blocks shows fixed copy and never reads
  `error.message`. The jargon feeds `sendLogToDataDog` — it is diagnostic value.
  Leave it.

---

## Dead code found while doing this

`static/js/expense.js`, `opening.js` and `login.js` had **zero** references
anywhere and held 12 blocking `alert()` calls. Deleted.

**`static/js/scripts.js` has never parsed.** Line 28 is a truncated string
literal (`document.getElementById('noE`) and has been that way since the file
was first committed in `42f73fa`. The whole file is a SyntaxError, so none of it
runs — including `submitForm`, `handleDownloadStatements` and every
`calculateTotal*`.

It is loaded by `templates/index.html` and `templates/edit_report.html`, and
**neither template is rendered by any route** — no `render_template("index.html")`
or `("edit_report.html")` exists. That is why a permanently broken file never
caused a visible problem: all three are orphaned legacy files.

**Do not "fix" line 28 in isolation.** Repairing it would activate ~800 lines of
code that has never once run. Either delete all three files, or revive them
deliberately with testing. The `alert()` calls inside `scripts.js` were
converted to toasts for consistency, but nothing in that file executes today.

Three unreachable stubs whose only body was a blocking `alert()` were removed:
`saveAsImage()` / `generatePDF()` in `templates/report/submitted.html` (their
buttons are commented out with `{# #}`) and `saveAndNext()` in
`templates/report/cash_count.html` (no callers).

---

## Still open

- **`{"skipped": true}` semantics.** `blueprints/entity/routes/billing_sync.py`
  now returns **500** when it catches an exception, instead of 200. The consumer
  (`billing-backend/bills/services/flask_billing_sync.py`) logs any `>= 400` at
  ERROR and still returns `True`, so nothing downstream changed shape — but the
  other `{"skipped": true, "reason": …}` 200s in that file are genuine skips and
  were left alone.
- **Envelope unification** (`error` vs `status`/`message`) — see above.
- **Placeholder copy.** `'This feature is currently in progress, Stay Tuned!'`
  still ships at several sites. Not errors, but user-facing dead ends; decide
  whether to hide, disable, or write real copy.

## How to verify a fix

1. `window.mintyErrorCopy('Failed to fetch')` in the console should return the
   house fallback; a real sentence should pass through unchanged.
2. Force a non-JSON error (point an endpoint at a URL returning HTML) and
   confirm the toast reads friendly copy rather than `Unexpected token '<'`.
3. `fetch()` a route behind `@login_required` while logged out with
   `Accept: application/json` — assert a JSON body, not Werkzeug HTML.
4. Sweep: this should return nothing.
   ```
   grep -rnE '(notifyError|showErrorToast|showFlashErrorToast|showNotification|publishingFailed|showToast)\((err|error)\.message' templates/
   ```
5. The suite is **not green at HEAD** (~90 non-passing). Diff a full run against
   a full run and grep `ERROR` as well as `FAILED`; a single-file run tells you
   nothing.
