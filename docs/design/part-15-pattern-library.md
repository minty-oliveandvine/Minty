<!-- Mirror of "Part 15. Minty Pattern Library.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

# Part 15. Minty Pattern Library

Version 1.1 · Approved · 7 October 2026

Status: approved by the Product Owner (7 Oct 2026, “approve as recommended”). Stage 4 (whole-package review) may proceed. v1.1 (7 Oct 2026) applies Stage 4 corrections only: mapping table uses Part 4 archetype names; Drawer scrim follows the Part 13 token; Settings ‘Subscription’ area clarified as module status (Sidebar Subscription stays top-level); sources moved from legacy Part 12 to current Parts 3, 5 and 8; Bank Deposit row cites D15-05. Targeted review (7 Oct 2026): future-validation items FV15-01 and FV15-02 recorded in Appendix E; Voided shown as Neutral. Built on Part 13 v1.0 (Visual Design System) and Part 14 v1.0 (Component Library). Stage 3 of the Parts 13–15 Development Instructions.

## 15.0 Purpose, scope and authority

Part 15 defines how the approved foundations (Part 13) and components (Part 14) are assembled into repeatable pages, workflows, states and responsive screen compositions. It records the reusable rule behind each successful screen, not the screenshot.

**Scope:** page and workflow compositions for all customer-facing Minty screens (55 of the 57 routed screens; the two staff-only Admin screens are excluded). **Authority:** Parts 1–12 govern meaning, goals and boundaries (Part 4 is the authoritative archetype model; Part 12 is reference only); Part 13 governs visual foundations; Part 14 governs components; Part 15 governs composition. Where documents conflict, the latest update wins and the conflict is logged (Appendix E).

**How to use Part 15:** (1) classify the screen with the Part 2 record (Product Goal → User Perceived Goal → profile → Mental Mode → Work Type → UX Boundary); (2) pick the archetype pattern (15.3–15.8); (3) apply the cross-product layer (15.1 header, 15.2 actions, 15.13 documents); (4) add workflow and state patterns (15.9–15.12); (5) add a module pattern (15.15–15.21) only for what the general patterns cannot express.

**Status labels** follow the Development Instructions §18: Approved = approved in this version (Stage 4 review closed 7 Oct 2026); Draft = supported but not yet validated; Future = must not drive current design.

## 15.A Pattern-inventory method

All 57 routed screens in the Screen map (UI file page 00 · Screen map, taken from code routes) and the Figma frames on pages 00 · Common area, 02 · Onboarding, 03 · Petty Cash, 04 · Payment Request, 05 · Settings and 07 · Subscription were reviewed. Each screen was classified with the Part 2 integrated record and mapped to one archetype pattern plus the cross-product layer. Compositions that recur across modules became cross-product patterns; compositions with a validated module rule became module patterns; single-screen implementations were not elevated (Development Instructions §13.2.8).

| **Front end** | **Screens** | **Pattern families used** |
|---|---|---|
| Auth & account (Flask) | 9 | 15.21a, 15.11, 15.10 |
| Entities (Flask) | 8 | 15.8a, 15.6, 15.9e/f, 15.12, 15.10 |
| Onboarding (Next) | 9 | 15.18, 15.3, 15.8b, 15.20 |
| Report wizard (Flask) | 7 | 15.15, 15.9, 15.3, 15.12 |
| Reports & records (Flask) | 7 | 15.7, 15.4b, 15.3c |
| Settings (Flask) | 5 | 15.20, 15.3b, 15.19 |
| Payments & profile (Next) | 10 | 15.16, 15.17, 15.19, 15.5h, 15.8c |
| Admin (Flask, staff only) | 2 | Out of scope |

## 15.B Pattern layers and catalogue

Patterns are organised in the five layers required by the Development Instructions §13.3, plus a separate Draft layer for AI-assisted patterns so that future concepts are not mistaken for current standards.

| **Layer** | **Patterns** | **Rule** |
|---|---|---|
| A · Cross-product composition | 15.1 Page header · 15.2 Action hierarchy · 15.13 Supporting document | Applies to every screen |
| B · Archetype implementation | 15.3 Form · 15.4 List · 15.5 Detail · 15.6 Dashboard · 15.7 Report · 15.8 Selection | One per screen; implements Part 4 |
| C · Workflow | 15.9 Workflow · 15.12 Completion | Multi-stage work and its end |
| D · State and recovery | 15.10 Feedback & recovery · 15.11 Empty & no-result | Smallest scope that contains the state |
| E · AI-assisted (Draft) | 15.14 AI-assisted | Only supported patterns; Future items labelled |
| F · Module and screen family | 15.15 Daily Closing · 15.16 PR Requester · 15.17 PR Treasury · 15.18 Onboarding · 15.19 Subscription & billing · 15.20 Settings and People & Access · 15.21 Entry and Entity context | Only what a general pattern cannot express; each states its justification |

## 15.C Screen-to-pattern mapping and migration

Every routed screen, its classification, its pattern and its migration decision (Preserve · Refine · Replace · Retire). Figma node IDs refer to the UI file FINAL UI/UX (fileKey WLoKoO5mXK6hB3JOIW6qI4). Counts: Preserve 2 · Refine 49 · Replace 3 · Retire 1 · Out of scope 2.

