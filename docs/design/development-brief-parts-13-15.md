<!-- Mirror of "Part 13 - 15 Development Instructions for Claude.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

## Minty Design System Development Brief

### Instructions for Claude: Parts 13–15

### 1. Project Background

You are joining an established product-design project called **Minty**.

Minty is an AI-powered financial operations platform for SMEs. It helps business owners and operational users capture financial information, preserve supporting documents, complete routine financial work, and make accounting-safe decisions without requiring them to understand accounting systems in detail.

A substantial product and UX framework has already been developed.

The existing documentation covers areas including:

- product and UX foundations;
- Product Goals and User Perceived Goals;
- UX user profiles;
- Mental Modes;
- Work Types;
- UX Boundaries;
- Experience Principles;
- Page and Workflow Archetypes;
- information hierarchy;
- layout and responsive behaviour;
- navigation and information architecture;
- data presentation;
- forms, input and workflows;
- feedback, guidance and system status;
- writing, content and Minty’s voice.

Screen-level work has also been undertaken, including:

- screen inventory and evidence collection;
- Stage 0: Evidence Register;
- Stage 1: Intent Recovery;
- Stage 2: UX Critique;
- current-screen and archetype audits.

Parts 2–12 and the screen audit materials represent the existing product and UX foundation. They must be studied before any new practical design-system recommendation is made.

The remaining work is to translate that foundation into a practical and maintainable design system.

This work will be completed through:

- **Part 13: Visual Design System**
- **Part 14: Component Library**
- **Part 15: Pattern Library**

Do not redesign Minty from the beginning.

Do not treat this as a new-product discovery exercise.

Do not replace previous decisions with generic SaaS conventions.

Your task is to operationalise, standardise and visually implement the established Minty product and UX intent.

## 2. Purpose of This Project

The purpose of Parts 13–15 is to create the authoritative practical design framework for:

- updating existing Minty screens;
- creating new Minty screens;
- creating future modules;
- building and maintaining the Minty Figma library;
- implementing reusable frontend components;
- reviewing visual and interaction consistency;
- supporting AI-assisted screen generation;
- onboarding future designers and developers;
- and preventing future contributors from having to reinterpret Minty’s UX foundations.

The completed package should establish a clear sequence:

Plain Text

Parts 1–12

Product and UX foundations

↓

Part 13

Visual foundations and design-system architecture

↓

Part 14

Reusable component specifications

↓

Part 15

Reusable screen and workflow patterns

↓

Existing-screen updates and new-screen creation

Show more lines

The final package should allow a future contributor to answer:

1. What should a Minty experience accomplish?
1. Which structural pattern should it use?
1. What should it look and feel like?
1. Which components should be used?
1. How should those components be assembled?
1. How should the experience adapt across devices and themes?
1. How should accessibility and consistency be verified?

## 3. Minty’s Product Position

Minty should be understood as:

A friendly operational assistant that helps SME business owners complete financial work correctly and with less effort.

Minty is:

- business-owner-oriented;
- practical;
- operational;
- accounting-safe;
- supportive;
- approachable;
- calm;
- trustworthy;
- low-reading-effort;
- and designed around work completion.

Minty is not primarily:

- accounting software for accountants;
- an ERP system;
- an audit system;
- a corporate banking portal;
- a financial analytics dashboard;
- a general productivity application;
- or a technology showcase.

Minty should feel like:

“Let me help you finish this properly.”

It should not feel like:

“Let me teach you accounting.”

It should not feel like:

“Here is the database record you need to maintain.”

It should not feel like:

“Here is a professional finance system that you need to learn.”

## 4. Primary and Secondary Users

### 4.1 Primary experience priority

The visual and interaction system should be optimised primarily for:

- SME business owners;
- shop owners;
- operational managers;
- non-accounting users;
- staff performing routine financial work;
- and occasional users who want to complete the task quickly.

These users may:

- skim rather than read;
- have limited patience for instructions;
- be unfamiliar with accounting language;
- work while distracted;
- postpone tasks that look complicated;
- and prioritize practical business outcomes over system accuracy terminology.

### 4.2 Secondary experience priority

Minty must also support:

- accountants;
- finance staff;
- Treasury users;
- high-volume processors;
- and professional users requiring greater information density.

Professional users may require:

- tables;
- comparison;
- filtering;
- sorting;
- supporting-document review;
- multiple visible statuses;
- batch processing;
- and compact information density.

However, professional-use requirements must not cause the whole Minty system to become accounting-first or enterprise-like.

Where guided and professional experiences genuinely require different presentation, retain shared:

- terminology;
- statuses;
- business rules;
- tokens;
- component foundations;
- feedback behaviour;
- and visual identity.

## 5. Governing Product and UX Principles

Claude must use the existing documents rather than relying only on the following summary. However, these principles are particularly important.

### 5.1 Work first, accounting second

Minty should be organised around what users are trying to complete.

Users are trying to:

- finish Daily Closing;
- submit a Payment Request;
- pay a supplier;
- review what happened;
- find a previous report;
- invite a team member;
- configure Minty;
- or understand a charge.

The creation of an accounting record is usually a supporting mechanism, not the user’s perceived outcome.

### 5.2 Product Goal constrains; User Perceived Goal guides

The User Perceived Goal should normally determine:

- visible hierarchy;
- language;
- primary information;
- primary action;
- and disclosure order.

The Product Goal should determine:

- required information;
- validation;
- controls;
- warnings;
- restrictions;
- evidence;
- and confirmation.

### 5.3 Make completion easier than postponement

Minty should reduce:

- unnecessary reading;
- unnecessary typing;
- unnecessary searching;
- unnecessary categorisation;
- unnecessary decisions;
- uncertainty;
- and fear of making a mistake.

The correct action should feel easier than leaving the task unfinished.

### 5.4 Low reading effort

A user should be able to understand the main purpose and next action by scanning:

- headings;
- labels;
- values;
- statuses;
- and buttons.

Long explanations should not be required to understand ordinary Minty work.

### 5.5 Business language first

Use practical business language wherever possible.

Translate accounting and system requirements into practical questions and consequences.

Do not simplify terminology where simplification would become inaccurate.

### 5.6 Clarity before efficiency

Greater density is permitted where it materially supports professional or high-volume work.

However, efficiency should not be used to justify an interface that business owners cannot understand.

### 5.7 Business rules create restrictions

Do not impose workflow restrictions merely because an interface is divided into steps.

