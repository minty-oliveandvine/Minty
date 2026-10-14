<!-- Mirror of "Part 10. Feedback, Guidance & System Status.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

## Part 10. Feedback, Guidance & System Status

### Version 1.0 Draft

## 10.1 Purpose

This chapter defines how Minty communicates:

- progress;
- completion;
- saved states;
- system activity;
- system failure;
- data-quality issues;
- required user decisions;
- AI uncertainty;
- business issues;
- integration status;
- and other system conditions.

Feedback should help users understand:

1. What happened?
1. Is their work safe?
1. Does Minty need anything from them?
1. Can they continue?
1. What should they do next?

Minty should not interrupt users merely because the system has information to report.

Feedback should appear when it helps users:

- protect their work;
- maintain reliable business records;
- complete a task;
- provide required judgement;
- or recover from a problem.

The governing principle is:

**Minty surfaces feedback when data integrity, work completion, core business information, or user responsibility is affected.**

## 10.2 Feedback Priority Framework

Feedback priority should not be determined only by technical severity.

Minty should evaluate:

Risk of data loss

↓

Responsibility for resolution

↓

Impact on Minty’s core business records

↓

Impact on task completion

↓

Business importance

↓

Administrative importance

Minty should ask:

- Could the user’s work disappear?
- Is Minty able to resolve the issue without the user?
- Is the collected business data incomplete or questionable?
- Is the user required to make a decision?
- Can the current task continue?
- Does the issue require immediate resolution?
- Is the information merely useful for awareness?

The answers determine:

- whether feedback appears;
- when it appears;
- how prominent it becomes;
- whether it interrupts the user;
- and whether it blocks completion.

## 10.3 Feedback Categories

Minty should distinguish between five feedback categories.

### 10.3.1 System Failure

Examples:

- save failure;
- upload failure;
- page-loading failure;
- connection failure;
- Xero sync failure;
- and data processing failure.

System failures concern something Minty was responsible for completing.

### 10.3.2 Core Business Data Issue

Examples:

- cash discrepancy;
- missing compulsory amount;
- missing Supporting Document;
- inconsistent transaction data;
- incomplete accounting information;
- and possible duplicate invoice.

These issues affect information that Minty exists to capture or preserve.

### 10.3.3 User Judgement Required

Examples:

- uncertain AI extraction;
- uncertain document classification;
- user confirmation required;
- account-code decision required;
- approval required;
- and conflicting information that Minty cannot resolve.

Minty cannot responsibly determine the final answer without the user.

### 10.3.4 Business Issue

Examples:

- outstanding Payment Request;
- pending approval;
- unpaid supplier invoice;
- delayed reimbursement;
- unusual cash result;
- and trial ending.

Business issues may be important without being immediately urgent.

### 10.3.5 Convenience or Administrative Data Issue

Examples:

- unusual phone-number format;
- typo in an optional company nickname;
- incomplete profile information;
- missing optional note;
- and non-essential metadata.

These issues should not compete with the user’s primary work.

## 10.4 Feedback Urgency

Minty should use four feedback urgency levels.

### Immediate and Interruptive

Use where:

- work may be lost;
- the user may proceed with materially incorrect core data;
- Minty cannot continue without user input;
- a consequential action cannot be completed safely;
- or the current system state creates an immediate integrity risk.

Examples:

- entered information did not save;
- document upload failed and the file was not preserved;
- compulsory transaction information is missing at submission;
- AI could not determine a field that must be confirmed;
- and a payment action requires unresolved user judgement.

### Immediate but Non-Interruptive

Use where:

- a core-data issue should be visible now;
- the user can continue working toward resolution;
- or the issue belongs in the current task.

Examples:

- cash amount differs from the expected amount;
- one compulsory field remains incomplete;
- possible duplicate document found;
- and Supporting Document needs review.

The feedback should appear in context without automatically using a modal or blocking dialog.

### Persistent Awareness

Use where:

- a business or integration issue exists;
- the issue does not prevent the current task;
- and resolution may occur later.

Examples:

- Xero is disconnected, but no current action requires synchronisation;
- Payment Request remains pending;
- subscription trial is approaching its end;
- and a Draft remains incomplete.

The information should remain discoverable without continuously interrupting the user.

### Passive or Deferred

Use where:

- information is administrative;
- the current task is unaffected;
- or the issue becomes relevant only during a later action.

Examples:

- optional profile information is incomplete;
- company nickname has unusual formatting;
- non-essential metadata is missing;
- and technical details that do not affect current processing.

## 10.5 Feedback Decision Rule

Minty should use the following decision model:

Could the user’s work or data be lost?

│

├── Yes → Inform immediately and provide recovery

│

└── No

│

├── Is core business data incorrect, incomplete or questionable?

│ ├── Yes → Flag immediately in context

│ └── No

│

├── Does Minty require user judgement or confirmation?

│ ├── Yes → Request input immediately

│ └── No

│

├── Does the issue prevent completion?

│ ├── Yes → Explain and block the affected completion action

│ └── No

│

├── Is this a non-urgent business issue?

│ ├── Yes → Maintain persistent awareness

│ └── No

│

└── Is this administrative or non-essential?

├── Yes → Defer or remain silent

└── No → Use the lowest sufficient feedback level

The default should be:

**Use the least disruptive feedback that still protects the user, the Record, and the Product Goal.**

## 10.6 Feedback Presentation Hierarchy

Minty should use feedback mechanisms deliberately.

From least to most disruptive:

Silent System Handling

Inline Supporting Text

Field-Level Feedback

Status Indicator

Toast or Temporary Confirmation

Inline Alert

Page-Level Banner

Blocking Confirmation or Modal

Dedicated Recovery Experience

The most visible treatment is not automatically the most effective.

The chosen treatment should correspond to:

- urgency;
- responsibility;
- consequence;
- and location of resolution.

## 10.7 Silent System Handling

Minty should silently handle an issue where:

- the system can resolve it reliably;
- user awareness provides no practical value;
- work remains safe;
- and no user decision is required.

Examples may include:

- automatic retry;
- background refresh;
- temporary connection recovery;
- and recalculation after a field changes.

Silent handling should not conceal:

- data loss;
- unresolved processing;
- failed submission;
- or an issue requiring user judgement.

The principle is:

**Solve quietly where Minty can take responsibility. Communicate clearly where responsibility moves to the user.**

## 10.8 Inline Supporting Text

Use inline supporting text where the information:

- helps the user understand a field;
- explains a calculation;
- clarifies an expected input;
- or prevents confusion before an issue occurs.

Examples:

- explanation of expected cash;
- explanation of a Xero account;
- explanation of what a role permits;
- and explanation of why a document is required.

Supporting text should not be styled like a warning unless a current issue exists.

## 10.9 Field-Level Feedback

Field-level feedback should appear near the field requiring attention.

Use it where:

- a compulsory value is missing;
- an entered value cannot be processed;
- the value conflicts with another input;
- or the user must correct the information.

The feedback should state:

What needs attention

↓

What the user should do

↓

Why, only where useful

Example:

The amount is still empty. Add the amount to continue.

Avoid presenting field-specific issues only in a general page banner.

Users should not need to search for the affected field.

## 10.10 Status Indicators

Status indicators communicate the state of:

- a Record;
- workflow;
- upload;
- integration;
- invitation;
- subscription;
- or system process.

Examples:

- Draft;
- Saving;
- Saved;
- Uploading;
- Processing;
- Submitted;
- Payment Requested;
- Partially Paid;
- Xero Disconnected;
- and Invitation Pending.

Status should be prominent only where it affects:

- the next action;
- workflow progression;
- completion;
- or required attention.

Status should remain secondary where the user’s primary question concerns:

- business outcome;
- amount;
- summary;
- or completed information.

## 10.11 Temporary Confirmations

Temporary confirmations may be used for low-risk actions where the user only needs quick reassurance.

Examples:

- changes saved;
- note added;
- filter applied;
- link copied;
- and Draft preserved.