| **Screen (route)** | **Profile · Mode · Work Type** | **Archetype (Part 4 names) · Device · Boundary** | **Pattern** | **Migration** |
|---|---|---|---|---|
| Login<br>/login<br>Figma: 183:325 | All (account access)<br>Context Selection (entry)<br>— | Record Form<br>Both<br>Converge | 15.21a Account access | Refine — One card, one task; Minty welcome allowed |
| Email code<br>/auth/email/verify-code<br>Figma: — | All<br>Entry<br>— | Record Form<br>Both<br>Converge | 15.21a Account access | Refine — Code field + resend; field-level error |
| Register<br>/register<br>Figma: — | All<br>Entry<br>— | Record Form<br>Both<br>Converge | 15.21a / 15.3a | Refine — Same shell as Login |
| Find account<br>/find_user<br>Figma: — | All<br>Entry<br>— | Record Form<br>Both<br>Converge | 15.21a Account access | Refine |
| Reset password<br>/reset_password<br>Figma: — | All<br>Entry<br>— | Record Form<br>Both<br>Converge | 15.21a Account access | Refine |
| Accept terms<br>/legal/accept<br>Figma: — | All<br>Entry<br>— | Record Form<br>Both<br>Converge | 15.21a + 15.9e gate | Refine — Gate explains why, one action |
| Legal document<br>/legal/&lt;doc><br>Figma: — | All<br>Reading<br>— | Report Page<br>Both<br>Preserve | 15.21a reading variant | Refine — Long text, readable measure 72ch |
| Awaiting approval<br>—<br>Figma: — | All<br>Entry<br>— | Empty State<br>Both<br>Converge | 15.11e Data not yet available | Refine — Minty waiting pose |
| No permission<br>/no-permission<br>Figma: — | All<br>Entry<br>— | Empty State<br>Both<br>Converge | 15.11d No access | Refine — Say who can grant access |
| Entity list<br>/entity<br>Figma: 118:244 | All<br>Context Selection<br>— | Selection Page (Context Selection)<br>Both<br>Preserve | 15.8a Context selection | Refine — Search appears from 6+ entities; FAB → page-level Create button |
| Entity list — empty<br>/entity<br>Figma: — | Owner<br>Context Selection<br>Configuration | Empty State<br>Both<br>Converge | 15.11a First-use | Refine |
| Create entity<br>/create<br>Figma: — | Owner<br>System Configuration<br>Configuration | Record Form<br>Both<br>Converge | 15.3a Simple form | Refine |
| Entity created<br>—<br>Figma: — | Owner<br>System Configuration<br>Configuration | Workflow<br>Both<br>Converge | 15.12f Configuration completed | Refine — Next step = start onboarding |
| Dashboard (Petty Cash)<br>/entity/&lt;id><br>Figma: 66:6 · 66:172 · 66:374 | Data Submitter<br>Work Coordination<br>Scheduled Operational | Dashboard (Action Dashboard)<br>Mobile<br>Separate from Report (2.10.1) | 15.6a + 15.15a Daily Closing launch | Replace — Calendar is example only (dashboard being redefined); Quick Actions retire |
| Continue draft<br>/report/resume<br>Figma: — | Data Submitter<br>Work Coordination<br>Scheduled Operational | Workflow<br>Mobile<br>Converge | 15.9f Save & resume | Refine — Becomes a Page banner + Continue on the launch page |
| Invite blocked<br>—<br>Figma: — | Owner<br>People & Access<br>People & Access | Empty State<br>Both<br>Converge | 15.9e Business-rule gate | Refine — Explain: connect Xero first; one action |
| Error<br>—<br>Figma: — | All<br>—<br>— | Empty State<br>Both<br>Converge | 15.10j Dedicated recovery | Refine — No angry/crying Minty |
| 1 Basic Information<br>step 1<br>Figma: 41:19 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 Onboarding · 15.3b grouped form | Refine — A/B frames = module-path variants, not separate patterns |
| 2 Select Module<br>step 2<br>Figma: 50:364 (+50:447/526/605) | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.8b Feature selection | Refine — A/B frames = module-path variants, not separate patterns |
| 3 User Invite<br>step 3<br>Figma: 42:173 · 42:84 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.20c Invite | Refine — A/B frames = module-path variants, not separate patterns |
| 4 Accounting Setup (Xero)<br>step 4<br>Figma: 42:240 · 42:316 · 192:993 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.20b Integration | Refine — A/B frames = module-path variants, not separate patterns |
| 5 Sales Setting<br>step 5<br>Figma: 45:208 (+53:1946/58:863) | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.3b grouped form | Refine — A/B frames = module-path variants, not separate patterns |
| 6 Account Code<br>step 6<br>Figma: 46:253 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.3f dense form | Refine — A/B frames = module-path variants, not separate patterns |
| 7 Others (Contacts)<br>step 7<br>Figma: 46:451 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.3a | Refine — A/B frames = module-path variants, not separate patterns |
| 8 Payment Settings<br>step 8<br>Figma: 47:346 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.3b | Refine — A/B frames = module-path variants, not separate patterns |
| 9 All Set<br>step 9<br>Figma: 47:497 | Owner / Setup lead<br>Mixed (2.9.10 hybrid)<br>Configuration | Workflow<br>Desktop + Mobile<br>Preserve shell; step content Converge with Settings | 15.18 · 15.12f + 15.9i | Refine — A/B frames = module-path variants, not separate patterns |
| Opening balance → Addition to Drawer<br>/report/…<br>Figma: 67:63 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.15b Daily Closing stage | Refine — Rename stage (Parts 2/12 latest) |
| Sales<br>/report/…<br>Figma: 67:139 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.15b stage · 15.3a | Preserve — Grouped amount inputs + running subtotal: strong existing pattern |
| Expenses<br>/report/…<br>Figma: 69:136 · 69:229 · 69:345 · 69:421 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.15c entry list + 15.3c document-supported form | Refine — Add expense = Drawer (desktop) / full sheet (mobile) |
| Deposit (Bank Deposit)<br>/report/…<br>Figma: 70:297 · 70:453 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.15d cash count & discrepancy | Refine — Stage not in latest 5-stage list → folded into Cash Count (D15-05, owner confirmed 7 Oct 2026) |
| Cash count<br>/report/…<br>Figma: 70:363 · 70:510 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.15d cash count & discrepancy | Preserve — Denomination calculator preserved |
| Ending / summary → Close<br>/report/…<br>Figma: 71:521 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.15e Work Verification + final submit | Replace — Verification ≠ final report (2.10.3) |
| Submitted / publish<br>/report/…<br>Figma: 71:624 · 104:1086 | Data Submitter<br>Work Execution / Verification<br>Scheduled Operational | Workflow<br>Mobile<br>Preserve (workflow) | 15.12e Daily Report finalised | Refine — Completion → link to Report |
| Add expense<br>/report/expense/add<br>Figma: 69:229 | Data Submitter<br>Work Execution<br>Scheduled Operational | Record Form<br>Mobile<br>Converge | 15.3c Document-supported form | Refine |
| Report detail<br>/report/&lt;id><br>Figma: 104:592 · 104:773 | Daily Summary Reviewer<br>Operational Review<br>Scheduled Operational | Report Page<br>Mobile<br>Separate from verification (2.10.3) | 15.7 Report · 15.15f | Refine — 3 KPIs first; Delete/Edit move to overflow; Close button retire |
| Edit report<br>/report/edit/&lt;id><br>Figma: — | Data Submitter<br>Work Execution<br>Scheduled Operational | Workflow<br>Mobile<br>Converge with Daily Closing | 15.15b (edit mode) | Refine — Same stages, 'Editing' banner |
| Report list<br>—<br>Figma: — | Daily Summary Reviewer<br>Historical Retrieval<br>Scheduled Operational | List Page (Historical Retrieval List)<br>Mobile<br>Converge with Report history | 15.4b Historical list | Retire — Duplicate of Report history |
| Report history<br>/entity/&lt;id>/reports<br>Figma: 93:515 · 93:676 · 379:5024 | Daily Summary Reviewer<br>Historical Retrieval<br>Scheduled Operational | List Page (Historical Retrieval List)<br>Mobile<br>Separate from analytics (2.10.4) | 15.4b Historical list | Refine — Row = Record row; delete in overflow |
| Shared report<br>/Minty_Report/<..><br>Figma: 104:949 | External viewer<br>Operational Review<br>— | Report Page<br>Mobile<br>Preserve | 15.7 Report · public variant | Refine — No actions, no navigation |
| Download statements<br>/admin/download_statements<br>Figma: — | Accountant / Owner<br>Historical Retrieval<br>— | Record Form<br>Desktop<br>Converge | 15.7g Download & sharing | Refine |
| Users<br>settings > users<br>Figma: 83:29 · 83:150 · 217:259 · 83:281 | Owner / Admin<br>People & Access<br>People & Access | List Page (Administrative List)<br>Desktop<br>Separate area (2.10.6) | 15.20c People & Access | Refine |
| Entity & Integration<br>settings > entity<br>Figma: 84:68 | Owner / Admin<br>System Configuration<br>Configuration | Detail Page + Record Form<br>Desktop<br>Separate area (2.10.6) | 15.20b Configuration · 15.10f integration | Refine |
| Petty Cash Settings<br>settings > pettycash<br>Figma: 84:217 · 84:480 | Owner / Admin<br>System Configuration<br>Configuration | Record Form<br>Desktop<br>Converge with Onboarding 5–7 | 15.20b · 15.3b | Refine — Same fields as onboarding, no intro text (2.9.10) |
| Module & Subscription<br>settings > module<br>Figma: 86:156 · 1347:23428 | Owner / Payer<br>Commercial Decision<br>Commercial | Detail Page<br>Desktop<br>Separate from Subscription overview (2.10.8) | 15.19 Subscription | Refine |
| Payment Settings<br>settings > payment<br>Figma: 87:222 | Owner / Admin<br>System Configuration<br>Configuration | Record Form<br>Desktop<br>Converge with Onboarding 8 | 15.20b · 15.3b | Refine |
| Module selection<br>/module-selection<br>Figma: 118:317 | All<br>Feature Selection<br>— | Selection Page (Feature Selection)<br>Both<br>Separate from Context (2.10.9) | 15.8c Module selection | Refine — Locked module = 15.8f |
| Payment request workspace<br>/payment-request/&lt;id><br>Figma: 839:1236 · 839:1405 · 78:63 · 422:5404… | Payment Processor (+ Requester)<br>Work Coordination / Execution<br>Triggered Operational | List Page (Operational List) + Detail Page<br>Desktop (Treasury) / Mobile (Requester)<br>Differentiate: Easy/Table (2.10.10) | 15.16 Requester · 15.17 Treasury | Replace — Inline payment panel in row → Drawer; character in row retire |
| Bill settings<br>/settings<br>Figma: — | Owner / Admin<br>System Configuration<br>Configuration | Record Form<br>Desktop<br>Converge with Settings | 15.20b | Refine — One Settings destination |
| Profile<br>/profile<br>Figma: 183:244 · 287:369 | All<br>Configuration (personal)<br>Configuration | Detail Page<br>Both<br>Converge | 15.5h Administrative detail | Refine |
| Billing<br>/profile/billing<br>Figma: 1347:21871 | Payer<br>Commercial Detail Review<br>Commercial | Detail Page + Record Form<br>Desktop<br>Separate but connected (2.10.8) | 15.19 Billing details | Refine |
| Invoices<br>/profile/invoices<br>Figma: 1347:23285 | Payer<br>Commercial Detail Review<br>Commercial | List Page (Historical Retrieval List)<br>Desktop<br>Separate but connected (2.10.8) | 15.19 · 15.4b | Refine |
| Subscriptions<br>/profile/subscriptions<br>Figma: 1347:1014 · 1347:25639 | Payer<br>Commercial Decision<br>Commercial | Dashboard (Decision Dashboard)<br>Desktop<br>Separate (2.10.7) | 15.6b + 15.19 | Refine — Strong state library — preserve rules |
| Incoming transfers<br>/subscriptions/incoming<br>Figma: 1347:21571 | Payer (receiving)<br>Commercial Decision<br>Commercial | List Page (Operational List) + Confirmation Modal<br>Desktop<br>Converge | 15.19 Transfer | Refine — Two-party scene: Minty sends, Ms Lemon receives |
| Subscriber view<br>/subscriptions/subscriber<br>Figma: — | Subscriber<br>Commercial Detail Review<br>Commercial | Detail Page<br>Desktop<br>Open (nav model conflict Part 1 vs 6) | 15.19 | Refine — Conflict C-3 |
| Maintenance<br>/maintenance<br>Figma: — | All<br>—<br>— | Empty State<br>Both<br>Converge | 15.10j Dedicated recovery | Refine |
| Admin<br>/admin<br>Figma: — | Minty staff<br>—<br>— | — (out of scope)<br>Desktop<br>Out of scope | — (excluded) | Retain as-is — Not customer-facing |
| Admin dashboard<br>/admin_dashboard<br>Figma: — | Minty staff<br>—<br>— | — (out of scope)<br>Desktop<br>Out of scope | — (excluded) | Retain as-is — Not customer-facing |

## 15.D Global composition rules

- **Screen frame.** App bar (60 desktop / 56 phone) → Body. Desktop body = Main (fill) + Sidebar 280 fixed on the right at ≥ 1280 px; below 1280 the Sidebar opens as a sheet from the App bar menu (D14-15).
- **Main width.** Lists and dashboards: fill, maximum 1200 content width on wide screens. Forms, reports, selection and administrative detail: centred column 720 (forms) / 640 (selection). Treasury document-and-record review: two columns 1:1, maximum 1440.
- **Page padding** 16 phone · 24 tablet · 32 computer (40 on 1440 desktop frames for Main); header to content 24 (phone) / 32 (computer); between sections 20–24; between list rows 8 (Part 5 spacing scale, 4 px base).
- **Breakpoints** (Part 5 5.12): Mobile 0–767 · Tablet 768–1199 (Small Desktop) · Standard computer 1200–1599 · Wide computer ≥ 1600. Design frames: phone 430, desktop 1440.
- **Action placement** follows 15.2; sticky action bars are exceptions, documented per pattern.
- **Characters** follow Part 13 placement: allowed on empty, onboarding, completion, loading, login, home greeting; never in tables, rows, active input, money errors or delete confirmations.
- **Browser translation:** no fixed-width text containers; amounts, codes and “Minty” carry translate="no".

## 15.E Responsive treatment matrix

|  | **Mobile** | **Tablet** | **Standard computer** | **Wide computer** |
|---|---|---|---|---|
| Lists | Record cards; filters in sheet; Show more | Record rows; sidebar sheet | Record rows or Table view; sidebar right ≥ 1280 | Table view extra columns |
| Detail | Stacked; document as File card → full-screen viewer | Stacked; preview 50% | Document : record 1:1 (Treasury); 720 column otherwise | Document up to 60% |
| Forms | Single column; amount pairs; capture first | Single column 640 | 720 column; dense forms 2 columns | Same as standard |
| Workflow | Step progress top, labels wrap | 720 column | 720 column; onboarding left sub-steps | Same |
| Actions | Primary full width, first | Desktop order | Header right; drawer footer | Same |
| Overlays | Full-screen sheets | Drawer 480 | Drawer 480 + scrim | Drawer 480 |

## 15.F State matrix

| **State** | **Where it shows** | **Pattern / component** |
|---|---|---|
| First use | Body | 15.11a · Empty state First use (Minty) |
| Empty / no records | Body | 15.11b |
| Loading | In place | Skeleton row / text |
| Draft | Header + list row | Status pill Neutral · Saving status |
| Incomplete | Section / Step | Section counter · Step progress |
| Complete | Step / record | Step done · Status pill |
| Requires attention | Section or page | Inline alert / Page banner |
| Blocked | Page or action | 15.9e gate · disabled Primary + reason |
| Submitted | Record | Status pill Info · Outcome state |
| Processing | Action | Button processing · Saving status |
| Failed | Smallest scope | 15.10 |
| Retry | Same place as failure | Button / File card Retry |
| No results | List body | 15.11c |
| No access | Body | 15.11d · Outcome state No access |
| Archived / Voided | Record | Status pill Neutral · read-only (Voided is Neutral, Part 13 D-27) |

## Cross-product, archetype, workflow and state patterns

### 15.1 Page-header patterns

