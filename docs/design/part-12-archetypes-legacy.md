<!-- Mirror of "Part 12. Page and Workflow Archetypes.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

## Part 12. Page and Workflow Archetypes

**Legacy Reference Document**

This document reflects an earlier stage of Minty archetype development.

The authoritative archetype model is now:

Part 4 – Page & Workflow Archetypes

Part 12 should be treated as historical reasoning and reference material only.

Where conflicts exist, Part 4 takes precedence.

### 12.1 Purpose

Page and Workflow Archetypes define the approved structural patterns used throughout Minty.

They provide a consistent starting point for:

- UI and UX design;
- Figma screens;
- AI-generated designs;
- product specifications;
- development; and
- future modules.

The purpose of these archetypes is to:

- reduce unnecessary UI variation;
- prevent every screen from being designed from the beginning;
- create predictable user experiences;
- improve consistency across modules and devices;
- accelerate design and development;
- provide clearer instructions to AI design tools; and
- ensure that screen structure reflects the user’s objective and operating context.

A new screen should begin with an approved archetype.

A new archetype should be introduced only when the existing archetypes cannot adequately support the confirmed workflow.

### 12.2 Difference Between a Page and a Workflow

Minty distinguishes between:

1. Page Archetypes; and
1. Workflow Archetypes.

#### 12.2.1 Page Archetype

A Page Archetype defines the structure of an individual screen.

Examples include:

- Dashboard Page;
- List Page;
- Detail Page;
- Record Form;
- Report Page;
- Settings Page;
- Empty State; and
- Confirmation Modal.

#### 12.2.2 Workflow Archetype

A Workflow Archetype defines how a user moves across multiple sections, stages or pages to complete a business process.

Examples include:

- preparing a Daily Report;
- completing an initial setup process; and
- performing another multi-stage operational process.

A workflow may contain several different Page Archetypes.

For example, the Daily Report is not simply a Create Page. It is a multi-stage operational workflow that includes:

- Addition to Drawer
- Sales
- Expenses
- Cash Count
- Close

Within the Expenses stage, however, an individual expense item may use a Record Form.

Therefore:

A workflow defines the complete business journey. A page defines one interface within that journey.

### 12.3 Archetype Selection Rules

Before designing a screen or workflow, the designer should identify:

1. Module
1. UX user profile
1. Module context
1. Primary objective
1. Primary information
1. Secondary information
1. Primary device
1. Secondary device
1. Whether the design represents a page or a workflow
1. Applicable Page or Workflow Archetype

A screen should normally belong to one primary Page Archetype.

A workflow may contain multiple Page Archetypes, but it should follow one primary Workflow Archetype.

Where one screen serves multiple profiles, the primary profile for that screen must be identified.

The needs of secondary profiles or secondary activities should be supported without weakening the experience of the primary profile.

## 12.4 Archetype Design Principles

### 12.4.1 Clarity Before Efficiency

Minty prioritizes clarity over operational efficiency when the two are in conflict.

The default approach should favor:

- fewer visible elements;
- clearer information hierarchy;
- appropriate whitespace;
- progressive disclosure;
- understandable next actions; and
- separation of information into manageable sections.

Minty may require one additional action or an additional screen where this materially improves understanding.

However, operational screens may use greater information density where efficiency genuinely requires it.

This exception applies particularly to:

- Treasury;
- multi-record review;
- filtering and sorting;
- batch activities; and
- other high-volume processing workflows.

The overall principle is:

Clarity first. Efficiency where operational requirements justify it.

### 12.4.2 Preserve Vertical Space

Vertical screen space is a scarce resource in Minty, particularly on mobile.

Minty is an operational and accounting application. Its screens naturally contain:

- amounts;
- transactional information;
- statuses;
- supporting documents;
- references;
- reconciliation information;
- history; and
- system actions.

Achieving sufficient whitespace and visual calm can therefore be difficult.

Minty should preserve vertical space by default.

Designs should:

- minimize persistent interface elements;
- avoid unnecessary navigation chrome;
- avoid excessive introductory text;
- use progressive disclosure;
- place supporting information inside expandable sections where appropriate;
- avoid permanently visible controls that provide limited value; and
- prioritize business information over interface decoration.

Persistent sticky bottom bars should not be the default.

Workflow-completion actions do not automatically require a sticky bottom bar. Where the user understands that an action is needed to complete a workflow, the action may appear naturally at the end of the relevant page or review stage.