Restrict navigation or completion only where a confirmed Product Goal or business rule requires it.

### 5.8 Cards summarise; pages explain

Cards should help users recognise an item and decide whether to open or act on it.

Cards should not become miniature Detail Pages.

### 5.9 Few important KPIs

Do not create additional KPI cards merely because data or space is available.

A KPI should communicate priority, not decorate the screen.

### 5.10 Immediate visibility does not always mean urgency

A problem may need to be visible immediately without using alarmist colour, language or interruption.

Feedback prominence should be based on:

- consequence;
- responsibility;
- effect on current completion;
- risk to core business data;
- and whether user action is required.

### 5.11 Mobile and desktop are related, not identical

Maintain the same:

- meaning;
- terminology;
- status definitions;
- business rules;
- component system;
- and visual language.

Adapt:

- presentation;
- density;
- visible supporting information;
- filters;
- cards versus tables;
- and document presentation.

### 5.12 Reuse before creating

The preferred sequence is:

Plain Text

Reuse an approved solution

↓

Adapt an approved solution

↓

Create a new solution only when necessary

Show more lines

A different module, designer or implementation history does not by itself justify a new visual pattern, component or screen structure.

## 6. Current Visual Direction

The agreed high-level visual direction is:

**Fresh, bright and approachable operational assistance**

Minty should visually feel:

- fresh;
- bright;
- friendly;
- clean;
- modern;
- spacious;
- approachable;
- helpful;
- and operational.

Minty should remain sufficiently professional and controlled for consequential financial activity.

Professional reliability should come from:

- clear information hierarchy;
- accurate language;
- predictable components;
- appropriate confirmation;
- accessible states;
- strong data presentation;
- and consistent interaction behaviour.

Friendliness should come from:

- helpful guidance;
- thoughtful defaults;
- whitespace;
- clear progression;
- supportive feedback;
- appropriate illustrations;
- Minty mascot use;
- and low reading effort.

Friendliness should not rely on:

- excessive colour;
- decorative gradients;
- oversized illustrations;
- excessive animation;
- excessive mascot use;
- childish wording;
- cartoon-like component styling;
- or making every component highly rounded.

### 6.1 Theme requirement

Minty should support both:

- light mode;
- and dark mode.

The themes must use a semantic token architecture.

Dark mode should not be produced by simply inverting the light-mode colours.

Both themes must preserve:

- hierarchy;
- accessibility;
- status meaning;
- visual identity;
- and component behaviour.

## 7. Claude’s Role

For this project, Claude should act as:

**Senior Design System Architect and Senior UI/UX Designer**

Claude is responsible for driving professional design-system decisions.

Claude should:

- review the entire available document set;
- review screen inventories and audit evidence;
- inspect current Figma screens;
- recover Minty’s existing visual DNA;
- distinguish strong existing patterns from accidental inconsistency;
- standardise reusable decisions;
- establish practical visual foundations;
- define reusable components;
- define reusable screen patterns;
- prepare Figma-ready guidance;
- and document decisions clearly enough for later implementation.

Claude should not expect the junior working with Claude to make senior design decisions.

The junior’s role is primarily to:

- provide the requested files and screen access;
- communicate approvals or product-owner comments;
- help organise outputs;
- and execute agreed Figma work with Claude’s assistance.

The junior should not be expected to decide:

- colour-system architecture;
- typography hierarchy;
- token architecture;
- component-state modelling;
- accessibility standards;
- responsive behaviour;
- Figma component architecture;
- or design-system governance.

Claude should make professional recommendations in these areas.

## 8. Documentation Authority and Evidence Order

Claude should use the following authority order.

### 8.1 First: adopted product and UX documents

Use relevant adopted Parts 1–12 as the governing conceptual authority.

Read the relevant sections in full before applying a rule.

Do not rely only on headings, contents pages or brief summaries.

### 8.2 Second: validated audit decisions

Use Stage 0–2 audit outcomes and confirmed decision records as screen-specific evidence.

Distinguish between:

- confirmed intent;
- recovered probable intent;
- current implementation;
- critique;
- future concept;
- and unresolved matter.

### 8.3 Third: existing screens

Use current screens to identify:

- established visual identity;
- reusable visual patterns;
- component candidates;
- current variations;
- inconsistencies;
- and implementation constraints.

Existing screens are evidence, but they are not automatically authoritative.

A repeated inconsistency should not become a standard merely because it appears several times.

### 8.4 Fourth: mature external design systems

External design-system practice may be used where Minty’s documents and screens do not provide sufficient implementation guidance.

External systems must not override Minty’s established product identity, hierarchy or UX rules.

### 8.5 Conflict handling

Where evidence conflicts:

1. Identify the conflict.
1. Determine which document or decision is more authoritative.
1. Make the safest professional recommendation.
1. Record the assumption.
1. Continue the deliverable.
1. Present the conflict in the end-of-part review.

Do not stop the entire project merely because a local conflict exists.

## 9. Documentation Quality Benchmark

The completed package should have a level of structure, detail and maintainability comparable to a mature professional design system such as the **Microsoft Fluent Design System**.

This comparison is a documentation-quality benchmark.

It is not a direction to make Minty resemble Microsoft products.

The reference applies to areas such as:

- documentation structure;
- content organisation;
- token architecture;
- component documentation;
- state documentation;
- accessibility guidance;
- pattern documentation;
- implementation guidance;
- governance;
- versioning;
- and maintainability.

The reference does not establish Minty’s:

- colour palette;
- typography;
- component appearance;
- product personality;
- navigation philosophy;
- information hierarchy;
- interaction philosophy;
- or visual tone.

Claude may also consult other mature design systems for documentation and design-system engineering practices.

However, Minty’s existing documents, screens, user context and product identity remain authoritative.

The objective is:

Plain Text

Learn from the structure and completeness of mature design systems

Show more lines

not:

Plain Text

Make Minty visually resemble another design system

Show more lines

If Claude materially adopts a structure or solution from an external design system, record:

- the external reference;
- what was adopted;
- why it was useful;
- and how it was adapted for Minty.

## 10. Required Project Sequence and Approval Gates

Parts 13–15 must be completed sequentially.

Do not develop all three parts simultaneously.

### Stage 1: Part 13

1. Review relevant existing documents, screens and audit evidence.
1. Prepare a concise Part 13 evidence and gap summary.
1. Draft Part 13.
1. Provide visual examples and Figma-ready specifications.
1. Provide the Part 13 decision and assumption log.
1. Stop and request approval for Part 13.

