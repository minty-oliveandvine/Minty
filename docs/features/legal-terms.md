# Terms of Use and consent

What a person agrees to, how the wording is versioned, and how the app makes sure nobody
uses it without agreeing.

**The documents are minty-web's since 2026-10-12.** The `.md` files, the Markdown renderer,
the public pages and the fingerprints printed on them live in `minty-web/lib/legal/` and are
served at `my.dailyminty.com/terms` and `/privacy`
([minty-web/docs/features/legal.md](../../../minty-web/docs/features/legal.md)). This app keeps
the **record** — `terms_consent`, the gate, and the version manifest that decides what a record
may name. The invariant:

> **This app names the version. minty-web supplies the text.**

Code here: `legal/registry.py` (the manifest), `blueprints/legal/` (the gate, the consent model
and service, the two bearer routes). The runbook with the product decisions is
`docs/terms/T&C runbookv2.md`.

## What moved, and what that cost

Deleted from this app: `legal/terms/*.md` and `legal/privacy/*.md`, `legal/render.py`,
`templates/legal/` (the whole panel: `accept.html`, `document.html`, `_terms_panel.html`,
`_terms_script.html`, `_terms_styles.html`, `_terms_read_modal.html`),
`blueprints/legal/routes/accept.py`, `static/img/minty_important_update.png`, and the document
routes in what is now `blueprints/legal/routes/consent_status.py`.

Two consequences worth knowing:

- **minty-web is part of this app's sign-in path** for anyone who owes an acceptance. The gate
  redirects them to `/entity`, which hands over to minty-web, which draws the panel. There is no
  Flask screen to fall back on if minty-web is down. (`/entity` has been an unconditional
  hand-off since phase 2, so this widens an existing dependency rather than creating one.)
- **The page someone was trying to reach is no longer remembered.** `terms_next` and the
  `remember_intended_destination` / `take_intended_destination` pair went with `/legal/accept`:
  the panel lifts where the person stands, in minty-web, and never returns here to resume a
  Flask destination.

Flask's old addresses **404** — deleted outright, no redirect (the owner's decision). Nothing in
any repo links to them, and the pinned document names no URL of its own, only
`hello@dailyminty.com`.

## The manifest (`legal/registry.py`)

A text-free table: per published version, its `sha256`, its `effective_date` and whether it is
`pinned`. `sha256` is **mandatory for `terms`** — it is the number stamped into
`terms_consent.document_hash`, so a version without one could be agreed to but not recorded.
`privacy` may have none: no consent is ever recorded for the Privacy Policy, and minty-web's own
registry supplies the fingerprint its `/privacy` page prints.

Rules, unchanged: a published version is **never edited** (a change is a new version, `beta-2`);
old versions are never deleted; `terms/beta-1` is pinned to
`c90a335e…` and effective **18 September 2026**; `privacy/beta-1` is an unpinned placeholder and
shows the draft notice.

`verify_manifest()` runs at start-up. It **cannot verify the wording any more** — there is no
file here — so it only catches a live version missing from the manifest (which would stop the
gate enforcing) and a `terms` version with no fingerprint.

### Keeping the two repos in step

`MANIFEST` here and `PINNED_HASHES` in `minty-web/lib/legal/registry.server.ts` are the same
table. **Change them together.** What catches a divergence, earliest first:

1. minty-web's `lib/legal/__tests__/registry.test.ts` — re-hashes every `.md` and holds
   `c90a335e…` as a frozen literal.
2. `tests/test_legal_manifest.py` — this table's invariants and the same frozen literal.
3. `verify_manifest()` at start-up — a live version with no entry.
4. The stack e2e job — the two **running** services compared.
5. `POST /api/me/terms/accept`'s 409 `document_mismatch` — the last line, and unreachable in
   normal operation.

## The routes