Temporary feedback should:

- appear close enough to the action to be understood;
- remain visible long enough to be noticed;
- avoid blocking later work;
- and avoid requiring dismissal.

Temporary confirmation should not be the only record of a consequential business state.

For example, final submission should also be reflected through:

- Record status;
- completion state;
- and the resulting destination.

## 10.12 Inline Alerts

Use inline alerts where an issue belongs to a specific:

- section;
- Record;
- document;
- calculation;
- or workflow stage.

Examples:

- cash difference;
- possible duplicate invoice;
- receipt missing from an expense;
- and account mapping required.

Inline alerts are preferred over global warnings where resolution occurs in the same section.

They should explain:

- what Minty observed;
- whether action is required;
- and how the user can proceed.

## 10.13 Page-Level Banners

Page-level banners should be reserved for information affecting a substantial part of the current page.

Appropriate examples:

- current Entity cannot connect to Xero;
- a page-wide processing limitation;
- scheduled system maintenance affecting the current work;
- and several Records affected by the same issue.

Do not use page-level banners for:

- individual field errors;
- optional information;
- ordinary workflow status;
- or non-actionable general announcements.

Persistent banners should be removable only where the underlying issue has been resolved or no longer affects the page.

## 10.14 Blocking Feedback

Blocking feedback is appropriate where:

- final submission would create an invalid outcome;
- a consequential action cannot safely continue;
- required user decision is unresolved;
- user authentication or permission prevents access;
- or Minty cannot preserve the user’s work.

Blocking should apply to the affected action wherever possible.

Avoid blocking the entire product when only one activity is affected.

The blocking feedback should provide:

1. the issue;
1. the required action;
1. the recovery path; and
1. access to support where the user cannot resolve it.

## 10.15 Modal Use

A modal may be appropriate where:

- the decision is consequential;
- the action is irreversible or difficult to reverse;
- immediate confirmation is necessary;
- or allowing the user to continue without resolving the decision would be unsafe.

Examples:

- final report submission;
- deletion;
- disconnecting Xero;
- cancelling a subscription;
- and confirming a payment.

A modal should not be used merely to display information already visible on the page.

A modal should not become a substitute for:

- field validation;
- inline guidance;
- page-level recovery;
- or a multi-step workflow.

## 10.16 System Failure

When Minty fails to complete an action it owns, feedback should be:

- immediate;
- honest;
- calm;
- and recovery-focused.

Examples:

- save failed;
- upload failed;
- synchronisation failed;
- page did not load;
- and session expired.

### Data-Loss Risk

If work may be lost, Minty should say so immediately.

The feedback should explain:

- whether the information is safe;
- what was not completed;
- what the user should do;
- and whether Minty preserved a copy.

Minty should never display a reassuring “Saved” state before the information has been preserved reliably.

### Recoverable Failure

Where Minty can retry safely, it may:

- preserve the user’s information;
- attempt recovery;
- inform the user that processing is continuing;
- and request action only if recovery fails.

### Unrecoverable or User-Dependent Failure

Where the system cannot proceed, Minty should:

- stop the affected action;
- preserve all possible work;
- explain the required user step;
- and offer support where appropriate.

## 10.17 Saving Feedback

Users should not have to wonder whether their work is safe.

Minty should distinguish:

Unsaved

Saving

Saved

Save Failed

### Unsaved

Use only where manual saving genuinely applies.

### Saving

Show where saving is noticeable or may take more than an immediate moment.

### Saved

Provide lightweight confirmation.

### Save Failed

Inform immediately if work is not preserved.

The saved state should be persistent enough that users can trust it without repeatedly checking.

## 10.18 Upload Feedback

Document preservation is a core Product Goal.

File-upload status should therefore remain clear.

Minty should distinguish:

Selected

Uploading

Uploaded

Processing

Unable to Upload

Users should be able to identify:

- which file is affected;
- whether Minty has preserved it;
- whether processing is still occurring;
- and whether further action is required.

Upload failure should not remove the selected document without explanation.

