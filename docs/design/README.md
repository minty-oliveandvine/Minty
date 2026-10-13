# Minty design guidelines (UX & user flow rules)

These rules cover every Minty frontend: the three Next.js apps, Flask's templates and the marketing site.
The owner writes and approves them as Word files. The files here are **read-only Markdown mirrors**,
made by `scripts/design_docs_to_md.py`.

- **Do not edit them here.** When a Part is revised, re-run the script on the new Word file:
  `python -I scripts/design_docs_to_md.py "<…>/Part NN. ….docx" docs/design/<file>.md`
- The source folder is not in git, nor are the screenshots, Figma exports, drafts, archive and AI-test receipts.

## Authority order
1. **Parts 1–12** set meaning: product goals, users, mental modes, work types, UX boundaries,
   archetypes, hierarchy, navigation, data, forms, feedback, writing.
2. **Part 13** sets how it looks: colour, type, spacing, shape, icons, mascot, tokens, themes and
   accessibility.
3. **Part 14** sets the reusable components.
4. **Part 15** sets how components are assembled into pages and workflows.
5. **The Stage 4 review** (7 Oct 2026) corrects across all of them. Its decisions are S4-01…S4-15,
   summarised in the handoff, §5.

When they conflict, the earlier layer wins on meaning and the later layer on implementation.
Part 12 is a legacy reference and is never used as evidence (S4-06).
Part 7 is deferred: Part 14's Button and Part 15.2 (action hierarchy) stand in for it.
QA follows the user flow and checks screens against Parts 13–15 by token and component name.
The checklist for that is Part 13 §13.19.

## Files
| File | Source | Version / status |
|---|---|---|
| [part-13-visual-design-system.md](part-13-visual-design-system.md) | Part 13. Minty Visual Design System | v1.1 · Approved 7 Oct 2026 |
| [part-14-component-library.md](part-14-component-library.md) | Part 14. Minty Component Library | v1.1 · Approved 7 Oct 2026 |
| [part-15-pattern-library.md](part-15-pattern-library.md) | Part 15. Minty Pattern Library | v1.1 · Approved 7 Oct 2026 |
| [stage-4-whole-package-review.md](stage-4-whole-package-review.md) | Stage 4. Final Whole-Package Review | v1.1 · Approved 7 Oct 2026 |
| [part-11-writing-content-voice.md](part-11-writing-content-voice.md) | Part 11. Writing, Content & Minty Voice | v1.1 Draft · 7 Oct 2026 (current) |
| [part-04-page-workflow-archetypes.md](part-04-page-workflow-archetypes.md) | Part 4. Page & Workflow Archetypes | 1.0 Draft (current; the nine archetypes Part 15 maps to) |
| [part-10-feedback-guidance-status.md](part-10-feedback-guidance-status.md) | Part 10. Feedback, Guidance & System Status | 1.0 Draft (current) |
| [existing-ui-intent-audit.md](existing-ui-intent-audit.md) | Minty Existing UI Design Intent Recovery Audit | v0.1 (current) |
| [part-12-archetypes-legacy.md](part-12-archetypes-legacy.md) | Part 12. Page and Workflow Archetypes | **Legacy**: historical reasoning only |
| [development-brief-parts-13-15.md](development-brief-parts-13-15.md) | Part 13–15 Development Instructions for Claude | The brief Parts 13–15 were built to (complete) |
| [handoff-2026-10-07.md](handoff-2026-10-07.md) | Design System Handoff, 7 Oct 2026 after Stage 4 | Korean; progress, Stage 4 decisions, Figma ids |

## Not yet here (the newer versions are still to be supplied)
The copies on hand are older than the versions the handoff names as current, so they were left out.
Add each one when its current file arrives.

| Document | Version on hand | Current version (per the handoff) |
|---|---|---|
| Master Guide (Minty Design Guidelines) | 0.3 | **0.4** |
| Part 1 Product and Design Foundations | Draft 1.0 | **Draft 1.1** (navigation model) |
| Part 2 User, Mental Model, Work and UX Foundations | Draft 2.0 | **Draft 2.1** |
| Part 3 Minty Experience Principles | 1.0 | **v1.1** |
| Part 5 Information Hierarchy, Layout and Cross-System Consistency | Draft 1.0 | **Draft 1.1** (tablet, the 1200–1279 sidebar sheet; tokens sourced from Part 13) |
| Part 6 Navigation & Information Architecture | 1.0 | **v1.1** (two meanings of "Subscription", navigation model) |
| Part 8 Data Presentation & Visualization | 1.0 | **v1.1** |
| Part 9 Forms, Input & Workflows | 1.0 | **v1.1** |

Part 7 is deferred. *Part 4 Archetype Audit Results* has been replaced by Part 4 and is kept for the record only.

## Figma
- **Library** `DLW6MbAfaydNsKqWiHn9ob` ("digitalisation's team library").
  - Variables: Primitives 56, Semantic Light/Dark 48, Dimension 24.
  - Components: 54.
  - The pages are "Minty v2 · Foundations" and "Minty v2 · Components".
- **UI file** `WLoKoO5mXK6hB3JOIW6qI4`.
  - The pattern library is on page `15 · Pattern Library`; the layout map is on `13b · Page layouts by Part 4 archetype` (draft).
  - Its screen pages still use the old components.

## Where the code differs today
These gaps are tracked in CLAUDE.md, under *Known gaps → Design system*.

- **Breakpoints.**
  - The code uses Tailwind's defaults: 640 / 768 / 1024 / 1280.
  - Part 5 §5.12 and Part 15 use Mobile 0–767, Tablet 768–1199, Computer 1200–1599 and Wide ≥ 1600, and fix the right Sidebar only at ≥ 1280.
  - Until screen migration settles this, CLAUDE.md's values stay the rule in code (owner's decision, 2026-10-13).
- **Icons.** Part 13 adopts Material Symbols **Rounded** (D-20), but all three Next apps import `material-symbols/outlined.css`.
- **Components.** No screen in code has moved to the Parts 13–15 components and tokens yet. That migration is the handoff's recommended next step.
