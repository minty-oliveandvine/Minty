<!-- Mirror of "Part 14. Minty Component Library.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

# Part 14. Minty Component Library

Version 1.1 · Approved · 7 October 2026

Status: approved by the Product Owner (answers of 7 Oct 2026). Built on Part 13 v1.1. Part 15 (patterns) may proceed. v1.1 (7 Oct 2026) applies Stage 4 corrections only: Step label minimum aligned to 12px (Part 13); Step progress and Pagination rebuilt and published; Pagination Size = Pointer | Touch; Filter-chip tab semantics and current-step cue added; all statuses Approved (Stage 4 closed 7 Oct 2026). Targeted review (7 Oct 2026): answer-before-record rule added to the global rules; Status pill shows Voided in the Neutral tone (Part 13 D-27).

## 14.0 Purpose, scope and authority

Part 14 turns the Part 13 foundations into reusable, Figma-ready and implementation-ready components. It is not a screenshot catalogue: every component states its purpose, when to use and not use it, anatomy, variants, states, content rules, behaviour, responsive and accessibility requirements, Figma properties and development notes.

**Scope:** primitives, components and small composites. Full screens and workflows belong to Part 15. **Authority:** Parts 1–12 govern meaning, Part 13 governs visual foundations, Part 14 governs component behaviour and structure. The Figma library “digitalisation’s team library” → page “Minty v2 · Components” is the executable source.

**Global rules for every component:** bound only to Minty v2 semantic tokens (so Light and Dark work automatically); built with auto layout; 44px minimum touch targets on touch devices; visible 2px focus ring; meaning never by colour alone; English-only copy following Part 11; amounts in text/primary with tabular numerals. Components present the answer before the record (Part 13 principle 9): the element that answers the user’s question — amount, status with next action, KPI value — leads; identifiers and accounting attributes follow.

## 14.A Audited component inventory

Inventory of the FINAL UI/UX file (57 screens; Flask, Next and billing front-ends) and the team library before v2:

| **Source** | **Components found** | **Observation** |
|---|---|---|
| 02 · Components (onboarding) | 22 — Brand mark, 8 icons, Top bar, Step tile, 5 buttons, Field, Select, Card, Side item, Side menu, Step nav | Onboarding-only set; buttons duplicated with other apps |
| 03 · Petty Cash components | 11 — Avatar, Status badge, Header, Header plain, Step pill, Button, Button outline, Link, Card, Input, Total row | Phone dialect of the same controls |
| 04 · Payment Request components | 13 — Header, Button, Button outline, Button ghost, Filter pill, Status pill, Field, Select, SET/Header, SET/Tab pill, Pay mode, Pagination | Desktop dialect; white text on #54D3DA |
| Team library (legacy) | Banner, Date field, Search field, Icon button, Header, Table row, Subscription status, Status pill (Sep 2026) | Partial, not bound to a token system |
| One-off treatments in screens | Expanded grey sub-rows, ‘Pay’ button in status column, coloured amounts, mascot scene panel, red calendar dots | Replaced by Table row (Nested payment), Status pill + action, KPI/Record rules, Character, Warning tone |

**Duplicates found:** 9 button implementations, 4 field implementations, 3 status badges, 4 headers, 2 filter/tab pills. **Future-ready components added** (no current screen yet): AI field, Document viewer, Camera capture, Supplier picker, Bulk action bar, Saving status, Timeline item, Entity selector, Outcome state.

## 14.B Component rationalisation map