Where technically possible, Minty should preserve the file or offer a clear retry path.

## 10.19 Processing Feedback

Minty may need time to:

- process a document;
- extract information;
- generate a report;
- sync with Xero;
- calculate results;
- or prepare a file.

Processing feedback should explain:

- what Minty is doing;
- whether the user can continue elsewhere;
- and when user action will next be required.

Avoid technical descriptions such as:

Executing OCR extraction pipeline.

Prefer practical descriptions such as:

Minty is reading the invoice details.

Do not present determinate progress percentages unless the value is reliable.

## 10.20 Long-Running Processes

For longer processes, Minty should distinguish between:

### User Must Remain

The user cannot continue until processing is complete.

Use a visible in-context waiting state.

### User May Continue

The process can continue independently.

Allow the user to leave the page where technically supported and maintain clear status on return.

Because Minty cannot perform work asynchronously in all technical contexts, product implementation should state accurately whether background processing is supported.

The interface should never imply that work will continue if the system cannot actually do so.

## 10.21 Core Business Data Issues

Issues affecting Minty’s core business data should be flagged immediately in the relevant context.

Examples:

- cash discrepancy;
- possible duplicate;
- missing compulsory transaction data;
- and mismatch between calculated and entered totals.

Immediate flagging does not necessarily mean:

- modal;
- alarm color;
- urgent notification;
- or blocked navigation.

It means the issue should become visible at the point where:

- the data is entered;
- the Record is reviewed;
- or completion is attempted.

The user should not discover the problem only after final submission if Minty could have identified it earlier.

## 10.22 Cash Discrepancy

A cash discrepancy is important because it affects core operational and accounting data.

Minty should flag the difference when it becomes known.

The feedback should:

- remain calm;
- state expected and actual amounts clearly;
- distinguish the difference;
- request a note or review where required;
- and explain what happens next.

A cash discrepancy is not automatically an emergency.

The design should avoid combining:

Immediate Visibility

with:

Artificial Urgency

The issue should be visible now, while the tone and treatment remain proportionate.

## 10.23 Missing Supporting Document

A missing Supporting Document should be treated according to its role.

### Compulsory for Final Processing

Flag immediately and prevent final completion where required.

### Expected but Temporarily Unavailable

Allow Draft where safe and explain what remains missing.

### Optional

Do not warn merely because it is absent.

The system should not apply one universal document-warning rule across every Record type.

## 10.24 User Judgement Required

Minty should immediately surface an issue when the system cannot responsibly determine the answer and requires the user’s input.

Examples:

- uncertain AI extraction;
- material ambiguity in document classification;
- conflicting dates or amounts;
- account-code confirmation;
- and approval decision.

The feedback should state:

1. what Minty found;
1. what Minty could not determine;
1. what the user needs to confirm;
1. and what happens after confirmation.

Minty should not hide uncertainty behind an apparently confident result.

## 10.25 AI Feedback

AI feedback should distinguish between:

Processing

Suggested

Confirmed

Uncertain

Unable to Determine

### Processing

Minty is reading the invoice details.

### Suggested

Minty thinks this may be a utilities expense.

### Confirmed

The user has reviewed or accepted the suggestion.

### Uncertain

Minty found more than one possible match. Choose the best one to continue.

### Unable to Determine

Minty could not identify the Xero account. Choose one to continue.

AI feedback should focus on:

- user decision;
- effect on completion;
- and correction.

Avoid exposing technical confidence metrics unless they provide practical value.

## 10.26 AI Responsibility Transfer

When Minty can process information reliably, it should reduce the user’s work.

When Minty cannot responsibly determine the answer, responsibility transfers to the user.

That transfer should be visible.

The user should understand:

- why Minty is asking;
- what requires confirmation;
- and whether the workflow is blocked.

The governing principle is:

**When ownership moves from Minty to the user, communicate immediately and clearly.**

## 10.27 Business Issues

Business issues should usually support awareness rather than interruption.

Examples:

- bill unpaid;
- approval pending;
- reimbursement delayed;
- subscription trial ending;
- and Draft not yet completed.

