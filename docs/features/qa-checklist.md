# Manual QA checklist — Minty

Minty's one manual QA checklist (one per repo). Minty is backend only since 2026-10-20 (no
pages), so it covers **what the onboarding wizard depends on here** — email OTP sign-in,
minting the onboarding JWT, the Xero OAuth connect/callback round-trip for step 4, and
launching/resuming the wizard. The daily report's screens are minty-petty-cash-web's and are
checked there.

Run this alongside the automated suites named in each section, not instead of them. Tick
each box against a disposable test entity and a disposable OTP-only inbox — never a real
company or a real Xero organisation (see "The onboarding-connect race" below for why).

## Email OTP sign-in (the identity gate before the onboarding JWT)

`blueprints/auth/routes/email_auth.py` + `services/email_auth.py`
([authentication.md](authentication.md) §2.1); `tests/test_otp_identity_gate.py`.

- [ ] `POST /auth/email/request-code` in login mode (`mode: "login"`) for an address with
      no `user` row → 404 "Please sign up first", **before** any code is sent.
- [ ] The same unknown address in sign-up mode is accepted (a code is sent).
- [ ] An address held only as `user.xero_email` (never `username`) gets a code in login
      mode — the gate reads `resolve_user_by_email`, not `username` alone.
- [ ] An address that is only `username`/`email_otp`-known with no resolvable user row no
      longer opens the gate (the pre-2026-10-05 regression).
- [ ] The 6-digit code expires at 60 s; a code entered after that is refused.
- [ ] Resend cooldown is 60 s; failed-attempt counts carry forward across a resend (not
      reset to zero).
- [ ] The 5th wrong code locks the address for 15 minutes, HTTP 429 `ERR_LOCKED`, anchored
      to the row's `created_at` (check the lock clears itself at 15 minutes, not on next
      request).
- [ ] If the mail send itself fails, the code request is rolled back and answers 400 — a
      retry right after succeeds (no orphaned "code was sent but isn't valid" state).
- [ ] `POST /auth/email/verify-code` with a correct code signs an existing user in.
- [ ] The same call for a brand-new address with a first/last name creates the
      passwordless user on the spot, with terms consent recorded as `signup_otp` (or
      `signup_invite` when an invite token rode along).
- [ ] A new address with **no** name answers 404 "please sign up" rather than creating a
      blank account.
- [ ] `GET /auth/email/handoff` sets the session cookie on Minty's origin and then honours
      a signed `next` only when it is a path on this site; otherwise it falls back to
      `/index` (the company list), a superadmin included.
