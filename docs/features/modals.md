# Modals — minty-web's design, on every app

**The rule** (the user, 2026-09-30): "use modals designed in minty web. that should be how
modals is going to be designed accross repos". minty-web's family is the design everywhere:
`ModalFrame` (the blurred page and the card over it), `ConfirmDialog` (the title with Minty
beside it, the sentences, the secondary button and the confirming one in its tone) and
`SheetFrame`-style sheets for forms. **Every new modal follows it; an existing one changes when
its page is next worked on.** The sources are minty-web's
`features/subscription/components/{ModalFrame,ConfirmDialog,InterruptedDialogs}.tsx` and
`lib/changeModal.ts`; minty-payment-request-web holds copies at the same paths. Change all three
together (minty-web, minty-payment-request-web, here).

## The Flask port

A PORT, not a copy — `@minty/shared` is TypeScript and cannot serve Jinja; it retires with the
Jinja pages (Part 3).

| File | What it is |
|---|---|
| `templates/components/minty_dialog.html` | include ONCE in a page's `<head>`, before the page's own scripts |
| `static/js/minty_dialog.js` | `MintyDialog.confirm(...)` and `MintyLeaveGuard` |
| `static/css/minty_dialog.css` | the look, value for value, scoped under `#minty-dialog` |
| `static/img/portal/minty-dont.png`, `minty-surprised.png` | the two pictures it ships (minty-web's `public/portal/`) |

`MintyDialog.confirm({title, body, image, confirmLabel, confirmTone, backLabel, backTone, safe,
name})` resolves `"confirm"`, `"back"` or `"dismiss"` (Escape or the backdrop — the safe way
out). `image` is `"dont"` or `"surprised"`; `confirmTone` teal / orange / red; `backTone` grey /
teal; `safe` names the button focused first (the one that changes nothing); `name` lands on the
dialog as `data-modal`, for tests. `body` is a list of sentences — a string, or pieces with
`{strong: "..."}` — always put in as text.

Mechanics: the script builds the dialog on first use as the page's last element (outside any
fade or stacking context), at **z-index 250** — above the sidebar drawer (200), so a link pressed
inside the open drawer asks over it; below the loading overlays (300) and the flash toast (400).
It opens by an attribute (`data-open`), not `[hidden]`. The backdrop is the card's sibling.
Escape is caught on the way down, so the drawer under the dialog stays open. Tab stays on the
card's two buttons; focus goes back where it was when the dialog closes.

## "Leave without saving?" (Figma A-11)

`MintyLeaveGuard.watch(isDirty)` arms it for a page with unsaved changes; minty-web's
`LeaveDialog` words: "You have unsaved changes." / "Your changes will be lost if you leave this
page.", the "dont" Minty, **Discard changes** (teal outline) and **Go Back** (teal).

- A click on a link that would leave the page is held (on `window`, in the capture phase, before
  the page's own handlers) and the dialog asks. Let through: `#` and `javascript:` links,
  non-http(s) links, any `target` other than `_self`, `download`, modifier and middle clicks,
  `[data-sidebar-open]` (the initials and the ≡ open the sidebar), a jump within the page
  (same address, a `#fragment`), and links inside the dialog. **A link to exactly this
  address DOES ask** — it reloads (the current pill, the sidebar's Settings).
- **Discard changes** replays the original click once, so each link keeps its own behaviour
  (the sidebar closing, a fade, a full load); the browser's own prompt is switched off first.
- `beforeunload` gives the browser's own prompt for a reload, a closed tab, a typed address and
  Back/Forward.
- `saving()` before the page's own `form.submit()`; `ask(proceed)` for an exit that is not a
  link.

minty-payment-request-web's `lib/leaveGuard.ts` (`useLeaveGuard`, `guardLeave`) does the same with the
same rules, for its Payment Request Settings; there, Back/Forward inside the Next app are soft
navigations and leave without asking (a documented gap).

## Where it is used

- Petty Cash Settings ([petty-cash-settings.md](petty-cash-settings.md)): the leave guard, and
  the delete-method confirm ("Delete Electronic Method", the surprised Minty, Go back / a red
  Delete).
- minty-payment-request-web Payment Request Settings (its `docs/features/settings.md`): the leave guard, and its
  Logout asks first.

Not yet: the report pages' modals. (Users' and Entity & Integration's went with their pages
to minty-web in phase 2, where they are minty-web's own `ConfirmDialog`.) They change when their page is next worked on.