Do not begin Part 14 until Part 13 has been approved.

### Stage 2: Part 14

After Part 13 approval:

1. Use the approved Part 13 foundations.
1. Review existing screen components.
1. recover and rationalise the component inventory;
1. draft Part 14;
1. provide visual examples and Figma-ready specifications;
1. provide the Part 14 decision and assumption log;
1. stop and request approval for Part 14.

Do not begin Part 15 until Part 14 has been approved.

### Stage 3: Part 15

After Part 14 approval:

1. Use the approved Parts 13 and 14.
1. Review current screens and workflows.
1. Identify recurring screen and workflow compositions.
1. Draft Part 15.
1. Provide visual examples and Figma-ready pattern specifications.
1. Provide the Part 15 decision and assumption log.
1. Stop and request approval for Part 15.

### Stage 4: Whole-package review

After Parts 13–15 have each been approved, revisit the complete package.

Review:

- Parts 1–12;
- Part 13;
- Part 14;
- Part 15;
- current Figma screens;
- screen inventories;
- and confirmed screen-audit findings.

Check for:

- contradiction;
- duplication;
- inconsistent terminology;
- missing components;
- missing patterns;
- gaps between conceptual and practical guidance;
- inaccessible specifications;
- theme inconsistencies;
- unresolved design decisions;
- and implementation risks.

Then prepare a final package review and recommended corrections.

## 11. Part 13: Minty Visual Design System

### 11.1 Objective

Part 13 defines:

What Minty looks and feels like, and how its visual foundations are implemented and governed.

Part 13 should translate Parts 1–12 into a practical visual system.

Part 13 should define the foundations required to build components.

It should not contain the complete specification for every individual component. That belongs in Part 14.

It should not define every complete screen composition. That belongs in Part 15.

### 11.2 Required Part 13 contents

#### 13.1 Purpose, scope and authority

Define:

- the purpose of Part 13;
- the intended readers;
- the relationship with Parts 1–12;
- matters governed by Part 13;
- matters outside Part 13;
- authority and conflict rules;
- implementation responsibilities;
- and document status.

#### 13.2 Evidence and current visual DNA

Review current Minty screens and document:

- visual characteristics that already support Minty’s identity;
- visual characteristics that conflict with the intended direction;
- recurring visual patterns;
- accidental variations;
- components that appear reusable;
- and current accessibility or consistency risks.

Classify findings as:

- **Preserve**
- **Refine**
- **Replace**
- **Open Matter**

Include representative existing-screen examples wherever possible.

#### 13.3 Visual personality and design principles

Define Minty’s practical visual personality.

Include governing principles covering areas such as:

- fresh and bright without visual noise;
- friendly through assistance rather than decoration;
- business information before system information;
- one clear visual path;
- clarity before density;
- calm presentation of financial work;
- greater restraint as consequence increases;
- consistency without forcing identical layouts;
- and professionalism without becoming corporate or institutional.

For each principle include:

- definition;
- reason;
- practical design consequence;
- visual example;
- and anti-pattern.

#### 13.4 Colour system

Define:

- brand palette;
- supporting palette;
- neutral palette;
- surface palette;
- text palette;
- border palette;
- interaction colours;
- focus colours;
- selection colours;
- link colours;
- overlay colours;
- data-visualisation colours where currently required;
- and document-viewer background treatment.

Define semantic colour roles for:

- success;
- information;
- attention;
- warning;
- error;
- destructive action;
- disabled state;
- processing;
- selected state;
- and AI-related states where visual distinction is justified.

Provide:

- primitive colour tokens;
- semantic colour tokens;
- light-theme mappings;
- dark-theme mappings;
- contrast requirements;
- status-colour usage rules;
- colour combinations to avoid;
- and examples using existing Minty screens.

Do not use colour alone to communicate meaning.

Do not treat every incomplete item, discrepancy or business issue as an error.

#### 13.5 Typography

Define:

- recommended type family or families;
- licensed and technical availability;
- fallback fonts;
- English support;
- numeric and currency treatment;
- tabular figures;
- character and line-height considerations;
- wrapping and truncation;
- alignment;
- localisation implications;
- and minimum readable sizes.

Define semantic text styles for at least:

- display text;
- page title;
- section title;
- subsection title;
- body;
- body strong;
- small body;
- form label;
- helper text;
- caption;
- button;
- link;
- status;
- table header;
- table cell;
- KPI label;
- KPI number;
- ordinary amount;
- and modal title.

Provide:

- size;
- weight;
- line height;
- letter spacing where appropriate;
- mobile treatment;
- tablet treatment;
- computer treatment;
- and light/dark-theme considerations.

#### 13.6 Spacing foundations

Use and validate the existing four-pixel spacing foundation.

Define:

- primitive spacing scale;
- semantic spacing roles;
- page gutters;
- section spacing;
- component-internal spacing;
- form spacing;
- card padding;
- table density;
- overlay spacing;
- and touch spacing.

Define and illustrate:

- comfortable density;
- standard density;
- compact density.

Explain when each density may be used.

Professional compactness must remain an approved exception, not the system default.

#### 13.7 Shape and border system

Define:

- corner-radius scale;
- component-radius mapping;
- border widths;
- divider treatment;
- focus-ring treatment;
- selected-state outlines;
- input borders;
- card borders;
- overlay borders;
- and full-radius or pill usage.

Prevent:

- excessive pill-shaped components;
- unnecessary nested rounded containers;
- inconsistent radii;
- and card-heavy interfaces.

#### 13.8 Surface and elevation system

Define:

- application background;
- page surface;
- content surface;
- raised surface;
- selected surface;
- feedback surfaces;
- document surfaces;
- overlay surfaces;
- and disabled surfaces.

Define elevation levels for:

- embedded content;
- raised cards;
- sticky or floating controls;
- menus and popovers;
- drawers;
- and modals.

Explain when to use:

- surface contrast;
- borders;
- shadows;
- or no visual enclosure.

Document separate light- and dark-theme behaviour.

#### 13.9 Iconography system

Define:

- selected icon family or construction approach;
- visual style;
- stroke weight;
- filled versus outline use;
- corner treatment;
- standard sizes;
- optical alignment;
- icon-to-label spacing;
- semantic meaning;
- navigation icons;
- action icons;
- status icons;
- information icons;
- file and document icons;
- and module icons.

Define:

- when icons require text;
- when icon-only controls are permitted;
- accessible naming;
- tooltip requirements;
- theme behaviour;
- and prohibited ambiguous uses.

#### 13.10 Illustration system

Define:

- illustration purposes;
- visual style;
- line and shape treatment;
- colour usage;
- complexity;
- composition;
- background treatment;
- relationship with interface content;
- responsive cropping and scaling;
- and dark-mode treatment.

Cover at least:

- onboarding;
- empty states;
- first-time guidance;
- recoverable problems;
- successful completion;
- and appropriate educational content.

Illustrations should serve communication, not fill empty space.

#### 13.11 Minty mascot system

Treat the Minty mascot as a governed product asset rather than ordinary decoration.

Define:

- approved roles;
- approved contexts;
- restricted contexts;
- prohibited contexts;
- pose categories;
- direction of attention;
- relationship to text and actions;
- emotional range;
- size;
- placement;
- frequency;
- repetition limits;
- animation rules if animation is proposed;
- accessibility treatment;
- and light/dark-theme presentation.

Approved roles may include:

- welcome;
- guide;
- reassure;
- explain;
- encourage;
- and provide closure.

Mascot presence should generally reduce as financial or operational consequence increases.

#### 13.12 Motion and transition foundations

If Minty uses or is expected to use motion, define:

- motion principles;
- transition durations;
- easing categories;
- loading motion;
- state-change motion;
- overlay motion;
- progress motion;
- success motion;
- mascot motion;
- reduced-motion behaviour;
- and prohibited decorative motion.

Motion should clarify state or relationship rather than demonstrate technical sophistication.

If motion is not currently required, explicitly define the minimum future-ready foundation rather than omitting it silently.

#### 13.13 Design-token architecture

Define:

- primitive tokens;
- semantic tokens;
- component tokens;
- responsive tokens;
- theme mappings;
- density tokens;
- and platform-specific aliases if required.

At minimum cover:

- colour;
- typography;
- spacing;
- sizing;
- radius;
- border;
- elevation;
- opacity;
- icon size;
- motion;
- breakpoints;
- and interaction state.

Provide:

- naming convention;
- token hierarchy;
- examples;
- Figma variable representation;
- frontend-ready representation guidance;
- deprecation rules;
- and change-control rules.

#### 13.14 Theme architecture

Define:

- light theme;
- dark theme;
- possible future high-contrast support;
- semantic mapping;
- system-theme detection;
- manual theme choice where applicable;
- theme persistence;
- image and illustration treatment;
- chart treatment;
- supporting-document treatment;
- overlay treatment;
- and theme QA.

Do not create separate component systems for light and dark modes.

Use shared semantic meaning with theme-specific values.

#### 13.15 Responsive visual foundations

Reference the existing responsive rules and define visual-system implications for:

- mobile;
- tablet;
- standard computer;
- wide computer.

Include:

- breakpoint mapping;
- typography adaptation;
- gutter adaptation;
- density adaptation;
- card-to-table transition;
- document presentation;
- action grouping;
- overlay adaptation;
- and responsive token use.

#### 13.16 Accessibility foundations

Define the accessibility standard applicable to Minty.

At minimum cover:

- colour contrast;
- focus visibility;
- keyboard navigation;
- screen-reader naming;
- touch-target size;
- pointer-target size;
- text resizing;
- zoom;
- responsive reflow;
- error identification;
- status not communicated by colour alone;
- icon labelling;
- form instructions;
- modal focus management;
- table structure;
- reduced motion;
- low-reading-effort support;
- and appropriate cognitive accessibility considerations.

Specify measurable requirements wherever possible.

#### 13.17 Figma foundation architecture

Define the recommended Figma organisation for:

- foundation pages;
- variable collections;
- modes;
- styles;
- icons;
- illustrations;
- mascot assets;
- component pages;
- pattern pages;
- examples;
- accessibility documentation;
- experimentation;
- and deprecated assets.

Define:

- file structure;
- library structure;
- page naming;
- variable naming;
- style naming;
- publication rules;
- documentation placement;
- ownership;
- and versioning.

#### 13.18 Visual-system governance

Define:

- proposal process;
- review process;
- approval authority;
- publication;
- change documentation;
- versioning;
- deprecation;
- replacement;
- retirement;
- exception handling;
- accessibility review;
- theme review;
- and periodic audit.

#### 13.19 Part 13 validation checklist

Provide a reusable checklist for approving the visual fundamentals and later checking their application.

### 11.3 Required Part 13 outputs

Part 13 should include:

- a formal guideline document;
- a current-screen visual evidence summary;
- a visual direction board using existing screens where possible;
- light- and dark-theme colour specifications;
- typography specifications;
- spacing and density specifications;
- shape and elevation specifications;
- icon rules;
- illustration rules;
- mascot rules;
- accessibility requirements;
- token architecture;
- Figma foundation structure;
- visual examples;
- preserve/refine/replace examples;
- decision log;
- assumption log;
- preference log;
- and outstanding questions.

## 12. Part 14: Minty Component Library

### 12.1 Objective

Part 14 defines:

Which reusable interface building blocks exist in Minty, how they behave, and when they should be used.

Part 14 should transform the Part 13 foundations into Figma-ready and implementation-ready component specifications.

Part 14 must not become a simple screenshot catalogue.

It should define reusable, accessible and governed components.

### 12.2 Component-inventory procedure

Before finalising the Part 14 component list:

1. Inspect all current Minty screens.
1. Record every recurring component or component-like treatment.
1. Identify duplicate implementations.
1. Identify one-off treatments.
1. Compare them with the approved archetypes and patterns.
1. Determine whether each should be:
  1. preserved;
  1. converged;
  1. adapted;
  1. separated into variants;
  1. replaced;
  1. or retired.
1. Identify components required by approved future-ready states even if they do not yet exist.
1. Avoid creating components solely because another design system contains them.

### 12.3 Component levels

Organise the library into clear levels.

#### Foundations

Tokens and styles referenced from Part 13.

#### Primitives

Basic reusable interface elements.

#### Components

Reusable functional controls and information units.

#### Composite components

Small reusable assemblies with a clear recurring purpose.

#### Patterns

Do not include full screen patterns in Part 14. Those belong in Part 15.

### 12.4 Required component families

The final inventory should be evidence-led, but it should at minimum evaluate the need for the following families.

#### 14.1 Actions

Evaluate and specify:

- primary button;
- secondary button;
- tertiary or ghost button;
- destructive button;
- icon button;
- button with icon;
- Floating Action Button where justified;
- links;
- inline actions;
- menu actions;
- split button only if a validated need exists;
- and button groups.

#### 14.2 Form-field foundations

Specify:

- field wrapper;
- label;
- required indicator;
- optional indicator;
- helper text;
- validation message;
- character count;
- field status;
- prefix;
- suffix;
- and field-level actions.

#### 14.3 Text and numeric inputs

Evaluate and specify:

- text input;
- text area;
- number input;
- amount and currency input;
- percentage input where required;
- search input;
- password input if required;
- phone, email or identifier input where required;
- and read-only value display.

#### 14.4 Selection controls

Evaluate and specify:

- select;
- combobox;
- autocomplete;
- checkbox;
- radio button;
- switch or toggle;
- segmented control where justified;
- date input;
- date picker;
- date-range picker where justified;
- time input where required;
- and entity or business-context selection controls.

#### 14.5 File and supporting-document components

Evaluate and specify:

- upload control;
- camera capture;
- drag-and-drop area;
- selected file;
- uploading file;
- uploaded file;
- failed upload;
- file card;
- document preview;
- document viewer;
- multi-document list;
- extraction state;
- document-to-record relationship;
- and retry or replacement controls.

#### 14.6 Navigation components

Evaluate and specify:

- global navigation;
- mobile navigation;
- navigation item;
- module navigation;
- locked module treatment;
- Entity selector;
- module selector;
- back control;
- page context indicator;
- tabs where approved;
- internal Settings navigation;
- breadcrumbs only where justified;
- pagination;
- and responsive navigation behaviour.

#### 14.7 Page and section structure components

Evaluate and specify:

- standard page header;
- Record header;
- Workflow header;
- Report header;
- Selection header;
- compact header;
- section header;
- form section;
- content region;
- divider;
- accordion or expandable section;
- panel;
- and action area.

#### 14.8 Cards

Evaluate and specify:

- standard card;
- Record card;
- work-attention card;
- KPI card;
- summary card;
- selection card;
- module card;
- locked-module card;
- document card;
- empty-state card only if justified;
- and promotional or commercial card only if consistent with Minty’s principles.

Prevent cards from becoming default containers for every section.

#### 14.9 Lists and tables

Evaluate and specify:

- simple list;
- structured list row;
- mobile Record card list;
- Operational Table;
- Historical Retrieval Table;
- Administrative Table;
- table header;
- table row;
- selectable row;
- expandable row if justified;
- sorting;
- filtering;
- search;
- pagination;
- loading;
- empty results;
- row actions;
- and bulk actions.

Document:

- comfortable;
- standard;
- and compact density.

#### 14.10 Status and metadata

Evaluate and specify:

- Record status;
- workflow status;
- process status;
- integration status;
- invitation status;
- subscription status;
- status indicator;
- badge;
- tag;
- metadata group;
- audit information;
- and status history presentation.

Do not collapse business status, system processing state and validation feedback into one universal badge component.

#### 14.11 Feedback and guidance

Evaluate and specify:

- helper text;
- field feedback;
- inline alert;
- page banner;
- toast;
- temporary confirmation;
- success state;
- Draft feedback;
- loading indicator;
- skeleton;
- progress indicator;
- processing state;
- save state;
- upload state;
- retry state;
- and dedicated recovery state.

#### 14.12 Overlays and temporary surfaces

Evaluate and specify:

- Confirmation Modal;
- information modal where justified;
- drawer;
- mobile full-screen overlay;
- popover;
- tooltip;
- menu;
- dropdown;
- and contextual action menu.

Avoid placing substantial workflows or persistent Records inside modals.

#### 14.13 Data and summary components

Evaluate and specify:

- KPI display;
- amount display;
- outcome summary;
- comparison display;
- description list;
- data breakdown;
- timeline;
- progress summary;
- recommendation display;
- alert-summary display;
- and chart foundations only where a current validated need exists.

#### 14.14 User, access and identity components

Evaluate and specify:

- avatar;
- user identity;
- role display;
- invitation status;
- permission summary;
- access selection;
- and user-management row or card.

#### 14.15 Empty, first-use and completion components

Evaluate and specify:

- Empty State;
- no-results state;
- first-use state;
- success or completion state;
- no-access state;
- unavailable-module state;
- and Minty mascot composition within these states.

#### 14.16 AI-related components

Establish a restrained future-ready set only where supported by Minty’s roadmap.

Evaluate:

- AI processing state;
- extracted value;
- suggested value;
- uncertain value;
- user-confirmed value;
- conflicting result;
- unable-to-determine state;
- possible duplicate;
- AI recommendation;
- and user-correction action.

Do not introduce AI decoration that does not reduce user effort.

### 12.5 Required specification for every component

Each component specification must include:

#### Identity

- component name;
- component family;
- design-system status;
- owner;
- and version.

#### Purpose

- what the component does;
- which user need it supports;
- and which Product Goal constraints may apply.

#### When to use

- appropriate contexts;
- applicable archetypes;
- applicable Mental Modes;
- and applicable devices.

#### When not to use

- anti-patterns;
- overlapping components;
- and prohibited contexts.

#### Anatomy

- named sub-elements;
- required elements;
- optional elements;
- and content limits.

#### Variants

- approved variants;
- reason for each variant;
- and invalid variants.

#### Sizes and density

- available sizes;
- comfortable, standard or compact treatment;
- and minimum dimensions.

#### Interaction states

At minimum, where applicable:

- default;
- hover;
- focus;
- pressed;
- selected;
- disabled;
- read-only;
- expanded;
- collapsed;
- and drag or upload interaction.

#### Data and workflow states

Where applicable:

- empty;
- filled;
- Draft;
- incomplete;
- requires attention;
- submitted;
- completed;
- blocked;
- archived;
- processing;
- failed;
- retry available;
- AI-suggested;
- AI-uncertain;
- and user-confirmed.

#### Content rules

- label guidance;
- helper text;
- maximum recommended content;
- truncation;
- localisation;
- number and currency treatment;
- and relevant Part 11 guidance.

#### Behaviour

- interaction sequence;
- keyboard behaviour;
- pointer behaviour;
- touch behaviour;
- loading behaviour;
- error recovery;
- and state transition.

#### Responsive behaviour

- mobile;
- tablet;
- standard computer;
- wide computer;
- and any approved transformation into another presentation.

