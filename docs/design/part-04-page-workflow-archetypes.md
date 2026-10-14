<!-- Mirror of "Part 4. Page & Workflow Archetypes.docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

## Part 4. Page & Workflow Archetypes

### Version 1.0 Draft

## 4.1 Purpose

This document defines the approved Page and Workflow Archetypes used throughout Minty.

An archetype describes:

The structural shape of an experience.

It defines:

- how information is organized;
- how actions are organized;
- how content is consumed;
- how information is entered;
- and how the user progresses through the experience.

An archetype does **not** define:

- the user profile;
- the Mental Mode;
- the Work Type;
- the Product Goal;
- or the User Perceived Goal.

Those are defined elsewhere.

## 4.2 Relationship with Other Design Guideline Chapters

Before selecting an archetype, identify:

Product Goal

↓

User Perceived Goal

↓

User Profile

↓

Mental Mode

↓

Work Type

↓

UX Boundary

↓

Archetype

↓

Layout

↓

Components

The purpose of Part 4 is not to define why users are present.

The purpose of Part 4 is to define:

What structural pattern should be used once those questions are already answered.

## 4.3 Archetype Design Principles

### Principle 1

#### Fewer Archetypes Are Better

Minty should maintain a small number of reusable archetypes.

Creating new archetypes should be rare.

Whenever possible:

- reuse an existing archetype;
- use an approved variant;
- use information hierarchy differences;
- use component differences;

before creating a completely new archetype.

### Principle 2

#### Structured Consistency

Users do not need every page to look identical.

Users should be able to recognize:

- how information is organized;
- where actions appear;
- how records behave;
- how workflows progress.

Archetypes support structural consistency.

### Principle 3

#### One Archetype Can Support Multiple Mental Modes

Example:

A Dashboard can support:

- Work Coordination
- Commercial Decision
- Operational Review

through different variants.

Mental Modes and Archetypes are separate concepts.

## 4.4 Approved Core Archetypes

Minty currently recognizes nine core archetypes.

| **Archetype** | **Primary Purpose** |
|---|---|
| Dashboard | Summarize information to support understanding, action or decisions |
| List Page | Browse, locate and compare records |
| Detail Page | Understand one record |
| Record Form | Create or edit information |
| Workflow | Complete a multi-step activity |
| Report Page | Review completed outcomes |
| Selection Page | Choose context or capability |
| Empty State | Guide the user when no content exists |
| Confirmation Modal | Support focused temporary decisions |

## 4.5 Dashboard Archetype

### Definition

A Dashboard presents summarized information intended to help the user:

- understand;
- decide;
- or act.

A Dashboard is not:

- a data dump;
- a report;
- a record list;
- or a workflow.

A Dashboard should highlight only the most important information.

## 4.5.1 Dashboard Variants

### Action Dashboard

Primary question:

What should I do?

Examples:

- Petty Cash Dashboard
- Future work queues
- Future operational launch pages

Primary information:

- work requiring attention;
- progress;
- delays;
- next action.

Primary action:

- continue work.

Information hierarchy:

Work Requiring Attention

↓

Next Action

↓

Progress

↓

Supporting Information

Supports Mental Modes such as:

- Work Coordination

### Decision Dashboard

Primary question:

What should I choose?

Examples:

- Subscription Overview
- Future upgrade recommendations
- Future feature recommendations

Primary information:

- current position;
- current commitment;
- available choices;
- recommendation.

Primary action:

- make a decision.

Information hierarchy:

Current Position

↓

Recommendation

↓

Available Options

↓

Supporting Information

Supports Mental Modes such as:

- Commercial Decision

### Monitoring Dashboard

Primary question:

What is happening?

Examples:

- Future Business Monitor
- Future operational monitoring
- Future analytical summaries

Primary information:

- trends;
- KPIs;
- alerts;
- indicators.

Primary action:

- understand.

Information hierarchy:

Summary

↓

Indicators

↓

Trends

↓

Supporting Insight

Supports Mental Modes such as:

- Operational Review

## 4.6 List Page Archetype

### Definition

A List Page allows users to:

- browse;
- locate;
- filter;
- sort;
- compare;
- and access records.

The List Page is one of Minty's most reusable archetypes.

## 4.6.1 List Variants

### Operational List

Primary question:

What requires attention?

Examples:

- Payment Request List
- Approval queues
- Active operational records

Characteristics:

- active records;
- significant status visibility;
- action-heavy;
- work-oriented.

### Historical Retrieval List

Primary question:

Where is that record?

Examples:

- Report History
- Historical records
- Future archives

Characteristics:

- chronology important;
- retrieval-focused;
- completed records;
- lower emphasis on actions.

Important note:

Historical Retrieval is treated as a specialized List variant rather than a standalone archetype.

### Administrative List

Primary question:

Which item do I want to manage?

Examples:

- Users
- Entities
- Setup catalogues

Characteristics:

- management-focused;
- lower urgency;
- administrative actions.

## 4.7 Detail Page Archetype

### Definition

A Detail Page explains one record.

Primary question:

What is this?

Examples:

- Payment Request Detail
- User Detail
- Invoice Detail

A Detail Page prioritizes:

Summary

↓

Status

↓

Supporting Information

↓

Actions

Detail Pages explain.

They do not primarily coordinate work.

## 4.8 Record Form Archetype

### Definition

A Record Form creates or edits information.

Primary question:

What information must be entered?