| **Existing** | **v2 component** | **Decision** |
|---|---|---|
| Button/Primary, Button/Primary Disabled, Button/Ghost, Button/Block, PC/Button, PC/Button outline, PR/Button, PR/Button outline, PR/Button ghost | Button | Converged |
| Button/Link, PC/Link | Button Kind=Link | Converged |
| Field, PC/Input, PR/Field | Input | Converged |
| Select, PR/Select | Select | Converged |
| PC/Status badge, PR/Status pill, legacy Status pill | Status pill | Converged |
| PR/Filter pill, SET/Tab pill | Filter chip | Converged |
| Top bar, PC/Header, PC/Header plain, PR/Header, SET/Header | App bar | Converged |
| Side menu, Side item | Sidebar · Nav item | Adapted (right-side, per One layout) |
| Step tile, Step nav, PC/Step pill | Step · Step progress | Converged |
| Card, PC/Card, Bill list rows | Record row | Replaced |
| PR/Pagination | Pagination | Preserved & tokenised |
| PR/Pay mode | Segmented control | Replaced |
| PC/Total row | KPI card / Description row | Separated |
| PC/Avatar | Avatar | Preserved & tokenised |
| Icon/* (8 local icons) | Icon (Material Symbols Rounded, 28) | Replaced |
| Grey expanded sub-rows | Table row Type=Nested payment | Replaced |
| Mascot scene panel in list | Character + Empty/Outcome state | Replaced |
| Legacy Banner | Page banner / Inline alert | Separated |
| Brand mark | — (logo asset, not a component) | Retired from component set |

## 14.C Component taxonomy and levels

**Foundations** (Part 13): tokens, text styles, effect styles. **Primitives:** single-purpose elements. **Components:** functional controls and information units. **Composites:** small recurring assemblies. All entries below: design-system status Approved, owner Design lead, version 1.0.

| **Component** | **Family** | **Level** |
|---|---|---|
| Button | 14.1 Actions | Primitive |
| Menu · Menu item | 14.1 Actions | Composite |
| Input | 14.2–14.3 Fields | Component |
| Amount input | 14.2–14.3 Fields | Component |
| Search input | 14.2–14.3 Fields | Component |
| Textarea | 14.2–14.3 Fields | Component |
| Select | 14.4 Selection | Component |
| Supplier picker | 14.4 Selection | Composite |
| Checkbox | 14.4 Selection | Primitive |
| Radio | 14.4 Selection | Primitive |
| Switch | 14.4 Selection | Primitive |
| Segmented control | 14.4 Selection | Composite |
| Filter chip | 14.4 Selection | Primitive |
| Date field · Calendar | 14.4 Selection | Composite |
| File card | 14.5 Files & documents | Component |
| Camera capture | 14.5 Files & documents | Composite |
| Document viewer | 14.5 Files & documents | Composite |
| App bar | 14.6 Navigation | Composite |
| Sidebar · Nav item | 14.6 Navigation | Composite |
| Entity selector | 14.6 Navigation | Composite |
| Step · Step progress | 14.6 Navigation | Composite |
| Pagination | 14.6 Navigation | Component |
| Page header | 14.7 Page & section structure | Composite |
| Section header | 14.7 Page & section structure | Component |
| Description row | 14.7 Page & section structure | Component |
| Record row | 14.8 Cards | Composite |
| KPI card | 14.8 Cards | Component |
| Module chip | 14.8 Cards | Primitive |
| Table row | 14.9 Lists & tables | Composite |
| Bulk action bar | 14.9 Lists & tables | Composite |
| Skeleton row | 14.9 Lists & tables | Primitive |
| Status pill | 14.10 Status & metadata | Primitive |
| Saving status | 14.10 Status & metadata | Component |
| Audit meta | 14.10 Status & metadata | Primitive |
| Timeline item | 14.10 Status & metadata | Component |
| Inline alert | 14.11 Feedback | Component |
| Page banner | 14.11 Feedback | Component |
| Toast | 14.11 Feedback | Component |
| Confirmation modal | 14.12 Overlays | Composite |
| Drawer | 14.12 Overlays | Composite |
| Tooltip | 14.12 Overlays | Primitive |
| Avatar | 14.14 Users & access | Primitive |
| Role badge | 14.14 Users & access | Primitive |
| User row | 14.14 Users & access | Composite |
| Empty state | 14.15 Empty & completion | Composite |
| Outcome state | 14.15 Empty & completion | Composite |
| Character | 14.15 Empty & completion | Primitive |
| AI field | 14.16 AI-related | Component |

## 14.D Figma naming and property model

- Component and set names are plain nouns in Title case (‘Status pill’, ‘Record row’). Variants use Property=Value (Kind, State, Tone, Type, Size, Device, Value, Position, Character).
- Text properties for editable copy (Label, Title, Message, Term, Value…). Boolean properties only for optional parts (Show helper, Show dismiss, Show character, Show back, Show count).
- Instance swap: icons always come from the Icon set; characters from Character; nested Buttons/Pills are instances, never detached copies.
- Every fill, stroke, radius, padding and gap binds to Minty v2 variables; text uses Minty v2 text styles. No local styles.
- A shared text property must not be used where variants need different example text (lesson from validation); such text stays a direct override.
- Auto layout everywhere; variants set to hug their content unless a fixed track is part of the spec (Record row, Table row columns).

## 14.E Component-state matrix

| **Component** | **Default** | **Hover** | **Focus** | **Pressed/Selected** | **Disabled** | **Error** | **Read-only** | **Loading/Processing** |
|---|---|---|---|---|---|---|---|---|
| Button | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | ✓ |
| Input | ✓ | — | ✓ | — | ✓ | ✓ | ✓ | — |
| Amount input | ✓ | — | ✓ | — | — | ✓ | ✓ | — |
| Search input | ✓ | — | ✓ | — | — | — | — | ✓ |
| Textarea | ✓ | — | ✓ | — | — | ✓ | — | — |
| Select | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | — |
| Checkbox | ✓ | — | ✓ | ✓ | ✓ | — | — | — |
| Radio | ✓ | — | ✓ | ✓ | ✓ | — | — | — |
| Switch | ✓ | — | ✓ | ✓ | ✓ | — | — | ✓ |
| Segmented control | ✓ | — | ✓ | ✓ | — | — | — | — |
| Filter chip | ✓ | ✓ | ✓ | ✓ | — | — | — | — |
| Date field · Calendar | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | — |
| File card | ✓ | — | ✓ | — | — | ✓ | — | ✓ |
| Record row | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ |
| Table row | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ |
| Nav item | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Menu item | ✓ | ✓ | ✓ | — | ✓ | — | — | — |
| AI field | ✓ | — | ✓ | ✓ | — | ✓ | — | — |

## 14.F Responsive-component matrix

| **Component** | **Phone (430)** | **Tablet (Small Desktop)** | **Desktop (1440)** |
|---|---|---|---|
| App bar | 56; back + module; entity → avatar < 360 | 60 | 60; module + entity name |
| Sidebar | Sheet from menu | Sheet from menu | Fixed right ≥ 1280 |
| Record row / Table row | Record row (card) | Record row | Record row (Easy) or Table row (Table view) |
| Button | Full-width Primary in forms | Inline | Inline, Primary right |
| Pagination | Load more / prev-next | Pages | Pages + rows per page |
| Bulk action bar | Sticky bottom | Top of list | Top of list |
| Drawer / Modal | Full-screen sheet / bottom sheet | Drawer 480 / modal | Drawer 480 / modal 440 |
| Date field / Select | Native picker | Custom popover | Custom popover |
| Camera capture | Take photo first | Choose file first | Choose file only |
| Document viewer | Full screen | Side panel | Side panel ≥ 480 |

## 14.G Theme matrix

All components bind exclusively to Minty v2 semantic roles, so Dark mode is automatic. Dark-mode rendering was validated on: Button, Input, Status pill, Module chip, Record row (Light/Dark preview frame) and on two full screens (visual direction board). Remaining components are expected to pass because they use the same roles; formal Dark review of each is scheduled with screen migration (Part 15). High-contrast: focus ring, borders ≥3:1 and text ≥4.5:1 hold in both themes, except the documented Primary CTA label exception (Part 13 §13.4).

## 14.1 Actions

### Button

| **Field** | **Specification** |
|---|---|
| Purpose | Starts an action. Primary moves work forward (Save & Next, Submit, Confirm). |
| When to use | One Primary per screen/modal; Secondary for alternatives; Ghost for low-emphasis; Danger only to confirm destruction; Link for text actions (Save & Exit, View all). |
| When not to use | Navigation between pages (use links/nav); status display (use Status pill); two Primaries side by side. |
| Anatomy | Container · optional leading icon (instance swap, Icon) · label. |
| Variants & Figma properties | Kind = Primary \| Secondary \| Ghost \| Danger \| Link × State = Default \| Hover \| Focus \| Disabled. Text prop Label. |
| Sizes & density | Height 44 (touch), radius 12, padding 16; Link padding 4. No size variants — 32px compact only inside desktop tables via Ghost/Link. |
| States | Default, hover, pressed (pressed token), focus ring 2px outside, disabled, processing (label → ‘Saving…’, disabled, spinner/icon). |
| Content rules | Verb + object (‘Record payment’, not ‘OK’). ≤ 3 words where possible; never truncate — wrap or shorten. Primary white label ≥ 14px SemiBold (13.4 exception). |
| Behaviour & keyboard | Enter/Space activates; disable on submit to prevent double-submit; restore on failure with error shown near the cause. |
| Responsive | Full-width Primary on phone forms; inline on desktop. Order: Secondary left, Primary right (desktop); Primary on top/first (phone stacked). |
| Accessibility | &lt;button>; accessible name = label; icon-only not allowed except back/close/menu/search/more with aria-label. Focus ring always visible. |
| Development notes | Primary = action/primary (#3CBCC3) + on-primary white; never brand/primary #54D3DA as a fill. |
| Replaces | Button/Primary, Button/Ghost, Button/Block, Button/Link, PC/Button(+outline), PC/Link, PR/Button(+outline, ghost) |
| Level · status · version | Primitive · Approved · 1.0 |

### Menu · Menu item

| **Field** | **Specification** |
|---|---|
| Purpose | Groups secondary actions for a record (⋮ overflow) or a dropdown. |
| When to use | 3+ secondary actions on a row/record; destructive actions that should be one step away. |
| When not to use | A single action (show it as a button); navigation menus (use Sidebar). |
| Anatomy | Raised surface · Menu items (icon + label) · divider · danger item last. |
| Variants & Figma properties | Menu item State = Default \| Hover \| Danger \| Disabled; text prop Label. |
| Sizes & density | Item 40 tall; menu width 220–280. |
| States | Default, hover, focus, disabled-with-reason, danger. |
| Content rules | Labels are verbs. Disabled items say why (‘Export (no access)’). Max ~7 items. |
| Behaviour & keyboard | Opens below trigger, flips at edges; ↑↓ moves, Enter selects, Esc closes and returns focus to trigger. Danger items open a Confirmation modal. |
| Responsive | On phone opens as a bottom sheet with the same items. |
| Accessibility | role=menu / menuitem; trigger aria-haspopup, aria-expanded. |
| Development notes | Overlay elevation; never nest menus deeper than one level. |
| Level · status · version | Composite · Approved · 1.0 |

## 14.2–14.3 Fields

### Input

| **Field** | **Specification** |
|---|---|
| Purpose | Single-line text entry with label, helper and error. |
| When to use | Short text values (reference, name, description line). |
| When not to use | Amounts (Amount input), dates (Date field), long notes (Textarea), choices (Select/Radio). |
| Anatomy | Label · field (value/placeholder) · helper or error message. |
| Variants & Figma properties | State = Default \| Focus \| Error \| Disabled \| Read-only; props Label, Value, Show helper. |
| Sizes & density | Height 44, radius 12; width by content expectation (not always full). |
| States | Empty, filled, focus, error, disabled, read-only (sunk surface, not disabled look), incomplete. |
| Content rules | Label = business question in plain words (Part 11). Helper says what good looks like. Error = what is wrong + how to fix. |
| Behaviour & keyboard | Validate on blur, not on every keystroke; keep the value on error; error replaces helper. |
| Responsive | Full width on phone; aligned grid on desktop. |
| Accessibility | &lt;label for>; aria-describedby → helper/error; aria-invalid on error; border/input 3.44:1. |
| Development notes | Read-only is not disabled — it remains selectable/copyable. |
| Replaces | Field, PC/Input, PR/Field |
| Level · status · version | Component · Approved · 1.0 |

### Amount input

| **Field** | **Specification** |
|---|---|
| Purpose | Money entry that prevents over- and under-payment at the source. |
| When to use | Any money value: payment amount, cash count, expense. |
| When not to use | Read-only amounts (show as text); non-money numbers. |
| Anatomy | Label · currency prefix · right-aligned value · helper showing the limit that matters. |
| Variants & Figma properties | State = Default \| Focus \| Error \| Read-only; props Label, Currency. |
| Sizes & density | Height 44, radius 12. |
| States | Empty, filled, error (over limit), read-only (calculated). |
| Content rules | Two decimals, thousands separators on blur; currency from entity; helper shows the limit (‘Unpaid: HK$4,800.00’). |
| Behaviour & keyboard | inputmode=decimal; block non-numeric; paste normalises ‘4,800’ → 4800.00; error shows allowed value. |
| Responsive | Numeric keypad on phone. |
| Accessibility | Announce currency in the label (‘Payment amount in HK$’). |
| Development notes | Never round silently; store minor units. |
| Level · status · version | Component · Approved · 1.0 |

### Search input

| **Field** | **Specification** |
|---|---|
| Purpose | Filters the current list by text. |
| When to use | Lists and tables with > ~10 items. |
| When not to use | Global search across modules (not in scope). |
| Anatomy | Search icon · text · clear (×) when filled. |
| Variants & Figma properties | State = Default \| Focus \| Filled. |
| Sizes & density | Height 44, width 280–360. |
| States | Empty, typing, filled, no results (handled by Empty state No results). |
| Content rules | Placeholder names what can be searched (‘Search supplier, description or amount’). |
| Behaviour & keyboard | Debounced (≈300 ms); Esc clears; result count announced. |
| Responsive | Full width on phone above the list. |
| Accessibility | role=searchbox; clear button labelled ‘Clear search’. |
| Development notes | Search scope = current filters; keep query in URL so refresh keeps it. |
| Level · status · version | Component · Approved · 1.0 |

### Textarea

| **Field** | **Specification** |
|---|---|
| Purpose | Multi-line explanation or note. |
| When to use | Cash-difference notes, return reasons, comments. |
| When not to use | Single-line values. |
| Anatomy | Label · field (min 96) · helper/error · counter (only when a limit exists). |
| Variants & Figma properties | State = Default \| Focus \| Error. |
| Sizes & density | Min height 96, grows to ~240 then scrolls. |
| States | Empty, filled, error (required note missing). |
| Content rules | Error explains why the note matters (‘so the reviewer knows what happened’). |
| Behaviour & keyboard | Counter updates live; never cuts text silently. |
| Responsive | Full width. |
| Accessibility | aria-describedby helper + counter. |
| Development notes | Preserve line breaks in display. |
| Level · status · version | Component · Approved · 1.0 |

## 14.4 Selection

### Select

| **Field** | **Specification** |
|---|---|
| Purpose | Choose one value from a list of 6+ options. |
| When to use | Accounts, categories, rows-per-page. |
| When not to use | 2–5 visible options (Radio/Segmented); searchable large lists (Supplier picker). |
| Anatomy | Label · field with value · chevron · option list. |
| Variants & Figma properties | State = Default \| Open \| Error \| Disabled. |
| Sizes & density | Height 44, radius 12. |
| States | Default, open, error, disabled. |
| Content rules | Business label first; keep the accounting value visible (‘429 — General Expenses’). |
| Behaviour & keyboard | Native select on phone; keyboard type-ahead on desktop. |
| Responsive | Native picker on phone. |
| Accessibility | Native &lt;select> or ARIA listbox pattern. |
| Development notes | Same geometry as Input. |
| Replaces | Select, PR/Select |
| Level · status · version | Component · Approved · 1.0 |

### Supplier picker

| **Field** | **Specification** |
|---|---|
| Purpose | Searchable select that prevents duplicate suppliers. |
| When to use | Choosing a supplier/contact from Xero-synced data. |
| When not to use | Short static lists. |
| Anatomy | Search field · option list (name + identifying fact) · ‘Add “…” as a new supplier’ last. |
| Variants & Figma properties | Single composite (open state shown). |
| Sizes & density | Field 44; options 52. |
| States | Typing, results, no match (only the add option), loading. |
| Content rules | Each option shows a fact that disambiguates (last bill date, Xero contact). |
| Behaviour & keyboard | ↑↓ Enter; creation never automatic. |
| Responsive | Full-screen list on phone. |
| Accessibility | ARIA combobox + listbox; result count announced. |
| Development notes | Matches on name and alias; trims spaces/case to prevent duplicates. |
| Level · status · version | Composite · Approved · 1.0 |

### Checkbox

| **Field** | **Specification** |
|---|---|
| Purpose | Select one or more independent options; select rows. |
| When to use | Bulk selection, multi-choice settings that need Save. |
| When not to use | Immediate settings (Switch); one-of-many (Radio). |
| Anatomy | 20px box · label; whole 44px row clickable. |
| Variants & Figma properties | Value = Off \| On \| Mixed × State = Default \| Disabled; prop Label. |
| Sizes & density | Hit row 44. |
| States | Off, on, mixed (select-all partial), disabled. |
| Content rules | Label states the outcome (‘Include in bulk payment’). |
| Behaviour & keyboard | Space toggles. |
| Responsive | Same. |
| Accessibility | Native checkbox; mixed → aria-checked=mixed. |
| Development notes | Checked fill = border/selected (#1D8A90, ≥3:1). |
| Level · status · version | Primitive · Approved · 1.0 |

### Radio

| **Field** | **Specification** |
|---|---|
| Purpose | Choose exactly one from 2–5 visible options. |
| When to use | Payment method choice in a form, small option sets. |
| When not to use | More than 5 options (Select). |
| Anatomy | 20px circle · label. |
| Variants & Figma properties | Value = Off \| On × State = Default \| Disabled; prop Label. |
| Sizes & density | Hit row 44. |
| States | Off, on, disabled. |
| Content rules | Options are parallel phrases. |
| Behaviour & keyboard | Arrow keys move within the group. |
| Responsive | Stack vertically on phone. |
| Accessibility | role=radiogroup with a group label. |
| Development notes | — |
| Level · status · version | Primitive · Approved · 1.0 |

### Switch

| **Field** | **Specification** |
|---|---|
| Purpose | Turns a setting on/off immediately. |
| When to use | Easy view, notification preferences. |
| When not to use | Anything that needs Save or confirmation. |
| Anatomy | Track · knob · label. |
| Variants & Figma properties | Value = Off \| On × State = Default \| Disabled; prop Label. |
| Sizes & density | Track 40×24, row 44. |
| States | Off, on, disabled, saving. |
| Content rules | Label names the setting, not the action. |
| Behaviour & keyboard | Applies instantly; shows Saving status if remote. |
| Responsive | Same. |
| Accessibility | role=switch, aria-checked. |
| Development notes | Persist per user. |
| Level · status · version | Primitive · Approved · 1.0 |

### Segmented control

| **Field** | **Specification** |
|---|---|
| Purpose | Choose one of 2–4 modes that change the form below. |
| When to use | 2–4 exclusive modes that change the form below (e.g. payment method). The option list itself is a business rule, not a design decision. |
| When not to use | List filtering (Filter chip); > 4 options (Select). |
| Anatomy | Sunk track · Segments. |
| Variants & Figma properties | Segment State = Selected \| Default; prop Label. |
| Sizes & density | Height 36 + 3px track padding. |
| States | Selected, default, focus. |
| Content rules | 1–2 words per segment. |
| Behaviour & keyboard | Arrow keys move selection; changes the dependent fields without losing typed values. |
| Responsive | Full width on phone; may scroll if labels are long. |
| Accessibility | role=radiogroup. |
| Development notes | Replaces PR/Pay mode. |
| Replaces | PR/Pay mode |
| Level · status · version | Composite · Approved · 1.0 |

### Filter chip

| **Field** | **Specification** |
|---|---|
| Purpose | Shows a subset of a list. |
| When to use | Status filters above lists; Settings tabs. |
| When not to use | Business status display (Status pill). |
| Anatomy | Label · optional count. |
| Variants & Figma properties | State = Default \| Hover \| Selected; props Label, Count, Show count. |
| Sizes & density | Height 32, full radius. |
| States | Default, hover, selected, focus. |
| Content rules | Status names exactly as in pills; counts are live. |
| Behaviour & keyboard | Single-select by default; multi-select allowed where documented. |
| Responsive | Horizontal scroll on phone. |
| Accessibility | aria-pressed when it filters a list; role=tablist / tab with ←/→ arrow keys when it switches page areas (e.g. Settings). |
| Development notes | Replaces PR/Filter pill and SET/Tab pill. |
| Replaces | PR/Filter pill, SET/Tab pill |
| Level · status · version | Primitive · Approved · 1.0 |

### Date field · Calendar

| **Field** | **Specification** |
|---|---|
| Purpose | Enter or pick a date. |
| When to use | Invoice/due dates, report dates. |
| When not to use | Date ranges (future component). |
| Anatomy | Label · field (value + calendar icon) · Calendar popover. |
| Variants & Figma properties | Date field State = Default \| Open \| Error. |
| Sizes & density | Field 44; calendar 300 wide. |
| States | Empty, filled, open, error (future date where not allowed), disabled days. |
| Content rules | Format D MMM YYYY (5 Oct 2026). Today outlined; selected tint + bold. |
| Behaviour & keyboard | Typing allowed; arrows move days, PgUp/PgDn months, Enter selects, Esc closes. |
| Responsive | Native date picker on phone. |
| Accessibility | Grid semantics; announce ‘selected’ and ‘today’. |
| Development notes | Validate against business rules (no future invoice dates). |
| Level · status · version | Composite · Approved · 1.0 |

## 14.5 Files & documents

### File card

| **Field** | **Specification** |
|---|---|
| Purpose | One supporting document attached to a record. |
| When to use | Invoices, bank slips, receipts on any record. |
| When not to use | Images inside content (use viewer). |
| Anatomy | Thumbnail · name (truncated) · meta · actions. |
| Variants & Figma properties | State = Uploading \| Uploaded \| Failed. |
| Sizes & density | Width ≥ 360; height by content. |
| States | Uploading (progress in Minty Primary), uploaded, failed (keep other input), removed. |
| Content rules | Accepted: PDF, JPG/JPEG, PNG, HEIC (converted to JPG). Max 10 MB per file, up to 10 files per record. Name truncates at the end; meta = size · date. |
| Behaviour & keyboard | Background upload; Try again on failure; Remove asks confirmation only after submission. |
| Responsive | Stacked full width on phone. |
| Accessibility | Progress announced via aria-live. |
| Development notes | Compress photos on the device before upload (typical phone photo 2–5 MB → < 1 MB). Show the limits before upload, and say which file failed and why. |
| Level · status · version | Component · Approved · 1.0 |

### Camera capture

| **Field** | **Specification** |
|---|---|
| Purpose | Add a receipt from the phone camera. |
| When to use | Petty Cash expenses at the till. |
| When not to use | Desktop-only flows (use File card upload). |
| Anatomy | Empty: icon, title, hint, Take photo / Choose file. Captured: preview, readability check, Retake/Remove. |
| Variants & Figma properties | State = Empty \| Captured. |
| Sizes & density | Full width on phone. |
| States | Empty, captured, readable/unreadable, uploading (via File card). |
| Content rules | Hint: keep total and date in view. |
| Behaviour & keyboard | Opens camera; compresses to < 1 MB before upload; HEIC converted to JPG; never blocks the form. |
| Responsive | Phone-first; on desktop shows Choose file. |
| Accessibility | Buttons labelled; preview has alt text ‘Receipt photo’. |
| Development notes | Run readability check client-side when possible. |
| Level · status · version | Composite · Approved · 1.0 |

### Document viewer

| **Field** | **Specification** |
|---|---|
| Purpose | Shows a document beside the form so values can be checked. |
| When to use | Payment Request review, AI-extracted values. |
| When not to use | Thumbnails in lists (File card). |
| Anatomy | Toolbar (name, page, zoom, download) · document canvas · field highlight. |
| Variants & Figma properties | Single component. |
| Sizes & density | ≥ 480 wide on desktop. |
| States | Loading, loaded, highlight active, failed to load. |
| Content rules | — |
| Behaviour & keyboard | Focusing a field highlights its source in Minty Primary. |
| Responsive | Full-screen on phone. |
| Accessibility | Download and zoom buttons labelled. |
| Development notes | Render PDFs client-side; no data leaves the app. |
| Level · status · version | Composite · Approved · 1.0 |

## 14.6 Navigation

### App bar

| **Field** | **Specification** |
|---|---|
| Purpose | Identifies the module and entity on every screen. |
| When to use | All signed-in screens. |
| When not to use | Record state (Draft, date) — goes in the Page header. |
| Anatomy | Back (optional) · module name · entity name · avatar · menu. |
| Variants & Figma properties | Device = Desktop \| Mobile; props Show back, Module name, Entity name. |
| Sizes & density | 60 desktop / 56 phone. |
| States | Default; back shown in drill-down. |
| Content rules | Entity name spelled out; never acronym alone. |
| Behaviour & keyboard | Menu opens the Sidebar sheet on phone/tablet. |
| Responsive | Collapses entity name to avatar only below 360px. |
| Accessibility | &lt;header>; landmark; back has accessible name. |
| Development notes | Replaces Top bar, PC/Header, PR/Header, SET/Header. |
| Replaces | Top bar, PC/Header(+plain), PR/Header, SET/Header |
| Level · status · version | Composite · Approved · 1.0 |

### Sidebar · Nav item

| **Field** | **Specification** |
|---|---|
| Purpose | Moves between modules and settings within an entity. |
| When to use | Desktop ≥1280 always visible (right side); sheet on smaller screens. |
| When not to use | In-page sections (Section header). |
| Anatomy | Entity block · section labels · Nav items · Log out. |
| Variants & Figma properties | Nav item State = Default \| Hover \| Active \| Locked; prop Label. |
| Sizes & density | Width 280; items 44. |
| States | Active, locked (plan), hover, focus. |
| Content rules | Module names consistent everywhere (‘Payment Request’). |
| Behaviour & keyboard | Locked item opens plan explanation. |
| Responsive | Fixed on the right on desktop; on tablet/phone it opens as a sheet from the app-bar menu on the right — within easy thumb reach for right-handed users. |
| Accessibility | &lt;nav> with aria-current=page. |
| Development notes | Fixed right per ‘One layout’ decision. |
| Replaces | Side menu, Side item |
| Level · status · version | Composite · Approved · 1.0 |

### Entity selector

| **Field** | **Specification** |
|---|---|
| Purpose | Switch entity with role context. |
| When to use | Users with access to more than one entity. |
| When not to use | Single-entity users (hide). |
| Anatomy | Header · entity rows (avatar, name, role · modules) · current check. |
| Variants & Figma properties | Single composite. |
| Sizes & density | Width 300. |
| States | Current, hover, focus. |
| Content rules | Show the user’s role per entity. |
| Behaviour & keyboard | Switching keeps the module if available there. |
| Responsive | Bottom sheet on phone. |
| Accessibility | listbox with aria-selected. |
| Development notes | — |
| Level · status · version | Composite · Approved · 1.0 |

### Step · Step progress

| **Field** | **Specification** |
|---|---|
| Purpose | Shows where the user is in a multi-step workflow. |
| When to use | Daily Closing, onboarding, multi-step forms. |
| When not to use | Single-page forms. |
| Anatomy | Steps (indicator + label). |
| Variants & Figma properties | Step State = Done \| Current \| Upcoming; props Label, Mark. |
| Sizes & density | Indicator 28 tall; fills width. |
| States | Done (tint + check), current (Minty Primary + bold), upcoming (sunk + border). |
| Content rules | Short step names (Drawer, Sales, Expenses, Cash Count, Close). |
| Behaviour & keyboard | Done and current steps are clickable (free navigation, Part 9). |
| Responsive | Labels may wrap to two lines on phone; never below 12px (Part 13 §13.5 minimum). |
| Accessibility | ol with aria-current=step. The current step is always marked by a bold label and aria-current as well as colour (Minty Primary is 1.79:1 on white, so colour alone is never enough). |
| Development notes | Replaces Step tile, Step nav, PC/Step pill. |
| Replaces | Step tile, Step nav, PC/Step pill |
| Level · status · version | Composite · Approved · 1.0 |

### Pagination

| **Field** | **Specification** |
|---|---|
| Purpose | Moves through long lists. |
| When to use | Desktop lists/tables > 1 page. |
| When not to use | Phone (use Load more). |
| Anatomy | Range text · pages · rows-per-page. |
| Variants & Figma properties | Size = Pointer \| Touch. |
| Sizes & density | Pointer: targets 36 (desktop with mouse). Touch: targets 44 (tablet and any touch device, Part 13 §13.16). |
| States | Current page, disabled prev/next at ends. |
| Content rules | Rows per page 10/25/50/100 everywhere. |
| Behaviour & keyboard | Keeps filters; scrolls to list top. |
| Responsive | Phone: prev/next or Load more. |
| Accessibility | nav with aria-label=Pagination; aria-current=page; Touch size on touch devices. |
| Development notes | Replaces PR/Pagination. |
| Replaces | PR/Pagination |
| Level · status · version | Component · Approved · 1.0 |

## 14.7 Page & section structure

### Page header

| **Field** | **Specification** |
|---|---|
| Purpose | Names the page or record and holds its main actions. |
| When to use | Top of every page; record detail pages. |
| When not to use | Inside cards. |
| Anatomy | Page: title, purpose line, actions. Record: back link, name + Status pill, who/when, actions. |
| Variants & Figma properties | Type = Page \| Record. |
| Sizes & density | Full content width. |
| States | — |
| Content rules | One Primary; record state lives here. |
| Behaviour & keyboard | Actions collapse into a Menu on phone except Primary. |
| Responsive | Stacked on phone; Primary moves to bottom bar if needed. |
| Accessibility | h1 for title. |
| Development notes | — |
| Level · status · version | Composite · Approved · 1.0 |

### Section header

| **Field** | **Specification** |
|---|---|
| Purpose | Groups content within a page. |
| When to use | Forms and record pages with several sections. |
| When not to use | Page titles. |
| Anatomy | Title · optional description · optional Link action. |
| Variants & Figma properties | Type = Plain \| With action. |
| Sizes & density | 24 above, 12 below. |
| States | — |
| Content rules | Description says why the section exists. |
| Behaviour & keyboard | — |
| Responsive | Same. |
| Accessibility | h2/h3 by depth. |
| Development notes | — |
| Level · status · version | Component · Approved · 1.0 |

### Description row

| **Field** | **Specification** |
|---|---|
| Purpose | Shows a label/value fact on a record. |
| When to use | Record details, summaries, drawers. |
| When not to use | Editable values (use fields). |
| Anatomy | Term · value. |
| Variants & Figma properties | Layout = Horizontal \| Stacked; props Term, Value. |
| Sizes & density | Term column 160 (horizontal). |
| States | Filled, empty (‘Not set yet’). |
| Content rules | Values are exact (dates, names, amounts). |
| Behaviour & keyboard | — |
| Responsive | Stacked on phone. |
| Accessibility | dl/dt/dd. |
| Development notes | — |
| Level · status · version | Component · Approved · 1.0 |

## 14.8 Cards

### Record row

| **Field** | **Specification** |
|---|---|
| Purpose | Summarises one record with one action. |
| When to use | Default list presentation (Easy view) for every list; Table view is an opt-in toggle. |
| When not to use | High-volume accounting review (Table row). |
| Anatomy | Identity (title, meta) · amount · Status pill · one action. |
| Variants & Figma properties | Device = Desktop \| Mobile. |
| Sizes & density | Desktop tracks: amount 160, status+action 360. |
| States | Default, hover, selected; data: Draft, Payment Requested, Partially Paid, Paid, Returned, Voided. |
| Content rules | Amount always text/primary; status via pill. |
| Behaviour & keyboard | Whole row opens the record; action does its own thing. |
| Responsive | Mobile = stacked card. |
| Accessibility | Row is a link/button with the record name; action has its own label. |
| Development notes | Replaces Card, PC/Card and Bill list rows. |
| Replaces | Card, PC/Card |
| Level · status · version | Composite · Approved · 1.0 |

### KPI card

| **Field** | **Specification** |
|---|---|
| Purpose | One fact at a glance. |
| When to use | Dashboards and summaries. |
| When not to use | Interpreted trends (Analytics Stage 2). |
| Anatomy | Label · value (amount/kpi) · meta · optional Status pill. |
| Variants & Figma properties | Type = Default \| With status; prop Label. |
| Sizes & density | Width 220–300. |
| States | Loading (skeleton), filled. |
| Content rules | Facts only; meaning via pill, never by colouring the number. |
| Behaviour & keyboard | Card may link to the filtered list. |
| Responsive | 2-up on phone. |
| Accessibility | Value announced with label. |
| Development notes | — |
| Level · status · version | Component · Approved · 1.0 |

### Module chip

| **Field** | **Specification** |
|---|---|
| Purpose | Shows module identity. |
| When to use | Navigation, plan cards, module headers. |
| When not to use | Status, amounts, alerts. |
| Anatomy | Icon circle (module wash + colour) · label. |
| Variants & Figma properties | Module = Petty Cash \| Payment Request. |
| Sizes & density | Circle 32. |
| States | — |
| Content rules | Module names exact. |
| Behaviour & keyboard | — |
| Responsive | — |
| Accessibility | Decorative circle hidden; label read. |
| Development notes | Only place module colour appears (with art and nav). |
| Level · status · version | Primitive · Approved · 1.0 |

## 14.9 Lists & tables

### Table row

| **Field** | **Specification** |
|---|---|
| Purpose | Dense, comparable rows for accounting review. |
| When to use | Table view — available to every role; users choose Easy view or Table view themselves. |
| When not to use | Phone (use Record row). |
| Anatomy | Checkbox · columns (supplier, date, amount right-aligned, status, action). |
| Variants & Figma properties | Type = Header \| Default \| Hover \| Selected \| Nested payment. |
| Sizes & density | Header 40, rows 56 (compact 44 on desktop Table view). |
| States | Selected, hover, nested/expanded, sorted header. |
| Content rules | Currency in header, not cells; tabular numerals. |
| Behaviour & keyboard | Click row opens record; checkbox selects; sort from header. |
| Responsive | Becomes Record rows on phone/tablet portrait. |
| Accessibility | table semantics; sortable headers aria-sort. |
| Development notes | Nested payment replaces grey sub-rows. |
| Level · status · version | Composite · Approved · 1.0 |

### Bulk action bar

| **Field** | **Specification** |
|---|---|
| Purpose | Acts on several selected rows. |
| When to use | When ≥1 row is selected. |
| When not to use | Single-row actions. |
| Anatomy | Count + money total · Clear · Secondary · Primary. |
| Variants & Figma properties | Single component. |
| Sizes & density | Replaces filters row. |
| States | Visible when selection > 0. |
| Content rules | Primary names action and count (‘Record payment for 2’). |
| Behaviour & keyboard | Clear deselects; Esc clears. |
| Responsive | Sticky bottom bar on phone. |
| Accessibility | Announce selection count (aria-live). |
| Development notes | Total must use the same rounding as records. |
| Level · status · version | Composite · Approved · 1.0 |

### Skeleton row

| **Field** | **Specification** |
|---|---|
| Purpose | Loading placeholder for lists. |
| When to use | Lists loading > 300 ms. |
| When not to use | Button actions (use button processing). |
| Anatomy | Bars shaped like Record row. |
| Variants & Figma properties | Single component. |
| Sizes & density | Matches Record row. |
| States | Loading only. |
| Content rules | — |
| Behaviour & keyboard | Replace with content in place, no jump. |
| Responsive | Same. |
| Accessibility | aria-busy on the list. |
| Development notes | No shimmer when reduced motion. |
| Level · status · version | Primitive · Approved · 1.0 |

## 14.10 Status & metadata

### Status pill

| **Field** | **Specification** |
|---|---|
| Purpose | Shows a record’s business status. |
| When to use | Lists, headers, timelines. |
| When not to use | Selection, processing, validation, roles. |
| Anatomy | Soft background · deep ink label. |
| Variants & Figma properties | Tone = Success \| Warning \| Danger \| Info \| Neutral. |
| Sizes & density | Height ~24, padding 4/12. |
| States | — |
| Content rules | Exact status words: Paid, Partially Paid, Returned, Voided, Payment Requested, Submitted, Draft. Tones: Paid → Success; Partially Paid, Returned → Warning; Payment Requested, Submitted → Info; Draft, Voided → Neutral; Danger only for failures (Payment failed, Upload failed). |
| Behaviour & keyboard | Not interactive. |
| Responsive | Same. |
| Accessibility | Text carries meaning; no colour-only. |
| Development notes | Payment Requested = Info (blue) — Treasury to-do. |
| Replaces | PC/Status badge, PR/Status pill |
| Level · status · version | Primitive · Approved · 1.0 |

### Saving status

| **Field** | **Specification** |
|---|---|
| Purpose | Tells the user their work is safe. |
| When to use | Workflows with autosave. |
| When not to use | Final submission confirmation (Toast/Outcome). |
| Anatomy | Icon · text. |
| Variants & Figma properties | State = Saving \| Saved \| Offline. |
| Sizes & density | — |
| States | Saving, saved (time), offline (warning). |
| Content rules | ‘Saved 2 min ago’; offline reassures nothing is lost. |
| Behaviour & keyboard | Updates silently. |
| Responsive | Same. |
| Accessibility | aria-live=polite. |
| Development notes | — |
| Level · status · version | Component · Approved · 1.0 |

### Audit meta

| **Field** | **Specification** |
|---|---|
| Purpose | Who changed what, when. |
| When to use | Under records and key fields. |
| When not to use | Marketing-style ‘recently’ text. |
| Anatomy | Icon · text. |
| Variants & Figma properties | Single component; prop Text. |
| Sizes & density | — |
| States | — |
| Content rules | Real name/system + exact time. |
| Behaviour & keyboard | — |
| Responsive | Same. |
| Accessibility | Plain text. |
| Development notes | — |
| Level · status · version | Primitive · Approved · 1.0 |

### Timeline item

| **Field** | **Specification** |
|---|---|
| Purpose | One status change in a record’s history. |
| When to use | Record detail history. |
| When not to use | Notifications feed. |
| Anatomy | Rail (dot, line) · Status pill · who/when · note. |
| Variants & Figma properties | Position = Middle \| Last. |
| Sizes & density | Width ≥ 360. |
| States | — |
| Content rules | Exact times; notes quoted. |
| Behaviour & keyboard | — |
| Responsive | Same. |
| Accessibility | ol of events. |
| Development notes | History is never deleted (void keeps history). |
| Level · status · version | Component · Approved · 1.0 |

## 14.11 Feedback

### Inline alert

| **Field** | **Specification** |
|---|---|
| Purpose | Issue inside the section where it is fixed. |
| When to use | Cash difference, sync issue on a record, upload failure. |
| When not to use | Page-wide conditions (Page banner); confirmations (Toast). |
| Anatomy | Icon · title · body · one Link action. |
| Variants & Figma properties | Tone = Info \| Success \| Warning \| Danger. |
| Sizes & density | Width = section. |
| States | — |
| Content rules | Title = what happened; body = what to do and that work is safe. |
| Behaviour & keyboard | Stays until resolved. |
| Responsive | Same. |
| Accessibility | role=status (or alert for Danger). |
| Development notes | Tone follows consequence, not technical severity. |
| Level · status · version | Component · Approved · 1.0 |

### Page banner

| **Field** | **Specification** |
|---|---|
| Purpose | Account- or page-wide condition. |
| When to use | Sync paused, unsubmitted day, billing. |
| When not to use | Section issues (Inline alert). |
| Anatomy | Icon · title · body · action · dismiss. |
| Variants & Figma properties | Tone = Info \| Success \| Warning \| Danger; prop Show dismiss. |
| Sizes & density | Content width. |
| States | Visible, dismissed. |
| Content rules | One banner at a time, highest consequence first. |
| Behaviour & keyboard | Billing Danger not dismissible until resolved. |
| Responsive | Same; text wraps. |
| Accessibility | role=region with label; alert for Danger. |
| Development notes | — |
| Level · status · version | Component · Approved · 1.0 |

### Toast

| **Field** | **Specification** |
|---|---|
| Purpose | Confirms a completed low-risk action. |
| When to use | Saved, recorded, moved — with optional Undo. |
| When not to use | Errors or anything requiring action. |
| Anatomy | Character slot (optional) · message · Undo. |
| Variants & Figma properties | Kind = Simple \| With action; props Message, Show character. |
| Sizes & density | Auto width ≤ 480. |
| States | Visible, dismissing. |
| Content rules | Names what happened (‘Payment recorded for Kwok Transport Ltd.’). |
| Behaviour & keyboard | 4–6 s; 8 s with Undo; pauses on hover/focus. |
| Responsive | Bottom centre on phone, bottom left on desktop. |
| Accessibility | aria-live=polite. |
| Development notes | — |
| Level · status · version | Component · Approved · 1.0 |

## 14.12 Overlays

### Confirmation modal

| **Field** | **Specification** |
|---|---|
| Purpose | Confirms consequential or irreversible actions. |
| When to use | Submit report, void, remove user. |
| When not to use | Ordinary saves; forms (use pages/drawer). |
| Anatomy | Title (question) · what happens · reversibility · Cancel + specific verb. |
| Variants & Figma properties | Kind = Standard \| Destructive. |
| Sizes & density | Width 440. |
| States | Open, processing. |
| Content rules | Verb matches the action; consequence in bold. |
| Behaviour & keyboard | Focus trapped; Esc = Cancel; focus returns to trigger. |
| Responsive | Bottom sheet on phone. |
| Accessibility | role=dialog, aria-modal, labelled by title. |
| Development notes | — |
| Level · status · version | Composite · Approved · 1.0 |

### Drawer

| **Field** | **Specification** |
|---|---|
| Purpose | Quick review or one small action without leaving the list. |
| When to use | Record preview, quick edit. |
| When not to use | Long workflows (open the full page). |
| Anatomy | Header (record, status, close) · body · footer actions. |
| Variants & Figma properties | Single component. |
| Sizes & density | Width 480; full screen on phone. |
| States | Open, loading. |
| Content rules | — |
| Behaviour & keyboard | Esc closes; focus returns to the row. |
| Responsive | Full screen on phone. |
| Accessibility | role=dialog. |
| Development notes | Over overlay/scrim. |
| Level · status · version | Composite · Approved · 1.0 |

### Tooltip

| **Field** | **Specification** |
|---|---|
| Purpose | Short hint on hover/focus. |
| When to use | Explaining a column or icon. |
| When not to use | Essential information; touch-only UIs. |
| Anatomy | Inverse surface · text. |
| Variants & Figma properties | Single component; prop Text. |
| Sizes & density | ≤ 1 line. |
| States | Visible on hover/focus. |
| Content rules | ≤ ~60 characters. |
| Behaviour & keyboard | Delay 300 ms; Esc hides. |
| Responsive | Not used on touch. |
| Accessibility | aria-describedby. |
| Development notes | — |
| Level · status · version | Primitive · Approved · 1.0 |

## 14.14 Users & access

### Avatar

| **Field** | **Specification** |
|---|---|
| Purpose | Represents a person or entity. |
| When to use | App bar, sidebar, user rows. |
| When not to use | Decoration. |
| Anatomy | Initials circle. |
| Variants & Figma properties | Size = 28 \| 40; prop Initials. |
| Sizes & density | 28 / 40. |
| States | — |
| Content rules | Always next to the full name. |
| Behaviour & keyboard | — |
| Responsive | — |
| Accessibility | Decorative when name is adjacent. |
| Development notes | — |
| Replaces | PC/Avatar |
| Level · status · version | Primitive · Approved · 1.0 |

### Role badge

| **Field** | **Specification** |
|---|---|
| Purpose | Shows what a person may do. |
| When to use | User rows, invitations. |
| When not to use | Status. |
| Anatomy | Icon · role label. |
| Variants & Figma properties | Role = Cashier \| Shop Manager \| Accountant \| Admin. |
| Sizes & density | Height ~22. |
| States | — |
| Content rules | Role names exact. |
| Behaviour & keyboard | — |
| Responsive | — |
| Accessibility | Plain text. |
| Development notes | Neutral; roles are not tied to characters. |
| Level · status · version | Primitive · Approved · 1.0 |

### User row

| **Field** | **Specification** |
|---|---|
| Purpose | One person’s access in an entity. |
| When to use | Users settings. |
| When not to use | — |
| Anatomy | Avatar · name + email + entity · Role badge · access status · menu. |
| Variants & Figma properties | Single component. |
| Sizes & density | Width = content. |
| States | Invited, active, expired, removed. |
| Content rules | — |
| Behaviour & keyboard | Menu: resend, change role, remove (confirm). |
| Responsive | Stacked on phone. |
| Accessibility | Row semantics; menu labelled. |
| Development notes | Role change takes effect server-side immediately. |
| Level · status · version | Composite · Approved · 1.0 |

## 14.15 Empty & completion

### Empty state

| **Field** | **Specification** |
|---|---|
| Purpose | Explains an empty area and the next step. |
| When to use | First use, no results. |
| When not to use | Errors. |
| Anatomy | Character (Minty, first use) · title · explanation · one action. |
| Variants & Figma properties | Kind = First use \| No results. |
| Sizes & density | Width ≤ 400. |
| States | — |
| Content rules | Never ‘No data’. |
| Behaviour & keyboard | — |
| Responsive | Same. |
| Accessibility | Character decorative. |
| Development notes | No character for No results. |
| Level · status · version | Composite · Approved · 1.0 |

### Outcome state

| **Field** | **Specification** |
|---|---|
| Purpose | Shows the result of a finished or blocked journey. |
| When to use | Report submitted, no access, module not in plan. |
| When not to use | Toasts for small actions. |
| Anatomy | Character (Minty; second character only for two-party outcomes such as a completed transfer) / module chip · title · body · optional summary · actions. |
| Variants & Figma properties | Kind = Completion \| No access \| Not in plan. |
| Sizes & density | Width 440. |
| States | — |
| Content rules | Completion summarises facts; no-access names who can help. |
| Behaviour & keyboard | — |
| Responsive | Same. |
| Accessibility | Heading + text; character decorative. |
| Development notes | — |
| Level · status · version | Composite · Approved · 1.0 |

### Character

| **Field** | **Specification** |
|---|---|
| Purpose | Places the official cast; Minty is the default everywhere. |
| When to use | Empty, completion, onboarding, toasts (S). Second characters only in two-party moments (e.g. transfer: Minty sends, Ms Lemon receives). |
| When not to use | Tables, rows, fields, money errors. |
| Anatomy | Art frame. |
| Variants & Figma properties | Character = Minty \| Penny \| Ollie \| Ms Lemon × Size = S 56 \| M 120 \| L 240. |
| Sizes & density | 56 / 120 / 240. |
| States | — |
| Content rules | Minty by default; never swap by module or role. |
| Behaviour & keyboard | — |
| Responsive | Smaller size on phone. |
| Accessibility | Decorative (alt empty). |
| Development notes | Final transparent 2× assets assumed available. |
| Level · status · version | Primitive · Approved · 1.0 |

## 14.16 AI-related

### AI field

| **Field** | **Specification** |
|---|---|
| Purpose | Shows where a filled value came from and who decides. |
| When to use | Values extracted or suggested by Minty. |
| When not to use | Values typed by the user. |
| Anatomy | Field · source line (icon + text) · optional accept action. |
| Variants & Figma properties | State = Extracted \| Suggested \| Needs check \| Confirmed. |
| Sizes & density | Height 44. |
| States | AI-suggested, AI-uncertain, user-confirmed, extracted. |
| Content rules | Plain source text (‘Read from the invoice’). No ‘AI’ jargon. |
| Behaviour & keyboard | Suggestions are never applied without acceptance; Needs check blocks submit only when the rule requires. |
| Responsive | Same. |
| Accessibility | Source line in aria-describedby. |
| Development notes | Log acceptance for audit. |
| Level · status · version | Component · Approved · 1.0 |

## 14.H Accessibility checklist

- Every interactive element reachable by keyboard in visual order; visible 2px focus ring.
- Accessible names: buttons = label; icon-only only for back/close/menu/search/more with aria-label.
- Form fields: label linked; helper and error via aria-describedby; aria-invalid on error.
- Status never by colour alone — Status pill text, icons in alerts, bold + tint for selection.
- Contrast: text ≥4.5:1, UI boundaries ≥3:1 in both themes (Primary CTA label = documented exception).
- Targets ≥44px on touch; whole checkbox/radio row clickable.
- Overlays: focus trapped, Esc closes, focus returns to trigger.
- Live regions for toasts, saving status, upload progress, selection count.
- Reduced motion: no shimmer, no confetti, instant fades.
- Characters and decorative art hidden from assistive technology.

## 14.I Screen-to-component traceability

| **Screen family** | **Key components** |
|---|---|
| Petty Cash home (phone) | App bar · Step progress · Button · Nav/quick actions · KPI card · Page banner |
| Daily Closing steps | Step progress · Amount input · Camera capture · File card · Textarea · Inline alert · Saving status · Confirmation modal · Outcome state |
| Payment Request list | App bar · Page header · Filter chip · Search input · Record row / Table row · Bulk action bar · Pagination · Empty state |
| Payment Request detail / record payment | Page header (Record) · Description row · Document viewer · AI field · Amount input · Segmented control · File card · Timeline item · Drawer |
| Add Payment Request | Supplier picker · Date field · Amount input · AI field · File card · Button |
| Settings & users | Sidebar · Section header · User row · Role badge · Switch · Menu · Confirmation modal |
| Onboarding & subscription | Step progress · Input · Select · Module chip · Character · Outcome state · Page banner |
| Entity switching | Sidebar · Entity selector |

## 14.J Deprecated component list

Marked superseded on 5–6 Oct 2026 (banners on UI pages 02, 03, 04); kept until screen migration in Part 15, then retired: Button/Primary, Button/Primary Disabled, Button/Ghost, Button/Block, Button/Link, Field, Select (onboarding), Card, Top bar, Side menu, Side item, Step tile, Step nav, Icon/* (8), PC/Avatar, PC/Status badge, PC/Header, PC/Header plain, PC/Step pill, PC/Button, PC/Button outline, PC/Link, PC/Card, PC/Input, PC/Total row, PR/Header, PR/Button, PR/Button outline, PR/Button ghost, PR/Filter pill, PR/Status pill, PR/Field, PR/Select, PR/Pay mode, PR/Pagination, SET/Header, SET/Tab pill, and the legacy library Banner, Date field, Search field, Icon button, Header, Table row, Status pill.

## 14.K Visual examples

- Library → “Minty v2 · Components — 5 Oct 2026”: every component set with all variants; Light/Dark preview frame with real instances.
- UI file → “02 · Components”: v2 board with library instances and replacement notes.
- UI file → “13 · Visual direction”: Payment Request list and Petty Cash home rebuilt from v2 components (Light and Dark), current vs v2.

## Appendix A — Decision log

| **ID** | **Decision** | **Reason** |
|---|---|---|
| D14-01 | One Button with Kind × State replaces 9 implementations; Link is a Button kind | Convergence; consistent focus/disabled behaviour |
| D14-02 | Checked selection controls use border/selected (#1D8A90), not Minty Action | Non-text UI needs 3:1 on white; #3CBCC3 is 2.29:1 |
| D14-03 | Step progress current step uses Minty Primary (#54D3DA) | Owner rule: progress indicators are a brand use |
| D14-04 | Record row has fixed desktop column tracks | Values must align across rows (visual direction finding) |
| D14-05 | Table row Nested payment replaces grey sub-rows | Consistent hierarchy; no off-system grey |
| D14-06 | Filter chip serves both list filters and Settings tabs | Same ‘show this subset’ intent |
| D14-07 | Segmented control replaces PR/Pay mode | 2–4 exclusive modes that change the form |
| D14-08 | Bulk action bar shows count and money total | User sees consequence before acting (Part 1) |
| D14-09 | AI field: four states, no AI colour; suggestions need acceptance | Part 11 AI voice; user decides |
| D14-10 | Supplier picker puts ‘Add new supplier’ last, never automatic | Prevents duplicate suppliers |
| D14-11 | Character component (4 characters × 3 sizes); Minty is the default in Empty state, Toast and Outcome state | Owner rule 7 Oct 2026: Minty first, second characters only in special two-party cases |
| D14-12 | Date format D MMM YYYY | Unambiguous for HK/UK/US users |
| D14-13 | Rows per page 10/25/50/100 everywhere | Resolves conflicting QA documents |
| D14-14 | Icons as a 28-glyph Icon component set (Material Symbols Rounded) | Instance-swappable; one icon language |
| D14-15 | Sidebar fixed on the right | Owner: right-handed thumb reach on mobile; consistent with One layout |
| D14-16 | Easy view is the default list; Table view toggle available to every role | Owner: users choose for themselves |
| D14-17 | Files: PDF/JPG/PNG/HEIC, 10 MB each, up to 10 per record, photos compressed on device | Covers phone photos and multi-page scanned PDFs; owner accepted recommendation |

## Appendix B — Assumption log

| **ID** | **Assumption** |
|---|---|
| A14-01 | Supplier data is synced from Xero contacts, so the picker can show ‘Xero contact’. |
| A14-02 | Future invoice dates are not allowed (Date field disables them). |
| A14-03 | Development can compress photos and convert HEIC on the device/client. |
| A14-04 | Role changes are enforced server-side immediately (per development QA checklist). |
| A14-05 | Option lists inside components (e.g. payment methods) are business rules owned outside the design system; examples only. |
| A14-06 | Final transparent character assets (incl. happy/celebrating poses) are available (owner, 7 Oct 2026). |

## Appendix C — Preference log (resolved 7 Oct 2026)

| **ID** | **Preference** | **Proposed** |
|---|---|---|
| P14-01 | Sidebar position | Right (D14-15) |
| P14-02 | Character on completion screens | Minty; second character only for two-party moments (D14-11) |
| P14-03 | Payment Request list default view | Easy view with Table view toggle for every role (D14-16) |

## Appendix D — Outstanding questions

All Part 14 questions were answered on 7 Oct 2026 (D14-15 to D14-17, A14-05, A14-06). Payment-method lists were confirmed as out of design-system scope.
