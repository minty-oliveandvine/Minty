<!-- Mirror of "Minty Existing UI Design Intent Recovery Audit v0 (based on screenshots 16 Sep 2026).docx" (converted by scripts/design_docs_to_md.py). The Word file is the master: do not edit here - re-run the script on the new file. -->

## Minty Existing UI Design Intent Recovery Audit v0.1

### Working Document

#### Purpose

This document records the recovered design intent behind the current Minty UI.

It exists because Minty was developed across multiple projects, teams, designers, developers and time periods. Different screens may look inconsistent, but not all variation is accidental.

The purpose of this audit is to determine:

- why each screen family was designed the way it was;
- whether the underlying intention remains valid;
- whether the implementation remains valid;
- which variations should be preserved;
- which variations should be standardized;
- and which patterns should become future Minty standards.

This document should be treated as a working analysis document.

Current screens are evidence of previous design decisions.

They should not automatically be treated as the future Minty standard.

## Audit Framework

For each screen family we capture:

1. Current screen
1. Product Goal
1. User Perceived Goal
1. Mental Mode
1. Work Type
1. Original Design Intention
1. Valid Intention to Preserve
1. Implementation to Reconsider
1. Provisional Recommendation

## Audit 1

## Petty Cash Dashboard

#### Screens

- Petty Cash Dashboard
- Related dashboard states

#### Product Goal

- Ensure Daily Closing is completed.
- Prevent missed operational work.
- Support operational discipline.

#### User Perceived Goal

What work still needs to be completed today?

#### Mental Mode

**Work Coordination**

#### Work Type

**Scheduled Operational Work**

#### Original Design Intention

The dashboard was created to:

1. Remind users that today's closing is incomplete.
1. Show how delayed prior closings are.
1. Provide shortcut entry points to work.
1. Use available screen space when navigation was less mature.

#### Valid Intentions to Preserve

✅ Daily progress reminder

✅ Visibility of overdue work

✅ Clear entry point into Daily Closing

#### Implementation to Reconsider

⚠ Monthly calendar may be more than necessary.

⚠ Simpler weekly progress representation may be sufficient.

⚠ Quick-launch buttons partly compensated for an earlier navigation structure and may need reevaluation.

#### Provisional Recommendation

Retain:

- Work coordination purpose.
- Progress visibility.

Reevaluate:

- Calendar design.
- Launcher area.

The dashboard should not evolve into a management reporting dashboard.

## Audit 2

## Daily Closing Review Screens

#### Screens

- 07 Ending — Summary.png
- 10 Report View — Submitted.png [Part 2C. M...Work Model | Word]

### Screen A

#### Ending Summary

#### Product Goal

Validate completeness before submission.

#### User Perceived Goal

Did I enter everything correctly?

#### Mental Mode

**Work Verification**

#### Work Type

**Scheduled Operational Work**

#### Valid Intention

This page is still part of work completion.

It is not a management report.

#### Recommendation

Treat as a verification step rather than a review page.

### Screen B

#### Submitted Report View

#### Product Goal

Provide visibility into the completed day.

#### User Perceived Goal

What happened today?

#### Mental Mode

**Operational Review**

#### Work Type

**Scheduled Operational Work**

#### Valid Intention

Provide a clean operational summary.

#### Recommendation

Maintain separation between:

- Work Verification
- Operational Review

Even if the screens share similar information.

## Audit 3

## Report History

#### Screens

- Report History
- History Navigation

#### Product Goal

Access historical records.

#### User Perceived Goal

Where is that report?

#### Mental Mode

**Historical Retrieval**

#### Current User Behaviour

Most common:

✅ Find a past report

Secondary:

✅ Periodic historical review

#### Future User Desire

Future users would like:

- trend review
- operational comparison

Dream future:

- anomaly investigation

#### Critical Recovery Finding

Report History should not evolve into:

- an analytics page
- a management dashboard
- an exception-investigation page

Those should become separate experiences.

#### Recommendation

Maintain:

**Historical Retrieval**

Future additions should become:

- Analytics
- Insights
- Exception Investigation

as separate surfaces.

## Audit 4

## Payment Request List

#### Screens

- Easy View
- Table View
- Expanded Easy View Preview
- Status Views

#### Product Goal

- Control payments
- Avoid duplicate payments
- Maintain accounting support
- Maintain auditability

#### User Perceived Goal

Make sure the vendor gets paid so they do not get angry, but never overpay them.

#### Mental Mode

Work Coordination

#### Work Type

**Triggered Operational Work**

### Easy View

#### Intended User

- Owner
- Family member
- Trusted manager
- Less accounting-oriented treasury user

#### User Question

Should I pay this?

#### Information Needed

Examples:

- When was this supplier paid last?
- Have we already entered this invoice?
- What future payments are likely?
- Does something look suspicious?

#### Key Observation

Invoice due date is often less important than:

- business relationship
- practical judgement
- recent payment history

#### Valid Intention

✅ Simpler decision support

✅ Less accounting-heavy

✅ More approachable

### Table View

#### Intended User

- Accountant
- Finance user
- Treasury user comfortable with accounting information

#### User Question

What should I process?

#### Information Needed

- Status
- Dates
- Supporting documents
- Processing controls
- Accounting visibility

#### Valid Intention

✅ Operational processing

✅ Efficient review

✅ Information density where justified

### Major Recovery Finding

The current distinction is not:

Simple view versus Detailed view

The actual distinction is:

Non-accounting treasury user versus accounting-oriented treasury user

#### Recommendation

Preserve the existence of both viewpoints.

Do not automatically standardize them into one presentation.

Future implementation may move away from a simple UI toggle and toward capability-aware experiences.

## Audit 5

## Settings

#### Screens

- User Management
- Settings
- Entity Setup
- Payment Settings
- Integrations

#### Product Goal

Configure and operate Minty correctly.

#### Recovery Finding

Settings currently contains two fundamentally different jobs.

### Category A

#### System Configuration

#### Examples

- Xero
- Account Codes
- Sales Methods
- Payment Methods

#### Product Goal

Get the accounting support system operating correctly.

#### User Perceived Goal

Most common:

Make Minty work.

or

My accountant told me to do this.

#### Mental Mode

**System Configuration**

### Category B

#### People & Access

#### Examples

- Users
- Invitations
- Roles
- Access

#### Product Goal

Access control and permissions.

#### User Perceived Goal

Did the invitation send?

and

Can my staff use Minty?

#### Mental Mode

**People & Access**

### Recovery Finding

These are not the same user problem.

They should not automatically be grouped together merely because both currently live under Settings.

#### Recommendation

Future information architecture should consider distinguishing:

- Configuration Management
- People & Access Management

through navigation, tabs, sections or dedicated areas.

## Audit 6

## User Invitation

#### Screens

- Users
- Invite User
- Edit User

#### Product Goal

- Access control
- Security
- Permissions

#### User Perceived Goal

Primary:

Did the invitation send?

Secondary:

Will they know what to do after joining?

#### Mental Mode

**People & Access**

#### Recovery Finding

User invitation is primarily an enablement experience.

It is not perceived as a permission-management task.

#### Valid Intention

✅ Focus on successful invitation

✅ Focus on staff participation

#### Recommendation

Permission complexity should remain secondary to onboarding success.

## Audit 7

## Subscription

#### Screens

- Module Selection
- Subscription Overview
- Invoice Detail

### Subscription Selection

#### Product Goal

Enable subscription adoption.

#### User Perceived Goal

Which capability do I want?

and

Which option provides the right value?

#### Mental Modes

- Feature Selection
- Commercial Decision

#### Recovery Finding

This is primarily a purchase decision.

Not a billing review experience.

### Subscription Overview

#### Product Goal

Manage subscription status.

#### User Perceived Goal

Am I paying the right amount?

Am I accidentally overpaying?

#### Mental Mode

**Commercial Decision**

#### Recovery Finding

This is not an operational dashboard.

It is a decision-support experience.

### Invoice Review

#### Product Goal

Provide billing transparency.

#### User Perceived Goal

Why was I charged?

#### Mental Mode

**Commercial Detail Review**

#### Recovery Finding

Invoice Review should not be conflated with Subscription Overview.

Different mental modes.

Different purposes.

## Cross-System Recovery Findings

### Finding A

#### Modules are implementation boundaries

Examples:

- Petty Cash
- Payment Request
- Settings
- Subscription

describe product organization.

They do not describe user intent.

### Finding B

#### Mental Modes are UX boundaries

The user's question should drive:

- Information hierarchy
- Actions
- Layout
- Navigation

more strongly than the module name.

### Finding C

#### Same Archetype does not require identical layout

Differences may be valid when they reflect:

- different capability levels;
- different mental modes;
- different work types;
- different user goals.

### Finding D

#### Historical variation is not automatically justified

Some UI choices existed because:

- Designers differed.
- Developers differed.
- Navigation was immature.
- Blank space needed to be filled.

These should be revalidated rather than automatically preserved.

### Finding E

#### Product Goal constrains User Perceived Goal

Minty should optimize for User Perceived Goal.

However, Product Goals remain important because they enforce:

- accounting accuracy;
- reconciliation integrity;
- payment control;
- auditability;
- security;
- subscription integrity.

The UI should make these constraints feel supportive rather than oppressive.
