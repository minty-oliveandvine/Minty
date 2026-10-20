# Error & warning message audit

How user-facing error copy works, what was fixed, and what is left. This file is the canonical
statement of the copy standard for every repo.

**Status: the leak classes below are closed.** Keep this updated — an earlier version of this
file sat stale for months and sent the next reader chasing issues that had already been fixed.

**Flask draws no page since 2026-10-20**, so it has no browser-side scrubber any more (the
`mintyErrorCopy` / `mintyApiError` globals went with its templates). Its whole part is to answer
every failure as JSON with copy that follows the standard below; the Next apps show it.

---

## The other repos

Each repo has its own `ERROR_COPY.md` describing its mechanism.

| Repo | Mechanism | Talks to |
|---|---|---|
| Minty (here) | JSON only: `{"status": "error", "message": …}` or `{"error": …}` from every route and error handler (`pettycash/core/hooks.py`) | serves the Next apps |
| minty-payment-request-web | `normalizeApiErrorDetail` + `readsAsProse` in `lib/api.ts`; `lib/payerPortal.ts` | Django billing backend, and Minty |
| onboarding | `friendlyError` / `errorCopy` in `lib/errorCopy.js` | Minty only |
| minty-payment-request-api | `core/exceptions.py` handlers | serves minty-payment-request-web |

The cross-repo bug worth remembering: django-ninja answers a schema failure with
`detail: [{type, loc, msg}, ...]`, and minty-payment-request-web used to `JSON.stringify`
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
Defaults must be **cause-neutral** — a default that names one cause lies for every caller that
passed nothing.

---

## Backend

### Every error is JSON — `pettycash/core/hooks.py`

Handlers exist for **500**, **CSRF** (400, `code: "csrf_expired"`) and **`HTTPException`**
(`HTTP_ERROR_COPY`: 400, 401, 403, 404, 405, 409, 413, 429, else a generic sentence). Since
2026-10-20 they answer JSON whatever the caller asked for: there is no HTML error page left. The
read-only superuser block (403) is JSON too. A refused browser request through `services/authz.py`
(`_forbidden`) is the one redirect: the message is flashed and carried by `/entity` to minty-web's
company list; a JSON caller gets 403 with `message` and `reason`.

One thing to preserve: the `HTTPException` handler **must not** rewrite anything under 400.
Werkzeug's trailing-slash `RequestRedirect` is an `HTTPException` with code 308; returning JSON
for it breaks the redirect.

### Response envelopes are inconsistent — still true

Two competing shapes, split by blueprint, not by route: `{"status": "error", "message": …}`
(`auth/`, `xero/`, `legal/`, the global handlers) and `{"error": …}` (`entity/routes/create.py` -
the onboarding API - and the Petty Cash bearer API). Unifying them is worthwhile but out of scope.

There is **no machine-readable error code** beyond a few strings (`session_expired`,
`csrf_expired`, `terms_acceptance_required`, `version_changed`, the authz `reason`s); copy is
authored at each raise site.

### Not leaks, despite appearances

- `services/auth/token_service.py` — `token_expired()` returns a **tuple** on
  failure as a sentinel. Both callers (`hooks.py`, the refresh flow) branch on
  `isinstance(..., tuple)`. It never reaches a response body. Keep the shape.
- `blueprints/xero/services/publish_errors.py` — the `<= 120` char passthrough
  is deliberate: a real Xero validation sentence ("Account code 'X' is not a
  valid code for this document") is exactly what the user needs to fix their
  mapping. It is gated on `_reads_as_prose()`, which rejects serialised
  bodies, markup, stack text and bare GUIDs.

---

## Still open

- **`{"skipped": true}` semantics.** `blueprints/entity/routes/billing_sync.py`
  returns **500** when it catches an exception, instead of 200. The consumer
  (`minty-payment-request-api/bills/services/flask_billing_sync.py`) logs any `>= 400` at
  ERROR and still returns `True`, so nothing downstream changed shape — but the
  other `{"skipped": true, "reason": …}` 200s in that file are genuine skips and
  were left alone.
- **Envelope unification** (`error` vs `status`/`message`) — see above.

## How to verify a fix

1. Any 404 or 405 answers JSON (`tests/test_flask_backend_only.py`). (A logged-out call to a
   `@login_required` route is still Flask-Login's redirect to `/`, the sign-in hand-off.)
2. `tests/test_zz_no_html_frontend.py` fails if any GET route answers `text/html`.