| **Field** | **Specification** |
|---|---|
| Identity | Cross-product composition · all modules · Approved · 1.0 |
| Purpose | Tells the user where they are, what this page is for and what they can do next, in the first screenful. Product Goal: correct context (Entity, module, record) before any action. User Perceived Goal: “Am I in the right place, and what do I do here?” Completion outcome: the user starts the right task without searching. |
| Classification | All profiles · every Mental Mode · every Work Type · used by every archetype. Device: all. UX Boundary: Converge — six header variants share one component (Page header) and one rule set; differences are content, not structure. |
| Variants | Standard (Page header Type=Page): title, one-line purpose, page-level actions — lists, dashboards, settings. Record (Type=Record): back link to the parent list, record name, Status pill, one line of key metadata, record actions — Payment Request detail, User detail, Invoice detail. Workflow: App bar (Show back) + Step progress + stage title + one sentence of guidance; no page actions except Save & Exit at the end of the stage. Report: report name + date + one Status pill (secondary) + Share/Download/overflow. Selection: question-style title (“Which business are you working on?”) + short reassurance; no actions in the header. Compact: on phone, App bar carries the module name; page title moves into the content at display/m; actions collapse to one Primary + overflow. |
| Information hierarchy | Primary: title (what this is). Secondary: purpose line or key metadata. Supporting: status (prominent only when it decides the next action — Part 5 §5.6.4). Administrative: never in the header (Audit meta goes to the bottom of the page). Primary Action: right end of the header on computer; first full-width button in content on phone. Secondary Actions: Secondary/Ghost buttons, maximum two visible, the rest in the overflow Menu. |
| Composition | Regions: App bar (60 desktop / 56 phone) → Page header → content. Components: App bar, Page header, Status pill, Button, Menu (overflow), Step progress (Workflow only). Order: back link → title → status → metadata → actions. Default disclosure: everything visible; no collapsible header. Optional regions: Page banner directly under the header for page-wide states (15.10). |
| Screen structure | App bar: module name (left) · Entity full name + avatar + menu (right) ▸ Back link (Record only) ▸ Title + Status pill ▸ One line: purpose or key metadata ▸ Actions: [Secondary] [Primary] [More] ▸ Page banner (only when a page-wide state exists) ▸ Content. |
| Responsive | Mobile: App bar 56 holds back + module name; title in content; Primary becomes the first full-width button below the summary, or at the end of a form; overflow More stays in the header row. Tablet (Small Desktop): desktop structure, actions may wrap below the title. Standard computer: one line — title left, actions right. Wide computer: same as standard; content width capped (see 15.D) so actions do not drift far from the title. |
| Theme | Header sits on surface/page, no fill or shadow, separated by spacing (Part 13 ‘white canvas’). App bar uses surface/card + border/subtle bottom line in both themes. Status pill tones swap to Dark soft fills automatically. |
| States | Loading: title renders immediately; status and metadata show Skeleton text. Draft: Status pill Neutral “Draft” + Saving status beside the title in forms. Requires attention: Page banner under the header, not a red title. Archived/Voided: Status pill Danger/Neutral, actions reduced to view-only and overflow. No access: header still names the page; body uses Outcome state No access (15.11). |
| Accessibility | One h1 per page = the page title (App bar module name is not a heading). Back link is a real link with the parent name (“Payment Requests”), not just an arrow. Status pill text is read after the title. Focus order: back → title (not focusable) → actions left to right → overflow. Landmarks: header (App bar), main (from Page header down). |
| Content guidance | Titles are nouns for places (“Payment Requests”, “Report history”) and verbs for tasks (“Record payment”, “Count the cash”). Purpose line ≤ 12 words, business language (“Supplier bills waiting for payment”). Never repeat the module name in the title on the same screen as the App bar. Dates D MMM YYYY. |
| Existing screens | Closest: PR list header (839:1236), PR detail header (78:63), Petty Cash wizard header (67:139), Settings header (83:29). Preserve: PR ‘Payment Request + toggle’ placement of the view switch near the title. Modify: PR detail puts status beside the title but Edit/More float in content → move to header. Retire: ‘Pick up where you left off’ heading style that doubles as a card title; date pill + status pill inside the phone App bar (move to Workflow header line). |
| Do / Do not | Do: one Primary per header. Do: put Delete in overflow. Do not: show two Primary buttons (Return + Record payment) side by side — Return is Secondary. Do not: put the entity name in the page title; it lives in the App bar. |
| Figma composition | Parent: screen frame (auto layout vertical, Fill). Page header instance Fill width inside Main (padding 32/24/16). Variant property Type=Page\|Record. Workflow header is a composition (App bar + wrapper frame 70px for Step progress + title text display/m + body/m guidance), documented as pattern frame ‘15.1 Workflow header’. |
| Implementation | Header actions are role-aware: hide actions the role cannot perform rather than disabling them, unless explaining the restriction helps (then disabled + tooltip). Record header status comes from the same status source as list rows. Exclusions: no breadcrumbs deeper than one level; no tabs in the header (tabs belong to content, 15.5). |

### 15.2 Action hierarchy patterns

| **Field** | **Specification** |
|---|---|
| Identity | Cross-product composition · all modules · Approved · 1.0 |
| Purpose | Makes the next correct action obvious and the dangerous action hard to hit by accident. Product Goal: controlled, auditable actions (no double payment, no accidental deletion). User Perceived Goal: “What do I press to finish?” Completion outcome: one clear forward action per context. |
| Classification | All profiles. Mental Modes: Work Execution, Verification, Configuration, Commercial Decision. Archetypes: all. UX Boundary: Converge on one rule set (replaces Part 7 Deferred action hierarchy; Button rules from Part 14). |
| Variants | Page-level creation: Primary in the Page header (“+ Add payment request”, “Invite person”). Floating + buttons are retired. Record-level action: in Record header (computer) or end of summary card (phone); in list rows only the single next action for that status (Record payment, Open draft, View). Workflow continuation: Save & Next (Primary) at the end of the stage + Save & Exit (Ghost/Link) beneath; not sticky by default (Part 3 §3.12, Part 5 §5.11.1). Final submission: on the Close/Review stage only; label names the outcome (“Submit Daily Report”, “Submit for payment”). Destructive: Delete/Void/Remove live in overflow or as Danger only inside a Confirmation modal (Kind=Destructive). Secondary actions: Secondary (outlined) — maximum two visible. Overflow: More menu for rare, administrative or destructive actions. Mobile adaptation: Primary full width; Secondary as full-width outlined or Ghost under it; order Primary first. |
| Information hierarchy | 1 Primary (forward), up to 2 Secondary (alternatives), Ghost/Link (leave or postpone), overflow (rare/destructive). Money actions show the amount in the label where useful (“Record HK$4,800.00”) so the consequence is visible before pressing (Part 1). |
| Composition | Desktop order: [Ghost] [Secondary] [Primary] right-aligned; Destructive never adjacent to Primary. Phone order: Primary on top, then Secondary, then Ghost. Drawers and modals: actions in the footer, Primary right (desktop) / bottom (phone). |
| Screen structure | Form end: [Save & Next — full width] / Save & Exit (link). Record header: [Return to requester] [Record payment] [More]. Confirmation modal: Title states the action ▸ consequence sentence ▸ [Cancel] [Void payment]. |
| Responsive | Mobile: one Primary visible at a time; sticky only for Camera capture and multi-step document intake where the keyboard hides the end of the page (documented exception). Tablet: desktop order. Standard/Wide: header actions; row actions right-aligned in a fixed track (Record row). |
| Theme | Primary uses action/primary in both themes (white SemiBold label, documented 2.29:1 brand exception). Danger buttons use action/danger; never red text links for destructive actions. |
| States | Processing: button label changes (“Recording…”), disabled, prevents double submit. Disabled: only when the reason is visible nearby (e.g. ‘Add a reason for the difference to continue’). Failed: button re-enables; error sits by the cause (15.10). Done: Toast + updated status; button does not stay in a ‘done’ state. |
| Accessibility | Native buttons; accessible names are the visible labels (amount included). Destructive confirmations focus Cancel first. Overflow menu: button with aria-haspopup, arrow-key navigation, Esc closes and returns focus. |
| Content guidance | Verb + object: Record payment, Submit Daily Report, Invite person, Save & Next, Save & Exit. Never OK/Yes/Submit alone. Destructive: “Delete report”, “Void payment” + consequence (“The payment is removed from the request. Xero is updated.”). |
| Existing screens | Petty Cash report view (104:592): Delete / Edit / Close stacked full-width → Edit in header, Delete in overflow, Close removed. PR detail (78:63): Return and Record payment both coloured → Return Secondary. Settings Users (83:29): floating + → ‘Invite person’ header Primary. Onboarding: Back / Save & Exit / Save & Next row → preserved. |
| Do / Do not | Do: show the money consequence before a payment action. Do: keep Save & Exit on every workflow stage. Do not: put Pay as a coloured button inside the Status column. Do not: use Danger for Return (it is not destructive). |
| Figma composition | Actions frame: auto layout horizontal (desktop, primaryAxisAlignItems MAX, gap 12) / vertical (phone, gap 8, children Fill). Button instances only; Kind set by role in the hierarchy. |
| Implementation | Double-submit protection on every money or status action. Role-aware visibility (Part 14 Role badge rules). Exclusions: no undo for payments in v1 — Void with confirmation instead. |

### 15.3 Form composition patterns

| **Field** | **Specification** |
|---|---|
| Identity | Archetype implementation (Record Form) · all modules · Approved · 1.0 |
| Purpose | Collects required information with the least reading and typing. Product Goal: complete, valid, auditable records. User Perceived Goal: “Let me enter this and be done.” Completion outcome: saved or submitted record with no hidden errors. |
| Classification | Data Submitter (primary), Payment Processor and Owner (secondary). Mental Modes: Work Execution, System Configuration, People & Access. Work Types: Scheduled/Triggered Operational, Configuration, People & Access. Archetype: Record Form. Device: phone-first for submitters, desktop for configuration. UX Boundary: Converge (one form system), Differentiate within one experience for density (guided vs professional). |
| Variants | a Simple form — ≤ 6 fields, one column (Login, Create entity, Add contact). b Grouped form — Section header groups with running subtotals (Sales entry, Payment settings). c Document-supported form — fields first, File card / Camera capture attached (Add expense). d Document-first form — capture or upload first, fields extracted (AI field) then confirmed (Create Payment Request, future). e Guided owner form — onboarding tone, one decision per section, Auto Fill offer (Sales setting). f Professional dense form — two columns on computer, inline table editing (Account code mapping). Create/Edit relationship — same form, same order; Edit pre-fills and shows Audit meta; Edit of a submitted record opens with a Page banner explaining the consequence. Final review — Description rows of entered values + edit links per section + one submit action. |
| Information hierarchy | Required fields first, in the order the user finds the information on the paper document; optional fields after a ‘More details’ disclosure; validation at field level on blur; Save/Submit at the end. Totals and differences are Primary information inside grouped forms (Description row / KPI-style subtotal bar). |
| Composition | Regions: header (15.1) → optional Page banner → sections (Section header + fields) → review/summary block (where totals exist) → actions (15.2). Components: Input, Amount input, Select, Supplier picker, Date field, Textarea, Checkbox/Radio/Switch, Segmented control, File card, Camera capture, AI field, Inline alert, Saving status. Disclosure: optional and administrative fields collapsed. |
| Screen structure | Title + one guidance line ▸ Section ‘Electronic payments’: amount fields (2 per row on phone only if both ≤ 10 characters) ▸ subtotal bar ▸ Section ‘Delivery’ … ▸ Totals ▸ [Save & Next] / Save & Exit. |
| Responsive | Mobile: single column; amount pairs allowed; numeric keypad for amounts; Camera capture first in document-first forms. Tablet: single column max 640 or paired fields. Standard: max form width 720 centred in Main, or two columns for dense professional forms; document preview to the right in document-supported forms. Wide: same widths — forms do not stretch. |
| Theme | Inputs on surface/card with border/input; error ring red in both themes; read-only values use Description row, never disabled inputs. |
| States | Empty (placeholders are examples, not labels), Draft (Saving status ‘Saved 6:02 pm’), incomplete (required markers + section counter), error (field message + summary at top if > 1), processing (submit disabled), failed save (15.10 preserved Draft), complete (15.12). |
| Accessibility | Visible label for every field (no placeholder-only); helper and error linked by aria-describedby; error summary with links to fields on submit; amount fields announce currency; logical tab order = visual order; required indicated in text (“required”) not only *. |
| Content guidance | Labels are nouns (“Invoice date”), helpers say why/format (“As shown on the invoice”), errors say how to fix (“Enter an amount above 0”). Never ‘Invalid input’. |
| Existing screens | Preserve: Sales entry grouped amounts + subtotal (67:139). Modify: PR detail read-only inputs (78:63) → Description rows; onboarding Account code (46:253) dense table → professional dense form. Retire: date format ‘16 08 2026’ → ‘16 Aug 2026’. |
| Do / Do not | Do: keep the same field order in Create and Edit. Do: show the subtotal as the user types. Do not: disable Save until every field is valid — let users save a Draft. Do not: put optional fields between required ones. |
| Figma composition | Form frame auto layout vertical gap 20 (phone) / 24 (desktop), max width 720; Section = auto layout vertical with Section header instance + fields Fill; paired fields = horizontal auto layout, children Fill. |
| Implementation | Server-side validation mirrors field rules; autosave Drafts every change for operational workflows; amounts stored as minor units; exclusions: no multi-currency entry in v1 unless Part 11 §11.30 accounting localisation requires it. |