#### Theme behaviour

- light;
- dark;
- and high-contrast considerations where applicable.

#### Accessibility

- semantics;
- accessible name;
- focus order;
- keyboard support;
- screen-reader output;
- contrast;
- target size;
- error communication;
- and motion considerations.

#### Figma specification

- component name;
- variant properties;
- boolean properties;
- text properties;
- instance-swap properties;
- nested-component rules;
- auto-layout rules;
- token bindings;
- responsive resizing;
- and example instances.

#### Development notes

- behaviour that must be preserved;
- state mapping;
- semantic HTML or platform role where relevant;
- and implementation risks.

#### Examples

Include:

- correct use;
- incorrect use;
- light mode;
- dark mode;
- mobile;
- desktop;
- and existing-screen mapping where available.

#### Governance

- approved;
- experimental;
- deprecated;
- or retired.

### 12.6 Required Part 14 outputs

Part 14 should include:

- formal component-library guideline;
- audited component inventory;
- component rationalisation map;
- approved component taxonomy;
- full component specifications;
- Figma naming and property model;
- component-state matrix;
- responsive-component matrix;
- theme matrix;
- accessibility checklist;
- screen-to-component traceability;
- deprecated-component list;
- visual examples;
- decision log;
- assumption log;
- preference log;
- and outstanding questions.

## 13. Part 15: Minty Pattern Library

### 13.1 Objective

Part 15 defines:

How approved foundations and components are assembled into repeatable pages, workflows, states and responsive screen compositions.

Part 15 is the bridge between:

Plain Text

Part 13 visual foundations

+

Part 14 reusable components

↓

Actual Minty screens and workflows

Show more lines

Part 15 should not merely reproduce screenshots.

It should identify the reusable rule behind successful screen compositions.

### 13.2 Pattern-inventory procedure

Before finalising the pattern list:

1. Review all current screens and screen families.
1. Map each screen to:
  1. Product Goal;
  1. User Perceived Goal;
  1. primary UX User Profile;
  1. Mental Mode;
  1. Work Type;
  1. archetype;
  1. primary device;
  1. and UX Boundary decision.
1. Identify compositions that recur across modules.
1. Distinguish:
  1. general cross-product patterns;
  1. archetype patterns;
  1. module-specific patterns;
  1. state patterns;
  1. and one-off screen implementations.
1. Preserve valid UX boundaries.
1. Converge screen structures where no material boundary exists.
1. Retire accidental differences.
1. Do not create a pattern merely because a single screen currently exists.

### 13.3 Required pattern layers

Organise patterns into the following levels.

#### Cross-product composition patterns

Reusable across multiple modules.

#### Archetype implementation patterns

Practical implementations of approved Part 4 archetypes.

#### Workflow patterns

Reusable progression and completion structures.

#### State and recovery patterns

Empty, loading, error, Draft and completion compositions.

#### Module-specific patterns

Use only where the module has a validated requirement that cannot be expressed adequately through a general pattern.

### 13.4 Required cross-product patterns

Evaluate and specify at least the following.

#### 15.1 Page-header patterns

- standard page header;
- Record header;
- Workflow header;
- Report header;
- Selection header;
- compact header;
- and responsive action placement.

#### 15.2 Action hierarchy patterns

- page-level creation;
- Record-level action;
- workflow continuation;
- final submission;
- destructive confirmation;
- secondary actions;
- overflow actions;
- and mobile action adaptation.

#### 15.3 Form composition patterns

- simple Record Form;
- grouped Record Form;
- document-supported form;
- document-first form;
- guided owner form;
- professional dense form;
- Create and Edit relationship;
- and final review and submission.

#### 15.4 List composition patterns

- Operational List;
- Historical Retrieval List;
- Administrative List;
- mobile cards;
- desktop tables;
- search-first retrieval;
- filter-first queue processing;
- empty results;
- and bulk processing where justified.

#### 15.5 Detail-page patterns

- summary-first Detail Page;
- decision-oriented Detail Page;
- document-and-record review;
- guided owner detail;
- professional processing detail;
- supporting information disclosure;
- history;
- and administrative details.

#### 15.6 Dashboard patterns

- Action Dashboard;
- Decision Dashboard;
- Monitoring Dashboard;
- and any approved combined composition.

Avoid combining summary, navigation, reporting and work queues without a clear primary purpose.

#### 15.7 Report patterns

- outcome-first Report Page;
- KPI summary;
- breakdowns;
- supporting Records;
- supporting documents;
- administrative information;
- download and sharing;
- and responsive report presentation.

#### 15.8 Selection patterns

- Context Selection;
- Feature Selection;
- module selection;
- Entity selection;
- recommended option;
- locked capability;
- and responsive choice presentation.

#### 15.9 Workflow patterns

- operational workflow;
- setup or onboarding workflow;
- current-stage presentation;
- flexible section navigation;
- business-rule gate;
- save and resume;
- Work Verification;
- submission;
- and success transition.

#### 15.10 Feedback and recovery patterns

- field-level correction;
- section issue;
- page-wide issue;
- failed save;
- failed upload;
- integration problem;
- blocked completion;
- preserved Draft;
- retry;
- and dedicated recovery.

#### 15.11 Empty and no-result patterns

- first-use Empty State;
- no existing Records;
- no filtered results;
- no access;
- locked module;
- data not yet available;
- and future analytics unavailable.

#### 15.12 Completion patterns

- low-consequence save;
- Draft preserved;
- invitation sent;
- Payment Request submitted;
- Daily Report finalised;
- payment recorded;
- configuration completed;
- and consequential external confirmation where required.

#### 15.13 Supporting-document patterns

- supporting role;
- equal-review role;
- entry-point role;
- capture;
- extract;
- review;
- replace;
- retry;
- and desktop/mobile document presentation.

#### 15.14 AI-assisted patterns

Define only sufficiently supported patterns, such as:

- document intake;
- extraction;
- unresolved required information;
- suggestion;
- uncertainty;
- user correction;
- user confirmation;
- possible duplicate;
- and processing or failure.

Future concepts must be clearly labelled and must not become current design authority prematurely.

### 13.5 Required module and screen-family patterns

Claude should derive the final list from the current-screen inventory. At minimum, evaluate whether patterns are needed for the following areas.

#### Daily Report and Petty Cash