These issues may appear through:

- dashboard summaries;
- status indicators;
- filtered Lists;
- contextual reminders;
- and appropriately timed notifications.

They should not automatically trigger:

- modals;
- repeated banners;
- or urgent language.

Presentation should reflect:

- consequence;
- due date;
- ownership;
- and whether immediate action is genuinely useful.

## 10.28 Future Risk

A future risk exists where no current action has failed, but a later activity may be affected.

Example:

- Xero is disconnected, but no current transaction needs to sync.

Minty should normally:

1. show the current status passively;
1. make the resolution path available;
1. avoid interrupting unrelated work;
1. increase prominence when the issue affects completion.

This creates escalation based on relevance:

Potential future impact

↓

Passive awareness

Current work affected

↓

Active feedback

Completion blocked

↓

Blocking feedback

## 10.29 Administrative and Convenience Issues

Administrative issues should receive low priority where they do not affect:

- core business records;
- completion;
- access;
- or data integrity.

Examples:

- optional phone-number formatting;
- optional company nickname;
- incomplete profile image;
- and missing non-essential note.

Minty may:

- validate when the field is submitted;
- provide optional guidance;
- or remain silent.

Do not interrupt the user’s accounting or operational work for unrelated administrative detail.

## 10.30 Guidance

Guidance helps users understand:

- what to do;
- why it matters;
- and how to complete it.

Guidance should be provided at the moment it is useful.

Use:

- contextual helper text;
- progressive disclosure;
- examples;
- practical descriptions;
- and short explanations.

Avoid:

- long introductory instructions;
- separate manuals inside workflows;
- repetitive guidance;
- and explanations that appear after the relevant decision.

Guidance should disappear or reduce once the user no longer needs it where technically appropriate.

## 10.31 First-Time Guidance

First-time guidance may be more visible where users need to learn:

- a workflow;
- a concept;
- a field;
- or a new module.

First-time guidance should:

- focus on the current action;
- avoid explaining the entire product;
- be easy to dismiss or move past;
- and not permanently consume working space.

The current task should remain central.

## 10.32 Progressive Guidance

Minty should introduce guidance progressively.

Short instruction

↓

Contextual explanation

↓

Detailed help or support

The user should not need to read the most detailed explanation before beginning.

Examples:

- field label;
- short helper text;
- info icon or expandable explanation;
- support or accountant assistance.

## 10.33 Empty States

An Empty State should communicate:

1. why no content exists;
1. whether the situation is normal;
1. what action is available;
1. and what will appear after the action.

Empty States should not imply a failure where the user simply has not created content yet.

Preferred:

No reports yet. Completed Daily Reports will appear here.

Avoid:

No data found.

## 10.34 Loading States

Loading feedback should be proportionate to expected waiting time.

### Immediate

No visible loading treatment may be needed.

### Short

Use a lightweight loading indicator or skeleton where helpful.

### Longer

Explain what Minty is preparing.

The interface should avoid layout shifts that cause users to lose context.

Loading states should resemble the expected content structure where possible.

## 10.35 Skeleton States

Skeleton states may be used where:

- content structure is predictable;
- loading is brief;
- and maintaining layout stability helps the user.

Do not use skeletons where:

- the process requires a meaningful explanation;
- user action is blocked for an extended period;
- or the system may require user intervention.

A skeleton communicates loading, not processing responsibility.

## 10.36 Completion Feedback

Completion should provide:

Recognition

↓

Result

↓

Next step, only where useful

Examples:

All done. Today’s report is ready.

Invite sent. The team member will receive an email.

Payment Request submitted. It is ready for review.

Completion feedback should make clear:

- what was completed;
- whether the action is final;
- what happens next;
- and where the completed work can be found.

Completion should feel like closure, not inspection.

## 10.37 Draft Feedback

Draft feedback should communicate:

- progress is preserved;
- work is incomplete;
- final submission has not occurred;
- and continuation remains available.

Example:

Saved as Draft. One compulsory detail is still missing.

