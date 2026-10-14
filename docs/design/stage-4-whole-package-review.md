<!-- Mirror of "Stage 4. Final Whole-Package Review.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

# Minty Design Guidelines — Stage 4

# Final Whole-Package Review of Parts 1–15

**Version 1.1 · Approved · 7 October 2026**

Scope: Parts 1–6 and 8–15, the Master Guide (v0.3), the Existing UI Design Intent Recovery Audit, the Development Instructions (§19), the team library (digitalisation’s team library) and the UI file FINAL UI/UX, including page 15 · Pattern Library. Part 7 (Actions and Commanding) is Deferred in the Master Guide; its scope is temporarily covered by the Part 14 Button rules and Part 15.2. QA follows the user flows against Parts 13–15; no separate QA instruction document applies (S4-12).

Method: every document was read in full and compared with the Figma library (54 components, 3 v2 variable collections, 13 text and 2 effect styles) and with the UI file (component usage measured per page). Findings resolved with the Product Owner on 7 Oct 2026 have already been applied and are marked Done.

## 1. Executive summary

The package is coherent and usable. Parts 13–15 faithfully implement the product intent of Parts 1–12: business before system, one primary action, calm tone, accounting-safe flows, Minty as a friendly presence outside money tasks, and Easy view / Table view as one experience with two densities. No Product Goal or UX Boundary from Parts 1–12 was lost.

The review found 14 contradictions, 4 duplications, 6 missing rules, 3 missing components (all future or rule-level), 3 missing patterns, 6 accessibility gaps and 7 Figma or migration risks. Nine items were corrected on 7 Oct 2026 (Parts 11, 13, 14, 15 → v1.1; Step progress and Pagination rebuilt, published and pulled into the UI file). The remaining corrections are text edits to Parts 1–12 and the Master Guide, plus small library additions. None changes an approved decision.

**Outcome:** approved by the Product Owner on 7 Oct 2026 (“추천대로”). All corrections R-01 to R-12 are applied; R-13 is closed (S4-12). The package is now the authoritative standard for screen migration.

## 2. Strengths of the completed package