### 15.4 List composition patterns

| **Field** | **Specification** |
|---|---|
| Identity | Archetype implementation (List Page) · all modules · Approved · 1.0 |
| Purpose | Helps the user find the record that needs them and act on it. Product Goal: nothing waits unseen; correct record opened. User Perceived Goal: “What needs me?” (Operational) / “Where is that record?” (Historical) / “Which one do I manage?” (Administrative). |
| Classification | Payment Processor (Operational), Daily Summary Reviewer (Historical), Owner/Admin (Administrative). Mental Modes: Work Coordination, Historical Retrieval, People & Access. UX Boundary: Easy view and Table view = Differentiate within one experience (2.10.10), same records, same statuses, same filters. |
| Variants | a Operational list — status filter chips with counts first, next-action button per row, Easy view default, Table view toggle for every role (D14-16). b Historical retrieval list — search/date filter first, chronological, view-only rows, no counts. c Administrative list — Record rows / User rows with Role badge, page-level Create/Invite, overflow per row. Mobile cards — Record row Device=Mobile. Desktop table — Table row, sortable headers, Compact density, Bulk action bar on selection. Search-first retrieval — Search input full width above filters (Historical, Entity list > 6). Filter-first queue — chips above search (Operational). Empty results — 15.11. Bulk processing — only Operational Table view and only for actions that are safe in bulk (mark paid with amounts shown, export). |
| Information hierarchy | Row: identity (supplier/date/name) → key amount (right-aligned, tabular figures) → status → one next action. Secondary in row meta line (description · due date). Administrative fields (IDs, created by) only in Table view columns or detail. |
| Composition | Header (15.1 Standard) → search + view toggle → filter chips → list → pagination (10/25/50/100). Components: Page header, Search input, Segmented control (Easy/Table), Filter chip, Record row / Table row, Bulk action bar, Pagination, Empty state, Skeleton row. |
| Screen structure | Payment Requests · [Export CSV] [+ Add payment request] ▸ [Search supplier, description or amount……] [Easy view \| Table view] ▸ (All 41) (Payment Requested 18) (Partially Paid 12) (Returned 3) (Draft 2) (Paid) ▸ rows ▸ Showing 1–10 of 41 · pages · Rows 10. |
| Responsive | Mobile: Record row Mobile cards (identity, amount, status, whole card tappable; next action inside the card only for the Operational variant); filters behind a Filter button opening a bottom sheet; pagination becomes ‘Show more’. Tablet: Record rows desktop layout, sidebar as sheet. Standard: Record rows or Table view; sidebar fixed right ≥ 1280. Wide: Table view may show extra columns (due date, account code); Easy view rows stay max 960 wide. |
| Theme | Rows: surface/card + border/subtle; hover state/hover; selected border/selected. Amount colour is never the status signal (status pill carries it). |
| States | Loading: 5 Skeleton rows. Empty first use / no results / no access: 15.11. Filtered: chip Selected + ‘Clear filters’. Bulk selected: Bulk action bar with count and total. Error loading: Inline alert in place of rows with Retry. |
| Accessibility | Desktop Table view is a real table (th scope); Easy view rows are a list (ul/li) with the row title as a link; row action buttons have record-specific names (“Record payment for Kwok Transport Ltd”); filter chips are toggle buttons with aria-pressed and counts read aloud. |
| Content guidance | Chip labels = status names exactly as in Status pill. Empty filter: “No requests match ‘Returned’. Clear filters”. Count format: “Showing 1–10 of 41”. |
| Existing screens | PR Easy view (839:1236), Table view (839:1405), Report history (93:515), Settings Users (83:29), Entity list (118:244). Preserve: status chips + Easy/Table toggle. Modify: mascot illustration panel beside the list → removed (Part 13: no characters beside tables/rows); ‘Pay’ coloured status column → Status pill + separate action. Retire: Report list (duplicate). |
| Do / Do not | Do: right-align amounts and keep them in one column track. Do: keep the same filters in both views. Do not: expand a payment form inside a row (use Drawer, 15.17). Do not: show bulk delete. |
| Figma composition | Main frame auto layout vertical gap 20; toolbar rows horizontal; list frame vertical gap 8 with Record row instances Fill; Table view uses Table row Type=Header + Default instances inside a card frame with border/subtle. |
| Implementation | Server-side filtering, sorting and pagination; filter state in URL; counts per status from the same query; view preference remembered per user; exclusions: no infinite scroll on desktop. |

### 15.5 Detail-page patterns

| **Field** | **Specification** |
|---|---|
| Identity | Archetype implementation (Detail Page) · all modules · Approved · 1.0 |
| Purpose | Explains one record so the user can understand it and decide. Product Goal: accurate, auditable record review. User Perceived Goal: “What is this, and is it right?” |
| Classification | Payment Processor, Data Submitter (after submission), Owner. Mental Modes: Commercial Detail Review, Work Verification, Operational Review. Archetype: Detail Page. UX Boundary: Differentiate within one experience — requester and Treasury see the same record with role-aware actions and density. |
| Variants | a Summary-first — key amount + status + 3–5 Description rows, details below (Requester submitted request, Invoice detail). b Decision-oriented — summary + the decision actions in the header (Treasury review). c Document-and-record review — document viewer and record side by side on computer (Treasury, 12.4.10 equal-review role). d Guided owner detail — summary + plain-language explanation + next step (Subscription module status). e Professional processing detail — more fields expanded, payment table visible (Treasury). f Supporting information disclosure — collapsible sections. g History — Timeline item list collapsed by default. h Administrative detail — Profile, User detail: Description rows with inline Edit per section. |
| Information hierarchy | Summary (identity, amount, status) → information needed for the decision → supporting document → payments/history (collapsed) → administrative (Audit meta, IDs). |
| Composition | Record header (15.1) → summary block → content columns (computer) or stacked sections (phone) → History (collapsed) → Audit meta. Components: Page header Record, Description row, Document viewer, File card, Table row Nested payment, Timeline item, Audit meta, Drawer (for actions that need input). |
| Screen structure | ← Payment Requests ▸ Kwok Transport Ltd [Payment Requested] ▸ Monthly delivery retainer · Requested by Jane Lee · 18 Aug 2026 ▸ [Return to requester] [Record payment] [More] ▸ \| Document viewer \| Description rows: Supplier, Description, Invoice amount, Paid so far, Unpaid, Invoice date, Due date, Account code, Requested by \| ▸ Payments (table) ▸ History (collapsed) ▸ Audit meta. |
| Responsive | Mobile: summary card first; document as a File card that opens full-screen viewer; Description rows stacked; actions under the summary. Tablet: stacked with document preview at 50% width. Standard: two columns 1:1 (document : record) for Treasury; single column 720 for requester and administrative detail. Wide: document column may grow to 60%. |
| Theme | Document viewer sits on surface/document (stays light in Dark mode so scans remain readable). |
| States | Draft (requester: Continue editing banner), submitted, partially paid, returned (Page banner Warning with return reason + ‘Edit and resubmit’), voided (read-only, Danger pill), loading (skeleton), no access (Outcome state), document failed to load (Inline alert in viewer + Download link). |
| Accessibility | Description rows = dl/dt/dd; section headings h2; collapsed sections are disclosure buttons with aria-expanded; document viewer has a text alternative (file name, pages) and keyboard zoom. |
| Content guidance | Terms match form labels exactly. Amounts with currency prefix and two decimals. History entries in past tense with actor and time (“Marcus Ho recorded a partial payment · 19 Aug 2026 14:08”). |
| Existing screens | PR details (78:63, 401:5253, 244:745), Profile (183:244), Report view (104:592). Preserve: document-left/record-right layout. Modify: disabled inputs → Description rows; History card → collapsed Timeline. Retire: ‘Detailed Information’ card title. |
| Do / Do not | Do: show unpaid amount next to invoice amount. Do not: make the detail page editable in place for money fields — Edit opens the form. |
| Figma composition | Columns frame horizontal gap 24, children Fill; Record card vertical with Description row instances Fill; History = Section header With action + Timeline items. |
| Implementation | Role-aware actions; status-driven action availability matrix (in 15.17); exclusions: no inline editing of Paid records. |

### 15.6 Dashboard patterns