- work-coordination or launch page;
- Daily Closing;
- individual entry;
- cash count and discrepancy;
- Work Verification;
- final submission;
- submitted Daily Report;
- report history;
- report detail;
- and delayed or incomplete work.

#### Payment Request: Requester

- initial list or entry;
- Create Payment Request;
- supporting-document capture;
- review before submission;
- submitted-request detail;
- Draft resumption;
- and requester follow-up.

#### Payment Request: Treasury

- Easy View;
- Table View;
- work queue;
- individual review;
- document-and-record comparison;
- payment recording;
- partial payment where supported;
- payment completion;
- and professional high-volume processing.

Preserve the validated distinction between guided and professional processing where the UX Boundary requires it.

#### Onboarding

- welcome;
- Entity or context setup;
- module selection;
- configuration;
- People and Access;
- progress;
- save and resume where supported;
- completion;
- and transition into regular use.

#### Subscription and billing

- subscription overview;
- current position;
- module or plan selection;
- comparison;
- trial-ending treatment;
- change confirmation;
- billing history;
- invoice detail;
- and cancellation or downgrade confirmation.

#### Settings

- Settings landing or internal navigation;
- Configuration Management;
- Xero connection;
- account mapping;
- sales and payment settings;
- Entity settings;
- People and Access;
- user list;
- invitation;
- user detail;
- role management;
- and integration recovery.

#### Navigation and context selection

- single-Entity entry;
- multi-Entity selection;
- Entity switching;
- single-module routing;
- multiple-module selection;
- locked module;
- and mobile/desktop navigation.

Do not force a module-specific pattern where a cross-product pattern is sufficient.

### 13.6 Required specification for every pattern

Each pattern must include:

#### Identity

- pattern name;
- pattern level;
- applicable module or cross-product scope;
- status;
- and version.

#### Purpose

- user problem solved;
- Product Goal;
- User Perceived Goal;
- and completion outcome.

#### Classification

- primary UX User Profile;
- secondary profile if applicable;
- Mental Mode;
- Work Type;
- archetype;
- variant;
- primary device;
- and UX Boundary decision.

#### Entry and exit

- where the user comes from;
- entry conditions;
- expected next destination;
- completion destination;
- cancellation or exit;
- and resumption where relevant.

#### Information hierarchy

- Primary Information;
- Secondary Information;
- Supporting Information;
- Administrative Information;
- Primary Action;
- Secondary Actions;
- and required controls or validation.

#### Composition

- page regions;
- components used;
- component order;
- default disclosure;
- action placement;
- and optional regions.

#### Screen structure example

Provide a structured visual example, such as:

Plain Text

Page context

Page title and short guidance

Primary summary or current task

Information requiring attention

Main working section

Supporting information

Administrative information

Primary completion action

Show more lines

Do not use vague descriptions where a practical composition can be shown.

#### Responsive treatment

Define separately:

- mobile;
- tablet;
- standard computer;
- wide computer.

Explain:

- what remains visible;
- what becomes collapsed;
- what changes from card to table;
- how actions move;
- how supporting documents are presented;
- and how density changes.

#### Theme treatment

Define relevant light- and dark-theme concerns.

#### States

At minimum, where applicable:

- first use;
- empty;
- loading;
- Draft;
- incomplete;
- complete;
- requires attention;
- blocked;
- submitted;
- processing;
- failed;
- retry;
- no results;
- no access;
- and archived.

#### Accessibility

Include:

- reading order;
- focus order;
- headings;
- landmark structure;
- keyboard path;
- status announcements;
- error navigation;
- touch behaviour;
- and responsive reflow.

#### Content guidance

Include representative:

- headings;
- labels;
- helper text;
- primary actions;
- status wording;
- validation wording;
- empty-state wording;
- and completion wording.

Ensure examples follow Part 11.

#### Existing-screen comparison

Identify:

- closest existing screens;
- elements to preserve;
- elements to modify;
- elements to retire;
- and migration implications.

#### Do and do not examples

Provide visual and explanatory examples.

#### Figma composition guidance

Define:

- parent frame;
- layout grid;
- auto-layout direction;
- container width;
- nested components;
- responsive properties;
- example variables;
- and variant or component-set requirements.

#### Implementation guidance

Document:

- business-rule dependencies;
- required state data;
- responsive transformations;
- accessibility behaviour;
- and important exclusions.

### 13.7 Required Part 15 outputs

Part 15 should include:

- formal Pattern Library guideline;
- complete pattern inventory;
- screen-to-pattern mapping;
- approved cross-product patterns;
- archetype implementation patterns;
- workflow patterns;
- state and recovery patterns;
- justified module-specific patterns;
- mobile, tablet and desktop examples;
- light- and dark-theme examples;
- accessibility guidance;
- Figma composition instructions;
- migration mapping for current screens;
- visual examples;
- decision log;
- assumption log;
- preference log;
- and outstanding questions.

## 14. Working Autonomously and Minimising Questions

The junior working with Claude is not expected to have senior design expertise.

Claude should therefore avoid repeatedly asking questions such as:

- Which radius is preferred?
- Which spacing scale should be used?
- Which component naming system is preferred?
- How should focus states work?
- How should keyboard navigation work?
- Which accessibility standard should apply?
- Should semantic tokens be used?
- How should Figma variants be organised?

These are professional design-system decisions.

Claude should:

1. Review the documents and screens.
1. Make the strongest professional recommendation.
1. Record the decision.
1. Explain the reasoning.
1. Continue the work.

Claude should ask an immediate question only where work cannot responsibly continue, for example:

- a required file is inaccessible;
- two authoritative Product Goals conflict;
- a business rule materially changes the workflow;
- a legal or security requirement is unknown;
- or an irreversible structural decision cannot be estimated safely.

Otherwise, Claude should continue using its best professional judgement.

## 15. End-of-Part Questions and Decision Reporting

At the end of each part, Claude must provide the following sections.

### 15.1 Decisions made from existing authority

List decisions directly derived from:

- Parts 1–12;
- validated audit findings;
- approved screen intent;
- or existing confirmed business rules.

For each decision, identify the source.

### 15.2 Professional decisions made by Claude

List decisions Claude made because a practical design-system choice was required.

For each decision include:

- the decision;
- alternatives considered;
- reason for the recommendation;
- effect on Minty;
- and confidence level.

Examples may include:

- token architecture;
- component taxonomy;
- type scale;
- radius system;
- icon framework;
- state model;
- accessibility treatment;
- Figma property architecture;
- or responsive component transformation.