A sticky action area should be used only where there is a specific and documented usability need.

### 12.4.3 Primary Information First

Every page should clearly distinguish between:

- primary information;
- secondary information; and
- administrative or supporting information.

Primary information should be visible immediately and receive the strongest visual hierarchy.

Secondary information should remain accessible without competing with the primary information.

Administrative information should not dominate a page unless administration is the user’s primary objective.

### 12.4.4 Few Important KPIs

Minty should normally display a small number of large, easily understood KPI cards.

Dashboards and reports should not attempt to display every useful metric simultaneously.

Additional metrics should normally appear through:

- expandable sections;
- supporting breakdowns;
- detail pages;
- report pages; or
- drill-down actions.

Where a particular user profile requires different information, the chosen KPIs may change. The default principle of using few important KPIs should still apply.

### 12.4.5 Cards Summarize; Pages Explain

A card should remain concise and scannable.

A card should contain only enough information for the user to:

1. identify the item;
1. understand its most important state or value;
1. determine whether it requires attention; and
1. decide whether to open it.

A card should not become a miniature Detail Page.

When the user needs to:

- investigate;
- review several fields;
- verify a supporting document;
- inspect history;
- compare information; or
- perform detailed actions,

the user should open the relevant Detail Page.

The governing principle is:

A card summarizes. A page explains.

### 12.4.6 Primary Information Expanded, Supporting Information Collapsed

Where a page contains both primary and supporting information:

- primary information should be visible or expanded by default;
- directly relevant working information may also be expanded;
- secondary information should normally be collapsed; and
- administrative, historical and audit information should normally be collapsed.

For example:

Primary Summary

Expanded

Sales Breakdown

Expanded where immediately relevant

Expense Details

Collapsed

Supporting Documents

Collapsed or visible depending on workflow

History

Collapsed

Audit Information

Collapsed

The appropriate default state may vary by user profile.

Treasury pages may require more information to be expanded where operational efficiency justifies it.

### 12.4.7 Business Rules Create Restrictions

The interface should not create unnecessary restrictions.

Users should generally be free to:

- move between sections;
- review previously entered information;
- return to incomplete work where drafts are supported; and
- complete permitted activities in an appropriate order.

Navigation should be restricted only where a confirmed business rule requires it.

For example, within a Daily Report, a user may move between:

- Sales;
- Expenses; and
- Cash Count.

However, the user cannot begin the next business day’s report before the preceding day’s ending balance is confirmed and the preceding report is finalized.

The restriction exists because of the underlying accounting and operational logic, not because step-by-step interfaces must always be sequential.

The governing principle is:

Business rules should create restrictions. The interface should not create additional restrictions without a clear reason.

### 12.4.8 Mobile and Desktop Are Related, Not Identical

Mobile and desktop experiences should use:

- the same terminology;
- the same business rules;
- the same status definitions;
- the same component system; and
- the same underlying information.

However, they do not need to use identical layouts.

Information may be reorganized to suit the device.

For example:

- a desktop List Page may use a table;
- the corresponding mobile List Page may use lightweight cards;
- desktop may expose commonly used filters;
- mobile may place filters behind a compact filter control; and
- desktop may support higher information density where operationally necessary.

The same workflow should remain understandable across devices even when the presentation differs.

### 12.4.9 Context Determines Status Prominence

A status should be prominent when it determines:

- the user’s next action;
- the actions available;
- the record’s position in a workflow;
- whether the record is editable; or
- whether the record requires attention.

For example, Payment Request statuses such as Draft, Submitted, Paid or Published may be prominent because they directly influence Treasury’s workflow.

A status should be secondary when the page’s primary purpose is to communicate business information.

For example, on the Daily Report summary, total sales, total expenses and cash position should receive greater prominence than submission status.

Status must remain visible where relevant, but it should not automatically become the most visually dominant element.

### 12.4.10 Supporting Document Priority Depends on Context

Supporting documents do not have the same importance in every Minty workflow.

#### Daily Report

Within the Daily Report, the business information remains primary.

Supporting documents support individual entries and the overall report.

The general hierarchy is:

1. business information;
1. item details; and
1. supporting documents.

#### Payment Request

Within the Payment Request module, the supporting document may be essential to reviewing and processing the request.

The payment record and supporting document may therefore have comparable importance, particularly for Treasury.