| **Field** | **Specification** |
|---|---|
| Identity | Archetype implementation (Dashboard) · Petty Cash, Subscription · Approved · 1.0 |
| Purpose | Answers one question at a glance: “What should I do?” (Action), “What should I choose?” (Decision). Monitoring (“What is happening?”) is Future — no current dashboard may be built for Business Monitor (2.4.6). |
| Classification | Action: Data Submitter / Payment Processor, Work Coordination, Scheduled Operational. Decision: Payer/Owner, Commercial Decision. UX Boundary: Work Coordination and Operational Review are Separate (2.10.1) — the launch page must not become the Daily Report. |
| Variants | a Action Dashboard — today’s work card (stage progress + Continue), items needing attention, recent records. b Decision Dashboard — current position (plan, modules, next bill), recommendation, options. c Monitoring — Future, labelled. Combined compositions are not approved; Petty Cash dashboard definition is in progress (calendar = example only). |
| Information hierarchy | Action: work requiring attention → next action → progress → supporting (recent reports). Decision: current position → recommendation → options → supporting (invoices link). |
| Composition | Greeting with Minty (conditional, home only) → primary work card → attention items (Page banner/Inline alert) → Section header + 2–3 Record rows + ‘See all’. Max 3 KPI cards where KPIs are justified (Decision dashboard). |
| Screen structure | Petty Cash · Vine Café Central ▸ (Minty) Good evening, Olive · Mon 5 Oct 2026 ▸ Today’s Daily Closing: Step progress · 3 of 5 done · Next: Cash Count · Saved 6:02 pm · [Continue Daily Closing] ▸ Recent reports · See all ▸ 2 Record rows. |
| Responsive | Mobile: single column as above (primary device for Petty Cash, 95%). Tablet: same, max width 640. Standard: primary card + recent list side by side (2:1). Wide: same, centred max 1200. |
| Theme | Primary work card uses surface/card + border; Step progress current step = brand (D14-03). |
| States | Not started (Start today’s Daily Closing), in progress (Continue), yesterday not finalised (business-rule gate banner: ‘Finish Sun 4 Oct first’ + action), done (Today’s report is submitted · View report), first use (15.11 first-use with Minty), loading (skeleton card). |
| Accessibility | Greeting is not a heading; h1 = “Petty Cash” visually hidden if App bar carries it; progress has text (“3 of 5 done”) not only dots. |
| Content guidance | Continue/Start labels name the work (“Continue Daily Closing”). No exclamation marks on routine states. |
| Existing screens | Dashboard (66:6, 66:172, 66:374). Replace: Quick Actions (View History / Entity Settings) and calendar → recent reports + sidebar navigation. Preserve: progress card + Continue. |
| Do / Do not | Do: one primary card. Do not: show sales KPIs on the launch page (that is Operational Review). |
| Figma composition | Phone frame 430 auto layout vertical; Content padding 16 gap 20; Step progress wrapped in a 70px frame so labels do not overlap (component height 10 + labels). |
| Implementation | Launch state derives from the open report (stage, last save) and the gate rule (previous day finalised). Exclusions: no calendar until the dashboard redefinition is approved. |

### 15.7 Report patterns

| **Field** | **Specification** |
|---|---|
| Identity | Archetype implementation (Report Page) · Petty Cash (Daily Report), Shared report · Approved · 1.0 |
| Purpose | Shows what happened. Product Goal: accurate, finalised operational record. User Perceived Goal: “How much did we sell, spend, and what cash do we have?” (Daily Summary Reviewer). |
| Classification | Daily Summary Reviewer · Operational Review · Scheduled Operational · Report Page · Mobile · Separate from Work Verification (2.10.3) and from analytics (2.10.4). |
| Variants | Outcome-first report; KPI summary (exactly 3: Total sales, Total expenses, Cash position); breakdowns (sales by method, expenses list) collapsed under each KPI; supporting records (expense entries); supporting documents (File cards); administrative (submitted by, time, Xero sync) at the bottom; download & sharing (Share link, Download PDF) in header; shared/public variant without actions or navigation. |
| Information hierarchy | 3 KPIs → difference/attention (cash short/over as Inline alert) → breakdowns → documents → administrative. |
| Composition | Report header (name, date, status secondary, Share/Download, More Edit/Delete) → KPI cards → Inline alert (if any) → collapsible breakdown sections → Audit meta. |
| Screen structure | Daily Report · Sun 4 Oct 2026 [Submitted] [Share] [More] ▸ Total sales HK$4,240.00 · Total expenses HK$516.50 · Cash position HK$1,876.50 ▸ ‘Cash was HK$120.00 short — note: evening float swap’ ▸ Sales by method (collapsed) ▸ Expenses (3) (collapsed) ▸ Receipts (3) (collapsed) ▸ Submitted by Olive Tan · 6:12 pm · Sent to Xero. |
| Responsive | Mobile: KPIs stacked full width. Tablet: 3 KPIs in a row. Standard/Wide: 3 KPIs in a row, breakdown sections in a single 720 column (reports are read, not compared). |
| Theme | Charts (if kept) use brand + neutral only; no red/green meaning without text. |
| States | Submitted, finalised/published, edited after submission (Page banner Info: ‘Edited by … · see history’), loading, not found/no access, shared link expired (Outcome state). |
| Accessibility | KPI value + label read together; collapsible sections as disclosures; charts have a table alternative. |
| Content guidance | ‘Cash position’ not ‘Cash balance’ where Part 2 uses position; shortages stated as fact, not blame. |
| Existing screens | Report view (104:592, 104:773), Share (104:949). Preserve: KPI cards + Show more. Modify: Sales history chart → optional, below KPIs (future analytics boundary). Retire: Delete/Edit/Close stacked buttons. |
| Do / Do not | Do not: add trend analysis to Report history pages (2.10.4). |
| Figma composition | KPI row = horizontal auto layout, KPI card instances Fill (desktop) / vertical (phone). |
| Implementation | Report figures are computed server-side from the finalised record; shared link is read-only and revocable. |

### 15.8 Selection patterns

| **Field** | **Specification** |
|---|---|
| Identity | Archetype implementation (Selection Page) · cross-product · Approved · 1.0 |
| Purpose | Lets the user choose context or capability before working. Product Goal: work is recorded against the right Entity and only in subscribed modules. User Perceived Goal: “Get me into the right business / tool.” |
| Classification | All profiles · Context Selection / Feature Selection · Selection Page · Both devices · Separate families (2.10.9). |
| Variants | a Context selection — Entity list (search from 7+ entities, last used first). b Feature selection — modules the user can use. c Module selection — onboarding choice of modules with price context. d Entity selection inside the app — Entity selector in Sidebar. e Recommended option — one option marked ‘Recommended’ with a reason. f Locked capability — module card with lock icon + ‘Not in your plan’ + action for payers / ‘Ask your admin’ for others. g Responsive choice presentation — cards on phone, cards in a 2–3 column grid on computer. |
| Information hierarchy | Question title → options (name, one-line meaning, status) → recommended/locked marks → continue. |
| Composition | Selection header (question + reassurance) → Search (if > 6 options) → option list/cards → page-level ‘Create entity’ (Secondary, not floating). |
| Screen structure | Which business are you working on? ▸ [Search businesses] ▸ Olive & Vine Limited · Admin · 2 modules › ▸ Vine Café Central · Cashier › ▸ … ▸ [+ Create a business]. |
| Responsive | Mobile: full-width rows. Tablet/Standard/Wide: centred column max 640; module cards 2–3 per row. |
| Theme | Selected card border/selected + check; locked uses text/muted + lock icon (not opacity only). |
| States | Single option → skip the page and route directly (single-Entity/single-module routing). Empty → 15.11 first use (Create entity). Loading → skeleton rows. No access → Outcome No access. |
| Accessibility | Options are links (navigate) or radio cards (choose then continue) — never both; locked options remain focusable with explanation. |
| Content guidance | Questions in plain language; locked text says who can unlock. |
| Existing screens | Entity list (118:244), Module selection (118:317), onboarding Select Module (50:364…). Modify: door illustration → Minty (character rules), FAB → page action. |
| Do / Do not | Do not: show a Selection page when there is only one choice. |
| Figma composition | Centred column frame max 640, Record rows / Module chip cards. |
| Implementation | Last-used Entity remembered; routing rules in 15.21. |

### 15.9 Workflow patterns

| **Field** | **Specification** |
|---|---|
| Identity | Workflow · Petty Cash, Onboarding, future AI intake · Approved · 1.0 |
| Purpose | Guides a multi-stage activity to completion without trapping the user. Product Goal: required stages, controls and verification completed. User Perceived Goal: “Get this done.” |
| Classification | Data Submitter / Owner · Work Execution → Work Verification · Scheduled Operational / Configuration · Workflow archetype · Mobile (Daily Closing), Desktop+Mobile (Onboarding) · Work Execution and Verification related but distinct (2.10.2). |
| Variants | a Operational workflow (Daily Closing). b Setup workflow (Onboarding shell, 15.18). c Current-stage presentation — Step progress, current stage brand-filled, done stages checked, labels always visible. d Flexible section navigation — tap any done or current stage; future stages open only when a business rule requires order (Part 12 12.4.7). e Business-rule gate — a page or banner that explains the rule and gives one action (‘Finish Sun 4 Oct first’; ‘Connect Xero before inviting’). f Save & resume — autosave + Saving status; launch page shows Continue; Draft preserved after failure. g Work Verification — a review stage that recalculates and shows differences before submit. h Submission — one action naming the outcome, Confirmation modal only when consequences are external (Xero, payment). i Success transition — Outcome state then route to the result. |
| Information hierarchy | Current stage task → values entered → what is missing → next action; done-stage data available but not shown. |
| Composition | Workflow header (15.1) → stage content (15.3 forms) → stage summary (if totals) → Save & Next / Save & Exit. |
| Screen structure | Daily Closing ▸ [✓ Drawer][✓ Sales][✓ Expenses][4 Cash Count][5 Close] ▸ Cash Count · Count the cash in the drawer… ▸ Cash taken for bank deposit (optional) ▸ Cash in the drawer ▸ Check: Expected / Counted / Difference + reason ▸ [Save & Next] / Save & Exit. |
| Responsive | Mobile: stages above content; labels may wrap to 2 lines. Tablet/Standard: Step progress full width of a 720 column; onboarding uses left section list (15.18). Wide: same. |
| Theme | Step colours: done = brand tint + check, current = brand fill, future = neutral; all with text labels. |
| States | Not started, in progress, Draft saved, offline (Saving status Offline + local queue), blocked by gate, verification differences, submitted, failed submit (Draft preserved). |
| Accessibility | Step progress is an ordered list with aria-current=step; stage title is h1; gate messages announced; Save & Exit always reachable by keyboard. |
| Content guidance | Stage names: Addition to Drawer · Sales · Expenses · Cash Count · Close (Step label short form ‘Drawer’). Gate: rule + reason + action. |
| Existing screens | Report wizard 67:63…71:521 (old names Opening/Bank Deposit/Ending → rename; Bank Deposit folded into Cash Count, D15-05). Onboarding 41:19…47:497. |
| Do / Do not | Do not: block navigation to done stages. Do not: hide Save & Exit. |
| Figma composition | Workflow frame = App bar + 70px Step progress wrapper + content column; one frame per stage. |
| Implementation | Stage completion is data-driven (required fields), not visit-driven; gate rule server-side. |

### 15.10 Feedback and recovery patterns