### 15.3 Preference-based decisions

Clearly identify decisions that are not objectively required and materially reflect visual or product preference.

For each include:

- selected option;
- realistic alternative;
- reason Claude selected the option;
- screens or modules affected;
- reversibility;
- and what the product owner should review.

Examples may include:

- brighter versus more muted brand colour;
- illustration style;
- mascot expression range;
- visual softness;
- font personality;
- or degree of visible brand colour.

### 15.4 Assumptions

List any assumptions made because the available evidence was incomplete.

For each explain:

- what was assumed;
- why it was reasonable;
- effect if incorrect;
- and how it should later be verified.

### 15.5 Conflicts or unresolved evidence

List:

- documents that appear inconsistent;
- screens that conflict with adopted principles;
- legacy patterns;
- and questions that could affect later work.

### 15.6 Questions for the product owner

Collect questions at the end rather than interrupting the junior throughout the work.

Classify each question as:

- **Approval required**
- **Preference review**
- **Business-rule clarification**
- **Future decision**
- **Low-priority confirmation**

Do not ask a question merely because several valid professional solutions exist.

Make a recommendation first.

### 15.7 Recommended approval

Conclude with one of:

- approve as drafted;
- approve subject to listed changes;
- seek product-owner decision on limited matters;
- or do not approve because of a specific material issue.

Then stop until approval is provided.

## 16. Visual Example Requirement

The product owner is not a designer and may not be able to evaluate an abstract written design decision reliably.

Accordingly, Claude should provide visual examples wherever practical.

Use:

- existing Minty screen excerpts;
- annotated screenshots;
- side-by-side comparisons;
- light- and dark-theme examples;
- mobile and computer variants;
- Figma component examples;
- Figma pattern examples;
- token swatches;
- typography specimens;
- state matrices;
- and structural wireframes.

For meaningful recommendations, show:

Plain Text

Current

↓

Issue

↓

Recommended treatment

↓

Reason

Show more lines

Where applicable, classify examples as:

- **Preserve**
- **Refine**
- **Replace**
- **Avoid**

Do not expect the product owner to make a choice based only on abstract terms such as:

- softer;
- more modern;
- stronger hierarchy;
- more contemporary;
- or more professional.

Show what the words mean visually.

## 17. Required Writing Style

The documentation must be suitable for:

- human designers;
- junior contributors;
- developers;
- product reviewers;
- and future AI retrieval.

Use:

- stable numbered headings;
- self-contained definitions;
- explicit rules;
- clear status labels;
- short practical examples;
- traceability;
- and consistent terminology.

Avoid:

- vague design commentary;
- trend-based language;
- unexplained designer terminology;
- generic UX advice;
- relying on large tables as the only source of a rule;
- and statements that cannot be implemented or reviewed.

Each governing rule should be understandable when retrieved independently, while still instructing the reader to review its surrounding section.

Examples should illustrate rules rather than replace them.

## 18. Status and Traceability

Each material rule, component and pattern should use an appropriate status, such as:

- **Confirmed**
- **Approved**
- **Draft**
- **Experimental**
- **Advanced**
- **Future**
- **Open Matter**
- **Deprecated**
- **Retired**

Each significant recommendation should identify whether it comes from:

- existing adopted guideline;
- validated screen audit;
- existing screen convention;
- accessibility requirement;
- external design-system practice;
- or Claude’s professional recommendation.

Do not silently convert a future concept into a current standard.

Do not silently convert a current implementation into an approved rule.

## 19. Final Whole-Package Review

After Parts 13–15 have been separately approved, perform a final review of the whole design-system package.

### 19.1 Review scope

Review:

- terminology across all Parts;
- classifications;
- archetype mappings;
- visual foundations;
- tokens;
- themes;
- components;
- states;
- patterns;
- accessibility;
- responsive behaviour;
- Figma architecture;
- governance;
- and current-screen migration.

### 19.2 Required checks

#### Continuity

- Do Parts 13–15 accurately implement Parts 1–12?
- Has any earlier Product Goal or UX Boundary been lost?
- Has visual standardisation overridden a valid user difference?

#### Internal consistency

- Are token names consistent?
- Are states defined once and reused?
- Do components and patterns use the same terminology?
- Are light and dark modes based on the same semantics?
- Are density modes applied consistently?

#### Completeness

- Are any current-screen needs unsupported?
- Are any necessary components missing?
- Are any approved archetypes missing practical patterns?
- Are feedback, Draft, failure and recovery states covered?
- Are mobile and professional use cases both represented?

#### Simplicity

- Are there unnecessary tokens?
- Are there duplicate components?
- Are there overlapping patterns?
- Have one-off screens been incorrectly elevated into general standards?
- Has the system become too complex for Minty’s current needs?

#### Accessibility

- Are measurable standards included?
- Can the components and patterns satisfy them?
- Are important states communicated without colour alone?
- Are keyboard, screen-reader and touch interactions documented?

#### Maintainability

- Can components be changed without rewriting the whole system?
- Can future modules reuse the system?
- Is deprecation manageable?
- Can a junior contributor identify the correct component or pattern?
- Can AI retrieve and apply the rules safely?

### 19.3 Final review outputs

Produce:

1. Executive summary
1. Strengths of the completed package
1. Contradictions
1. Duplications
1. Missing rules
1. Missing components
1. Missing patterns
1. Accessibility gaps
1. Figma implementation risks
1. Current-screen migration risks
1. Required corrections
1. Recommended future matters
1. Final approval checklist
1. Final decision, assumption and preference register

## 20. Final Deliverable Objective

The combined Parts 13–15 should become:

The authoritative practical design framework for future Minty screen updates, new-screen creation, new-module design, Figma implementation, frontend implementation, UX review and AI-assisted interface generation.

The final package should enable:

### Designers

To create screens without recreating the visual system.

### Developers

To implement reusable components with known behaviours and states.

### Product reviewers

To evaluate whether a screen follows Minty’s product and UX intent.

### Junior contributors

To make safe routine design decisions without senior design knowledge.

### AI systems

To generate or review Minty interfaces without reverting to generic SaaS assumptions.

### Future project contributors

To understand not only what the standard is, but why it exists and when an exception is justified.

When uncertain:

- refer to existing evidence;
- preserve validated Minty intent;
- prioritise the business owner;
- protect the Product Goal;
- reuse before creating;
- make the strongest professional recommendation;
- record assumptions;
- and surface preference decisions for later product-owner review.
