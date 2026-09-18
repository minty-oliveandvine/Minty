# Terms of Use and consent

What a person agrees to, how the wording is versioned, and how the app makes sure nobody
uses it without agreeing. Code: `legal/` (the documents and the registry),
`blueprints/legal/` (routes, the consent model, the gate). The runbook with the product
decisions is `docs/terms/T&C runbookv2.md`.

## The documents

```
legal/terms/beta-1.md      the Terms of Use — the master copy, Markdown (the Word original
                           was converted to it and retired on 2026-09-18)
legal/privacy/beta-1.md    the Privacy Policy — still a placeholder (unpinned, no date)
legal/registry.py          versions, effective dates, pinned fingerprints
legal/render.py            the four-construct Markdown → HTML renderer (escapes first)
```

Rules: a published version is **never edited** — a change is a new version (`beta-2`);
old versions are never deleted. `registry.py` names the current version of each kind
(`CURRENT_TERMS_VERSION` / `CURRENT_PRIVACY_VERSION`, env-overridable), its effective
date (`terms/beta-1`: **18 September 2026**) and its **pinned SHA-256** over the `.md`
(`_PINNED_HASHES`). `verify_pinned_hashes()` runs at start-up and logs a warning while a
version is unpinned (privacy today) — pinning is the assertion that the wording is final,
which is why `terms/beta-1.md` must not be touched again (`terms-beta1-pinned` note).

`render.py` deliberately understands only `# title`, `## section`, `- bullet` and
`**bold**`, and HTML-escapes the text before applying them, so a legal document can never
inject markup into the page.

## The routes

| Route | What |
|---|---|
| `GET /legal/terms`, `/legal/terms/<version>`, `/legal/privacy[/<version>]` | the rendered documents |
| `GET /legal/current` | which versions are live — the sign-up screens send that name back |
| `GET /legal/content/<kind>` | the rendered document as JSON, for a client that must show it inline (the onboarding app's terms modal) |
| `GET /legal/accept` / `POST /legal/accept` | the acceptance screen (scroll to the end, tick, accept) and the record |
| `GET /legal/invite-terms-status` | whether the person an invite was sent to still owes consent |
| `GET /minty/api/users/<id>/consents` | a person's consent history (superuser) |

## The record

`terms_consent`: `user_id`, `terms_version`, `document_hash` (the fingerprint of what was
shown), `accepted_at`, `source`, `ip_address`, `user_agent`. Sources: `gate` (the
acceptance screen), `signup_otp` (the tick box on self-serve sign-up), `signup_invite`
(the tick box on an invited sign-up). `POST /legal/accept` refuses a version that is no
longer live (the Terms changed while the page sat open) and a submission without
`accepted: true`.

**Existing users get no record invented for them** — they meet the screen on their next
sign-in. The production `terms_consent` table starts empty at the cutover, so every user
accepts once (the announcement should say so).

## The gate

`blueprints/legal/routes/gate.py::require_terms_acceptance` runs before every request
([authentication.md](authentication.md) §4): a signed-in user without a record for the
current terms version is redirected to `/legal/accept` (JSON callers get a JSON 403); the
allow-list is keyed on **endpoint names** and holds the legal routes, the login/OTP
endpoints, logout, leave-entity and static files — the seven load-bearing ones are
listed in the module with the reason each must stay.

## Tests

`tests/test_legal_documents.py`, `tests/test_terms_gate.py`, `tests/test_terms_accept_screen.py`,
`tests/test_terms_consent.py`, `tests/test_terms_signup_consent.py`,
`tests/test_terms_consent_history_api.py`, `tests/test_consent_takeover.py`; in the
browser `e2e/01_login.spec.ts` (first sign-in shows the modal; scroll, tick, accept).
