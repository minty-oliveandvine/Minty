# Visual anchors — second-stage corrective review (validation round, 2026-10-19)

The owner's brief, 2026-10-19: the revised UI is clearer, but it flattened hierarchy, page identity, colour and character. Each page needs one meaningful visual anchor that fits its Mental Mode. *Simplicity means less thinking, not fewer visual elements.* This round redraws four screens only. Everything else waits until this round is validated.

**Status (2026-10-19):**
- **The validation round is built.** The four screens are on branch `design/visual-anchors` in Minty, minty-web and minty-payment-request-web, on top of the 2026-10-16 work, and merged into each repo's `development` on 2026-10-19. They wait for the owner's validation.
- **The Daily Report now lives in the Next.js Petty Cash app** (minty-petty-cash-web's redesign track: `components/closing/DailyReport.tsx` + `ReportParts.tsx`), not in Flask's `report/ending.html`. Flask is backend only (the user's rule, 2026-10-16).
- **Close stays the verification page.** It gets no outcome band and no charts.
- **Built 2026-10-19:** Module selection (9C) and User invitation (9E) in minty-onboarding-web, §5–§6. Basic Information (9D) and the individual Payment Request (9G) are preserved, §7.
- Each screen ends with the brief's §11 sixteen points (**F**), describing what is BUILT. Where the build differs from sections A–E, the table says so.

## Why these four
| Test required by the brief | Screen | Brief finding |
|---|---|---|
| Reporting / Operational Review | Daily Report (minty-petty-cash-web, Part 15 redesign) | 9A |
| Orientation / major entry, with controlled illustration | Subscription & Billing overview (minty-web `/subscription`) | 9B |
| Work Coordination / overview | Payment Request overview (PRW) | 9F |
| Illustration appropriate but held back | Company selection (minty-web `/entities`) | 9H |

Not in this round:
- **Basic Information (9D)** and the **individual Payment Request (9G)** are preserved as they are. Each already has the right anchor: the form, and the document (§7).
- **Module selection (9C)** and **User invitation (9E)** are smaller hybrid or action-hierarchy fixes. They are built (§5, §6).

---

## 1. Daily Report — Operational Review
**A. Current problem**
- It does well: three KPIs, collapsed breakdowns, a clear cash-difference alert, and no clutter.
- It lost the charts and the visual diversity. The KPI tiles and the four `<details>` all weigh the same, so the report reads like a filled-in form rather than an outcome.

**B. Mental Mode**
- User Perceived Goal: "How much did we sell and spend, and what cash do we have?"
- Mode: Operational Review.
- Primary question: what happened today?
- Primary action: none. The page is read; Share and Download are secondary.

**C. Anchor**
- An **outcome band** on a brand/50 tint, carrying the Petty Cash module chip. **Cash position** is the one hero amount.
- Attention order: (1) cash position, (2) sales and expenses, (3) the cash-difference alert if there is one, or else how sales split by method.
- A figure-led anchor is right because the question asks for figures. A banner or character would not answer it.

**D. Hierarchy**
1. Header.
2. The band (hero amount, plus two secondary figures).
3. The cash-difference alert.
4. Composition charts: a stacked proportion bar for sales by method, and bar rows for expenses by account.
5. Collapsed details: sales, expenses, receipts and cash. These are the charts' table alternatives.
6. Audit meta.

Equal tiles become one band with a clear first point, and charts sit between the summary and the detail.

**E. Identity**
- Tint and module colour carry identity; numbers stay plain text.
- One small spot art (≤ 96px, hidden on phones) is the only illustration. There is no character, because this is a record.
- The charts answer the question "where did the money come from and go". There are no trends or history (2.10.4).
- **Close stays the verification page**, with no charts. Close is Work Verification and the report is Operational Review, so they look different on purpose.

**F. The sixteen points (as built: `DailyReport.tsx`, `ReportParts.tsx`)**
| # | Point | Daily Report |
|---|---|---|
| 1 | User Perceived Goal | "How much did we sell and spend today, and what cash do we have?" |
| 2 | Dominant Mental Mode | Operational Review. The day is already submitted, so the page is read, not worked. |
| 3 | Primary user question | What happened today, and is our cash where it should be? |
| 4 | Primary action | Nothing is required. While the report is not in Xero, *Publish to Xero* is the one Primary. Otherwise it moves into More, and Share is Secondary. Edit and Delete sit in More, with Delete last as Danger. |
| 5 | Primary visual anchor | The outcome band (`OutcomeBand`): one brand/50 (`state-selected`) band with the Petty Cash module chip. **Cash position** is the hero at `display-xl`, with Total sales and Total expenses as `title-l` figures beside it. |
| 6 | Why that anchor | The question asks for figures, so the anchor is a figure. One hero amount gives the page a single first point, where three equal tiles read as a form. |
| 7 | First / second / third points of attention | (1) Cash position. (2) Total sales and Total expenses. (3) The cash-difference alert when there is one, otherwise "Where the money came from and went". |
| 8 | Visually dominant info | Cash position, then the two secondary figures. |
| 9 | Supporting info | The difference as a Warning Inline alert, in words, with *Edit reason*. The sales-by-method proportion bar with its legend (name, amount, %). The expenses-by-account bar rows. The closing balance on a sunk surface. |
| 10 | Progressively disclosed info | Four native disclosures, closed by default: Sales by method, Expenses (n) with per-line Edit, Receipts (n) opening the full-screen viewer, and Cash with *Edit where the cash came from*. They are also the charts' table alternative. Audit facts sit at the very bottom. |
| 11 | Colour use | The brand/50 tint and the Petty Cash chip carry identity. Chart tones are brand plus neutral only (`[data-chart-tone]`), with no red/green meaning. Warning is used only for a cash difference. Amounts are always plain `text-primary`, never coloured. **No colour beyond identity and semantic use.** |
| 12 | Illustration / Minty character | One spot art: the safe box, 96px, decorative (`alt=""`), hidden below 640px. **No character**: this is a record. |
| 13 | Does a chart add understanding? | **Yes.** It answers "where did the money come from and go" as composition: one stacked bar for sales, bar rows for expenses against the largest. There are no trends or history (2.10.4). Each chart is a `role="img"` with its figures in its label. |
| 14 | How it avoids flat hierarchy | Four surface levels: the tinted band, the bordered chart card, the closed disclosures, and the muted audit lines. The type steps are display-xl, title-l, title-m and body. |
| 15 | Consistent without generic | It uses Part 14's Report header, Status pill, Inline alert, More menu and disclosure, so it matches every Part 15 page. Its identity comes from the band, the module chip and the safe box. |
| 16 | How it stays "not an obvious accounting system" | It uses the shop's words: "Cash position", "Where the money came from and went", "What the drawer and the safe box held". There is no ledger grid, no debit/credit and no account codes in the anchor. The table detail stays closed until asked for. |

## 2. Subscription & Billing — Orientation / Decision dashboard
**A. Current problem**
- It does well: accurate position data, clear cards, responsive behaviour.
- It lost the colourful summary area, the prominent billing outcome, and clear differences between billing, payment method and invoices.
- Three equal tiles and two equal cards make it look like a settings page. "Trial ending" is shown as a red number, which colours a count.

**B. Mental Mode**
- User Perceived Goal: "What am I paying, when, and is anything wrong?"
- Mode: Commercial Decision / Orientation.
- Primary question: what is my current position?
- Primary action: manage subscriptions, or fix the attention state.

**C. Anchor**
- A **gradient position header**, which is Part 13's approved subscription-header exception. The **next bill amount and date** is the hero, with the status and payer beside it. Minty holding cards sits in the header's side area (hidden on phones).
- Attention order: (1) next bill, (2) any attention banner, (3) the modules.

**D. Hierarchy**
1. Coloured header.
2. Attention banner, shown only when something needs action.
3. Modules, as identity-coloured rows with state pills.
4. Payment method, with clear brand marks.
5. The last three invoices, plus "See all".

Coloured, then identity-coloured, then neutral: three surface levels instead of one repeated card.

**E. Identity**
- The gradient, the module colours and one character make the page feel like Minty rather than a billing console.
- The character is justified on an entry page: it says "you're in Minty's billing" without taking space from the decision. It is hidden on phones, where space belongs to the figures.

**F. The sixteen points (as built: `SubscriptionOverviewScreen.tsx`, `BillingOverviewPanels.tsx`)**
| # | Point | Subscription & Billing |
|---|---|---|
| 1 | User Perceived Goal | "What am I paying, when, and is anything wrong?" |
| 2 | Dominant Mental Mode | Commercial Decision / Orientation. It is the payer's entry into billing. |
| 3 | Primary user question | What is my current position: the next bill, and does anything need me? |
| 4 | Primary action | *Manage Subscription* in the header (Secondary look, white on the gradient). When something is due, the action on each attention banner comes first. Clicking the header opens the billing-account sheet, and clicking the account name is *Change billing account*. |
| 5 | Primary visual anchor | The position header on the subscription gradient (`--subscription-header-gradient`, Part 13's approved exception). It shows the title, one status pill, the **next bill amount** at `display-xl` and its date at `display-l`, and the account it is billed to. |
| 6 | Why that anchor | The payer's first question is money and date. The gradient marks the page as Minty's subscription space and makes the one amount the first thing read. All text on it is `text-primary`, the only ink that passes AA on both stops. |
| 7 | First / second / third points of attention | (1) The next bill and its date. (2) An attention banner, if one is showing. (3) The modules. |
| 8 | Visually dominant info | The next bill amount, then its date and the status pill. |
| 9 | Supporting info | Who it is billed to. The modules: identity chip, state pills with counts, and a line per company that needs the payer, failures first. The payment method: the card's network mark drawn large, last four and expiry, with Expired or Expiring soon pills. |
| 10 | Progressively disclosed info | The per-company updates under the modules expand on demand. The account sheet and *Change billing account* are dialogs. **Invoices:** the last three of the shown billing account (number, date and period, amount in plain text, a status pill), then "See all invoices ›"; skeleton rows while loading, "No invoices yet." when none, and a failed read says so with Try again. |
| 11 | Colour use | The gradient (identity, used once). Module washes and inks on the chips (identity, never status). Part 13 status tones on pills and banners (danger, warning). Amounts are plain ink. "Trial ending" is no longer a red count. **No colour beyond identity and semantic use.** |
| 12 | Illustration / Minty character | One character: Minty holding cards (`/portal/minty-cards.png`), 128px (144px from 1024), decorative, in the header's side area, hidden below 640px. It is the one place in this round where a character is justified: an entry page. |
| 13 | Does a chart add understanding? | **No chart.** The position is one amount and one date. A spend chart would answer a question the payer is not asking here. |
| 14 | How it avoids flat hierarchy | Three surface levels: the coloured header, then identity-coloured module rows, then the plain sections for payment method and invoices (side by side from 768px). Banners appear only when something is due. |
| 15 | Consistent without generic | It uses shared status pills, banners and the 1200px column. The gradient, the module colours and the character are what make it Minty's billing rather than a billing console. |
| 16 | How it stays "not an obvious accounting system" | It shows the next bill and the card that pays it. It uses no ledger, no line-item table and no tax breakdown. The language is plain: "Manage Subscription", "Change billing account", "is now billed to". |

## 3. Payment Request overview — Work Coordination
**A. Current problem**
- It does well: status chips with counts, Easy/Table views, totals, and a consistent table.
- It lost the liveliness that showed what needs you. Title, totals and table read as generic accounts-payable software.

**B. Mental Mode**
- User Perceived Goal: "What needs paying next?"
- Mode: Work Coordination. It is action prioritisation first and record browsing second.
- Primary action: open the overdue or due-soon requests. Secondary action: Add payment request.

**C. Anchor**
- A **Needs attention strip** of three tiles: Overdue (count and unpaid), Due in 7 days, Returned. Each tile filters the list.
- Attention order: (1) overdue, (2) due soon or returned, (3) the list.
- Status is the right anchor because the user's question is about priority. Totals alone do not prioritise.

**D. Hierarchy**
1. Header with module identity.
2. The attention strip.
3. Totals, as the supporting figure.
4. Toolbar and chips.
5. Rows, whose meta line reads "Overdue N days".

When nothing is waiting, the strip collapses to one calm line, so a quiet day looks quiet.

**E. Identity**
- The Payment Request module art on its blue wash identifies the module.
- There is **no character**: Part 15.4 removed the mascot beside lists, and a cat next to rows would compete with the work. The first-use empty state keeps its cat.
- The brief's "less generic" is met through prioritisation and module identity, not mascots.

**F. The sixteen points (as built: `PaymentRequestAttentionStrip.tsx`, `PaymentRequestView.tsx`, the page header in `app/entity/[ref]/[slug]/payment-request/page.tsx`)**
| # | Point | Payment Request list |
|---|---|---|
| 1 | User Perceived Goal | "What needs paying next?" |
| 2 | Dominant Mental Mode | Work Coordination: prioritising first, browsing records second. |
| 3 | Primary user question | What needs my attention next? |
| 4 | Primary action | Open the overdue or due-soon requests. A tile press applies the list's own filter, and pressing it again releases it. *Add payment request* is the page header's Primary for people who may create. |
| 5 | Primary visual anchor | The **Needs attention** strip under the page header: three toggle tiles (Overdue, Due in 7 days, Returned). Each shows a count, and the unpaid amount per currency (two at most, then "+N more"). |
| 6 | Why that anchor | The question is about priority. Totals do not prioritise and a table does not either, but a count of what is late does. |
| 7 | First / second / third points of attention | (1) Overdue. (2) Due in 7 days and Returned. (3) The list, whose row meta reads "Overdue N days" / "Due in N days". |
| 8 | Visually dominant info | The Overdue tile when it has requests: a Warning surface with an icon and the word. The tile counts. |
| 9 | Supporting info | The totals banner under the strip. It shows only once the list is narrowed, rows are selected, or a non-Draft status is picked. The status chips with counts. |
| 10 | Progressively disclosed info | The filter panel (amount, dates, Xero status), bulk actions after selection, and Easy view vs Table. A quiet day collapses the strip to one line: "Nothing is overdue or due this week." |
| 11 | Colour use | Warning on the Overdue tile only, and only when its count is above zero, always with an icon and words. The selection border marks a pressed tile. The Payment Request wash sits behind the module art. Amounts are plain `text-primary`. **No colour beyond identity and semantic use.** |
| 12 | Illustration / Minty character | Module art only: the Payment Request mark on its blue wash, 40px, beside the h1. **No character beside the list** (Part 15.4). The first-use empty state keeps its cat. |
| 13 | Does a chart add understanding? | **No chart.** The question is "which ones", answered by counts that filter the rows. A chart of amounts would describe the list without saying what to open. |
| 14 | How it avoids flat hierarchy | The strip sits above the toolbar and the rows. Overdue gets its own surface, and a quiet day looks quiet instead of showing three zeros. The totals appear only when they mean something. |
| 15 | Consistent without generic | It uses the shared page header, chips, Inline alerts and pagination. The module art and the prioritising strip are what separate it from generic accounts-payable software. |
| 16 | How it stays "not an obvious accounting system" | It speaks in due dates and people: "Overdue", "Due in 7 days", "Back with the requester". There are no ageing buckets and no AP terms. |

## 4. Company selection — Orientation (illustration held back)
**A. Current problem**
- It does well: search, clear cards, chips.
- It lost the old surfacing of which company needs you and why. The large scene pushes the list down without helping the choice. Every card weighs the same, and the FAB floats.

**B. Mental Mode**
- User Perceived Goal: "Get me into the right business."
- Mode: Context Selection / Orientation.
- Primary question: which company needs me?
- Primary action: open a company.

**C. Anchor**
- The **"Needs you" group**. Each card names the reason and the action, such as "Trial ends in 3 days" or "Setup not finished".
- Attention order: (1) the question title, (2) the companies that need you, (3) the rest.
- Status beats a scene here: this page proves that more illustration is not more Minty.

**D. Hierarchy**
1. The question, with a small Minty greeting (≤ 96px, hidden on phones).
2. "Needs you".
3. "Your businesses", with role and module chips.
4. Search when there are more than six companies.
5. A page-level "Create a business" button.

It sits in a centred 640px column (15.8).

**E. Identity**
- Module identity chips and one small greeting give a friendly tone without displacing the decision.

**F. The sixteen points (as built: minty-web `features/entities/`)**
| # | Point | Company selection |
|---|---|---|
| 1 | User Perceived Goal | "Get me into the right business." |
| 2 | Dominant Mental Mode | Context Selection / Orientation. |
| 3 | Primary user question | Which business needs me, and which am I working on? |
| 4 | Primary action | Open a company: the whole card is the link. *Create a business* is a page-level Secondary under the list, replacing the floating "+". |
| 5 | Primary visual anchor | The **"Needs you"** group above "Your businesses", most urgent first. Each card in it states the reason and the action with an icon: "Payment failed" in Danger, the others (trial ending, setup, Xero) in Warning. |
| 6 | Why that anchor | The useful thing this page can say is which company needs the person and why. A scene would push the list down without helping the choice. |
| 7 | First / second / third points of attention | (1) The question title, "Which business are you working on?" (2) The Needs you companies. (3) Your businesses, last used first. |
| 8 | Visually dominant info | The question at `display-m`, then each company name at `title-m`. In Needs you, the reason line comes next; the person's role sits under the name as plain secondary text. |
| 9 | Supporting info | Module identity chips (Petty Cash on its yellow wash, Payment Request on its blue wash), the Free trial tag naming its modules, and the last-opened clock with who opened it. |
| 10 | Progressively disclosed info | Search appears only from seven companies and stays sticky above the rows. The last-opened detail is a hover tooltip. |
| 11 | Colour use | Module washes are identity. Danger ink marks a failed payment and Warning ink the other Needs you reasons, each with an icon and words (never colour alone). Everything else is neutral on the canvas. **No colour beyond identity and semantic use.** |
| 12 | Illustration / Minty character | One small greeting, Minty thinking (`/portal/minty-thinking.png`), 80px, decorative, beside the question, hidden below 640px. The old large scene is gone. The empty state ("No Entity Found") keeps its larger illustration. |
| 13 | Does a chart add understanding? | **No chart.** The decision is which company to open. Nothing on this page is a quantity to compare. |
| 14 | How it avoids flat hierarchy | It sorts into two named groups, so the cards that need the person are lifted out and say why, the most urgent (a failed payment) first. One 640px column (15.8) keeps the eye on one line of choices. |
| 15 | Consistent without generic | It uses the hub's header bar, shared tokens and Part 14 cards. The module chips and the greeting give identity without displacing the list. |
| 16 | How it stays "not an obvious accounting system" | It asks "which business", not "select entity". The reasons use the person's words ("Payment failed — update the payment method", "Trial ends in 3 days — choose a plan", "Setup not finished", "Xero is disconnected"), with no status codes. |

**Built vs C–D:**
- The card draws **four reasons**, most urgent first: Payment failed (Danger), a trial ending within 7 days ("Trial ends in N days" / "Trial ends today"), Setup not finished, and Xero is disconnected. They come from Flask's `GET /api/me/entities` fields `payment_failed`, `trial_ends_on` (`YYYY-MM-DD`, the earliest trial end, on the company's calendar) and the company status ([entities-and-members.md](entities-and-members.md)); the person's own `role` shows under the name ("Admin", "Member", …).

---

## 5. Module selection (onboarding 9C) — hybrid, built
The brief keeps the revised screen's logic and adds module identity back. It is a hybrid, not a redraw.

| # | Point | Module selection |
|---|---|---|
| 1 | User Perceived Goal | "Choose what my business will use, and see what it costs." |
| 2 | Dominant Mental Mode | Commercial Decision inside a guided setup. |
| 3 | Primary user question | Which modules do I need, and what will that cost? |
| 4 | Primary action | Select one or more modules, then Continue. |
| 5 | Primary visual anchor | The **module cards**. Each shows its module art large, on its own wash: Petty Cash on the yellow wash token, Payment Request on the blue wash token. Each card has the name and a one-line benefit. |
| 6 | Why that anchor | The decision is between two products. Strong module identity makes them recognisable at a glance and ties them to the chips the person will see everywhere afterwards (sidebar, company list, subscription). |
| 7 | First / second / third points of attention | (1) The module cards. (2) The selected state and the pricing summary it updates. (3) Progress and Continue. |
| 8 | Visually dominant info | The module art and name. Once a card is chosen, its selected state. |
| 9 | Supporting info | The revised explanation over the cards (kept), the one-line benefit, and the pricing summary (kept). |
| 10 | Progressively disclosed info | Price detail stays in the summary, not on each card, and the existing selection logic (kept) decides what is shown. A "learn more" stays a link, not inline copy. |
| 11 | Colour use | The module washes are identity. The selected state uses the selection border/fill (`state-selected`, `border-selected`) **plus a check mark and words**, never colour alone. Continue is the Primary CTA (Minty Action). No other colour. |
| 12 | Illustration / Minty character | Module art only, larger than today. **No character in the selection controls**: the art identifies the product, and a mascot inside a choice would compete with it. |
| 13 | Does a chart add understanding? | **No chart.** It is a choice between two products, with one price summary. |
| 14 | How it avoids flat hierarchy | The art-led cards carry the decision and the summary follows from it. Progress stays quiet at the top, which is the hybrid of the old colourful cards and the revised clarity. |
| 15 | Consistent without generic | It keeps the wizard's progress, buttons and summary. Identity comes from the same module art and washes as the rest of Minty. |
| 16 | How it stays "not an obvious accounting system" | It names what each module does for the shop in one line ("benefit"), not features or plan codes. Prices read as one summary. |

## 6. User invitation (onboarding 9E) — action hierarchy, built
The brief's fix is an explicit three-way action hierarchy, and saying in the header that the step is optional.

| # | Point | User invitation |
|---|---|---|
| 1 | User Perceived Goal | "Bring my team in, or get on without them for now." |
| 2 | Dominant Mental Mode | Guided setup with an optional step: a light decision. |
| 3 | Primary user question | Do I add people now, and if so, who and with what role? |
| 4 | Primary action | **Primary: "Send invitation" / "Add people now".** Secondary: "Add another person". **"Skip for now" is a real button** in the tertiary style. It is clearly visible but not dominant, never a bare link and never only a sentence in the copy. |
| 5 | Primary visual anchor | The invitation form (person, email, role) with its Primary button. |
| 6 | Why that anchor | Inviting is the step's purpose. Skipping is a legitimate path, so it must be findable without competing with the main action. |
| 7 | First / second / third points of attention | (1) The header, which states that the step is optional (for example "Invite your team — optional; you can do this later in Settings"). (2) The form and Send invitation. (3) Add another person and Skip for now. |
| 8 | Visually dominant info | The form and the Primary button. |
| 9 | Supporting info | Role explanations in plain words and the list of people already added. |
| 10 | Progressively disclosed info | Further person rows appear only through *Add another person*. Role detail sits beside the role picker. |
| 11 | Colour use | Minty Action only on the Primary. Secondary and tertiary use their Part 14 styles. Validation follows the as-you-type rule. **No colour beyond the button hierarchy and semantic use.** |
| 12 | Illustration / Minty character | **None needed.** It is a short form step, and the wizard's own chrome carries identity. |
| 13 | Does a chart add understanding? | **No chart.** |
| 14 | How it avoids flat hierarchy | Three distinct button weights (Primary, Secondary, tertiary) replace the old one-button-plus-text, so every path is visible and ranked. |
| 15 | Consistent without generic | Part 14 buttons and form fields, unchanged. The difference is the ranking, not new components. |
| 16 | How it stays "not an obvious accounting system" | It talks about people and what each role lets them do, in plain words, not permission names. |

## 7. Preserved: Basic Information (9D) and individual Payment Request (9G)
These two are deliberately left as they are, because each already has the right anchor for its mode.
- **Basic Information (9D) — guided data entry.** The form is the anchor: one column of fields, in the order the person knows them, validated as they type, with Continue as the one Primary. Adding a colour block, a character or a chart would put something between the person and the next field. The wizard's progress and header already carry identity.
- **Individual Payment Request (9G) — Record / document review.** The document is the anchor: the request with its status pill, amount, supplier, due date and attachments, with actions in Part 15's Record header. People come here to check and act on one record, and a record reads best as a document. A decorative element would only push the facts down. The list (§3) is where prioritising happens.

---

## Conflicts logged (the owner's brief is the latest update: Part 15 §15.0)
- §15.7 lists the report chart as "optional ('if kept')". This round keeps charts, following the theme rules (brand plus neutral, no red/green meaning) and the accessibility rules (each chart has a table alternative).
- §15.4 removed the mascot beside lists. That is honoured: PRW uses module art only.
- §13.10 and §13.11 sizes are respected, with at most one character per screen.