Examples:

- Create Payment Request
- Edit User
- Setup Configuration

A Record Form prioritizes:

Required Information

↓

Optional Information

↓

Validation

↓

Save / Submit

The primary responsibility is:

- input;
- editing;
- validation.

## 4.9 Workflow Archetype

### Definition

A Workflow guides users through a multi-step activity.

Primary question:

What step comes next?

Examples:

- Daily Closing
- Onboarding
- Future AI intake and routing
- Future guided operational tasks

### Workflow Characteristics

Workflows typically contain:

- multiple steps;
- progression;
- validation;
- completion.

The number of steps may vary significantly.

Examples:

#### Daily Closing

Many operational steps.

#### Onboarding

Several setup steps.

#### AI Intake

Potentially only a few quick steps.

Although these experiences differ, they share the same structural goal:

Help the user reach completion efficiently.

Therefore Minty treats them as one archetype.

### Workflow Principles

#### Completion First

Users generally want:

Get this done.

The workflow should not create unnecessary friction.

#### Product Goal Creates Steps

Multiple steps should exist only when required by:

- Product Goals;
- business rules;
- verification needs;
- or meaningful guidance requirements.

#### Navigation Should Be Flexible

Users should not be unnecessarily trapped inside a workflow.

Restrictions should exist only where justified.

## 4.10 Report Page Archetype

### Definition

A Report Page communicates outcomes and results.

Primary question:

What happened?

Examples:

- Submitted Daily Report
- Future summarized business reports

Report Pages emphasize:

Summary

↓

Key Figures

↓

Supporting Detail

↓

Administrative Information

A Report Page is not:

- a Dashboard;
- a Workflow;
- or a List.

Reports focus on understanding completed outcomes.

## 4.11 Selection Page Archetype

### Definition

A Selection Page helps users make a choice before proceeding.

Primary question:

Which option should I select?

Selection Pages reduce uncertainty.

They should not overwhelm users with unnecessary choices.

## 4.11.1 Selection Variants

### Context Selection

Primary question:

Which business am I working on?

Examples:

- Select Entity
- Select Company

Purpose:

Establish work context.

### Feature Selection

Primary question:

Which capability do I want?

Examples:

- Module Selection
- Subscription Module Selection

Purpose:

Choose product capability.

## 4.12 Empty State Archetype

### Definition

An Empty State helps users continue when no content exists.

Primary question:

What should I do next?

An Empty State should:

- explain;
- reassure;
- guide;
- encourage action.

An Empty State should never simply say:

No data.

without providing meaningful direction.

## 4.13 Confirmation Modal Archetype

### Definition

A Confirmation Modal supports a temporary focused decision.

Primary question:

Are you sure?

Examples:

- Submit
- Delete
- Confirm Payment
- Cancel

Information hierarchy:

Action

↓

Consequence

↓

Confirm

↓

Cancel

Confirmation Modals should not contain complex workflows.

## 4.14 Archetypes vs Mental Modes

A common mistake is confusing archetypes with Mental Modes.

Examples:

| **Mental Mode** | **Possible Archetypes** |
|---|---|
| Work Coordination | Action Dashboard, Operational List |
| Work Verification | Workflow Step, Report-like Summary |
| Operational Review | Monitoring Dashboard, Report Page |
| Historical Retrieval | Historical Retrieval List |
| Commercial Decision | Decision Dashboard, Selection Page |
| Commercial Detail Review | Detail Page, Report Page |

Mental Modes answer:

Why is the user here?

Archetypes answer:

What structural pattern is being used?

## 4.15 Archetypes vs Work Types

A common mistake is confusing archetypes with Work Types.

Examples:

| **Work Type** | **Possible Archetypes** |
|---|---|
| Scheduled Operational Work | Workflow, Report, Action Dashboard |
| Triggered Operational Work | List, Form, Detail |
| Configuration Work | Form, Detail, List |
| People & Access Work | List, Form, Detail |
| Commercial Work | Decision Dashboard, Selection, Detail |
| Future AI-Routed Work | Workflow, Detail, Selection |

Work Types answer:

What kind of work exists?

Archetypes answer:

What structure should be used?

## 4.16 Archetype Selection Checklist

Before creating a page:

### Step 1

Identify:

- Product Goal
- User Perceived Goal

### Step 2

Identify:

- User Profile
- Mental Mode
- Work Type

### Step 3

Review relevant UX Boundaries.

### Step 4

Choose the simplest archetype that can satisfy the user objective.

### Step 5

Only create a new archetype if:

- existing archetypes cannot support the experience;
- variants are insufficient;
- and the distinction is justified by a validated UX boundary.

New archetypes should be extremely rare.

## 4.17 Approved Archetype Matrix

| **Archetype** | **Approved Variants** |
|---|---|
| Dashboard | Action, Decision, Monitoring |
| List Page | Operational, Historical Retrieval, Administrative |
| Detail Page | None |
| Record Form | None |
| Workflow | None |
| Report Page | None |
| Selection Page | Context Selection, Feature Selection |
| Empty State | None |
| Confirmation Modal | None |

## 4.18 Governing Principle

Minty should rely on:

- a small number of reusable archetypes;
- carefully defined variants;
- shared visual foundations;
- and consistent decision-making patterns.

The objective is not to create many specialized page types.

The objective is to create:

**A small number of well-understood structural patterns that can support many user goals while remaining unmistakably Minty.**
