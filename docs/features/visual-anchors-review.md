# Visual anchors — second-stage corrective review (validation round, 2026-10-19)

The owner's brief, 2026-10-19: the revised UI is clearer, but it flattened hierarchy, page identity, colour and character. Each page needs one meaningful visual anchor that fits its Mental Mode. *Simplicity means less thinking, not fewer visual elements.* This round redraws four screens only. Everything else waits until this round is validated.

Built on branch `design/visual-anchors` in Minty, minty-web and minty-payment-request-web, on top of the 2026-10-16 work, and merged into each repo's `development` on 2026-10-19.

## Why these four
| Test required by the brief | Screen | Brief finding |
|---|---|---|
| Reporting / Operational Review | Daily Report (Flask `report/ending.html`) | 9A |
| Orientation / major entry, with controlled illustration | Subscription & Billing overview (minty-web `/subscription`) | 9B |
| Work Coordination / overview | Payment Request overview (PRW) | 9F |
| Illustration appropriate but held back | Company selection (minty-web `/entities`) | 9H |

Not in this round:
- **Basic Information (9D)** and the **individual Payment Request (9G)** are preserved as they are. Each already has the right anchor: the form, and the document.
- **Module selection (9C)** and **User invitation (9E)** are smaller hybrid or action-hierarchy fixes. They are next.

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

---

## Conflicts logged (the owner's brief is the latest update: Part 15 §15.0)
- §15.7 lists the report chart as "optional ('if kept')". This round keeps charts, following the theme rules (brand plus neutral, no red/green meaning) and the accessibility rules (each chart has a table alternative).
- §15.4 removed the mascot beside lists. That is honoured: PRW uses module art only.
- §13.10 and §13.11 sizes are respected, with at most one character per screen.
