<!-- Mirror of "Part 11. Writing, Content & Minty Voice.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

## Part 11. Writing, Content & Minty Voice

### Version 1.1 Draft · 7 October 2026 (§11.30 rewritten: English-only interface; localization = country accounting terms)

## 11.1 Purpose

This chapter defines how Minty communicates with users.

It governs:

- labels;
- helper text;
- buttons;
- validation;
- empty states;
- AI explanations;
- notifications;
- onboarding;
- workflow guidance;
- success messages;
- support experiences;
- and other user-facing content.

Minty's communication should always support the Experience Principles, Product Goals, and User Perceived Goals defined in previous chapters.

This chapter is not intended to replace the detailed copy libraries and message banks maintained elsewhere.

Instead, this chapter defines:

**Why Minty communicates in a particular way.**

and

**How teams should make communication decisions when no existing copy exists.**

## 11.2 Purpose of Communication

Minty's communication exists to help users achieve outcomes.

It does not exist to:

- show system intelligence;
- show accounting expertise;
- explain internal architecture;
- expose technical complexity;
- impress users with terminology;
- or demonstrate compliance knowledge.

The purpose of communication is:

Help user understand

↓

Help user decide

↓

Help user act

↓

Help user finish

Communication should reduce uncertainty and support completion.

## 11.3 Core Communication Philosophy

Minty should communicate as:

A capable helper

not:

A teacher

An auditor

A compliance officer

A controller

A finance lecturer

The role of Minty is:

**To absorb complexity and help users finish work properly with less stress.**

Communication should always feel:

- supportive;
- practical;
- calm;
- human;
- and trustworthy.

Communication should never feel:

- blaming;
- judgmental;
- cold;
- robotic;
- or unnecessarily technical.

## 11.4 Minty's Voice Identity

Minty should feel like:

A calm, competent helper.

Minty is:

- supportive;
- responsible;
- practical;
- sincere;
- reassuring;
- capable.

Minty is not:

- childish;
- sarcastic;
- overly playful;
- authoritarian;
- passive-aggressive;
- condescending.

Minty should feel:

"I'm here to help you finish this properly."

not:

"You made a mistake."

## 11.5 Communication Priorities

When writing content, priorities should be:

1. Clarity

2. Correctness

3. Simplicity

4. Efficiency

5. Personality

Personality should never reduce clarity.

Friendly language should never make important information unclear.

## 11.6 Business Language First

Minty should prefer business language over accounting language whenever practical.

Preferred:

Where should this expense be recorded?

Instead of:

Select nominal ledger account.

Preferred:

Count today's cash.

Instead of:

Perform reconciliation.

Preferred:

Choose who can access this feature.

Instead of:

Assign permission profile.

## 11.7 Accuracy Rule

Business language remains the default.

However:

**Minty should not sacrifice accuracy for simplicity.**

If simplification creates a materially incorrect understanding:

- use the correct term;
- explain the term;
- provide context;
- or show both versions.

Example:

Record this expense under a Xero account.

may be preferable to:

Choose a category.

if category would cause confusion.

The rule is:

Business Language First

unless materially inaccurate.

## 11.8 Practical Translation Principle

When accounting concepts must appear:

Minty should translate them.

Not hide them.

Not assume users understand them.

Example:

Account Code

may become:

Where should Minty record this expense?

Xero Account:

Utilities Expense

The user should understand:

- what the decision means;
- why it matters;
- and how to proceed.

Without needing accounting training.

## 11.9 Communication and Mental Modes

Communication should adapt to Mental Mode.

### Action Mode

Prioritize:

- brevity;
- guidance;
- completion.

Example:

Add today's sales.

Not:

Today's sales information is required for reporting purposes.

### Review Mode

Prioritize:

- understanding;
- comparison;
- explanation.

Future Analytics Example

The following examples illustrate possible future AI-assisted interpretation capabilities.

They are not current Minty behaviours and should not be treated as evidence that Minty currently performs trend analysis, anomaly detection or business interpretation.

Examples:

• Sales increased compared with last week.

• Cash is lower than usual this week.

### Decision Mode

Prioritize:

- implications;
- confidence;
- recommendations.

Example:

Cash is lower than usual this week.

### Configuration Mode

Prioritize:

- explanation;
- consequence;
- long-term impact.

Example:

Choose the Xero account this expense type should use.

## 11.10 One Action Principle

A message should normally guide only one action.

Preferred:

Add today's sales.

Not:

Add today's sales, review expenses, check cash and upload receipts.

Users should not be decoding instructions.

They should be progressing through work.

## 11.11 Reassurance Principle

When:

- anxiety may exist;
- information is missing;
- an error occurred;
- submission failed;
- a difference was detected;
- or work is incomplete;

Minty should reduce stress before requesting action.

Example:

That's okay.

One item is still missing.

Add it here to continue.

However:

not every message requires reassurance.

Ordinary tasks should remain concise.

Avoid:

No worries.

Let's click this button.

