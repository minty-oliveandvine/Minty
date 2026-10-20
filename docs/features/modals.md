# Modals — minty-web's design, on every app

**The rule** (the user, 2026-09-30): "use modals designed in minty web. that should be how
modals is going to be designed accross repos". minty-web's family is the design everywhere:
`ModalFrame` (the blurred page and the card over it), `ConfirmDialog` (the title with Minty
beside it, the sentences, the secondary button and the confirming one in its tone) and
`SheetFrame`-style sheets for forms. **Every new modal follows it; an existing one changes when
its page is next worked on.** The sources are minty-web's `components/ui/ModalFrame.tsx`,
`components/ui/ConfirmDialog.tsx`, `components/ui/LeaveDialog.tsx` ("Leave without saving?",
Figma A-11), `lib/leaveGuard.ts` and `features/subscription/components/InterruptedDialogs.tsx`.

**minty-payment-request-web left this family on 2026-10-13** (the owner: Part 14 wins there): its
modals are Part 14's (`components/ui/Overlay.tsx` - `Modal`, `Drawer`; see its
`docs/features/payment-requests.md`). Only the WORDS of "Leave without saving?" are still shared
with it. minty-web follows when it migrates to Parts 13–15 (`docs/design/`).

**Minty (Flask) has no modals since 2026-10-20**: it draws no page. Its port (`MintyDialog`,
`MintyLeaveGuard`) went with its templates; each screen's dialogs are its Next app's.