| **Field** | **Specification** |
|---|---|
| Identity | State and recovery · cross-product · Approved · 1.0 |
| Purpose | Tells the user what went wrong, what is safe, and how to fix it. Product Goal: no silent data loss, no silent integration failure. User Perceived Goal: “Is my work safe, and what do I do now?” |
| Classification | All profiles · all modes · Feedback is placed at the smallest scope that contains the problem (Part 10). |
| Variants | a Field-level correction — Input Error state + message under the field. b Section issue — Inline alert inside the section (cash difference, missing receipt). c Page-wide issue — Page banner under the header (Xero sync paused). d Failed save — Saving status ‘Not saved’ + Retry; Draft kept locally. e Failed upload — File card Failed + Retry/Remove; other files unaffected. f Integration problem — Page banner Warning with ‘Reconnect Xero’; work continues in Minty. g Blocked completion — disabled Primary + visible reason list with links. h Preserved Draft — Toast ‘Draft saved’ and Continue on return. i Retry — same action, same place. j Dedicated recovery — full page (Error, Maintenance) with Minty neutral pose, what happened, what is safe, one action. |
| Information hierarchy | What happened → is my work safe → what to do → (technical detail collapsed). |
| Composition | Scope rule: field < section < page < dedicated page. Toast only for success or undoable info, never for errors that need action. |
| Screen structure | [!] Xero sync is paused · Your transactions are saved in Minty and will be sent when Xero is reconnected. [Reconnect Xero] |
| Responsive | Same components at all widths; Page banner full width of Main; toasts bottom-centre on phone, bottom-left of Main on computer (sidebar is right). |
| Theme | Status tones soft-fill + deep text in both themes; icon + text always. |
| States | Info, Success, Warning, Danger tones; dismissible only when not blocking. |
| Accessibility | Errors: aria-live=assertive for blocking, polite for non-blocking; error summary focusable; never colour alone. |
| Content guidance | No blame, no codes in the main sentence; money errors: no characters, no jokes (Part 13). |
| Existing screens | Fix Negative Balance (70:453) → section issue + gate; errors.html → dedicated recovery; Subscription ‘When it fails’ section (1347:38158) → preserved rules. |
| Do / Do not | Do not: show a modal for a field error. Do not: use angry/crying characters. |
| Figma composition | Use Inline alert / Page banner / Toast / Saving status instances; no custom alert frames. |
| Implementation | Idempotent retries; client keeps unsent Draft; integration errors logged with user-safe message mapping. |

### 15.11 Empty and no-result patterns

| **Field** | **Specification** |
|---|---|
| Identity | State and recovery (Empty State archetype) · cross-product · Approved · 1.0 |
| Purpose | Turns ‘nothing here’ into a next step. User Perceived Goal: “What should I do now?” |
| Classification | All profiles · Empty State archetype · Minty allowed (Part 13 placement: always OK). |
| Variants | a First-use — Minty + what this page is for + one Primary (Create Payment Request). b No existing records — calmer, no illustration on lists after first use; secondary action. c No filtered results — no character; text + ‘Clear filters’. d No access — Outcome state No access + who can grant it. e Locked module — Outcome state Not in plan + payer action / ask admin. f Data not yet available — waiting state (‘Today’s report will appear after Close’; Awaiting approval). g Future analytics unavailable — labelled Future, no fake charts. |
| Information hierarchy | Title (state) → one sentence (why/next) → one action. |
| Composition | Empty state component in place of the list/body, centred in Main, max 400. |
| Screen structure | (Minty) No payment requests yet · Create one when a supplier bill arrives. [Create Payment Request] |
| Responsive | Same at all widths; character M on phone, L on computer. |
| Theme | Characters are transparent PNG assets; no background plate. |
| States | — |
| Accessibility | Character decorative (alt=""); title is h2 inside the page. |
| Content guidance | Never ‘No data’. Say what will appear and how. |
| Existing screens | Entity list empty, Report history empty, Select Module none (50:605), Subscription Empty sections. |
| Do / Do not | Do not: use a character for filtered no-results (it is not a moment). |
| Figma composition | Empty state Kind=First use\|No results; Outcome state Kind=No access\|Not in plan. |
| Implementation | Distinguish ‘no records’ from ‘no results’ from ‘no access’ in API responses. |

### 15.12 Completion patterns

| **Field** | **Specification** |
|---|---|
| Identity | Workflow · cross-product · Approved · 1.0 |
| Purpose | Confirms the outcome and the next step. Product Goal: user knows the record is final and what happened externally. User Perceived Goal: “It’s done.” |
| Classification | All profiles · end of Work Execution/Verification/Configuration. |
| Variants | a Low-consequence save — Toast ‘Saved’. b Draft preserved — Toast ‘Draft saved · Continue later from Petty Cash’. c Invitation sent — Toast + User row status ‘Invited’. d Payment Request submitted — Outcome state: what was sent, to whom, what happens next. e Daily Report finalised — Outcome state (Minty happy) with Cash counted, Difference, Sent to Xero; [View report] [Back to home]. f Payment recorded — Toast with amount + row status updates; no page change. g Configuration completed — Outcome state (All set) → enter the app. h Consequential external confirmation — Confirmation modal before (payment, void, subscription change), Outcome after. |
| Information hierarchy | Outcome sentence → key facts (3 max) → next action. |
| Composition | Toast for in-place actions; Outcome state page for workflow ends. |
| Screen structure | (Minty) Today’s report is submitted · Mon 5 Oct 2026 · Vine Café Central ▸ Cash counted HK$6,470 · Difference HK$20 short · note added · Sent to Xero Yes · 6:12 pm ▸ [View report] [Back to home] |
| Responsive | Outcome state centred, full width actions on phone. |
| Theme | Character on surface/page; no confetti (reduced motion). |
| States | Success; partial success (submitted, Xero pending → Info line). |
| Accessibility | Focus moves to the outcome title; toasts polite live region. |
| Content guidance | Past tense, factual; one celebratory word maximum for big moments. |
| Existing screens | Report Submitted (71:624), All Set (47:497), Entity created, Subscription After Confirm (1347:35775). |
| Do / Do not | Do not: celebrate routine saves. |
| Figma composition | Outcome state Kind=Completion; Toast Kind=Simple. |
| Implementation | Outcome facts come from the server response, not client assumptions. |

### 15.13 Supporting-document patterns

| **Field** | **Specification** |
|---|---|
| Identity | Cross-product composition · Petty Cash, Payment Request · Approved · 1.0 |
| Purpose | Attaches and reviews receipts, invoices and bank slips with the right weight for the workflow (12.4.10). |
| Classification | Data Submitter (capture), Payment Processor (review). |
| Variants | a Supporting role (Daily Report expenses): File card under the entry, optional. b Equal-review role (Treasury): Document viewer beside the record. c Entry-point role (document-first PR): capture first, then fields. Capture (Camera capture, multi-page), Extract (AI field, 15.14), Review (viewer with zoom/pages), Replace (File card Replace), Retry (Failed state). Files: PDF/JPG/PNG/HEIC, 10 MB each, max 10 per record, photos compressed on device (D14-17). |
| Information hierarchy | Supporting: business info first. Equal-review: document and record same weight. Entry-point: document first. |
| Composition | File card list + Upload/Camera button; Document viewer on computer review. |
| Screen structure | Receipts (2) [+ Add] ▸ File card Receipt_Taxi.jpg · 860 KB [View][Remove]. |
| Responsive | Mobile: Camera capture first, viewer full screen. Computer: viewer inline left column. |
| Theme | Viewer surface/document stays light. |
| States | Uploading, uploaded, failed, too large, wrong type, max reached. |
| Accessibility | Upload control is a button; progress announced; viewer keyboard zoom/page. |
| Content guidance | ‘Add receipt’, ‘Bank slip (optional)’; errors give the limit (‘Files up to 10 MB’). |
| Existing screens | Expense add (69:229), PR bank slip overlay (466:6739, 839:1778). |
| Do / Do not | Do not: block expense entry because a receipt is missing unless a business rule requires it. |
| Figma composition | File card State variants; Document viewer component. |
| Implementation | Client compression + HEIC conversion; virus scan before preview. |

### 15.14 AI-assisted patterns

| **Field** | **Specification** |
|---|---|
| Identity | AI-assisted · Payment Request intake, onboarding Auto Fill · Draft (partly Future) · 0.9 |
| Purpose | Reduces typing while leaving the decision with the user (Part 11 AI voice). |
| Classification | Data Submitter · Future AI-Routed Intake (2.5.12) · Non-AI and AI entry boundary (2.10.12): both paths stay available. |
| Variants | Current (supported): onboarding Auto Fill suggestions (accept/edit), document extraction into AI field for Create Payment Request (Draft until confirmed). Defined but Future: intake routing, possible duplicate warning, unresolved required information list, processing/failure of batch intake. All AI values: AI field states Suggested → Accepted → Edited → Unresolved; no AI colour; user confirms before submit. |
| Information hierarchy | Document → extracted fields (marked) → unresolved fields first → confirm. |
| Composition | Document-first form (15.3d) + AI field + Inline alert for duplicates. |
| Screen structure | Invoice_Kwok.pdf ▸ Supplier: Kwok Transport Ltd (suggested · Accept) ▸ Amount: HK$6,000.00 (suggested) ▸ Due date: — (please add) ▸ [Submit for payment] disabled until confirmed. |
| Responsive | Same as 15.3. |
| Theme | No special AI colour; icon + label ‘Suggested’. |
| States | Processing, suggested, accepted, edited, unresolved, failed (enter manually). |
| Accessibility | Suggested state announced; accept is an explicit button. |
| Content guidance | ‘Minty read this from the invoice. Check it before you submit.’ |
| Existing screens | Sales Setting Auto Fill (45:208). |
| Do / Do not | Do not: auto-submit AI values. |
| Figma composition | AI field component. |
| Implementation | Keep extraction confidence server-side; never hide manual entry. Future items must not become current authority before validation. |

## Module and screen-family patterns

### 15.15 Daily Closing and Daily Report (Petty Cash)

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific · Petty Cash · Approved · 1.0. Justification: cash reconciliation (expected vs counted, discrepancy note, previous-day gate) cannot be expressed by 15.9 alone. |
| Purpose | Product Goal: accurate operational records, reconciled cash, auditability. User Perceived Goal: “Finish today’s work and go home.” Completion outcome: Daily Report submitted and sent to Xero. |
| Classification | Data Submitter (preparation) · Daily Summary Reviewer (report) · Scheduled Operational · Work Coordination → Execution → Verification → Operational Review · Mobile (>95%). |
| Variants | a Launch page (Action Dashboard, 15.6). b Stages: Addition to Drawer · Sales · Expenses · Cash Count · Close. c Individual entry: expense = document-supported form in a full-screen sheet (phone) / Drawer (computer). d Cash count & discrepancy: optional ‘Cash taken for bank deposit’ first, then counted cash (calculator by notes and coins), then Check (Expected / Counted / Difference); any difference needs a reason before Save & Next. e Work Verification (Close): read-only summary of all stages with Edit links, recalculated totals, warnings; one action ‘Submit Daily Report’. f Submitted report: 15.7. g Report history: 15.4b. h Delayed/incomplete: gate banner on launch (‘Finish Sun 4 Oct first’) + Continue; edit after submission reopens stages with an Editing banner. |
| Information hierarchy | Per stage: the task’s fields and running total → difference/attention → Save & Next. Close: totals → differences → documents count → submit. |
| Composition | Workflow header + stage form + stage summary + actions (not sticky). |
| Screen structure | See Figma ‘15.15 · Daily Closing launch’ and ‘15.15 · Cash Count’ (Light/Dark). |
| Responsive | Phone primary; computer = 720 centred column of the same stages (no separate desktop workflow, 2.7.3). |
| Theme | Difference warning uses Warning tone; ‘short/over’ in text, not red numbers alone. |
| States | Not started, in progress, Draft, gate-blocked, difference unresolved, submitted, edited after submission, offline. |
| Accessibility | Calculator rows have labels per denomination; totals live region polite. |
| Content guidance | ‘Expected in drawer’, ‘Counted’, ‘Difference’, ‘HK$20.00 short’; never ‘Error’. |
| Existing screens | 02 Opening → Addition to Drawer (rename); 05 Bank Deposit + 05a Fix Negative Balance → Cash Count section + gate message; 06 Cash Count + calculator preserved; Ending → Close (replace with verification); 08 Report Submitted → Outcome state. |
| Do / Do not | Do not: show KPIs/trends inside the workflow. Do not: let a sticky bar cover amount fields. |
| Figma composition | Phone frames 430; stage frames named ‘15.15 · Stage · &lt;name>’. |
| Implementation | Expected cash = opening + additions + cash sales − cash expenses − bank deposit (assumption A15-01). Gate: previous report finalised and ending balance confirmed. |