The layout should reflect the role the document plays in the relevant workflow rather than applying one universal document-placement rule.

### 12.4.11 Minty Is Part of the Experience

Minty is not only a decorative illustration.

Minty may:

- welcome;
- explain;
- guide;
- reassure;
- encourage; and
- provide closure.

The mascot should have a meaningful presence particularly in:

- empty states;
- onboarding;
- successful completion states;
- appropriate guidance; and
- selected system feedback.

Minty’s use should remain professional and supportive rather than distracting or childish.

The specific illustration rules, poses, placements and frequency of appearance are **[Missing, Need to Develop]**.

## 12.5 Dashboard Family

### 12.5.1 Purpose

A Dashboard communicates the most important information available to a particular user profile and provides clear paths to relevant actions or deeper information.

Minty should not use one universal Dashboard structure for every user.

The Dashboard type should reflect:

- the UX profile;
- the user’s primary objective;
- the module;
- the information requiring priority; and
- the actions the user is expected to take.

Minty dashboards should generally be hybrid destinations.

They should:

1. communicate important information directly; and
1. provide clear paths to relevant work.

A Dashboard should not be only a static report or only a navigation menu.

### 12.5.2 Summary Dashboard

#### Purpose

The Summary Dashboard helps the user quickly understand the most important operational results.

#### Primary UX Profile

- Daily Summary Reviewer

#### Primary Content

The Summary Dashboard should normally contain a small number of large KPI cards.

For the Daily Report, the primary information is:

1. total daily sales;
1. total daily expenses; and
1. daily cash position.

#### Secondary Content

Secondary information may include:

- sales-method breakdown;
- other supporting operational information;
- report completion; and
- submission status.

Secondary information should not compete visually with the primary KPIs.

#### Status

Approved for current Minty use.

Detailed layout and responsive behaviour are **[Missing, Need to Develop]**.

### 12.5.3 Action Dashboard

#### Purpose

The Action Dashboard helps a user understand what requires action and navigate to the relevant working page.

#### Primary UX Profiles

- Payment Processor
- Other operational profiles where the workflow is confirmed

#### Typical Content

The Action Dashboard may include:

- items requiring attention;
- pending work;
- time-sensitive records;
- status-based queues;
- concise summaries; and
- links to relevant List or Detail Pages.

#### Design Rules

The Dashboard should not attempt to reproduce the full working List Page.

Cards should summarize the work requiring attention and direct the user to the appropriate operational page.

#### Status

Approved as an archetype.

Current Minty implementation details are **[Missing, Need to Develop]**.

### 12.5.4 Hybrid Dashboard

#### Purpose

The Hybrid Dashboard combines a small number of important KPIs with concise, actionable information.

#### Structure

The default hierarchy should be:

1. few important KPI cards;
1. information or items requiring attention; and
1. links to detailed working pages.

#### Design Rules

The Dashboard should not accumulate unrelated cards, metrics and shortcuts merely because they may be useful.

Each element should support the confirmed objective of the relevant UX profile.

#### Status

Approved as an archetype where both summary and action needs are confirmed.

### 12.5.5 Future Business Monitor Dashboard

The Business Monitor Dashboard is a future cross-module concept.

It should not currently determine:

- navigation;
- page layout;
- KPI selection;
- card design; or
- dashboard structure.

The relevant workflow and information needs are **[Missing, Need to Develop]**.

## 12.6 List Page

### 12.6.1 Purpose

The List Page allows users to find, review and manage multiple records.

The List Page should answer:

“What records exist?”

“Which records require my attention?”

“How can I find the record I need?”

### 12.6.2 Desktop Presentation

Desktop List Pages should normally use tables when users need to:

- review multiple records;
- compare fields;
- sort records;
- filter records;
- identify workflow status; or
- perform operational processing.

Tables should support the user’s actual information needs rather than displaying every available field.

Detailed table rules are **[Missing, Need to Develop]**.

### 12.6.3 Mobile Presentation

The corresponding mobile List Page should normally use lightweight cards.

Mobile cards should present only enough information for the user to:

- identify the record;
- understand its most important state;
- determine whether action is required; and
- decide whether to open it.

Mobile cards should not attempt to display every desktop table column.

Detailed record information belongs on the Detail Page.

### 12.6.4 Adaptive Presentation Rule

The approved default is:

- Desktop: table-first
- Mobile: card-first

Desktop and mobile should present the same underlying records but may prioritize and organize information differently.

