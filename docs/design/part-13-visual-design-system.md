<!-- Mirror of "Part 13. Minty Visual Design System.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

# Part 13. Minty Visual Design System

Version 1.1 · Approved · 7 October 2026

Status: approved by the Product Owner (decisions of 6 Oct 2026). v1.1 (7 Oct 2026) applies Stage 4 corrections only: stale Primary-button sentence in 13.14 and conflict C-04 aligned with D-02; ‘Submitted’ is Info in every module; colour-role principle 4 aligned with principle 7; counts corrected to the library (56 primitives, 56 legacy paint styles); sources point to Part 2 instead of legacy Part 12; Lemon Chick’s grumpy face recorded as an owner exception to the expression rule (13.11); targeted review added principle 9 (Answers before records, D-26) and moved Voided to Neutral (D-27). No other decision was reopened.

## 13.1 Purpose, scope and authority

Part 13 translates the product, user and UX rules of Parts 1–12 into a practical visual system: colour, typography, spacing, shape, surfaces, icons, illustration, the Minty mascot, motion, tokens, themes, responsive behaviour and accessibility. It defines the foundations that Part 14 (Component Library) and Part 15 (Pattern Library) are built from.

**In scope:** visual foundations and the rules for applying them. **Out of scope:** component anatomy and states (Part 14), screen and workflow patterns (Part 15), business rules and copy (Parts 1–12).

**Authority.** Parts 1–12 govern meaning — what something is, who it is for and what it must achieve. Part 13 governs how that meaning looks. Where this document and the Figma library disagree, this document states the intent and the library is corrected. Where a visual preference conflicts with a Parts 1–12 rule (for example, accessibility or 'business before system'), the Parts 1–12 rule wins.

**Executable source.** The values in this document live as variables and styles in the Figma library “digitalisation’s team library” (collections Minty v2 · Primitives, Minty v2 · Semantic, Minty v2 · Dimension; text styles and effect styles prefixed “Minty v2/”). Product screens bind to these; they never use raw hex values.

**Companion artefacts** (all dated 5–6 Oct 2026): library pages “Minty v2 · Foundations” and “Minty v2 · Components”; UI file pages “00 · Palette & tokens” (v2 board, bound to library variables), “02 · Components” (v2 board) and “13 · Visual direction” (current vs v2 on real screens).

## 13.2 Evidence and current visual DNA

Sources reviewed: Parts 1–12 (latest versions, 5 Oct 2026), the Existing UI Design Intent Recovery Audit, the FINAL UI/UX Figma file (22 pages, 57 screens across Flask, Next and billing frontends), the team library (variables, styles, the “Decision — brand teal” page), and the development QA checklist.

### Findings