### 15.16 Payment Request — Requester

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific · Payment Request · Approved · 1.0 |
| Purpose | Product Goal: payment controls, no duplicate/excess payment. User Perceived Goal: “Make sure the vendor gets paid correctly.” |
| Classification | Data Submitter (Payment Requester) · Triggered Operational · Work Execution · Mobile ~70% / Desktop ~30%. |
| Variants | Initial list/entry: same list as Treasury with role-aware defaults (My requests chip first, Draft and Returned surfaced). Create: document-first or form-first (15.3c/d), Supplier picker (‘Add new supplier’ last), amount, invoice/due dates, account code (if role allows). Capture: Camera capture/upload. Review before submission: Description rows + document + ‘Submit for payment’. Submitted detail: summary-first (status, paid so far, history). Draft resumption: ‘Open draft’ row action + Draft pill. Follow-up: Returned → Page banner with reason + ‘Edit and resubmit’. |
| Information hierarchy | Before submission: required info → document → missing items → submit. After: status → payment progress → submitted info (2.8.3). |
| Composition | 15.3 + 15.13 + 15.5a. |
| Screen structure | New payment request ▸ [Add invoice photo or PDF] ▸ Supplier ▸ Invoice amount ▸ Invoice date · Due date ▸ Description ▸ More details (collapsed) ▸ [Submit for payment] / Save as draft. |
| Responsive | Phone: capture first; computer: document preview right. |
| Theme | As 15.3. |
| States | Draft, submitted (Payment Requested), partially paid, paid, returned, voided. |
| Accessibility | As 15.3/15.5. |
| Content guidance | Status names exactly: Draft, Payment Requested, Partially Paid, Paid, Returned, Voided. |
| Existing screens | 01 PaymentRequestModal (884:2723) → full form page/sheet; 03 Draft Modal (681:16882) → Draft row + Continue. |
| Do / Do not | Do not: create a new supplier automatically from extraction. |
| Figma composition | Desktop 1440 + phone 430 frames. |
| Implementation | Duplicate check on supplier + amount + invoice date (Future warning, 15.14). |

### 15.17 Payment Request — Treasury processing

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific · Payment Request · Approved · 1.0. Justification: partial payments, return, void and bulk processing. |
| Purpose | Product Goal: pay correctly once, record it auditable. User Perceived Goal: “The necessary payments have been processed accurately.” |
| Classification | Payment Processor · Work Coordination / Execution · Triggered Operational · Desktop ~60% / Mobile ~40% · Easy view / Table view Differentiate within one experience (2.10.10). |
| Variants | Easy view (default, Record rows, next action per row). Table view (Table row, Compact, sortable, Nested payment rows, Bulk action bar). Work queue = status chips. Individual review = Detail 15.5c (document and record). Payment recording = Drawer (Pay in full \| Part payment, amount, date, paid by, bank slip optional, ‘Record HK$…’). Partial payment = same Drawer, amount < unpaid, unpaid-after shown live. Completion = Toast + status update. Return = Secondary action, reason required (Confirmation modal Standard). Void = overflow → Confirmation modal Destructive. Professional high-volume = Table view + bulk mark paid with count and total. |
| Information hierarchy | Requests needing attention → amount unpaid → due date → document → action. |
| Composition | List (15.4a) ↔ Detail (15.5c) ↔ Drawer for recording (never expanding rows). |
| Screen structure | See Figma ‘15.17 · Treasury · Easy view’ and ‘Review & record payment’ (Light/Dark). |
| Responsive | Mobile: Record row cards; Record payment opens full-screen sheet; Table view not offered below 768 (toggle hidden). Standard/Wide: as Figma. |
| Theme | As 15.4/15.5. |
| States | Status × action matrix: Payment Requested → Record payment, Return, Void; Partially Paid → Record payment, View payments, Void last payment; Paid → View payments; Returned → View (requester edits); Draft → (requester only); Voided → View. |
| Accessibility | Drawer focus trap, Esc closes with unsaved-change confirm. |
| Content guidance | ‘Record payment’, ‘Return to requester’, ‘Void payment’, ‘Unpaid after this payment: HK$0.00’. |
| Existing screens | 03d–03k inline row expansion (422:5404…) → Replace with Drawer; mascot panel (839:1236) → retire; Table view (839:1405) → refine; Bank slip overlay → File card in Drawer. |
| Do / Do not | Do not: put characters next to money tasks. |
| Figma composition | Drawer = 480 wide, elevation/overlay effect, overlay/scrim token (Part 13: 48% Light / 64% Dark). |
| Implementation | Server rejects payment above unpaid amount; void reverses Xero entry (assumption A15-03). |

### 15.18 Onboarding shell

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific (setup workflow shell) · cross-module · Approved · 1.0. Justification: 2.9.10 hybrid container. |
| Purpose | Product Goal: correct setup (modules, Xero, accounts, people). User Perceived Goal: “Make Minty work.” |
| Classification | Owner/Setup lead · mixed modes · Configuration · Desktop + Mobile · Preserve shell, Converge step content with Settings. |
| Variants | Welcome/Basic information → Select modules (Feature selection with price) → Invite people → Connect Xero → module setup (Sales methods, Account codes, Contacts, Payment settings — only for chosen modules) → All set (Outcome) → transition into regular use (first launch page). Save & resume on every step; Auto Fill suggestions (15.14). |
| Information hierarchy | Step title → why it matters (one line) → fields → Back / Save & Exit / Save & Next. |
| Composition | App bar ‘Getting started’ → Step progress (top, desktop) → left section list for sub-steps → 720 content column. |
| Screen structure | Getting started ▸ Step progress ▸ [Sales · Account Code · Others] \| Type of sales method ▸ Electronic (list) ▸ Delivery ▸ Opening balance ▸ [Back] … [Save & Exit] [Save & Next]. |
| Responsive | Mobile: step count ‘Step 5 of 8’ + current title instead of full progress bar. |
| Theme | Standard. |
| States | Path variants by module choice (A/B frames are data variants, not separate patterns). |
| Accessibility | As 15.9. |
| Content guidance | Minty voice allowed in intros, not in field labels. |
| Existing screens | 02 · Onboarding (41:19…), Subscription onboarding section (1347:23617). |
| Do / Do not | Do not: duplicate settings forms — reuse the same field components and order as Settings. |
| Figma composition | One shell frame + step content frames. |
| Implementation | Steps shown depend on selected modules; completing = Configuration completed (15.12g). |

### 15.19 Subscription and billing

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific · Subscription · Approved · 1.0. Existing state library (1347:25183) is preserved as the rule source. |
| Purpose | Product Goal: accurate subscription and billing transparency. User Perceived Goal: “Is what I pay right, and why was I charged?” |
| Classification | Payer/Owner · Commercial Decision / Commercial Detail Review · Desktop · Overview and Invoice detail Separate but connected (2.10.8). |
| Variants | Subscription overview (Decision Dashboard: current position per entity, modules, next bill). Module/plan selection & comparison (Selection 15.8c with price). Trial-ending treatment (Page banner Info → Warning 3 days before). Change confirmation (Confirmation modal names module and amount, ‘every button that costs money asks first’). Billing details & payment methods (forms). Billing history/Invoices (Historical list). Invoice detail (Detail summary-first, PDF). Cancellation/downgrade confirmation (Destructive modal with date effective). Transfer (two-party: Minty sends, Ms Lemon receives). |
| Information hierarchy | Current position → what changes and when → amount → confirm. |
| Composition | As 15.6b / 15.4b / 15.5a. |
| Screen structure | Subscriptions ▸ Olive & Vine Limited: Petty Cash (Active) · Payment Request (Trial · ends 12 Oct) ▸ Next bill HK$… on 1 Nov ▸ [Manage]. |
| Responsive | Mobile list of entities; modals become sheets. |
| Theme | Standard. |
| States | 36 module-status combinations (05·A) map to Status pill + summary text; failures (06·B) map to 15.10. |
| Accessibility | Prices read with currency and period. |
| Content guidance | Always name the module and the amount on money buttons. |
| Existing screens | 07 · Subscription sections 01–11. |
| Do / Do not | Do not: mix operational KPIs here (2.10.7). |
| Figma composition | Reuse existing state library; rebuild cards with Module chip, Status pill, Description row. |
| Implementation | Proration rules owned by billing service (out of design-system scope). |

### 15.20 Settings and People & Access

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific (administrative area) · Approved · 1.0 |
| Purpose | Product Goal: correct configuration and secure access. User Perceived Goal: “Change this setting / let this person in.” |
| Classification | Owner/Admin · System Configuration and People & Access (Separate groups, 2.10.6) · Desktop. |
| Variants | Settings landing: Sidebar SETTINGS group → three areas: Business setup (Entity details, Xero connection, Account mapping, Petty Cash settings, Payment settings), People & Access (Users, invitation, user detail, roles), Subscription — module status only (which modules are active for this entity, with a link to the Subscription module). The Sidebar keeps Subscription as its own top-level item (Part 6 §6.11); plans, billing and invoices live there (15.19). Configuration management = grouped forms (15.3b) with Save per section. Xero connection = status card + Reconnect (integration recovery 15.10f). User list = Administrative list with User row + Role badge + status. Invitation = Drawer form (email, role, entities) → Toast ‘Invitation sent’. User detail / role management = Detail h + Edit role Drawer; Remove = Destructive modal. |
| Information hierarchy | Area → section → fields; People: name, role, status, entities. |
| Composition | Standard header → Filter chips as in-page tabs (D14-06) only inside an area → content. |
| Screen structure | People & Access ▸ [Invite person] ▸ Search people · (All) (Invited) ▸ User rows. |
| Responsive | Mobile: Settings list → area page; Drawers become sheets. |
| Theme | Standard. |
| States | Xero not connected (gate for invite — ‘Invite blocked’ screen becomes banner + action), invited/pending, removed. |
| Accessibility | As 15.4/15.3. |
| Content guidance | ‘Invite person’, ‘Remove from Olive & Vine Limited’. |
| Existing screens | 05 · Settings (83:29, 84:68, 84:217, 86:156, 87:222), Bill settings (/settings) → one Settings destination. |
| Do / Do not | Do not: put Users as a pill next to Petty Cash settings. |
| Figma composition | Desktop 1440 with right Sidebar. |
| Implementation | Role changes enforced server-side (A14-04). |