Where no immediate reminder is required, Draft feedback should remain calm and lightweight.

Draft should not be visually confused with:

- Submitted;
- Complete;
- Approved;
- or Synced.

## 10.38 Integration Status

Integration feedback should distinguish:

Connected

Connecting

Syncing

Disconnected

Sync Failed

Action Required

A disconnected integration should not automatically interrupt unrelated work.

It should become prominent when:

- the current workflow depends on it;
- submission cannot complete;
- data cannot transfer;
- or the user must reconnect it.

Integration terminology should explain business impact.

Preferred:

Xero is not connected. Reconnect Xero to send this transaction.

Less useful:

Authentication token expired.

## 10.39 Notification Channels

Feedback should use the least disruptive effective channel.

### In-App

Use for:

- current work;
- field issues;
- workflow status;
- and immediate user decisions.

### Push Notification

Use for:

- time-relevant work;
- completion;
- and meaningful reminders where the user is not currently active.

### Email

Use for:

- invitations;
- consequential confirmations;
- detailed external records;
- and information the user may need outside the application.

### WhatsApp or SMS

Use selectively for:

- important operational reminders;
- onboarding;
- and approved communication scenarios.

Channel use should respect:

- user expectation;
- urgency;
- frequency;
- and available preference settings.

A message should not be repeated across several channels without a clear reason.

## 10.40 Reminder Rules

Reminders should be used where:

- the work remains important;
- delay creates a meaningful consequence;
- the user is likely to forget;
- and returning to Minty can resolve the issue.

Avoid reminders where:

- no user action is currently possible;
- the issue is low value;
- the user has already acknowledged it;
- or repeated prompting would create noise.

Reminder frequency should remain proportionate.

Minty should encourage completion without becoming controlling.

## 10.41 Status History

Status history may be useful for:

- consequential Records;
- auditability;
- payment processing;
- and integration events.

History should answer:

- what changed;
- when it changed;
- and what state resulted.

Detailed technical logs should not be exposed as user-facing history unless they help resolve an issue.

Timeline presentation should remain supporting information rather than the default representation of historical Records.

## 10.42 Accessibility and Readability

Feedback should remain understandable for users who:

- skim;
- have low reading patience;
- are working while distracted;
- or have reading difficulties.

Feedback should not rely only on:

- color;
- icons;
- animation;
- sound;
- or location.

Important feedback should include clear text.

Messages should be short and focused on one next action.

## 10.43 Feedback by Device

### Mobile

Prioritize:

- immediate action;
- compact inline feedback;
- preserved vertical space;
- and clear recovery.

Avoid stacking multiple banners or persistent notices.

### Tablet

Provide additional context where useful while retaining touch-friendly interaction.

### Computer

Support:

- richer process visibility;
- document-and-record comparison;
- and professional troubleshooting where justified.

Additional width should not cause every status and alert to remain permanently visible.

## 10.44 Feedback Anti-Patterns

Avoid:

### Warning Everything

Turning optional, administrative or future-risk information into immediate alerts.

### Silent Data Loss

Failing to tell users that information was not preserved.

### False Success

Showing completion before processing is reliably complete.

### Technical Severity as User Urgency

Presenting internal system severity as though the user must act immediately.

### Business Issue as Emergency

Using alarm language for issues that require awareness but not immediate action.

### Modal Overuse

Interrupting users for information that can be resolved inline.

### Responsibility Ambiguity

Failing to explain whether Minty or the user must act.

### Unclear Processing

Leaving users unsure whether Minty is saving, uploading, extracting or syncing.

### Repeated Notifications

Communicating the same issue across multiple channels without a defined reason.

### Unsupported AI Confidence

Presenting uncertain AI output as confirmed information.

### Permanent Warning Noise

Keeping resolved or irrelevant feedback visible.

## 10.45 Copilot Review Instructions

When reviewing feedback, guidance or system status, Copilot should evaluate:

### Responsibility

- Is Minty responsible for resolving the issue?
- Is user judgement required?
- Is ownership clear?

### Consequence