### 12.6.5 Search and Filter Placement

The current provisional default is:

#### Desktop

- Search remains visible.
- Common filters may remain visible.
- Less frequently used or advanced filters may be placed inside an additional filter control.
- Results should retain the majority of the available page space.

#### Mobile

- Search should normally remain visible.
- Filters should normally be accessed through a compact filter button or control.
- Applied filters should remain apparent.
- A persistent filter panel should be avoided.

Search and filter prominence should remain context-dependent.

If users commonly locate known records, search should receive greater emphasis.

If users commonly process queues by status, date or another attribute, filters may receive equal or greater emphasis.

The detailed arrangement should be validated for each List Page.

### 12.6.6 Search and Filter Behaviour

Search should update after a short pause rather than with every individual keystroke.

Simple filters may update the results immediately.

Where a filter panel contains several criteria, the panel should use explicit actions such as:

- Apply; and
- Clear all.

This allows the user to configure several filter choices before refreshing the results.

### 12.6.7 Summary Content

A List Page should not automatically include KPI cards above the results.

Summary metrics should be included only when they materially help the user understand or process the list.

The default should be to protect the working area and avoid combining too many dashboard and list functions on the same page.

### 12.6.8 Typical Examples

- Payment Request list
- Treasury payment queue
- User list
- Entity list
- Other future record lists

### 12.6.9 Status

Approved archetype.

Detailed table columns, card contents, selection behaviour, pagination and bulk-action rules are **[Missing, Need to Develop]**.

## 12.7 Detail Page

### 12.7.1 Purpose

The Detail Page allows the user to understand and, where permitted, act on one record.

The Detail Page should answer:

“What is this record?”

“What is its current state?”

“What information supports it?”

“What can I do next?”

### 12.7.2 Approved Structure

Minty Detail Pages should follow a summary-first, details-expand pattern.

The general structure is:

Page Header

Record Identity

Status

Key Information

Available Actions

Primary Detail Section

Expanded

Supporting Documents

Expanded or collapsed depending on context

Additional Details

Collapsed

History

Collapsed

Audit or System Information

Collapsed

### 12.7.3 Summary Area

The summary area should show only the key information required to understand the record.

For a Payment Request, this may include information such as:

- vendor;
- amount;
- due date;
- status; and
- action required.

Final field selection is **[Missing, Need to Develop]**.

### 12.7.4 Expandable Sections

Primary working information should normally be expanded.

Secondary information should normally be collapsed.

The appropriate default may vary by profile.

For Treasury, supporting documents or payment information may need to be expanded because they are necessary to the immediate workflow.

History and audit information should not normally occupy the initial view.

### 12.7.5 Tabs

Tabs should not be the default structure for Detail Pages.

Expandable sections are preferred because they:

- support progressive disclosure;
- work consistently across mobile and desktop;
- keep the page understandable as one record; and
- avoid separating closely related information unnecessarily.

Tabs may be introduced only where the information becomes genuinely distinct or too substantial for one expandable structure.

Any such use is **[Missing, Need to Validate]**.

### 12.7.6 Status Placement

Status should be prominent where it determines the available workflow actions.

Where status is administrative or secondary, it should remain visible without dominating the page.

### 12.7.7 Typical Examples

- Payment Request Detail
- Daily Report Detail
- User Detail
- Entity Detail

### 12.7.8 Status

Approved archetype.

Detailed field hierarchy and action positioning are **[Missing, Need to Develop]**.

## 12.8 Record Form

### 12.8.1 Purpose

The Record Form allows the user to create or edit an individual record.

Examples of individual records include:

- one Payment Request;
- one expense item;
- one user;
- one Entity; and
- one account configuration.

A Record Form should not be confused with a multi-stage Workflow Archetype.

### 12.8.2 Approved Structure

Record Forms should normally be presented as one page with clearly separated sections.

A typical structure is:

Page Title

Short Guidance Where Necessary

General Information

Supporting Document

Additional Details

Review

Save or Submit

``

Not every form requires every section.

Only relevant sections should be included.

### 12.8.3 Form Principles

Record Forms should:

- use clear section headings;
- group related fields;
- avoid excessive fields in one visual block;
- support document upload where required;
- explain incomplete information clearly;
- support draft behaviour where defined; and
- place the final action at the natural end of the form or review sequence.

### 12.8.4 Mobile Behaviour

Mobile forms should prioritize:

- clear vertical flow;
- suitable touch targets;
- camera or document upload;
- manageable section sizes;
- limited competing information; and
- preservation of vertical space.

A sticky bottom action area should not be assumed.

The completion action may appear naturally at the end of the form.

### 12.8.5 Desktop Behaviour

Desktop may use the additional width to improve readability and alignment.

Desktop should not introduce a fundamentally different form process unless the workflow requires it.

Fields should not be spread across multiple columns merely because horizontal space is available.

Clarity remains the primary objective.

### 12.8.6 Create and Edit Forms

Create and Edit Forms should generally use the same structural pattern.

An Edit Form may additionally need to communicate:

- current values;
- fields that cannot be changed;
- the effect of changes;
- existing status; and
- relevant history.

Detailed edit-state rules are **[Missing, Need to Develop]**.

### 12.8.7 Typical Examples

- Create Payment Request
- Edit Payment Request
- Add Expense Item
- Create User
- Edit User
- Create Entity
- Edit Entity
- Configure Account

### 12.8.8 Status

Approved archetype.

Detailed field, validation and draft rules belong in Part 7. Forms and the relevant module specification.

## 12.9 Operational Workflow

### 12.9.1 Purpose

The Operational Workflow guides the user through several related stages required to complete one business process.

It is appropriate where the process contains multiple meaningful sections that collectively produce one final result.

### 12.9.2 Primary Example

The Daily Report is the confirmed example of an Operational Workflow.

It may include stages such as:

1. Addition to Drawer
1. Sales
1. Expenses
1. Cash Count
1. Close

Each stage may contain one or more Record Forms or supporting page patterns.

### 12.9.3 Navigation Principle

The default should be free navigation between workflow sections.

Users should be able to move between sections unless a business rule requires a restriction.

For the Daily Report, the user may move between:

- Addition to Drawer
- Sales
- Expenses
- Cash Count
- Close

The system should validate completion and business logic at the appropriate time.

### 12.9.4 Business-Rule Gates

A restriction may be introduced where required by confirmed accounting or operational logic.

For example:

- a Daily Report cannot be validly submitted where required information is incomplete;
- the next business day cannot begin before the prior day’s ending balance is confirmed and the report is finalized; and
- other module-specific restrictions may apply where documented.

A wizard should not become sequential merely because it is visually divided into steps.

### 12.9.5 Progress Communication

The workflow should indicate:

- available sections;
- current section;
- completed sections;
- incomplete sections; and
- information preventing final completion where relevant.

Detailed progress-indicator design is **[Missing, Need to Develop]**.

### 12.9.6 Completion Action

The final action should normally appear at the natural end of the review or completion stage.

A persistent sticky action bar should not be assumed.

The system should clearly communicate any information preventing submission.

### 12.9.7 Status

Approved archetype.

Detailed Daily Report stage structure remains governed by the relevant module requirements.

## 12.10 Report Page

### 12.10.1 Purpose

The Report Page presents business information primarily for review and understanding rather than data entry.

The Report Page should answer:

“What happened?”

For the Daily Report, it should specifically answer:

“How much did we sell today?”

“How much did we spend today?”

“What is our cash position?”

### 12.10.2 Approved Structure

The standard Report Page should use a KPI-first structure.

Report Identity and Date

Large KPI Cards

Sales

Expenses

Cash Position

Expandable Supporting Sections

Sales Breakdown

Expense Details

Cash Movement Details

Other Operational Information

Administrative Information

Submission Status

Report Completion

System Information

### 12.10.3 KPI Rules

The Report Page should normally show a small number of large KPI cards.

For the current Daily Report, the primary KPIs are:

- total daily sales;
- total daily expenses; and
- daily cash position.

The page should not add additional KPI cards merely because more metrics are available.

### 12.10.4 Supporting Information

Supporting breakdowns should normally appear below the primary KPIs.

The sales-method breakdown is secondary or additional information.

It should remain readily available without competing visually with the primary figures.

### 12.10.5 Administrative Information

Information such as:

- submission status;
- missing report information;
- report completion; and
- system details

should remain secondary to the operational summary.

The Report Page should not be structured primarily as a compliance or submission-monitoring page.

### 12.10.6 AI Narrative

Narrative reporting is a future AI-supported capability.

The standard current Report Page should not depend on an AI-generated narrative.

Future AI may provide:

- a concise explanation;
- anomaly detection;
- trend analysis;
- historical comparison; or
- information requiring attention.

These capabilities are not part of the current approved Report Page hierarchy.

### 12.10.7 Status

Approved archetype.

The Daily Report is the confirmed current example.

## 12.11 Settings Page

### 12.11.1 Purpose

The Settings Page allows users to review and manage configuration information.

Settings should be treated as persistent business configuration rather than a temporary action.

### 12.11.2 Typical Content

Settings may include:

- Entity settings;
- user settings;
- module settings;
- connected services;
- accounting configuration;
- access-related settings; and
- other persistent preferences.

### 12.11.3 Page Rule

Settings that involve material information, permissions, accounting configuration or data that users may need to revisit should use a Page or Record Form.

They should not automatically use a modal.

### 12.11.4 Status

Approved archetype.

Detailed grouping, navigation and save behaviour are **[Missing, Need to Develop]**.

## 12.12 Empty State

### 12.12.1 Purpose

An Empty State appears when no relevant or usable data exists.

It should explain:

- what the user is seeing;
- whether the situation is normal;
- what the user can do next; and
- how Minty can help.

### 12.12.2 Approved Tone

Empty States should use Minty’s friendly, supportive and reassuring voice.

A purely technical message such as “No records found” should not normally be used on its own.

The Empty State should feel welcoming without becoming childish.

### 12.12.3 Approved Structure

A standard Empty State may contain:

1. Minty illustration;
1. short title;
1. concise explanation;
1. reassurance where appropriate; and
1. one recommended primary action.

Example structure:

Minty Illustration

Looks quiet here.

Create your first payment request and I’ll help keep everything organized.

Create Payment Request

Final wording should follow Minty’s approved writing and tone guidance.

### 12.12.4 Mascot Role

Minty should normally participate in Empty States as a guide or supportive presence.

Minty is not simply background decoration.

The exact visual treatment is **[Missing, Need to Develop]**.

### 12.12.5 Actions

An Empty State should normally contain one primary call to action.

Additional actions should be avoided unless genuinely necessary.

### 12.12.6 Status

Approved archetype.

Illustration and composition rules remain **[Missing, Need to Develop]**.

## 12.13 Confirmation Modal

### 12.13.1 Purpose

A Confirmation Modal allows the user to confirm an immediate action without leaving the current context.

Modals should have a temporary and focused purpose.

### 12.13.2 Primary Uses

Modals should primarily be used for actions such as:

- confirming deletion;
- confirming submission where confirmation is required;
- confirming publication;
- confirming disconnection from an integration;
- confirming a void or cancellation; and
- confirming another significant immediate action.

### 12.13.3 Structure

A Confirmation Modal should normally contain:

1. a clear question or action title;
1. a concise explanation;
1. the consequence of proceeding where relevant;
1. one primary action; and
1. one secondary cancellation action.

The modal should not contain a large form or substantial record information.

### 12.13.4 Status Prominence

Where the action changes the record’s status, the resulting change should be clearly explained.

### 12.13.5 Status

Approved archetype.

Detailed destructive-action and confirmation rules belong in Part 5. Commanding.

## 12.14 Modal Versus Page Rules

### 12.14.1 Default Rule

Minty should use pages by default for records and persistent configuration.

The guiding principle is:

Records deserve pages. Actions deserve modals.

### 12.14.2 Use a Page When

A Page should normally be used where the user may:

- save a draft;
- return later;
- review information;
- upload documents;
- continue over more than one session;
- manage consequential information;
- configure permissions;
- create a persistent business record; or
- need sufficient space to understand the task.

Current examples include:

- Payment Request;
- User creation;
- Entity creation;
- Account configuration;
- Settings; and
- Daily Report.

### 12.14.3 Use a Modal When

A Modal may be used where the user is:

- confirming an action;
- making a focused temporary decision; or
- entering genuinely lightweight supporting information.

Future simple contact creation may qualify as a lightweight supporting task if its confirmed workflow remains sufficiently simple.

A modal should not be selected merely because it is faster to design or implement.

### 12.14.4 Draft Consideration

Where users may reasonably expect to retain incomplete information and continue later, the interface should normally use a Page rather than a Modal.

Whether every incomplete entry should automatically be stored as a draft is a separate data and product decision.

It should not be assumed solely from the Page Archetype.

## 12.15 Primary Actions

### 12.15.1 Desktop