| **Finding** | **Evidence** | **Consequence for Part 13** |
|---|---|---|
| Teal has fragmented into many values | 68 distinct teals in the UI file; #54D3DA is the most used (4,420 nodes). White text on #54D3DA is 1.79:1. | One teal ramp with #54D3DA as the brand seed (Minty Primary); a dedicated Minty Action colour #3CBCC3 for primary CTAs. |
| Three neutral families are mixed | Warm greys (#FBFBFA, #D9D9D6), Tailwind greys (#D1D5DB, #9CA3AF, #374151) and pure greys (#656565) appear together in the library. | One teal-tinted neutral family with 15 steps, including dark-mode surfaces. |
| Inputs are not perceivable | Input borders #D1D5DB (1.47:1) and #E5E7EB (1.24:1) on white. WCAG 1.4.11 needs 3:1. | border/input = neutral/500 (3.44:1). |
| Module colours collide with meaning | Payment module blue is the same hex as the info colour; Petty Cash amber sits 4° of hue from warning. | Module colour is identity-only; info moves to neutral; warning always carries icon + text. |
| Library has two sources of truth | 110 variables in one Light mode (64 unscoped), plus 56 paint styles duplicating them; brand ramp out of order (500 lighter than 400); 32 text styles, 24 in Plus Jakarta Sans; 13 shadow styles; 8 radius values. | Three-tier token architecture, scoped variables, Light/Dark modes, 13 Inter text styles, 2 effect styles, 5 radii. |
| Status, action and amount share one visual grammar | Payment Request list: a filled 'Pay' button sits in the Status column next to status pills; unpaid amounts are coloured green/orange (≈3:1). | Status is always a pill; one action beside it; amounts are always text/primary. |
| The mascot occupies working space | A large office-scene cat takes ≈20% of the Payment Request working list. | Mascot rules (13.11): moments, not working surfaces. |
| A rich illustration and character library exists | An official 3D character cast — Minty (Shop Manager), Penny (Cashier), Ollie (Accountant), Ms Lemon (Admin) — each with expression, action and work-prop sheets; plus older 2D art (office-scene cat, Petty Cash step scenes, module art). | Characters follow the user role; use them widely wherever they do not harm the page's purpose (13.11). |
| Icons are local components | Chevron down ×1,093 and Check ×694 instances; billing frontend uses Material Symbols. | One outline icon set (13.9). |
| Form factors are intentional | Petty Cash is designed at 430 (phone at the till); Bill at 1440 (desk). | Preserve; responsive foundations (13.15) treat phone as primary for Petty Cash. |

### Visual DNA to preserve

- A bright, fresh Minty teal as the single brand colour.
- A friendly character cast led by Minty the cat, in teal brand accessories.
- White working canvas with lightly bordered cards; rounded but restrained geometry.
- Inter as the working typeface; step-based progress as the main orientation device in workflows.
- Easy view as the non-accounting reading of financial lists (Audit, Easy vs Table).

The visual direction board (UI file, page “13 · Visual direction”) shows two real screens — Payment Request list (desktop) and Petty Cash home (mobile 430) — current versus v2, labelled Preserve / Refine / Replace.

## 13.3 Visual personality and design principles

Minty should look like a friendly operating assistant, not accounting software: **fresh, bright, approachable, calm and trustworthy.** Brightness comes from the brand teal and the mascot; trust comes from dark readable text, quiet surfaces and consistent meaning.

| **#** | **Principle** | **What it means visually** |
|---|---|---|
| 1 | Business before system | Business status and money are the most prominent information; system and technical states are quieter (Part 1, Part 5). |
| 2 | Meaning is never colour alone | Every status, error and selection also has text, an icon or a shape change. |
| 3 | One primary action per screen | Only one Primary (filled teal) button is visible per screen or modal; other actions are Secondary, Ghost or Link. |
| 4 | Colour encodes role, not decoration | Status colours mean status; module colours mean module identity; Minty Action means the primary action; selection uses border/selected and state/selected. No colour is used for decoration alone. |
| 5 | Calm by default, urgency is earned | Tone follows consequence: a missed report or cash difference is Warning, not Danger. Red is reserved for destructive actions and failures that lose work (Part 10.22). |
| 6 | Borders separate, shadows float | Resting surfaces use a 1px border; only overlays (menus, popovers, modals) cast shadows. |
| 7 | Brand and action are separate colours | Minty Primary #54D3DA identifies (logo, icons, illustrations, progress); Minty Action #3CBCC3 moves work forward (primary CTAs, white label). |
| 8 | Characters make Minty friendly — without getting in the way | Use the cast as widely as possible, as long as the page’s own purpose is not harmed: never inside tables, rows, fields being filled, or money errors. |
| 9 | Answers before records | The first thing the eye lands on is the answer to the user’s question, not the record’s fields. The answer takes the strongest position (page or card heading, KPI value, status with next action); record attributes follow as Description rows or secondary text. Examples: “How much did we make yesterday?” before transaction lines; “Should this payment be processed?” before accounting attributes; “Can my staff access Minty?” before account administration; “Is everything set up and working?” before configuration details. (Part 3 §3.10, Part 5 §5.7.7–5.7.8, Part 8; evidenced by the Existing UI Design Intent Recovery Audit.) |

## 13.4 Colour system

Colour is organised in three tiers. **Primitives** are raw values (ramps) and are hidden from designers’ pickers. **Semantic roles** are what screens use; each role has a Light and a Dark value. **Component tokens** (Part 14) may alias semantic roles where a component needs its own name. Screens must bind to semantic roles only.

### Brand — one teal ramp (hue 183°)

The seed is **brand/400 #54D3DA**, the most-used teal in the product. All other teals (#00CBC6, #36C3B4, #4FC7C7, #2CB0A2 and others) are absorbed into this ramp.

| **Token** | **Hex** | **Role** |
|---|---|---|
| brand/50 | #EFFAFA | Selected fill (Light) |
| brand/100 | #D6F3F5 |  |
| brand/200 | #ACE8EC |  |
| brand/300 | #83DDE2 | Link/focus (Dark) |
| brand/400 | #54D3DA | Minty Primary — brand seed (never a CTA fill) |
| brand/500 | #3EC4CC |  |
| brand/600 | #29A7AE |  |
| brand/700 | #1D8A90 | Selected border · Secondary border |
| brand/800 | #19676B | Link · focus ring (Light) |
| brand/900 | #16484B | Selected fill (Dark) |
| brand/950 | #0B3B3E | Deep ink on brand surfaces |

### Minty Action — primary CTA colour (owner decision, 6 Oct 2026)

Primary CTA buttons (Save & Next, Continue, Submit Request, Confirm) use **Minty Action #3CBCC3** with a **white SemiBold label**. Hover #35B2B9, pressed #2FA4AB. This keeps the friendly mint look and white text while separating the brand colour (identity and recognition) from the action colour (confirmation and progression). No text outline, no artificial shadow, no dark teal, no dark text on mint.

| **Token** | **Hex** | **Role** |
|---|---|---|
| mint-action/500 | #3CBCC3 | Primary CTA fill |
| mint-action/600 | #35B2B9 | Hover |
| mint-action/700 | #2FA4AB | Pressed |

**Documented accessibility exception.** White on #3CBCC3 measures 2.29:1, below the WCAG AA text level (4.5:1). The product owner accepted this to preserve the brand personality. Safeguards: labels are at least 14px SemiBold; white-on-mint is used only for Primary CTA labels (never for body text, captions, amounts or status); every Primary button has a clear verb label; the button never carries information that is not also available elsewhere.

### Neutral — one teal-tinted grey family

| **Token** | **Hex** | **Role** |
|---|---|---|
| neutral/0 | #FFFFFF | Page and card (Light) |
| neutral/25 | #F8F9F9 |  |
| neutral/50 | #F3F4F4 | Sunk surface, hover |
| neutral/100 | #E8EAEA | Subtle divider |
| neutral/200 | #D9DCDB | Card border |
| neutral/300 | #BFC4C4 |  |
| neutral/400 | #A3AAAA | Disabled text |
| neutral/500 | #848C8C | Input border |
| neutral/600 | #676F6F | Muted text |
| neutral/700 | #535A5A | Secondary text |
| neutral/800 | #404545 | Info ink |
| neutral/900 | #242828 | Primary text; raised surface (Dark) |
| neutral/925 | #1E2222 | Sunk (Dark) |
| neutral/950 | #181B1B | Card (Dark) |
| neutral/975 | #111313 | Page (Dark) |

### Semantic roles (Light / Dark)

| **Role** | **Light** | **Dark** | **Use** |
|---|---|---|---|
| brand/primary | brand/400 #54D3DA | brand/400 #54D3DA | Minty Primary: logo, icons, illustrations, charts, highlights, progress |
| surface/page | neutral/0 #FFFFFF | neutral/975 #111313 | App background |
| surface/card | neutral/0 #FFFFFF | neutral/950 #181B1B | Cards, rows, inputs |
| surface/sunk | neutral/50 #F3F4F4 | neutral/925 #1E2222 | Read-only fields, grouped areas |
| surface/raised | neutral/0 #FFFFFF | neutral/900 #242828 | Menus, popovers, modals |
| surface/document | neutral/100 #E8EAEA | neutral/975 #111313 | Evidence/document viewer backdrop |
| border/subtle | neutral/100 #E8EAEA | neutral/900 #242828 | Table dividers, app bar rule |
| border/default | neutral/200 #D9DCDB | neutral/800 #404545 | Card and row borders |
| border/input | neutral/500 #848C8C | neutral/600 #676F6F | Input/select borders (≥3:1) |
| border/selected | brand/700 #1D8A90 | brand/400 #54D3DA | Selected item border |
| border/focus | brand/800 #19676B | brand/300 #83DDE2 | 2px focus ring |
| text/primary | neutral/900 #242828 | neutral/25 #F8F9F9 | Titles, amounts, body |
| text/secondary | neutral/700 #535A5A | neutral/300 #BFC4C4 | Descriptions, secondary text |
| text/muted | neutral/600 #676F6F | neutral/400 #A3AAAA | Captions, metadata, placeholders |
| text/disabled | neutral/400 #A3AAAA | neutral/600 #676F6F | Disabled labels (exempt) |
| text/link | brand/800 #19676B | brand/300 #83DDE2 | Links, emphasised text |
| text/inverse | neutral/0 #FFFFFF | neutral/900 #242828 | Text on dark fills |
| action/primary | mint-action/500 #3CBCC3 | mint-action/500 #3CBCC3 | Primary CTA fill (Minty Action) |
| action/primary-hover | mint-action/600 #35B2B9 | mint-action/600 #35B2B9 | Primary hover |
| action/primary-pressed | mint-action/700 #2FA4AB | mint-action/700 #2FA4AB | Primary pressed |
| action/on-primary | neutral/0 #FFFFFF | neutral/0 #FFFFFF | White label on Primary (brand exception) |
| action/secondary-border | brand/700 #1D8A90 | brand/400 #54D3DA | Secondary button border |
| action/secondary-text | brand/800 #19676B | brand/300 #83DDE2 | Secondary/Ghost label |
| action/danger | red/700 #C2363B | red/300 #F29A9D | Destructive button fill |
| action/on-danger | neutral/0 #FFFFFF | neutral/975 #111313 | Label on danger |
| action/disabled | neutral/100 #E8EAEA | neutral/900 #242828 | Disabled fill |
| state/selected | brand/50 #EFFAFA | brand/900 #16484B | Selected row/chip fill |
| state/hover | neutral/50 #F3F4F4 | neutral/925 #1E2222 | Hover fill |
| status/success-bg | green/100 #DFF4EC | green/900 #12352A | Success pill/alert bg |
| status/success-ink | green/800 #0C5C42 | green/300 #6FD7AE | Success text/icon |
| status/warning-bg | amber/100 #FDF0DC | amber/900 #3A2A0E | Warning bg |
| status/warning-ink | amber/800 #7E4E05 | amber/300 #F5C46E | Warning text/icon |
| status/danger-bg | red/100 #FCECEC | red/900 #3E1A1C | Danger bg |
| status/danger-ink | red/800 #A82A2F | red/300 #F29A9D | Danger text/icon |
| status/info-bg | blue/50 #E7F4FE | blue/900 #132A44 | Info bg (Payment Requested) |
| status/info-ink | blue/800 #1B57B4 | blue/300 #8CC8F8 | Info text/icon |
| status/neutral-bg | neutral/100 #E8EAEA | neutral/900 #242828 | Neutral bg |
| status/neutral-ink | neutral/700 #535A5A | neutral/300 #BFC4C4 | Neutral text |
| module/pettycash | yellow/500 #F5B945 | yellow/500 #F5B945 | Petty Cash identity |
| module/pettycash-wash | yellow/50 #FEF7E9 | yellow/900 #3A2D12 | Petty Cash icon bg |
| module/pettycash-ink | yellow/800 #8A5606 | yellow/300 #F7CE7A | Petty Cash glyph |
| module/payment | blue/500 #3AA6F5 | blue/500 #3AA6F5 | Payment identity |
| module/payment-wash | blue/50 #E7F4FE | blue/900 #132A44 | Payment icon bg |
| module/payment-ink | blue/800 #1B57B4 | blue/300 #8CC8F8 | Payment glyph |
| action/danger-hover | red/800 #A82A2F | red/200 #F5B8BA | Destructive hover |
| accent/avatar-bg | yellow/50 #FEF7E9 | yellow/900 #3A2D12 | Avatar bg |
| accent/avatar-ink | yellow/800 #8A5606 | yellow/300 #F7CE7A | Avatar initials |
| overlay/scrim | #111313 @48% | #000000 @64% | Modal backdrop |

### Status tones

Business status uses one grammar: a soft background with deep ink text, in a pill. The words carry the meaning; colour supports it.

| **Tone** | **Business statuses** | **Notes** |
|---|---|---|
| Success | Paid · Connected | Completed, nothing further needed. |
| Warning | Partially Paid · Returned · Not submitted · Cash difference · Trial ending soon | Needs attention; not a failure. |
| Danger | Payment failed · Upload failed | Something was lost, cancelled or blocked. |
| Info | Payment Requested · Submitted (every module, incl. Daily Report) · In review · Syncing | Blue. Payment Requested is Treasury’s to-do, so it must stand out (owner decision). |
| Neutral | Draft · Not started · Voided | No action pending yet. |

### Module colours

Petty Cash (amber #F5B945) and Payment Request (blue #3AA6F5) come from the module art and are kept. They are **identity colours only**: module chip, navigation, module art and plan cards. They are never used for amounts, alerts or buttons. The Info status uses the same blue family deliberately: inside Payment Request, ‘Payment Requested’ is the module’s central to-do.

### Rules

- Do bind every colour to a semantic role. Do not paste hex values into product screens.
- Do use Minty Action (action/primary) for primary CTAs only. Do not use Minty Primary #54D3DA as a button fill; use brand/primary for logo, icons, illustrations, charts, highlights and progress.
- Do show amounts in text/primary. Do not colour amounts to express status.
- Do use state/selected only for selection. Do not use it as a status pill background.
- Do use Danger for destructive actions and lost work only. Do not use red for business situations such as a missed report.
- The brand gradient #00CBC6 → #00D5BF (and the three-stop subscription header gradient) is an **exception asset**, not a token: marketing site, subscription header and celebratory moments only.

### Contrast (WCAG 2.1 AA)

All text/background and UI-boundary pairs pass in both themes except the documented Primary CTA exception above. Representative pairs:

| **Pair** | **Light** | **Dark** | **Required** |
|---|---|---|---|
| White label on Minty Action (documented exception) | 2.29:1 | 2.29:1 | 4.5:1 (exception) |
| Body text on card | 14.90:1 | 16.43:1 | 4.5:1 |
| Secondary text on card | 7.05:1 | 9.83:1 | 4.5:1 |
| Muted text on card | 5.15:1 | 7.34:1 | 4.5:1 |
| Link on card | 6.58:1 | 11.07:1 | 4.5:1 |
| Input border on card | 3.44:1 | 3.37:1 | 3:1 |
| Focus ring on card | 6.58:1 | 11.07:1 | 3:1 |
| Danger label on danger | 5.41:1 | 8.78:1 | 4.5:1 |
| Success ink on bg | 6.97:1 | 7.66:1 | 4.5:1 |
| Warning ink on bg | 6.27:1 | 8.57:1 | 4.5:1 |
| Danger ink on bg | 6.04:1 | 7.22:1 | 4.5:1 |
| Info ink on bg | 6.12:1 | 8.13:1 | 4.5:1 |
| Neutral ink on bg | 5.84:1 | 8.45:1 | 4.5:1 |
| Payment ink on wash | 6.12:1 | 8.13:1 | 4.5:1 |
| Petty Cash ink on wash | 5.77:1 | 8.99:1 | 4.5:1 |

## 13.5 Typography

**Inter** is the single working typeface for all product UI. **Plus Jakarta Sans** is reserved for the Minty wordmark and logo lock-ups. Minty is provided in **English only**, so no second-script typeface is part of the system.

Code stack: font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif. If a customer uses their browser’s translate feature, characters Inter does not cover fall back to the device’s own system fonts — no extra font is needed.

| **Style** | **Size / weight** | **Line height · tracking** | **Use** |
|---|---|---|---|
| display/xl | 40 / Extra Bold | 110% · −1.2 | Hero amount on a decision screen (max one per screen) |
| display/l | 32 / Bold | 115% · −0.9 | Large amount, KPI |
| display/m | 24 / Bold | 125% · −0.6 | Screen title |
| title/l | 20 / Bold | 135% · −0.3 | Card title, module name in app bar (desktop) |
| title/m | 16 / Semi Bold | 140% | Row title, supplier name |
| body/l | 15 / Regular | 160% | Reading text on decision screens |
| body/m | 14 / Regular | 155% | Default body, input values |
| body/m-strong | 14 / Semi Bold | 155% | Emphasis inside body, selected chip label |
| body/s | 13 / Regular | 150% | Secondary information, metadata |
| label | 12 / Semi Bold | 140% · +0.2 | Form labels, table headers |
| caption | 12 / Regular | 145% | Captions, footnotes |
| button | 14 / Semi Bold | 100% | Button labels |
| amount/kpi | 32 / Bold | 115% · −0.9 | KPI amounts (tabular numerals) |

### Rules

- Minimum text size is 12px. The previous 11.5px caption and 7.6–10px step labels are retired.
- White labels on Minty Action are at least 14px SemiBold (13.4 exception safeguard).
- Amounts use tabular numerals (font-variant-numeric: tabular-nums) and are right-aligned in tables.
- One display style per screen. Hierarchy comes from size and weight, not colour.
- Layouts tolerate longer or shorter text (browser translation, long supplier names): no fixed-width buttons, tabs or pills; text wraps rather than clips.
- Amounts, account codes, invoice numbers and the name ‘Minty’ are marked translate="no" in code so browser translation never alters them.
- Keep reading lines under roughly 72 characters on desktop.

## 13.6 Spacing foundations

Spacing follows a 4px base. Every padding and gap uses a Dimension token.

| **Token** | **Value** | **Typical use** |
|---|---|---|
| space/1 | 4 | Icon–label gap, tight groups |
| space/2 | 8 | Between related controls, button gap |
| space/3 | 12 | Inside compact components, alert padding |
| space/4 | 16 | Card padding (mobile), page padding (phone) |
| space/5 | 20 | Row-card padding (desktop) |
| space/6 | 24 | Between sections (mobile), modal padding |
| space/8 | 32 | Page padding (desktop), between sections (desktop) |
| space/10 · 12 · 16 | 40 · 48 · 64 | Large layout gaps, empty-state padding |

### Density

**Comfortable** is the default for every user and every phone screen: 44px controls, 16–20px row padding. **Compact** is allowed only on desktop Table view and accountant-oriented review screens (Professional Review / Reconciliation modes, Part 2): row padding may drop to 8–12px and secondary controls to 32px. Touch targets on touch devices never drop below 44px.

## 13.7 Shape and border system

| **Token** | **Value** | **Use** |
|---|---|---|
| radius/sm | 4 | Checkboxes, tags inside tables |
| radius/md | 8 | Inline alerts, small controls, tooltips |
| radius/lg | 12 | Buttons, inputs, selects (controls) · cards, record rows, modals |
| radius/xl | 16 | Sheets, large onboarding panels |
| radius/full | 999 | Status pills, filter chips, avatars, toggles |

- Buttons use radius 12 (owner decision: existing shape, 10–12px). Inputs and selects match at 12 so buttons and fields align in one row. Buttons are never pills.
- Nested corners: inner radius = outer radius − padding, never larger than the outer radius.
- Borders are 1px (border/default, border/input). 2px is reserved for focus, selected inputs and input errors.

## 13.8 Surface and elevation system

| **Level** | **Surfaces** | **Treatment** |
|---|---|---|
| 0 · Flat | Page, cards, rows, inputs | No shadow. Cards and rows separate with a 1px border/default. |
| 1 · Overlay | Menus, popovers, dropdowns, toasts | Effect style Minty v2/elevation/overlay; surface/raised. |
| 2 · Modal | Dialogs, sheets | Effect style Minty v2/elevation/modal over overlay/scrim; surface/raised. |

- No hover shadows. Hover is a fill change (state/hover).
- In Dark mode, elevation is shown by lighter surfaces (975 → 950 → 925 → 900), not by stronger shadows.
- The 13 legacy effect styles (step-active, btn-primary, card-hover, card-selected …) are deprecated.

## 13.9 Iconography system

Today icons are local Figma components (Chevron down ×1,093, Check ×694) and the billing frontend uses Material Symbols. Part 13 adopts **one icon set: Material Symbols Rounded** (weight 400, grade 0, Apache 2.0). It is the same family already used in code, in the rounded style that matches the friendly character cast.

| **Size token** | **Value** | **Use** |
|---|---|---|
| size/icon-sm | 16 | Inside pills, inline with 12–13px text |
| size/icon-md | 20 | Buttons, inputs, list rows |
| size/icon-lg | 24 | App bar, navigation, empty-state accents |

- Icons take a text colour role (text/secondary by default, text/link for actions, status ink inside alerts). They never introduce a new colour.
- Actions show an icon with a text label. Icon-only buttons are limited to universally understood actions (close, back, menu, search, more) and always carry an accessible name.
- Status icons always accompany text; an icon alone never communicates a status.
- Coloured icon circles are reserved for the Module chip (module wash) and quick actions (state/selected). The purple and orange circles on Petty Cash quick actions are retired.

## 13.10 Illustration system

| **Family** | **Existing assets** | **Where it may appear** | **Size** |
|---|---|---|---|
| Module art | pettycash-icon, payment-icon, mp-img | Module selection, plan cards, module chip (small) | 28–56 in UI; up to 208 on selection |
| Step scenes | opening, deposit, cash register, safebox | Introducing a Petty Cash step on phone, once per step | ≤ 240 wide |
| Scene illustrations | Office cat scene, Minty filling a form, Minty counting cash | Onboarding, completion, first-use empty states | 280–420 (onboarding/completion only) |
| Spot illustrations | Envelope, hourglass, confetti, card brands | Billing outcomes, small empty states | 80–120 |

- Illustrations are not allowed in working lists, tables, forms mid-entry, dense dashboards, or blocking errors about money.
- The official style is the 3D character render (soft studio light, transparent background, teal accessories). Older 2D art (office-scene cat, Petty Cash step scenes) is legacy and is replaced with 3D character assets over time.
- Decorative illustrations are hidden from assistive technology; meaningful ones have alt text.
- Dark mode: art with a white background is placed on a surface/sunk plate until transparent versions exist (asset audit required).

## 13.11 Minty character system

Minty has an official 3D character cast. **Minty is the default character on every screen.** Penny, Ollie and Ms Lemon appear only in special cases where a second character reduces confusion — typically a two-party moment such as a transfer, where Minty sends and a second character receives (e.g. subscription transfer: Minty → Ms Lemon). All characters are calm, supportive and conscientious helpers — never bossy, judging or alarming (Minty rendering brief).

| **Character** | **Role** | **Personality** | **Appears with** |
|---|---|---|---|
| Minty — black cat | Shop Manager · lead character | Sincere, steadfast, calmly attentive; ‘I want to help you finish this properly — without stress.’ | Default on all screens: home, onboarding, empty states, completion, guidance |
| Penny — penguin | Cashier | Hands-on, friendly, occasionally puzzled (question-mark antenna) | Special cases only — e.g. the other party in a handover |
| Ollie — owl | Accountant | Careful, precise, reassuring; ‘numbers match’ | Special cases only — e.g. the receiving side when work passes to the accountant |
| Ms Lemon — hen (with Lemon Chick) | Admin | Organised, welcoming, decisive | Special cases only — e.g. the receiving side of a subscription/ownership transfer |

### Placement — use widely, without harming the page’s purpose

| **Zone** | **Where** | **Size** |
|---|---|---|
| Always allowed | Onboarding, empty states, completion and success, loading and waiting, sign-in, settings landing, reminders and emails | 56–280 |
| Allowed with care | Home/dashboard greeting card, beside a list page title, desktop side area when width is spare (collapsible), step introductions on phone, toasts (small avatar) | 40–120 |
| Not allowed | Inside tables and rows, between fields being filled, money errors that block work, destructive confirmation dialogs, on top of data | — |

- One character per screen (Minty). Two characters only in sender/receiver moments; the full group only on welcome, onboarding and marketing surfaces.
- Do not swap characters by module or user role; consistency of one familiar guide matters more than role matching.
- Expressions in product UI: neutral, happy, waving, thumbs up, celebrating, explaining, pointing, thinking, approved, ‘numbers match’, and work-prop poses.
- Use with care, only to show empathy (never blame): confused, don’t-get-it, mistake, exhausted, sad — e.g. ‘Upload didn’t finish — let’s try again’.
- Not used in product UI: angry, very angry, judging, crying, rejected / not approved. These conflict with the calm, non-judgemental brief; keep them for internal or marketing use only. Exception (owner, 7 Oct 2026): Lemon Chick, the chick Ms Lemon carries, is grumpy by character — its angry face is its default and is allowed wherever Ms Lemon appears; it is shown calm only in genuinely happy moments. Ms Lemon herself stays calm, and the placement limits still apply (never in tables, fields, money errors or delete confirmations).
- Characters are decorative for assistive technology; the adjacent text must carry the message alone.
- Assets: the supplied files are PNGs with a beige background. Product use needs transparent PNG/WebP at 2× for each placement size; one master file per character in the asset library.
- Files named ‘Lemon_…’ show Lemon Chick (the chick Ms Lemon carries); ‘Ms Lemon’ is the hen.

## 13.12 Motion and transition foundations

| **Duration** | **Use** | **Easing** |
|---|---|---|
| 100 ms | State change (hover, press, toggle) | ease-out |
| 200 ms | Small enter/exit (menus, toasts, inline alerts) | ease-out in, ease-in out |
| 300 ms | Sheets and modals | standard (0.2, 0, 0, 1) |

- Celebration motion (confetti, all-set video) is for true completion only: module selection, onboarding finished, report submitted.
- No motion on errors other than moving focus to the message.
- Respect prefers-reduced-motion: confetti and video autoplay are disabled; transitions become instant fades.

## 13.13 Design-token architecture

| **Tier** | **Collection / style** | **Naming** | **Visible to designers?** |
|---|---|---|---|
| Primitive | Minty v2 · Primitives (56 colours, incl. 3 Minty Action) | color/&lt;family>/&lt;step> — e.g. color/brand/400 | No (scopes empty) |
| Semantic | Minty v2 · Semantic (Light, Dark) | color/&lt;group>/&lt;role> — e.g. color/action/primary | Yes, scoped by property |
| Dimension | Minty v2 · Dimension | space/4, radius/md, size/control-md, border/width-default | Yes, scoped |
| Type | Text styles “Minty v2/…” | Minty v2/body/m | Yes |
| Effect | Effect styles “Minty v2/elevation/…” | overlay, modal | Yes |

- Every variable has a WEB code syntax: semantic roles map to var(--color-&lt;group>-&lt;role>), primitives to var(--minty-&lt;family>-&lt;step>), dimensions to var(--space-4) etc.
- Scopes are set so fills only offer fill roles, strokes only stroke roles and text only text roles.
- New tokens are added at the semantic tier first; a new primitive is added only when no existing step fits.
- The legacy “Minty” collection (110 variables) and the 56 paint styles remain until screens migrate, then are deprecated (13.18).

## 13.14 Theme architecture

- Light and Dark are two modes of the Semantic collection with identical role names. Components are built once.
- Dark surfaces step up in lightness with elevation: page 975, card 950, sunk 925, raised 900.
- The Primary fill stays Minty Action (action/primary #3CBCC3) with the white label in both themes (D-02).
- Status pills invert: deep tinted background with light ink.
- Dark mode is part of the guideline now; screen implementation follows after launch (owner decision). Default theme at launch: Light.
- Status: tokens complete and validated on real screens (visual direction board, Dark versions); component dark-mode review happens in Part 14.

## 13.15 Responsive visual foundations

Breakpoint values are defined in Part 5. Part 13 defines what changes visually across the three form factors.

|  | **Phone (design 430)** | **Tablet (Small Desktop)** | **Desktop (design 1440)** |
|---|---|---|---|
| Page padding | 16 | 24 | 32 |
| Screen title | display/m | display/m | display/m |
| Hero amount | display/l | display/xl | display/xl |
| App bar | 56, back + module name | 60 | 60, module name + entity name |
| Lists | Record cards | Record rows | Record rows or Table view |
| Density | Comfortable only | Comfortable | Comfortable; Compact in Table view |
| Touch target | 44 minimum | 44 minimum | 44 for primary controls |

## 13.16 Accessibility foundations

- Target: WCAG 2.1 AA, with WCAG 2.2 Focus Appearance and Target Size adopted early.
- Contrast: 4.5:1 for text, 3:1 for large text and UI boundaries — met by every semantic pair in both themes, except the documented Primary CTA exception (13.4).
- Focus: a visible 2px border/focus ring outside every interactive element; never removed.
- Colour independence: status, errors and selection always add text, an icon or a shape change.
- Targets: 44×44 minimum on touch devices.
- Text: supports 200% zoom without loss of content; no text inside images.
- Motion: prefers-reduced-motion respected (13.12).
- Language: lang="en" on the document; no text inside images, so browser translation and screen readers can read everything.
- Images: decorative art hidden; meaningful art described.

## 13.17 Figma foundation architecture

| **File** | **Page / asset** | **Purpose** |
|---|---|---|
| digitalisation’s team library | Collections Minty v2 · Primitives / Semantic / Dimension | Source of truth for all values |
|  | Minty v2 · Foundations — 5 Oct 2026 | Colour roles (Light/Dark) and type specimen |
|  | Minty v2 · Components — 5 Oct 2026 | Part 14 components (v1.0, approved 7 Oct 2026) |
|  | Existing pages and the legacy “Minty” collection | Kept for running screens; deprecated after migration |
| FINAL UI/UX | 00 · Palette & tokens | v2 board bound to library variables; old draft kept, marked superseded |
|  | 02 · Components | v2 component board; legacy components bannered |
|  | 13 · Visual direction — 6 Oct 2026 | Current vs v2 on real screens, Preserve / Refine / Replace |
|  | 13 · Visual direction → Part 13 · Characters | Cast, role mapping, placement zones, expression rules (with the supplied 3D assets) |
|  | 13 · Visual direction → Part 13 · Icons & Motion | Material Symbols Rounded set, sizes, colour roles, icon+label rules, motion durations |
|  | 13 · Visual direction → Decision boards | Button colour, white-text options, status colours — all stamped ‘결정됨’ 6 Oct 2026 |

- Product screens use library instances and variables only — no local colours, no detached instances.
- Change flow: edit in the library → check contrast → publish → note in the decision log.

## 13.18 Visual-system governance

- **Roles:** the Product Owner approves token, style and preference changes; the Design lead edits and publishes the library. Names are recorded outside this document.
- **Versioning:** Minty v2.x. Value changes are minor versions; role additions or removals are major and are logged.
- **Deprecation:** done 6 Oct 2026. The legacy collection is renamed “Minty (legacy · deprecated 6 Oct 2026)” and its 110 variables, 56 paint, 13 effect and 32 text styles carry a ‘곧 사라짐’ note. They are removed after screen migration (Part 15).
- **QA link: QA follows the user flows and checks each screen against Parts 13–15 by token and component name (e.g. ‘Status pill Tone=Warning’), never by hex; Part 13 §13.19 is the visual checklist. No separate QA instruction document governs the design (owner, 7 Oct 2026).**

## 13.19 Part 13 validation checklist

| **ID** | **Check** | **How** |
|---|---|---|
| V-01 | No raw hex in product screens | Figma: no unbound solid fills on screen layers |
| V-02 | Every text/background pair meets AA in Light and Dark | Contrast table 13.4 |
| V-03 | Exactly one Primary button visible per screen/modal | Visual review |
| V-04 | Primary CTA uses Minty Action #3CBCC3 with a white 14px+ SemiBold label; #54D3DA is never a button fill | Visual review |
| V-05 | Amounts use text/primary and tabular numerals | Visual + code review |
| V-06 | Status shown by Status pill with text; module colours absent from status | Visual review |
| V-07 | Inputs use border/input; focus ring visible | Keyboard walk-through |
| V-08 | Resting cards have a border and no shadow | Visual review |
| V-09 | Characters follow the placement zones and role mapping (13.11); none inside tables, rows or fields | Visual review |
| V-10 | Text ≥ 12px; layouts survive longer text without clipping | Visual review with long strings |
| V-11 | Touch targets ≥ 44px on phone | Measure |
| V-12 | Reduced-motion disables celebration motion | OS setting test |
| V-13 | Dark mode renders with no unreadable text | Switch mode |

## Appendix A — Decision log

| **ID** | **Decision** | **Reason / source** |
|---|---|---|
| D-01 | Brand seed = brand/400 #54D3DA | Most-used teal (4,420 nodes); Decision — brand teal page |
| D-02 | Primary CTA = Minty Action #3CBCC3 + white label (hover #35B2B9, pressed #2FA4AB) | Product-owner decision 6 Oct 2026: keeps brand personality; separates brand and action. 2.29:1 documented as exception |
| D-03 | One teal ramp, hue 183°, 50–950 | Removes 68 fragmented teals |
| D-04 | One teal-tinted neutral family, 15 steps | Removes three mixed grey families; adds Dark surfaces |
| D-05 | White canvas, 1px borders, no resting shadows | ‘The language you picked’ (12 · One layout) |
| D-06 | border/input = neutral/500 (3.44:1) | WCAG 1.4.11 |
| D-07 | Info tone = blue; Payment Requested = Info | Product-owner decision: Treasury’s to-do must stand out |
| D-08 | Module colours kept, identity-only | Colours come from module art; prevents status confusion |
| D-09 | Status pill = soft bg + deep ink only; tint reserved for selection | One status grammar; Part 14 brief |
| D-10 | Destructive fill red/700 with white label (5.41:1) | Previous danger fill failed with white (3.91:1) |
| D-11 | Control height 44; buttons, inputs and selects radius 12 | Touch target; owner decision on button radius (10–12); fields aligned |
| D-12 | Radius scale reduced from 8 values to 5 | Consistency |
| D-13 | Inter for all UI; Plus Jakarta Sans for the wordmark only; no second-script font | Reduce 7 faces to 2; Minty is English-only (owner, 7 Oct 2026) |
| D-14 | Minimum text 12px (caption 11.5 → 12) | 4px grid; legibility at small sizes |
| D-15 | Light and Dark modes in the Semantic collection | Part 1 B.10 requirement |
| D-16 | Only two effect styles (overlay, modal) | Follows D-05 |
| D-17 | Gradients are exception assets, not tokens | Keeps brand moments without polluting the system |
| D-18 | v2 built alongside legacy; nothing deleted | No silent deletion; running screens depend on legacy |
| D-19 | Characters used widely within placement zones; never inside tables, rows or fields | Owner decision #4 balanced with Part 1 §1.12.4 |
| D-20 | Icon set = Material Symbols Rounded | Already in code; rounded style matches the character cast |
| D-21 | Missed report and cash difference = Warning; calendar ‘Today’ = ring | Part 10.22 / 10.27; owner approved. Petty Cash dashboard is being redefined, so treat as example only |
| D-22 | Brand role brand/primary (#54D3DA): logo, icons, illustrations, charts, highlights, progress | Owner decision: brand vs action separation |
| D-23 | Official cast: Minty (default), Penny, Ollie, Ms Lemon (special two-party cases only, e.g. transfer Minty → Ms Lemon) | Character files 6 Oct 2026; owner rule 7 Oct 2026 |
| D-24 | Dark mode in the guideline now; screen implementation after launch | Owner decision #8 |
| D-25 | Legacy tokens and styles marked deprecated, not deleted | Owner decision #10 |
| D-26 | Principle 9 “Answers before records” added (visual expression of Part 3 §3.10 and Part 5 rhythm rules) | Targeted review, 7 Oct 2026 |
| D-27 | Voided status tone moves from Danger to Neutral: an intentional, confirmed end state is not a failure (principle 5). The Void action and its confirmation stay Danger; Payment failed and Upload failed stay Danger | Targeted review, 7 Oct 2026 |

## Appendix B — Assumption log

| **ID** | **Assumption** |
|---|---|
| A-01 | Figma has no edit timestamps; ‘latest’ was judged from page creation order and explicit decision markers. |
| A-02 | The ‘Decision — brand teal’ page is the most recent colour decision; the palette draft is superseded. |
| A-03 | Front-ends consume tokens as CSS custom properties. |
| A-04 | Material Symbols can be used in all three front-ends. |
| A-05 | ‘Localization’ in Part 11 §11.30 means country-specific accounting concepts (e.g. Korean VAT, Singapore GST), not UI translation — no visual-system impact. |
| A-06 | Petty Cash keeps its amber identity because it is drawn into the module art. |
| A-07 | Daily Closing step names follow Part 2 §2.6.1 (confirmed by D15-05): Addition to Drawer · Sales · Expenses · Cash Count · Close. |
| A-08 | Light is the default theme at launch. |

## Appendix C — Preference log (resolved 6 Oct 2026)

| **ID** | **Preference** | **Outcome** |
|---|---|---|
| P-01 | Primary button colour | Minty Action #3CBCC3 + white label (D-02) |
| P-02 | Dark palette | Approved; theoretically correct palette applied (13.14) |
| P-03 | Status tone mapping | Approved; Payment Requested = blue Info (D-07) |
| P-04 | Character scope | Use widely; Minty first, second characters only in special cases (13.11) |
| P-05 | Calendar treatment | Approved; dashboard under redefinition (D-21) |

## Appendix D — Conflict log

| **ID** | **Conflict** | **Resolution** |
|---|---|---|
| C-01 | Theme concept: pill buttons (r999) vs Buttons page: r8 | Neither: radius 12 by owner decision (D-11) |
| C-02 | Theme concept: shadows vs One layout: borders | Borders (explicit pick) |
| C-03 | Palette draft: grey page vs One layout: white canvas | White |
| C-04 | Buttons page: ‘white text stays white’ vs WCAG | Superseded by D-02: Minty Action with white label, documented exception (C-08) |
| C-05 | Development QA checklist: Petty Cash #ea9713, red trial label, white-on-teal | Closed: QA follows user flows against Parts 13–15; older checklist values carry no authority (S4-12) |
| C-06 | Screens: Opening … Ending steps vs Part 2 §2.6.1: Addition to Drawer … Close | Documents win; screens migrate |
| C-07 | Theme concept Track B (game grammar, streaks) | Future only; not in v2 tokens |
| C-08 | Owner decision (white label on #3CBCC3) vs WCAG AA 4.5:1 | Decision applied; documented exception with safeguards (13.4) |
| C-09 | Character sheets include angry, judging and crying expressions (mostly Lemon Chick) vs the calm brief | Not used in product UI (13.11), except Lemon Chick’s default grumpy face (owner exception, 7 Oct 2026) |
| C-10 | Earlier proposals (deep-ink label, grey Info, button r8) in v0.1 and boards | Superseded by D-02, D-07, D-11; boards stamped ‘결정됨’ |
| C-11 | Part 11 §11.30 and the Part 13 brief mention Korean UI support; product is English-only | English-only applied (D-13). Suggest renaming §11.30 to reflect accounting localization |

## Appendix E — Questions

All Part 13 questions were answered on 6 Oct 2026. Items to watch (not blocking):

- The Petty Cash dashboard is being redefined; its calendar and progress card are examples only.
- Final transparent character assets are assumed available (owner, 7 Oct 2026).

### Inputs for Part 14 found during Part 13

- Record row needs fixed column tracks so amount, status and action align across rows (visual direction board, A).
- Components drafted early (Button, Status pill, Input, Select, Filter chip, Avatar, Module chip, Record row, Inline alert, App bar, Confirmation modal, Empty state) already follow v1.0 (Minty Action, radius 12, blue Info) and are re-validated in Part 14.
- Empty state and completion components need character slots that accept the 3D cast (13.11).