for routine actions.

## 11.12 Completion Principle

Every experience should support completion.

Communication should help users:

Start

↓

Understand

↓

Continue

↓

Finish

The user's next action should be obvious.

Messages should pull users forward rather than merely describe system state.

## 11.13 Labels

Labels should:

- describe what the user thinks about;
- use familiar language;
- be concise;
- avoid unnecessary jargon.

Good:

Today's Sales

Date

Team Member

Cash Count

Expense Type

Avoid:

Transaction Processing Date

User Access Classification

Cash Reconciliation Object

Labels belong to users, not databases.

## 11.14 Helper Text

Helper text should answer one of three questions:

What is this?

Why does it matter?

How should I complete it?

Helper text should be short.

Avoid documentation-style explanations.

Use helper text only when necessary.

## 11.15 Buttons and Actions

Action names should describe outcomes.

Preferred:

Save

Continue

Add Expense

Connect Xero

Invite Users

View Summary

Avoid:

Execute

Submit

Proceed

Run

Process

unless a more specific action is unavailable.

Users should understand what the button does before clicking it.

#### Exception: Business Actions May Use Submission Language

Generic system-oriented labels should normally be avoided because they do not communicate the user's practical outcome.

However, submission language may remain appropriate where the business activity itself is naturally understood as a submission.

Examples:

✅ Submit Payment Request  
 ✅ Submit Daily Report  
 ✅ Submit Application

These actions describe a real business event rather than a generic system operation.

The goal is to avoid system-centric language, not to prohibit every use of the word "Submit".

## 11.16 Empty States

Empty states should be useful.

Avoid:

No Data

``

Preferred:

No expenses added yet.

Add an expense when you're ready.

An empty state should explain:

- what exists here;
- why it is empty;
- and what can happen next.

## 11.17 Validation Language

Validation should help users succeed.

Validation should not:

- shame;
- blame;
- or create anxiety.

Avoid:

Error

Invalid

Violation

Mandatory

when simpler language communicates the same meaning.

Preferred:

One detail is still missing.

This doesn't look quite right.

This part is needed to continue.

## 11.18 Validation Structure

Validation messages should follow:

Issue

↓

Required action

↓

Reason (optional)

Example:

The amount is still empty.

Add the amount to continue.

This helps Minty prepare the report.

Users should know:

- what happened;
- what to do;
- and why.

## 11.19 Required Information

Part 9 established:

Block

Draft

Ignore

Part 11 defines how to communicate those states.

### Block

State:

- what is missing;
- how to resolve it.

Do not focus on the failure.

Do not focus on enforcement.

### Draft

State:

- work is saved;
- work is incomplete;
- where the user should resume.

Draft messaging should reduce anxiety.

### Optional Information

Do not create warnings.

Do not create guilt.

Do not pressure users to complete information that is not required.

## 11.20 Success Messages

Completion should feel like relief.

Not inspection.

Good success messages provide:

Recognition

+

Outcome

Examples:

All done.

Today's report is ready.

Saved.

Your changes are ready.

Success messages should be brief.

Avoid excessive celebration.

## 11.21 Serious Financial Moments

Some moments require greater restraint.

Examples:

- payments;
- approvals;
- subscriptions;
- access rights;
- Xero integration;
- accounting outcomes;
- legal consequences.

In these situations:

- reduce playful language;
- increase precision;
- maintain warmth;
- remain calm.

Minty should feel trustworthy first.

Friendly second.

## 11.22 AI Communication

AI should behave as:

Assistant

not:

Authority

AI should:

- explain;
- suggest;
- clarify;
- simplify.

AI should not sound certain when uncertainty exists.

## 11.23 AI Suggestions

AI suggestions should be presented as suggestions.

Example:

Minty thinks this may be a utilities expense.

Not:

Category assigned.

Users should understand:

- this is a suggestion;
- why it was suggested;
- whether confirmation is required.

## 11.24 AI Confidence

Confidence should normally be expressed in practical language.

Preferred:

Minty is fairly confident this is a utilities expense.

or

Minty wasn't able to identify this category.

Avoid exposing technical AI language unless useful.

Users rarely benefit from:

Confidence Score: 82.3%

## 11.25 AI Corrections

When AI is uncertain or incorrect:

Minty should not frame the situation as:

AI error.

Instead:

Minty wasn't able to determine this yet.

Please choose the best match.

The focus remains completion.

## 11.26 Product Goal Communication

When Product Goals require a particular action:

communication should remain:

- direct;
- clear;
- calm.

Part 9 established that compulsory information must be completed before submission.

In those moments:

Choose the Xero account to continue.

is preferable to:

You may wish to choose an account.

The user should clearly understand what is required.

## 11.27 Explanation Depth

Explanation should be proportional to consequence.

Low consequence:

Saved.

Medium consequence:

Choose the payment method.

High consequence:

This payment request will be submitted for approval.

Do not over-explain low-risk actions.

Do not under-explain high-risk actions.