| Route | What |
|---|---|
| `GET /api/me/terms` | minty-web's Terms panel: `{owed: false}`, or which version is owed — its number, effective date, draft flag and **`sha256`** — plus whether this is a re-acceptance and of which version. No wording, no links. |
| `POST /api/me/terms/accept` | the record. `{accepted, terms_version, document_hash}` |
| `GET /legal/current` | which version is live (`terms_version`, `privacy_version`, `effective_date`). Read by minty-web's sign-up screen before anyone has an account, which then fetches that version's text from its own registry. No URLs: `terms_url`/`privacy_url` pointed at deleted pages. |
| `POST /legal/invite-terms-status` | whether the person an invite was sent to still owes consent (the invite token in the JSON body; GET refused since 2026-10-05). Fails **safe**. |
| `GET /minty/api/users/<id>/consents` | a person's consent history (superuser). The fingerprint to check a row against is at the foot of minty-web's `/terms/<version>`. |

Both bearer routes are `blueprints/legal/routes/hub.py` on `blueprints/shared/hub_api.py`.

## The record

`terms_consent`: `user_id`, `terms_version`, `document_hash` (the fingerprint of what was
shown), `accepted_at`, `source`, `ip_address`, `user_agent`. Sources: `gate` (the deleted
acceptance screen — historical rows keep it), `signup_otp` (the tick box on self-serve sign-up),
`signup_invite` (an invited sign-up), `hub` (minty-web's panel, since 2026-09-29). `source` is a
plain `VARCHAR(32)` with no check constraint, here and in production, so a new source is no
schema change.

**The hash is never taken from the client.** The caller says which *version* was shown; the
fingerprint is looked up from the manifest. Since the documents moved, minty-web does send a
`document_hash` — the route **compares** it and refuses a mismatch with 409 `document_mismatch`,
logged at ERROR, then discards it. That is a canary against a stale bundle filing a row against
wording nobody saw, not an integrity control (the client picks the value it sends). Omitted, it
is not checked: a client too old to send one is not a client sending a wrong one.

**Existing users get no record invented for them** — they meet the panel on their next sign-in.

## The gate

`blueprints/legal/routes/gate.py::require_terms_acceptance` runs before every request
([authentication.md](authentication.md) §4): a signed-in user without a record for the current
version is redirected to `/entity`, which hands over to minty-web, which draws the panel. JSON
callers get a JSON 403 `terms_acceptance_required`.

The allow-list is keyed on **endpoint names**. Load-bearing:

- **`entity.entity_list`** — where the gate sends people. Gate it and the redirect points at a
  page we block: a loop with no exit, for everybody. The bounded cost is that someone who has not
  agreed reaches minty-web's list and could read their company *names* by removing the panel in
  devtools; they still cannot **enter** any company, because every other entity route stays gated
  here.
- **`auth.logout`** — someone who refuses must be able to leave.
- **the login/OTP endpoints** — or nobody can authenticate to reach the panel.
- `legal.current`, `legal.invite_terms_status`, `legal.hub_terms_status`,
  `legal.hub_terms_accept` — read or posted while blocked, two of them before anyone is signed
  in. `legal.user_consents` stays **gated**, deliberately.

It **fails open**: if the hook raises, the request goes through and the error is logged loudly.
minty-web's gate fails open the same way — including when its document and this app's manifest
disagree, which is the one case where showing nobody a document is better than showing the wrong
one.

An acceptance given in minty-web is honoured here on the person's next Flask page: the gate falls
back to the database whenever its session cache has no answer. That cache stores the **version**,
not a flag, so a Terms revamp invalidates every session by itself.

## Tests

`tests/test_legal_manifest.py` (the manifest's invariants, the frozen fingerprint,
`/legal/current`, and that the document pages are gone), `tests/test_terms_gate.py` (the
allow-list first — it is the lock-out risk — the redirect, the JSON 403, the session cache, the
revamp path, failing open), `tests/test_hub_terms.py` (minty-web's two routes, the payload shape,
the `document_hash` compare), `tests/test_terms_consent.py` (the server-side hash, idempotency,
never committing), `tests/test_terms_signup_consent.py` (account and consent in one transaction),
`tests/test_terms_consent_history_api.py`, and `tests/test_url_security.py`'s deleted-routes
list. In the browser `e2e/01_login.spec.ts` (first sign-in shows minty-web's panel; it is never
accepted on that account) — which needs minty-web up — and minty-web's `e2e/09_terms.spec.ts`,
which shows the real document.

The documents' own tests are minty-web's: `lib/legal/__tests__/{registry,render,serverOnly}.test.ts`
and `components/ui/__tests__/LegalDocumentPage.test.tsx`.