### 15.21 Entry, account access and Entity context

| **Field** | **Specification** |
|---|---|
| Identity | Module-specific (navigation & access) · Approved · 1.0 |
| Purpose | Gets the user signed in and into the right Entity and module with the fewest steps. |
| Classification | All profiles · Context Selection / Feature Selection · Both devices. |
| Variants | a Account access: Login, Email code, Register, Find account, Reset password, Accept terms (gate), Legal document (reading), Awaiting approval (waiting), No permission (no access) — one centred card shell max 440 with Minty welcome on Login only. Single-Entity entry → skip selection. Multi-Entity selection → 15.8a. Entity switching → Entity selector in Sidebar (computer) / App bar menu sheet (phone); switching keeps the module if available. Single-module routing → go straight to it. Multiple-module selection → 15.8b. Locked module → 15.11e. Navigation: Sidebar right ≥ 1280; App bar menu sheet below. |
| Information hierarchy | One task per screen. |
| Composition | Centred card shell / Selection page. |
| Screen structure | (Minty) Welcome back ▸ Email ▸ [Send code] ▸ Use a password instead. |
| Responsive | Card full-width on phone. |
| Theme | Standard. |
| States | Code expired, too many attempts, account pending. |
| Accessibility | One-time code field supports paste and autocomplete=one-time-code. |
| Content guidance | Plain verbs: ‘Send code’, ‘Sign in’. |
| Existing screens | Login (183:325), Entity list (118:244), Module selection (118:317), Sidebar (364:224). |
| Do / Do not | Do not: show module selection when one module exists. |
| Figma composition | Card shell frame 440. |
| Implementation | Routing rules server-side; last Entity remembered. |

## 15.G Pattern accessibility checklist

- Landmarks: header (App bar), nav (Sidebar), main; one h1 per page = page or stage title.
- Reading order = visual order on every breakpoint; columns collapse in DOM order (document before record only where the document is primary).
- Focus order: header actions → filters → list/content → pagination; drawers and modals trap focus and return it to the trigger.
- Status announcements: Saving status, upload progress, toasts and totals in polite live regions; blocking errors assertive.
- Error navigation: error summary at the top of forms with links to fields when more than one error exists.
- Touch: 44 px targets; whole Record row tappable on phone; no hover-only actions.
- Reflow: content usable at 320 px width and 200% zoom without horizontal scroll (except Table view, which is hidden below 768).

## 15.H Migration plan for current screens

- **Wave 1 — shell:** App bar, right Sidebar, Page header and action hierarchy on all screens (removes 4 header and 9 button implementations).
- **Wave 2 — Replace items:** Payment Request workspace (Drawer for record payment, Description rows, no characters by rows); Petty Cash launch page (Action Dashboard); Close stage (Work Verification).
- **Wave 3 — Daily Closing stage names** (Addition to Drawer · Sales · Expenses · Cash Count · Close) with Bank Deposit inside Cash Count (D15-05).
- **Wave 4 — Refine** remaining screens with v2 components; retire Report list; then delete the legacy variable collection and deprecated components (Part 14 14.J).
- Dark mode screens follow after launch (Part 13 owner decision); patterns are already theme-neutral.

## 15.I Visual examples

- UI file → page “15 · Pattern Library — 7 Oct 2026” → board “Part 15 · Pattern inventory” (3128:186): layers, migration summary and six Current → Issue → Recommended findings with current-screen thumbnails.
- Same page → representative screens built only from library components, Light (top row) and Dark (bottom row): 15.17 Treasury Easy view (3129:994 / 3133:670), 15.17 Review & record payment with Drawer (3130:537 / 3133:693), 15.15 Daily Closing launch (3132:291 / 3133:723), 15.15 Cash Count with optional bank deposit and difference (3133:364 / 3133:740).
- Dark versions are the same frames with the Semantic collection set to Dark — no separate design.

## Appendix A — Decisions derived from existing authority

| **ID** | **Decision** | **Source** |
|---|---|---|
| D15-01 | Nine archetypes with approved variants are the base of all patterns; the mapping table (15.C) uses only Part 4 archetype names, and finer differences are expressed by pattern numbers | Part 4 4.4, 4.17 |
| D15-02 | Work Coordination (launch) and Operational Review (Daily Report) are separate pages | Part 2 2.10.1 |
| D15-03 | Work Verification (Close) is a stage, separate from the finalised report | Part 2 2.10.2–2.10.3 |
| D15-04 | Easy view and Table view share records, statuses and filters; Table view is a density choice | Part 2 2.10.10, D14-16 |
| D15-05 | Daily Closing has five stages; Bank Deposit becomes an optional section at the start of Cash Count | Handoff 7 Oct, Parts 2/12 latest, owner “추천대로” 7 Oct 2026 |
| D15-06 | Settings separates Business setup and People & Access inside one destination | Part 2 2.10.6 |
| D15-07 | Subscription overview and Invoice detail are separate but connected | Part 2 2.10.8 |
| D15-08 | Sticky action bars are not the default | Part 3 §3.12, Part 5 §5.11.1 |
| D15-09 | Supporting-document weight depends on workflow (supporting vs equal-review) | Part 8 §8.3.1, §8.7 |
| D15-10 | No Business Monitor / Monitoring dashboard in current design | Part 2 2.4.6, Part 4 4.5.1 |

## Appendix B — Professional decisions made by Claude

| **ID** | **Decision** | **Alternatives · reason · effect** | **Confidence** |
|---|---|---|---|
| D15-11 | Record payment opens in a 480 Drawer from list or detail | Inline row expansion (current), separate page. Drawer keeps list context, isolates money input, works for partial payments; replaces 8 current frames. | High |
| D15-12 | Read-only record facts use Description rows, never disabled inputs | Disabled inputs (current). Improves scanning and contrast; edit becomes explicit. | High |
| D15-13 | Page-level creation is a header Primary; floating + buttons retired | FAB (current on Users, Entity list). Consistent placement; no overlap with right Sidebar. | High |
| D15-14 | Destructive actions only in overflow + Destructive modal | Danger buttons beside Primary (current). Prevents accidental deletes. | High |
| D15-15 | Forms max 720, selection 640, lists fill to 1200 | Full-width forms. Readability on 1440+ screens. | Medium |
| D15-16 | Toasts bottom-left of Main on computer | Bottom-right (conflicts with right Sidebar), top-centre. | Medium |
| D15-17 | Workflow header = App bar + Step progress in a 70px wrapper | Change Step progress component height. Avoids a library change now; component fix logged for Stage 4. | Medium |
| D15-18 | Table view hidden below 768 px | Horizontal scrolling tables on phone. Part 2 2.4.4 forbids shrinking dense tables. | High |
| D15-19 | Single-option Selection pages are skipped | Always show. Fewer steps; Part 4 selection should reduce uncertainty. | High |

## Appendix C — Preference-based decisions (resolved 7 Oct 2026)

| **ID** | **Selected** | **Alternative · affected · reversibility · owner review** |
|---|---|---|
| P15-01 | Minty greeting on the Petty Cash launch page (small, conditional) | Kept as recommended (owner, 7 Oct 2026). Petty Cash home only; reversible. |
| P15-02 | Amount shown in money button labels (“Record HK$4,800.00”) | Kept as recommended (owner, 7 Oct 2026). Payment Request, Subscription; reversible. |

## Appendix D — Assumptions

| **ID** | **Assumption · why reasonable · effect if wrong · how to verify** |
|---|---|
| A15-01 | Expected cash = opening + additions + cash sales − cash expenses − bank deposit. Standard drawer reconciliation. If wrong, the Check block formula changes, not the layout. Verify with the Petty Cash calculation in code. |
| A15-02 | Confirmed (owner, 7 Oct 2026): cash for the bank is taken out before counting, so the deposit section stays at the start of Cash Count. |
| A15-03 | Voiding a payment reverses the Xero entry automatically. Current void flow implies it. If not, the void modal must say what to do in Xero. Verify with development. |
| A15-04 | Requester and Treasury use the same Payment Request route with role-aware views. Single route in code. Verify with development. |
| A15-05 | Admin screens are staff-only tools outside customer guidelines. Routes /admin. Verify with the product owner later (low priority). |

## Appendix E — Conflicts and unresolved evidence

| **ID** | **Conflict** | **Handling** |
|---|---|---|
| C15-01 | Part 2 lists Bank Deposit as a stage in 2.5.4 but not in 2.6.1 | Resolved by D15-05; correct Part 2 in Stage 4 |
| C15-02 | Part 5 breakpoint 1200 (Standard) vs Sidebar fixed at ≥ 1280 (Part 14) | Both kept: 1200–1279 shows Sidebar as sheet |
| C15-03 | Navigation model Part 1 (Subscriber) vs Part 6 (Minty) | Subscriber view kept as Detail; resolve in Stage 4 |
| C15-04 | Current code still uses Opening / Deposit / Ending stage routes | Migration wave 3 |
| C15-05 | Pagination component default shows page 2 active | Cosmetic; fix in library during Stage 4 |
| C15-06 | Step progress component is 10 px tall while labels extend below | Wrapper workaround (D15-17); fix component in Stage 4 |
| FV15-01 | Future validation · Report consumption: do business-review experiences (people reviewing information others produced, e.g. an owner reading Daily Reports or a Shared Report) need a visual treatment distinct from workflow-oriented, producer experiences? Evidence: Shared Report View and the producer vs consumer distinction in the Existing UI Design Intent Recovery Audit. | Validate together with the future Dashboard — Monitoring variant (Part 4). Not a current pattern; no structural change. |
| FV15-02 | Future validation · Supplier-first Treasury view: Treasury users appear to think in suppliers, while Easy view rows represent individual payment requests (Stage 2 assessment; the audit lists “When was this supplier paid last?” among the information needed). | Explore supplier-grouped rows, expandable supplier summaries and supplier-level outstanding balances before introducing AI-based prioritisation (15.14). Exploration topic, not a current requirement. |

## Appendix F — Questions for the Product Owner (answered 7 Oct 2026)

| **Type** | **Question** | **Recommendation** |
|---|---|---|
| Approval required | Approve Part 15 v0.9 as the pattern standard for screen migration? | Approved |
| Preference review | P15-01 and P15-02 — look at the Figma screens; keep both? | Both kept |
| Business-rule clarification | A15-02: is cash for the bank always taken out before counting? | Yes — confirmed |
| Low-priority confirmation | A15-05: Admin screens stay outside the guideline? | Yes — accepted with the recommendation |

## Appendix G — Recommended approval

**Approved as drafted on 7 Oct 2026** (owner answer: “approve as recommended”), including P15-01, P15-02, A15-02 and A15-05. Stage 4 (whole-package review of Parts 1–15) is next.

Part 15 · Minty Pattern Library · v1.1 · Approved 7 Oct 2026