## 11.28 Notifications

Notifications should be:

- timely;
- useful;
- actionable.

Every notification should answer:

What happened?

Why does it matter?

What should I do?

If no action is required, the notification should not imply urgency.

## 11.29 Emails and External Communication

External communication should follow the same principles as in-app communication.

Communication should remain:

- consistent;
- human;
- supportive.

Users should not encounter a different personality across channels.

## 11.30 Language, Translation and Country Accounting Terms

Minty is written and supported in English only. There is no in-app language switch and no second-language copy.

Customers may use their browser’s translate feature, so copy must survive automatic translation:

- write short, plain sentences — no idioms, puns or wordplay in functional copy;
- never build a sentence from fragments (for example ‘Paid ’ + amount + ‘ to ’ + supplier); write complete sentences with placeholders;
- keep amounts, account codes, invoice numbers, entity names and the name ‘Minty’ untranslated (translate="no", Part 13 §13.5);
- never put text inside images.

In Minty, ‘localization’ means country-specific accounting, not interface language. Where a concept differs by country, use the term the customer’s accountant and tax authority use:

- label tax lines with the local name (for example ‘VAT’ for a Korean entity, ‘GST’ for a Singapore entity);
- the entity’s country decides the term, not the user’s browser language;
- currency and amount format follow the entity (Part 14, Amount input).

The objective is the same experience in every country: the same layout and voice, with correct local accounting terms.

## 11.31 Emoji Usage

Emoji are optional.

Use only when:

- they support the message;
- they increase warmth;
- they do not reduce professionalism.

Appropriate:

All done! 🎉

Potentially inappropriate:

Payment approved! 🎉🎉🎉💰💰💰

Financial moments should remain professional.

## 11.32 Content Consistency

Equivalent situations should communicate consistently.

Examples:

The same type of missing amount should not produce:

Field Error

in one place and:

One detail is missing.

in another.

Consistency reduces learning effort.

## 11.33 Communication Anti-Patterns

Avoid:

### Accounting First

Writing from accountant perspective rather than user perspective.

### System Language

Exposing internal processing terminology.

### Warning Noise

Interrupting users unnecessarily.

### Blame Language

Implying user failure.

### Instruction Overload

Combining many actions into one message.

### Technical AI Language

Exposing ML terminology without user value.

### Excessive Cheerfulness

Making serious financial moments feel unprofessional.

### Passive Communication

Describing problems without helping users continue.

### Persona Overload

Forcing Minty's personality into every sentence.

### Empty Messaging

Messages that only describe state without supporting action.

## 11.34 Copilot Review Instructions

When reviewing content, Copilot should evaluate:

### Clarity

- Is the message immediately understandable?
- Could simpler language be used?

### Business Language

- Does wording match how users think?
- Is accounting terminology unnecessarily exposed?

### Completion

- Does the message help users move forward?
- Is the next step obvious?

### Tone

- Is Minty supportive and calm?
- Is Minty avoiding blame?

### Accuracy

- Has communication remained correct?
- Has simplification become misleading?

### Mental Mode

- Does the communication fit the user's current task?

### Consistency

- Does the wording align with equivalent experiences elsewhere?

### AI Communication

- Are suggestions presented appropriately?
- Is uncertainty communicated appropriately?

Findings should be classified as:

1. Critical Clarity Issue
1. Product Goal Communication Issue
1. Mental Mode Mismatch
1. Consistency Issue
1. AI Communication Issue
1. Tone Issue
1. Enhancement

## 11.35 Writing Specification Template

### Context

**Feature:**

**Module:**

**Mental Mode:**

**User Profile:**

### Communication Purpose

**User Perceived Goal:**

**Product Goal:**

**Desired Action:**

### Communication Type

- Label
- Helper Text
- Validation
- Empty State
- Success Message
- Notification
- AI Suggestion
- Email
- Other

### Requirements

**Required information:**

**Business language translation:**

**Accounting terminology exposed:**

**Reason:**

### Tone

**Tone requirements:**

**Reassurance required:**

**Celebration required:**

**Seriousness level:**

### Validation

**Block / Draft / Ignore treatment:**

**Next action:**

### Country Accounting Terms

**Local term (only if country-specific):**

### AI Notes

**AI generated content:**

**Human confirmation required:**

## 11.36 Governing Principles

Minty communicates to help users finish work.

Minty uses business language first.

Minty remains accurate when simplicity risks misunderstanding.

Minty explains complexity instead of exposing it.

Minty avoids blame, jargon and unnecessary warning noise.

Minty supports completion rather than merely describing system state.

Minty treats AI as an assistant that explains and suggests.

Minty remains calm, capable and trustworthy across all channels.

The final principles are:

**Business language first.**

**Simple unless simplicity becomes incorrect.**

**Help the user finish.**

**Reduce stress, not responsibility.**

**Explain complexity. Don't expose it.**

**Supportive, not judgmental.**

**Confident, not commanding.**

**Warm, but never childish.**
