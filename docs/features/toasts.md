# Toasts — minty-web's card, on every app

**The rule** (the user, 2026-10-01): every app's toast looks like minty-web's — the card that
says "Success / You're signed in with Xero." after a Xero sign-in. A white card, a bold type
label, the message in grey and a `×`, stacked at the top-right. **No per-type colour and no
icon**: the label (Success / Error / Warning / Information) carries the type. This replaced
the old coloured pill (5px border, rounded-full, a PNG icon per tone) in every app.

The reference is minty-web's `components/ui/Toast.tsx`. Change the apps below together.

**Minty (Flask) has no toast since 2026-10-20**: it draws no page. A `flash()` is carried by
`/entity` to minty-web's company list as a signed notice, which minty-web shows as this toast;
a redirect into any other app drops the queue and logs it
(`pettycash/core/hooks.py::drop_flashes_leaving_flask`; [entities-and-members.md](entities-and-members.md)).
This page stays here because the other repos link it as the system-wide rule.

**minty-payment-request-web left this rule on 2026-10-13** (the owner: Part 14 wins there): its
toast is Part 14's - bottom-left on a computer, bottom-centre on a phone, for success only; an
error is an inline alert, never a toast. Its row below still gives its file and API; the look is
Part 14's until minty-web migrates to Parts 13–15 (`docs/design/`).

## The look, value for value

| Part | Value |
|---|---|
| Stack | fixed, top 16px, right 16px; 320px wide, at most `calc(100vw - 2rem)`; 8px between toasts; `aria-live="polite"` |
| Card | `#ffffff`, 1px `#e5e7eb` border, 4px radius, Tailwind's `shadow`, 12px padding, 14px text, 12px gap |
| Label | weight 600, `#171717` |
| Message | `#6b7280` |
| `×` | `#6b7280`, `#171717` on hover, `aria-label="Dismiss"` |
| Roles | `role="alert"` for an error, `role="status"` otherwise; `data-toast-type` names the type |

minty-web also has a dark theme through its CSS variables; the other apps are light only.

## Each app

| App | File | API | Behaviour |
|---|---|---|---|
| minty-web | `components/ui/Toast.tsx` | `useToast().showToast(message, type = "info")` | stacks; 4s |
| minty-payment-request-web | `components/Toast.tsx` | `useToast().showToast(message, type = "success")`, `dismissToast(id)` | stacks; 4s |
| onboarding | `components/Toast.tsx` | `useToast().success/error/warning/info(message?)`, `show`, `hide` | one at a time (a new one replaces it); 4s; each type has a fallback sentence |
