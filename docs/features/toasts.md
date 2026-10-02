# Toasts — minty-web's card, on every app

**The rule** (the user, 2026-10-01): every app's toast looks like minty-web's — the card that
says "Success / You're signed in with Xero." after a Xero sign-in. A white card, a bold type
label, the message in grey and a `×`, stacked at the top-right. **No per-type colour and no
icon**: the label (Success / Error / Warning / Information) carries the type. This replaced
the old coloured pill (5px border, rounded-full, a PNG icon per tone) in every app.

The reference is minty-web's `components/ui/Toast.tsx`. Change all four together (minty-web,
minty-payment-request-web, minty-onboarding-web, here).

## The look, value for value

| Part | Value |
|---|---|
| Stack | fixed, top 16px, right 16px; 320px wide, at most `calc(100vw - 2rem)`; 8px between toasts; `aria-live="polite"` |
| Card | `#ffffff`, 1px `#e5e7eb` border, 4px radius, Tailwind's `shadow`, 12px padding, 14px text, 12px gap |
| Label | weight 600, `#171717` |
| Message | `#6b7280` |
| `×` | `#6b7280`, `#171717` on hover, `aria-label="Dismiss"` |
| Roles | `role="alert"` for an error, `role="status"` otherwise; `data-toast-type` names the type |

minty-web also has a dark theme through its CSS variables; the other three apps are light
only.

## Each app

| App | File | API | Behaviour |
|---|---|---|---|
| minty-web | `components/ui/Toast.tsx` | `useToast().showToast(message, type = "info")` | stacks; 4s |
| minty-payment-request-web | `components/Toast.tsx` | `useToast().showToast(message, type = "success")`, `dismissToast(id)` | stacks; 4s |
| onboarding | `components/Toast.tsx` | `useToast().success/error/warning/info(message?)`, `show`, `hide` | one at a time (a new one replaces it); 4s; each type has a fallback sentence |
| Minty (here) | `templates/components/flash_messages.html` | `showFlashMessages(message, type, durationMs)` + aliases | stacks; 4s, 12s for a flashed error/warning |

## Here: one toast, no page copies

`components/flash_messages.html` is the only toast. `base/layout.html` and every standalone
template include it; it drains `get_flashed_messages()` on load (see
`tests/test_flash_messages_drain.py`) and builds each card with `textContent` — never
`innerHTML`, so server text cannot become markup.

- `showFlashMessages(message, type, durationMs)` — `type` is `success | error | danger |
  warning | info` (`danger` is error; anything else is success). `durationMs` defaults to
  4000; `0` keeps it until dismissed. Each card has its own timer, so toasts never cut each
  other short.
- Error and warning text goes through `mintyErrorCopy` (see
  [ERROR_MESSAGE_LEAKS.md](ERROR_MESSAGE_LEAKS.md)); success and info pass through.
- The aliases callers use — `showToast(m, t = 'error')`, `showSuccessToast`,
  `showErrorToast`, `showWarningToast`, `showInfoToast`, the `showFlash*Toast` four,
  `showSettingsFlashToast`, `hideFlashMessages` and its old `hide*` names — are set
  unconditionally. **No page defines its own toast function or toast markup**; a top-level
  `function showErrorToast` in a page would silently replace the shared one.
- A server-rendered toast (register's form errors, `errors.html`) uses the
  `components.toast(message=..., toastBorder='errorBorder')` macro, which only emits a
  `showFlashMessages` call.
- The cards are `.minty-toast`, styled by the partial's own `<style>` block, not Tailwind
  classes. They are deliberately not `.toast`: a page's old "hide every `.toast` after 4s"
  sweep cut the Xero sign-in toast to 3.5s and blanked later ones. Those sweeps are gone; do
  not add one.

Until 2026-10-01 there were ten page copies (the dashboard, report history / submitted /
ending, cash count, deposit, opening, expense, the unsaved-changes toast on six report steps,
entity settings, users settings, and the bottom-centre macro). All of them now call the shared
toast; the unsaved-changes notice is a warning toast.