- Could work be lost?
- Could core business data become incorrect?
- Is completion affected?
- Is the issue merely administrative?

### Timing

- Should feedback appear immediately?
- Can it remain passive until relevant?
- Is the issue being shown too early or too late?

### Feedback Mechanism

- Is the least disruptive effective mechanism used?
- Could a modal become inline feedback?
- Could a banner become a status indicator?
- Is a temporary confirmation sufficient?

### Recovery

- Does the user know what to do?
- Is existing work preserved?
- Can the affected action be retried?
- Is support available where necessary?

### Core Business Data

- Are discrepancies, missing evidence and uncertain core data visible at the relevant moment?
- Is immediate visibility being confused with artificial urgency?

### AI

- Is AI processing state clear?
- Is uncertainty visible?
- Is user confirmation requested where responsibility transfers?
- Can users correct the suggestion?

### Communication

- Does the feedback follow Part 11?
- Is it calm, direct and non-blaming?
- Is the next action obvious?

### Consistency

- Do equivalent conditions use equivalent feedback?
- Are status terms consistent?
- Does the treatment feel recognizably Minty?

Copilot should classify findings as:

1. **Critical Data Integrity Issue**  
 Work may be lost or a materially incorrect final outcome may be created.
1. **Responsibility Issue**  
 It is unclear whether Minty or the user must act.
1. **Core Data Feedback Issue**  
 Important business-data quality is not flagged at the relevant moment.
1. **Completion Issue**  
 The user cannot understand why work cannot continue or how to recover.
1. **Warning Noise Issue**  
 Feedback is more disruptive than its consequence justifies.
1. **System Status Issue**  
 Saving, processing, uploading or integration status is unclear.
1. **AI Transparency Issue**  
 AI uncertainty or user-confirmation requirements are hidden.
1. **Consistency Issue**  
 Equivalent system states use different feedback without justification.
1. **Enhancement**  
 The feedback works but could become clearer, calmer or less disruptive.

## 10.46 Feedback Specification Template

### Experience

**Page, form or workflow:**

**Module:**

**Mental Mode:**

**Primary device:**

### Condition

**What happened:**

**Category:**

- System Failure
- Core Business Data Issue
- User Judgement Required
- Business Issue
- Administrative or Convenience Issue

### Responsibility

**Minty can resolve:**

**User action required:**

**Third-party or integration action required:**

### Consequence

**Risk of data loss:**

**Impact on core business data:**

**Impact on current completion:**

**Business urgency:**

**Administrative importance:**

### Timing

- Immediate and Interruptive
- Immediate but Non-Interruptive
- Persistent Awareness
- Passive or Deferred

### Feedback Mechanism

- Silent Handling
- Inline Supporting Text
- Field Feedback
- Status Indicator
- Temporary Confirmation
- Inline Alert
- Page Banner
- Modal
- Dedicated Recovery Experience
- External Notification

### Message

**What happened:**

**What the user should do:**

**Reason, if needed:**

**Support path:**

### Recovery

**Data preserved:**

**Retry supported:**

**Resume location:**

**Escalation path:**

### AI

**AI state:**

**Uncertainty:**

**User confirmation:**

**Correction method:**

### Resolution

**How feedback disappears or changes after resolution:**

## 10.47 Governing Principles

Minty should surface problems based on responsibility and consequence, not technical severity alone.

Minty should communicate immediately where:

- work may be lost;
- core business data is questionable;
- completion is affected;
- or user judgement is required.

Minty should not interrupt users merely because:

- a future risk exists;
- optional information is incomplete;
- or a business issue is not ready for immediate resolution.

The final principles are:

**Protect the user’s work first.**

**Flag questionable core business data when it becomes known.**

**When responsibility transfers to the user, communicate immediately.**

**Use awareness for business issues and interruption for issues requiring action now.**

**Use the least disruptive feedback that still protects completion, data integrity and trust.**

**Never show success before Minty has reliably completed its responsibility.**

**Immediate visibility does not always mean urgency.**

**Minty should solve quietly where it can and explain clearly where it cannot.**