- [ ] A non-ASCII address is refused by `POST /auth/email/request-code` with a 400 (the
      as-you-type check is minty-web's sign-in page).

## Minting the onboarding JWT

`blueprints/entity/routes/create.py::_mint_onboarding_token` / `onboarding_launch_url`
([authentication.md](authentication.md) §6, §9; [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md)).

- [ ] `GET /entity/create` (brand-new company) mints a token and redirects with `fresh=1`
      and **no** `entity_id`.
- [ ] Resuming an in-progress company passes `entity_id=` and never sets `fresh`.
- [ ] Decode the minted token: claims are exactly `user_id`, `scope: "onboarding"`, `iat`,
      `exp` — nothing else (no `entity_id`, no role claims — those belong to the module
      token, not this one).
- [ ] Token lifetime is 60 minutes from `iat`.
- [ ] The token is HS256, signed with `SECRET_KEY` — verify it decodes successfully against
      minty-onboarding-api's `OnboardingBearerAuth` using the **same** local `.env` value;
      a deliberately wrong key 401s (this is the cross-repo failure mode the
      `prod-secret-key-differs-from-local` note warns about).
- [ ] An invitation link (`/invitation/accept/<token>`) lands on minty-web's sign-in page
      with the invite token — the invite is still honoured after signing in.
- [ ] `GET /entity/<id>/enter?token=` (the *module*-token re-entry route) refuses an
      onboarding-scoped token — the two token kinds are not interchangeable
      (`test_billing_relogin_handback.py`, `test_url_security.py`).

## Xero OAuth connect/callback (onboarding step 4)

`blueprints/xero/routes/routes.py`, `services/integration.py`
([xero-integration.md](xero-integration.md) §1–2); `tests/test_xero_scopes.py`,
`tests/test_xero_entity_connect_race.py`.

- [ ] `GET /xero_connect?entity_id=…` requires `XERO_SETTINGS_UPDATE` (an admin on that
      entity) — a cashier/shop_manager session is refused.
- [ ] The outgoing OAuth `state` carries the entity as `<base>:<entity_id>:<name>[:<initiator>]`
      — confirm by inspecting the redirect URL, since the Flask session does not survive
      the round trip to Xero and back.
- [ ] The requested scope set is the app's exact minimal granular list — not the composite
      `accounting.transactions` (Xero rejects that scope for this app registration).
- [ ] `/xero_reconnect` requests the identical scope set as first-time connect.
- [ ] `GET /callback` exchanges the code onto the **connecting user's** `user_token` row,
      and stamps `entities.connected_by_user_id` as that same user — not whoever currently
      holds any token on the entity.
- [ ] After callback: `entities.xero_org_id`, `xero_tenant_name` are set and
      `status = connected`.
- [ ] After callback (connect and reconnect): `entities.financial_year_end_day` /
      `financial_year_end_month` hold the organisation's year end as Xero's *Financial
      settings* show it. If Xero's Organisation can't be read, the connect fails, nothing
      on the company changes and the grant is revoked (Xero's *Connected apps* shows no
      new Minty entry).
- [ ] Connecting an organisation that is already linked to a **different** company
      disconnects that other company first — one Xero organisation ↔ one company at a
      time. (Use a scratch Demo Company for this check, never a shared/real org — see the
      callout below.)
- [ ] The background sync kicks off after callback (contacts, chart of accounts, bill
      account codes) and `GET /api/entity/<id>/xero-sync-status` reports progress while it
      runs.
- [ ] A re-sync after an organisation switch clears the entity's petty-cash mapping
      (`entity_pettycash_settings`'s FKs are `ON DELETE SET NULL`) — expected, not a bug;
      it must be picked again (out of scope here — see `xero-integration.md` §3).

## Launching and resuming the wizard (module handoff)

[onboarding-and-module-handoff.md](onboarding-and-module-handoff.md); `tests/test_onboarding_launch_fresh.py`,
`tests/test_onboarding_module_state.py`, `tests/test_onboarding_csrf_exempt.py`.

- [ ] The redirect to the wizard is `<ONBOARDING_WEB_URL>/?token=<jwt>[&entity_id=…][&fresh=1]`
      — no other query params leak the token elsewhere (e.g. not also appended to a
      Referer-visible link).
- [ ] `/api/onboarding/*` calls that still run through Minty (not proxied to
      minty-onboarding-api) are CSRF-exempt — confirm a same-path POST without a CSRF
      token still succeeds for those, while an ordinary session-authenticated Flask route
      elsewhere is not.
- [ ] CORS on Minty's `/api/onboarding/*` answers names `ONBOARDING_WEB_URL` only — a
      request with a different `Origin` does not get `Access-Control-Allow-Origin` back.
- [ ] A wizard session with nothing granted yet lands on the Modules step (state's
      `current_step` derivation) rather than skipping ahead.
- [ ] An explicit module grant (and an explicitly disabled one) shows the same on both the
      wizard's state response and wherever Minty itself reads the grant.

## The onboarding-connect race (read before testing Xero connect by hand)

**The entity on a Xero connect/callback is resolved from the OAuth `state` string, not
from the Flask session** — the session does not survive the round trip to Xero's
authorize page and back. `tests/test_xero_entity_connect_race.py` exists because two
people onboarding and connecting Xero *at the same time* used to let one user's callback
bind the wrong user's entity
(`test_old_code_would_have_corrupted_data_regression_proof`). One tester clicking through
the flow once will never see this — it only shows up with two concurrent sessions. If you
want to exercise it by hand:

1. Use two disposable onboarding entities, never two people racing to connect the **same**
   entity or the same real Xero organisation.
2. Start both `/xero_connect` redirects before either completes `/callback`, so the two
   `state` values are both in flight together.
3. Confirm afterward that each entity's `xero_org_id` and `connected_by_user_id` match the
   session that actually requested it — not swapped.

Don't test this against a shared or production Xero organisation: connecting it elsewhere
disconnects whoever currently holds it (see the connect checklist above).

## Out of scope for this checklist

- **The Petty Cash screens** (the daily report, history, exports, Petty Cash Settings, the
  share page) — minty-petty-cash-web's, over minty-petty-cash-api; each repo's own checklist.
- **Xero publish/republish, the modules/subscription reads, the terms gate, expense AI** — no
  checklist items yet; see the table in [README.md](README.md) for where each is documented,
  and add a section here when that surface needs one (one checklist per repo).
- **Finalize and the All Set step (step 9)** — served by minty-onboarding-api, not Minty;
  its own checklist (`minty-onboarding-api/docs/features/qa-checklist.md`) covers it,
  including the "never land a test session on saved step 9" trap.
- **The email OTP's actual inbox delivery** — ends at a real mailbox; this checklist only
  covers what Minty does before and after the mail is sent.

## See also

- [authentication.md](authentication.md) — the system-wide auth picture; §2.1 (OTP), §6
  (hand-off tokens), §9 (shared `SECRET_KEY`).
- [onboarding-and-module-handoff.md](onboarding-and-module-handoff.md) — the launch URL,
  the `/api/onboarding/*` dual-backend table, and Minty's side of the hand-off.
- [xero-integration.md](xero-integration.md) — §1 "Connecting" and §2 "Tokens" for the
  connect/callback mechanics this checklist exercises.
- [README.md](README.md) — the full feature index.
- `minty-onboarding-api/docs/features/qa-checklist.md` — the sibling checklist on the
  other side of the handoff (the wizard's own endpoints, the step-9 trap, finalize).