- Clear authority chain: Parts 1–12 govern meaning, Part 13 visuals, Part 14 components, Part 15 composition; conflicts default to the latest owner decision and are logged.
- One executable source of truth: Minty v2 variables (Primitives, Semantic Light/Dark, Dimension), 13 text styles and 2 effect styles; product screens never use raw hex.
- Strong convergence: 9 button, 4 field, 3 status-badge and 4 header implementations reduced to single components with documented replacements.
- Brand and action are separated (Minty Primary #54D3DA for identity, Minty Action #3CBCC3 for primary CTAs), with the white-label contrast exception documented and safeguarded.
- Status grammar is single and text-led (soft background + deep ink; Info = Payment Requested / Submitted), so no state relies on colour alone.
- Every one of the 57 routed screens is classified with the Part 2 record, mapped to a Part 4 archetype and given a migration decision (Preserve 2 · Refine 49 · Replace 3 · Retire 1 · Out of scope 2).
- Money safety is built into components (Amount input limits, Drawer for payment recording, overflow + Destructive modal for void) rather than left to screens.
- Character rules protect the product: Minty is the default, second characters only in two-party moments, never in tables, fields or money errors.

## 3. Contradictions

| **ID** | **Where** | **Contradiction** | **Resolution · status** |
|---|---|---|---|
| C4-01 | Part 13 §13.14, App. D C-04 | Sentence said Primary = #54D3DA with deep ink, contradicting D-02 | Aligned with D-02 · Done (v1.1) |
| C4-02 | Part 13 §13.3 principle 4 vs 7 | ‘Brand teal means action’ vs ‘brand and action are separate’ | Principle 4 rewritten · Done |
| C4-03 | Part 13 status tones | ‘Submitted’ was Success (report) and Info (Payment Request) | Info in every module (S4-03) · Done |
| C4-04 | Part 15.20 vs Part 6 §6.11 | Subscription appeared to sit inside Settings | Two meanings clarified (S4-02) · Done in Part 15; Part 6 sentence to add |
| C4-05 | Part 15.17 vs Part 13 token | Drawer scrim 32% vs overlay/scrim 48%/64% | Token value applies · Done |
| C4-06 | Part 14 Step vs Part 13 §13.5 | Label minimum 11px vs 12px | 12px · Done |
| C4-07 | Part 15.C vs Part 4 | Archetype column used names not in Part 4 | Part 4 names only (S4-05) · Done |
| C4-08 | Part 13 A-07, Part 15 D15-08/09, 15.1 | Legacy Part 12 cited as authority | Re-sourced to Parts 2, 3, 5, 8 · Done |
| C4-09 | Part 11 §11.30 | Text described UI translation; owner meaning is country accounting terms | Rewritten · Done |
| C4-10 | Part 13 counts | 53 primitives / 57 paint styles vs library 56 / 56 | Counts follow library · Done |
| C4-11 | Part 1 §1.14.1 vs Part 6 §6.2 | Navigation starts at ‘Subscriber’ vs ‘Minty’ | Open — wording proposed in §11 (R-01) |
| C4-12 | Part 2 §2.5.4, Part 3 §3.16, Part 9 §9.19, Part 8 §8.2 | Bank Deposit as a stage; ‘Ending Summary’ | Open — D15-05 wording (R-02 to R-04) |
| C4-13 | Part 5 §5.11.2 | ‘Small Desktop’ but ‘avoid copying desktop / richer cards before tables’; 1200 vs 1280 | Open — rewrite (R-05); 1200–1279 = Sidebar as sheet (C15-02) |
| C4-14 | Master Guide v0.3 | Chapter numbers (12 Visual, 13 Components, 14 AI/Figma), statuses and Part 4 coverage outdated | Open — v0.4 (R-06) |

## 4. Duplications

- Part 4 and Part 12 both define archetypes. Resolved by Part 12’s ‘Legacy Reference’ label; Parts 13–15 now cite only Part 4.
- Part 4 Archetype Audit Results classifies User List as an Operational List; Part 4 and Part 15 classify it as Administrative List. Mark the Audit Results as superseded by Part 4 (R-07).
- Spacing tokens are listed in Part 5 (space-4) and Part 13 (space/4) with the same values but different notation. Part 5 should point to Part 13 for values and state the mapping: Figma space/4 = CSS --space-4 = Part 5 space-4 (R-08).
- Filter chip is used both for list filters and Settings tabs (D14-06). One component is acceptable, but the semantics differ — see missing rule M-01.

## 5. Missing rules

| **ID** | **Missing rule** | **Recommendation** |
|---|---|---|
| M-01 | Filter chip used as in-page tabs has no tab semantics | Part 14 Filter chip: when it switches page sections, render as role=tablist/tab with arrow-key navigation; otherwise it is a toggle button group |
| M-02 | Touch target for Pagination on tablet (36px) vs ‘44 on touch’ | Pagination targets 44 on touch devices, 36 allowed on pointer-only desktop |
| M-03 | Current Step indicator uses #54D3DA (1.79:1 on white) | Current step must also be marked by bold label and aria-current (already built); add rule so the cue is never removed |
| M-04 | Wide Computer (≥1600) is defined in Part 5 but not in Part 13/15 | Content keeps max widths (form 720, list 1200); extra space becomes margin, never wider columns |
| M-05 | Settings ‘Subscription’ area vs Subscription module | Add to Part 6 §6.10: Settings shows module status only and links to Subscription for plans and billing |
| M-06 | Status labels ‘Approved (draft)’ in Parts 14–15 | On Stage 4 approval, change to ‘Approved’ (Instructions §18) |

## 6. Missing components

- Tabs — not needed as a separate component if M-01 is adopted (Filter chip with tab semantics).
- Chart — Part 8 §8.19 defines chart rules but no component exists. Future: build when a chart is first required (Analytics Stage 2).
- Notification centre / in-app notification list — Part 10 §10.39 describes channels; current screens use Page banner and Toast. Future.

## 7. Missing patterns

- Delayed and overdue work reminders across modules (Part 10) are covered only by Page banner inside Petty Cash; a cross-module reminder pattern is a future matter.
- Dark-mode screen patterns exist for 4 representative screens only; full coverage follows the after-launch dark-mode implementation (D-24).
- Analytics and Exception Investigation (Part 2 B.7) remain Future and must not drive current design — correctly excluded.

## 8. Accessibility gaps

| **ID** | **Gap** | **Severity** | **Action** |
|---|---|---|---|
| AX-01 | White label on Minty Action 2.29:1 | Documented owner exception | Keep safeguards (14px+ SemiBold, verb labels, never sole carrier of information) |
| AX-02 | Current step colour 1.79:1 | Low (bold label + aria-current present) | Rule M-03 |
| AX-03 | Pagination 36px on touch tablets | Medium | Rule M-02; component Size property |
| AX-04 | Filter chip as tabs lacks tab semantics | Medium | Rule M-01 |
| AX-05 | Focus state not built as Figma variants for Checkbox, Radio, Switch, Filter chip, Nav item, Menu item, Record row; Button lacks Pressed/Processing | Medium (spec exists in 14.E) | Add variants or one shared ‘Focus ring’ overlay documented in each component |
| AX-06 | Dark-mode review done for 5 components and 4 screens only; 200% zoom not yet tested on screens | Low until dark launch | Include in migration QA (V-10, V-13) |

## 9. Figma implementation risks

- Resolved 7 Oct: Step progress and Pagination had collapsed to 10px height; rebuilt, published, and the 6 instances on 15 · Pattern Library updated (Step 68px, Pagination 36px, page 1 active). The 70px wrapper (D15-17) is no longer required.
- Resolved 7 Oct: Document viewer highlight bound to brand/primary at 15%; Focus variants added (Checkbox, Radio, Switch, Filter chip, Nav item, Menu item, Record row); Button Pressed and Processing added; Pagination Size = Pointer | Touch; Components page re-flowed with no overlaps.
- Resolved 7 Oct: legacy library pages renamed ‘(legacy · deprecated 6 Oct 2026)’.
- Resolved 7 Oct: nine exploration pages moved below an Archive divider in the UI file and prefixed ‘Archive ·’.
- Component count: the library has 54 components (39 sets + 15 single); use this number in all documents.

## 10. Current-screen migration risks

| **Area** | **Measured state (7 Oct 2026)** | **Risk** | **Mitigation** |
|---|---|---|---|
| Petty Cash | 217 instances, all legacy local components | High volume; stage names outdated | Wave order per Part 15; rename stages first |
| Payment Request | 84 legacy local instances; inline row expansion | Replace screen (Drawer) | Build from 15.17 frames |
| Onboarding | 408 legacy local instances | Largest volume | Preserve shell; swap components step by step |
| Subscription | 1,955 legacy-library + 80 local instances | Legacy deletion would break screens | Delete legacy collection only after this page migrates |
| Code routes | Opening / Deposit / Ending (C15-04) | Docs and code differ | Migration wave 3 |
| Petty Cash dashboard | Being redefined | Pattern may change | Treat calendar as example (D-21) |

## 11. Required corrections

| **ID** | **Document** | **Change** | **Status** |
|---|---|---|---|
| S4-01–08 | Parts 11, 13, 14, 15 | Items C4-01 to C4-10 (see §3) | Done — v1.1, 7 Oct 2026 |
| S4-09 | Library + UI file | Step progress and Pagination rebuilt; published; instances updated | Done — 7 Oct 2026 |
| R-01 | Part 1 §1.14.1, Part 6 §6.2 | One model: Minty → Entity → Module → Work → Record. The Subscriber (paying account) owns Entities but is not a navigation step; it appears only in Subscription and Profile | Done — 7 Oct 2026 |
| R-02 | Part 2 §2.5.4; close B.3, B.4, B.5 | Remove Bank Deposit from stage examples; close open matters resolved by Parts 14–15 | Done — 7 Oct 2026 |
| R-03 | Part 3 §3.16, Part 9 §9.19 | ‘Sales, Expenses, Cash Count (incl. optional Bank Deposit)’ | Done — 7 Oct 2026 |
| R-04 | Part 8 §8.2 | ‘Daily Report Ending Summary’ → ‘Close (Work Verification)’ | Done — 7 Oct 2026 |
| R-05 | Part 5 §5.11.2 | Align ‘Avoid’ list with Small Desktop; add 1200–1279 Sidebar sheet note | Done — 7 Oct 2026 |
| R-06 | Master Guide → v0.4 | Chapter map 1–15, statuses, Part 7 Deferred, Part 12 legacy | Done — 7 Oct 2026 |
| R-07 | Part 4 Audit Results | Mark superseded by Part 4 | Done — 7 Oct 2026 |
| R-08 | Part 5 §5.8 | Point to Part 13 for token values and notation | Done — 7 Oct 2026 |
| R-09 | Part 6 §6.10 | Rule M-05 | Done — 7 Oct 2026 |
| R-10 | Part 14 | Rules M-01, M-02, M-03; statuses → Approved (M-06) | Done — 7 Oct 2026 |
| R-11 | Library | Focus/Pressed variants (AX-05); bind Document viewer fill; label legacy pages | Done — 7 Oct 2026 |
| R-12 | UI file | Archive divider for exploration pages | Done — 7 Oct 2026 |
| R-13 | Development QA checklist | Not needed: QA follows user flows against Parts 13–15; no separate instruction document (S4-12) | Closed — 7 Oct 2026 |

## 12. Recommended future matters

- Develop Part 7 (Actions and Commanding) from Part 14 Button and Part 15.2 rather than from scratch.
- Chart component when Analytics Stage 2 begins; Notification centre when push and in-app reminders are scoped.
- Dark-mode screen implementation after launch, with per-component dark review.
- Replace the Primary CTA contrast exception if the brand is revisited (e.g. darker Minty Action with white label).
- Code Connect mappings between library components and front-end components once migration starts.

## 13. Final approval checklist

| **Check (Instructions §19.2)** | **Result** |
|---|---|
| Parts 13–15 implement Parts 1–12; no Product Goal or UX Boundary lost | Pass |
| Valid user differences preserved (Easy/Table view, guided/professional, mobile/desktop) | Pass |
| Token names consistent; states defined once | Pass (notation mapping R-08) |
| Light and Dark share the same semantics | Pass |
| Density applied consistently (Comfortable default, Compact only in Table view) | Pass |
| Every current screen supported by a pattern | Pass (57/57) |
| Feedback, Draft, failure and recovery states covered | Pass |
| No unnecessary tokens or duplicate components | Pass |
| Accessibility measurable and achievable | Pass (AX-02 to AX-05 resolved; AX-06 in migration QA) |
| Junior contributor and AI can pick the right component/pattern | Pass (Master Guide v0.4) |
| Owner confirmation: navigation model wording (R-01) | Confirmed 7 Oct 2026 |
| Owner confirmation: pagination 44px on touch (M-02) | Confirmed 7 Oct 2026 |

## 14. Final decision, assumption and preference register

### 14.1 Registers carried forward

| **Part** | **Decisions** | **Assumptions** | **Preferences** |
|---|---|---|---|
| Part 13 v1.1 | D-01 – D-25 | A-01 – A-08 | P-01 – P-05 (resolved) |
| Part 14 v1.1 | D14-01 – D14-17 | A14-01 – A14-06 | P14-01 – P14-03 (resolved) |
| Part 15 v1.1 | D15-01 – D15-19 | A15-01 – A15-05 | P15-01 – P15-02 (resolved) |

### 14.2 Stage 4 decisions (owner, 7 Oct 2026)

| **ID** | **Decision** |
|---|---|
| S4-01 | D-02 stands: Primary CTA = Minty Action #3CBCC3 + white label; stale text removed |
| S4-02 | ‘Subscription’ has two meanings: top-level Sidebar module (plans, billing, invoices) and the third Settings area (module status only) |
| S4-03 | ‘Submitted’ = Info (blue) in every module |
| S4-04 | Where numbers differ, Part 13 values apply (scrim 48%/64%, minimum text 12px) |
| S4-05 | Pattern mapping uses Part 4 archetype names only; differences are expressed by pattern numbers |
| S4-06 | Legacy Part 12 is never cited as authority |
| S4-07 | Part 11 §11.30: English-only interface; ‘localization’ = country accounting terms |
| S4-08 | Documents follow the library counts (56 primitives, 56 legacy paint styles, 54 components) |
| S4-09 | Step progress and Pagination corrected, published and pulled into the UI file |
| S4-10 | Navigation model: Minty → Entity → Module → Work → Record; Subscriber owns Entities but is not a navigation step (R-01) |
| S4-11 | Pagination targets 44 on touch devices, 36 on pointer-only desktop (M-02) |
| S4-12 | QA always follows the user flows and checks screens against Parts 13–15 (Part 13 §13.19); no other instruction document governs the design |

### 14.3 Assumptions added in Stage 4

- A4-02 Accepting library updates in the UI file by swapping instances preserves overrides (verified on 6 instances).