On desktop, a page-level primary creation action should normally appear near the page title or in another consistent top-page action area.

Examples include:

- Create Payment Request;
- Add User; and
- Create Entity.

Detailed desktop positioning belongs in Part 3. Layout and Part 5. Commanding.

### 12.15.2 Mobile Object Creation

On mobile, a Floating Action Button may be used for clear object-creation actions.

Examples include:

- create a payment request;
- add an item;
- add a user where appropriate; and
- create another record.

A Floating Action Button should represent one clear and predictable primary action.

It should not be used where the action is ambiguous.

### 12.15.3 Workflow Completion

Workflow-completion actions should normally appear at the natural end of the relevant form, review stage or workflow.

Examples include:

- Submit Daily Report;
- Submit Payment Request; and
- confirm a final review.

A sticky bottom action area should not be assumed.

Minty should preserve vertical space unless persistent access to the action is shown to be necessary.

## 12.16 Mobile Navigation

### 12.16.1 Default Navigation

Minty should use hamburger-first navigation on mobile.

The purpose is to:

- preserve the content area;
- minimize permanent interface elements;
- protect vertical space; and
- allow business information to receive priority.

The governing principle is:

Information first. Navigation second.

### 12.16.2 Bottom Navigation

Persistent bottom navigation should not be the default.

It may be considered only where a confirmed module-specific workflow clearly benefits from it.

No such exception is currently confirmed.

### 12.16.3 Module-Specific Navigation

A module-specific navigation structure may be introduced where a unique workflow clearly requires it.

This is **[Future, Need Validation]**.

## 12.17 Archetype Approval Matrix

| **Archetype** | **Classification** | **Current Status** |
|---|---|---|
| Summary Dashboard | Page Archetype | Approved |
| Action Dashboard | Page Archetype | Approved |
| Hybrid Dashboard | Page Archetype | Approved where both needs are confirmed |
| Business Monitor Dashboard | Page Archetype | Future |
| List Page | Page Archetype | Approved |
| Detail Page | Page Archetype | Approved |
| Record Form | Page Archetype | Approved |
| Report Page | Page Archetype | Approved |
| Settings Page | Page Archetype | Approved |
| Empty State | Page State Archetype | Approved |
| Confirmation Modal | Modal Archetype | Approved |
| Operational Workflow | Workflow Archetype | Approved |
| Module-Specific Navigation | Navigation Pattern | Future, need validation |

## 12.18 Archetype Design Checklist

Before approving a new design, confirm:

### User and Purpose

- Has the UX profile been identified?
- Has the module context been identified?
- Is the primary user objective clear?
- Is the required user action clear?

### Archetype

- Has an approved Page Archetype been selected?
- If this is a multi-stage process, has a Workflow Archetype also been selected?
- Is a genuinely new archetype required, or can an existing one be reused?

### Information Hierarchy

- Is primary information immediately clear?
- Is secondary information visually subordinate?
- Is administrative information prevented from dominating the page?
- Are there too many KPI cards?
- Has a card become too detailed and therefore better suited to a Detail Page?

### Device Strategy

- Is the primary device identified?
- Does the mobile design preserve vertical space?
- Does the desktop design add density only where useful?
- Are mobile and desktop related without being forced into identical layouts?

### Interaction

- Are restrictions based on confirmed business rules?
- Can the user navigate freely where no restriction is required?
- Are expandable sections used appropriately?
- Are primary sections expanded and secondary sections collapsed?
- Is status prominence appropriate to the workflow?

### Actions

- Is the primary action clear?
- Is a modal being used only for a temporary or focused action?
- Does a persistent control consume space without sufficient benefit?
- Is a Floating Action Button appropriate and unambiguous on mobile?

### Minty Experience

- Does the page remain calm despite the amount of information?
- Is sufficient whitespace preserved?
- Does the Empty State explain and guide?
- Is Minty’s presence supportive rather than decorative or distracting?

## 12.19 Overall Archetype Principle

Minty should not create a new screen structure for every module.

The designer should first determine:

1. who the user is in the workflow;
1. what the user is trying to achieve;
1. what information must receive priority;
1. which device is primarily used;
1. whether the requirement is a page or a workflow; and
1. which approved archetype applies.

Only after these questions have been answered should the detailed layout and components be selected.

The objective is not for every Minty page to look identical.

The objective is for different pages to behave predictably, share a consistent structural language and feel unmistakably part of the same product.
