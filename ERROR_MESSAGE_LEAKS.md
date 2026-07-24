# Error & warning message audit

Audit of user-facing error/warning messaging across the app. Covers three
classes of defect:

1. **Raw exception text leaking to users** — `error.message` / `str(e)` shown verbatim
2. **Misleading or inaccurate copy** — messages that state the wrong outcome or cause
3. **Inconsistent tone & delivery** — blocking `alert()` vs toast, `'Error: '` prefixes

Status: **audit only — nothing fixed yet.** Counts below supersede the earlier
version of this document, which undercounted and contained a false claim (see
"Corrections" at the bottom).

---

## The fix pattern

`templates/report/expense.html` already establishes the right shape for the
frontend — tag errors the server actually authored:

```js
const serverError = new Error(errorData.message || 'Network response was not ok');
serverError.fromServer = Boolean(errorData.message);
throw serverError;
```

…and only show `error.message` when that flag is set:

```js
showFlashMessages(
  error && error.fromServer && error.message
    ? error.message
    : "I couldn't add that contact. Mind trying again?",
  'error'
);
```

Anything reaching `.catch()` **without** `fromServer` is a JS/parser failure and
must not be surfaced verbatim.

---

## The copy standard

Every replacement string in this document follows these rules. They are derived
from the only three strings in the repo already written in the intended voice:

```
"I couldn't add that contact. Mind trying again?"      templates/report/expense.html:2684
"I couldn't send that invitation. Mind trying again?"  templates/entity/settings_users_scripts.html:443
"Who should I put down as the contact?"                showFlashMessages call site
```

**Rules**

1. **Under two sentences.** One clause naming what failed, one short offer to
   retry. Never a third.
2. **First person, Minty speaking.** *"I couldn't …"* — not *"Error:"*, not
   *"The system encountered"*, not *"Failed to"*.
3. **Name the specific thing.** *"that invitation"*, *"that expense"* — never
   *"the operation"* or *"your request"*.
4. **Warm close, no blame.** *"Mind trying again?"* is the house default. Drop it
   when retrying won't help (a validation error, a hard limit) and say what to do
   instead.
5. **No error codes, stack text, or jargon** in the visible string. That detail
   goes to DataDog/logs, never the toast.
6. **Sentence case, no `Error:` prefix, no exclamation marks** on failures.

**Shape**

> `I couldn't <do the specific thing>. <Short next step>?`

Validation and limit messages skip the apology — they aren't Minty's fault and
retrying unchanged won't fix them. State the requirement instead:

> `Files need to be under 10MB.`
> `Pick a start and end date first.`

---

# Class 1 — Raw exception text leaking to users

## 1a. Frontend — 22 sites

### `templates/entity/settings_users_scripts.html` — 4 sites
Highest priority: user-management screen, all four bare `'Error: ' + err.message`.

| Line | Context | Suggested copy |
|---|---|---|
| 776 | update user | `I couldn't update that user. Mind trying again?` |
| 822 | remove user | `I couldn't remove that user. Mind trying again?` |
| 984 | cancel invitation | `I couldn't cancel that invitation. Mind trying again?` |
| 1020 | resend invitation | `I couldn't resend that invitation. Mind trying again?` |

Lines 984 and 1020 log to DataDog on the line above — keep that, replace only the toast.

Line **437** in this file is also worth fixing while you're here:
`showErrorToast(data.message || 'Unknown error.')` — the fallback `Unknown error.`
is the opposite of the house voice. Use `I couldn't send that invitation. Mind trying again?`,
matching line 443 four lines below it.

### `templates/entity/settings.html` — 3 sites
Lines **2757**, **3595**, **4724** — all `showErrorToast('Error creating contact: ' + error.message);`

### `templates/entity/partials/xero_mapping_classic_script_fragment.html` — 3 sites
Lines **1925**, **2763**, **3892** — identical to the above.

All six: `I couldn't add that contact. Mind trying again?` — the exact string
already live at `templates/report/expense.html:2684`.

> These six create-contact handlers are the same duplicated block. Worth
> collapsing into one shared function rather than fixing six times.

### `templates/report/expense.html` — 6 sites
| Line | Current | Suggested copy |
|---|---|---|
| 1571 | `'...unable to save your expense information: ' + error.message` | `I couldn't save that expense. Mind trying again?` |
| 3302 | `alert('Error updating expense: ' + (data.message \|\| 'Unknown error'))` | `I couldn't update that expense. Mind trying again?` |
| 3309 | `alert('Error updating expense. Please try again.')` | `I couldn't update that expense. Mind trying again?` |
| 4000 | `alert('Error deleting expense: ' + (data.message \|\| 'Unknown error'))` | `I couldn't delete that expense. Mind trying again?` |
| 4015 | `alert('Error deleting expense: ' + error.message)` | `I couldn't delete that expense. Mind trying again?` |
| 4270 | `'...unable to save your expense information: ' + error.message` | `I couldn't save that expense. Mind trying again?` |

All six also need `alert()` → toast (Class 3). This file already has the
`fromServer` guard elsewhere — these were missed.

The two CSRF alerts in the same file (**3265**, **3958**,
`'Error: CSRF token not found. Please refresh the page.'`) are a different case:
retrying won't help, so skip the apology and give the action —
`Your session expired. Refresh the page to keep going.`

### `templates/download_statements.html` — 1 site
Line **157**: ``alert(`Error: ${error.message}`)``. Logs to DataDog above — keep that.
Suggested: `I couldn't download those statements. Mind trying again?`

Line **104** in the same file is a validation message, not a failure —
`'Please select a start date and end date.'` → `Pick a start and end date first.`

### `static/js/` — 3 sites
`opening.js:179`, `expense.js:398`, `scripts.js:775` — all
``alert(`Error: ${data.message || 'An unknown error occurred.'}`)``.
Server-authored `data.message`, so lower risk, but blocking `alert()` and
`'Error: '` prefix both need normalizing. Fallback copy, per file:
`I couldn't save that opening entry. Mind trying again?` /
`I couldn't add that expense. Mind trying again?` /
`I couldn't save that. Mind trying again?`

## 1b. Backend — 13 user-facing sites

`str(e)` / `str(exc)` placed directly into a response body:

| File | Line(s) |
|---|---|
| `blueprints/auth/routes/tokens.py` | 20, 35 |
| `blueprints/entity/routes/billing_sync.py` | 66, 105, 149 |
| `blueprints/entity/services/settings.py` | 1580 |
| `blueprints/xero/routes/settings.py` | 72, 126 |
| `blueprints/report/routes/submitted.py` | 369 |
| `blueprints/report/routes/download.py` | 39 |
| `blueprints/report/routes/history.py` | 53 |
| `blueprints/report/routes/export_screenshot.py` | 443 |
| `blueprints/report/services/report_detail.py` | 34 |
| `blueprints/report/services/ending.py` | 165 |
| `services/helpers/xero_bridge.py` | 194 |

Fix: log the exception server-side, return a generic message in the body.

Backend strings follow the same standard — these are rendered directly by
clients that surface `message` to the user:

| Context | Suggested copy |
|---|---|
| token refresh/exchange (`tokens.py`) | `I couldn't refresh your Xero connection. Mind reconnecting?` |
| billing sync (`billing_sync.py`) | `I couldn't sync with Xero. Mind trying again?` |
| entity settings save (`settings.py:1580`) | `I couldn't save those settings. Mind trying again?` |
| Xero settings (`xero/routes/settings.py`) | `I couldn't save those Xero settings. Mind trying again?` |
| report download/detail/export | `I couldn't open that report. Mind trying again?` |
| report history (`history.py:53`) | `I couldn't load your report history. Mind trying again?` |
| ending balance (`ending.py:165`) | `I couldn't save that closing balance. Mind trying again?` |
| Xero API bridge (`xero_bridge.py:194`) | `I couldn't reach Xero just now. Mind trying again?` |

**Not** in scope — these are logger calls, correctly keeping detail server-side:
`services/auth/token_service.py` lines 84, 118, 134, 182, 226, 262.

---

# Class 2 — Misleading / inaccurate copy

### Failures reported as successes — `blueprints/entity/routes/billing_sync.py`
Lines **66**, **105**, **149** return **HTTP 200** with `{"skipped": true,
"reason": "exception"}` after catching a real exception. A caught exception is a
failure, not a skip — any client treating 200 as success will silently believe
the sync worked.

Two separate bugs on one line: wrong status semantics *and* a leaked `str(exc)`.
Decide whether these should be 5xx, or a 200 with an explicit `"status":
"failed"` the client actually checks.

### Wrong severity — `blueprints/report/routes/download.py:39`, `report_detail.py:34`, `export_screenshot.py:443`
All return **404** from a generic `except Exception`. A crash is not "not
found" — this misreports server faults as missing resources and will mislead
anyone reading logs or metrics.

### Placeholder copy shipped to users — 14 sites
`'This feature is currently in progress, Stay Tuned!'` (11 sites) and
`'... would be implemented here'` (`templates/report/submitted.html:296`, `303`).
Not errors, but user-facing dead ends. Confirm whether these should be hidden,
disabled, or given real copy.

### Misleading default toast — `templates/entity/settings.html:688`
`function showErrorToast(message = 'Please connect to Xero and set up Entity Settings')`
— any caller invoking `showErrorToast()` with no argument tells the user to
connect Xero regardless of the real cause.

Defaults must be cause-neutral, since they fire for unknown reasons. Use
`Something went wrong on my end. Mind trying again?` for all four duplicate
implementations' defaults (see Class 3), and let callers pass the specific string.
Same applies to `settings_entity.html:2291` and
`electronic_delivery_scripts.html:1544`, both defaulting to
`'Error updating entity settings'`.

---

# Class 3 — Inconsistent tone & delivery

### Blocking `alert()` — ~45 sites
The app has a toast system (`templates/components/flash_messages.html`,
`showFlashMessages`), but ~45 call sites still use blocking `alert()`, including
every error path in `templates/report/` (`deposit`, `cash_count`, `sales`,
`opening`, `ending`, `expense`) and all of `static/js/`.

Worst offender — `templates/report/cash_count.html:1218`:
`alert('Saving data and proceeding to next step...')` — a blocking modal for a
*progress* message. This shouldn't be a message at all; use the existing saving
indicator.

Recurring strings and their replacements:

| Current (repeated across report/) | Suggested copy |
|---|---|
| `An error occurred while saving. Please try again.` (8 sites) | `I couldn't save that. Mind trying again?` |
| `Please complete the current report before navigating away.` (4 sites) | `Finish this report first, then you can move on.` |
| `File size must be less than 10MB` | `Files need to be under 10MB.` |
| `Please upload PDF, JPEG, or PNG files only` | `I can take PDF, JPEG, or PNG files.` |
| `Please fix the validation errors before submitting.` | `Some fields need a second look before I can save.` |
| `Please fill in all required fields and ensure valid values.` | `A few required fields still need filling in.` |
| `Could not find expense details` / `Could not find expense to edit.` | `I couldn't find that expense.` |
| `Could not save modules. Please try again.` | `I couldn't save those modules. Mind trying again?` |
| `At least one module should be active.` | `Keep at least one module active.` |
| `You can only delete the latest submitted report. A newer report exists.` | `Only the newest report can be deleted.` |
| `An error occurred while processing the connection. Please try again.` | `I couldn't finish connecting. Mind trying again?` |
| `Form elements not found. Please refresh the page.` | `Something got out of sync. Refresh the page to keep going.` |

Note the validation rows drop *"Please"* and the apology — they state the rule
directly, per rule 4 of the copy standard.

### Five duplicate toast implementations
`showErrorToast` / `showSuccessToast` are redefined independently in:
- `templates/entity/settings_users_scripts.html:304, 326`
- `templates/entity/settings_entity.html:2291, 2320`
- `templates/entity/settings.html:688, 718`
- `templates/entity/partials/electronic_delivery_scripts.html:1544, 1579`

…each with different default messages, alongside the shared
`showFlashMessages` in `templates/components/flash_messages.html:86`.
Consolidating these is a prerequisite for consistent tone — otherwise every copy
fix has to be made four times.

### `'Error: '` prefix
~10 sites prefix user copy with `Error: `. The repo's established voice (per the
`fromServer` examples) is conversational — *"I couldn't … Mind trying again?"*.

---

# Corrections to the previous version of this doc

- **The claim "Python/backend leaks are fixed (commit `ad9a952c`)" is false.**
  That SHA does not exist in this repository (`git cat-file -t ad9a952c` →
  *Not a valid object name*), and no commit in the log matches an
  error-message/leak fix. **13 backend leaks are live.** Treat the old
  "backend is done" status as unverified.
- Frontend count was **12**, actually **22**.
- Line numbers for `templates/entity/settings.html` had drifted:
  2667/3505/4634 → now **2757/3595/4724**.
- `blueprints/xero/routes/settings.py:72` was listed as a footnote; it is one of
  13 equivalent backend sites, and line **126** in the same file was missed.

---

## Suggested fix order

1. Consolidate the five duplicate toast implementations (prerequisite — otherwise
   every copy fix must be made four times)
2. Backend `str(e)` leaks (security-adjacent)
3. Frontend `error.message` leaks
4. Misleading status codes (`billing_sync` 200s, the three 404s)
5. Tone pass — `alert()` → toast, drop `'Error: '` prefixes

## How to verify a fix

Force a non-JSON error response (make the endpoint 500, or point it at a URL
returning HTML) and confirm the toast shows the friendly copy rather than
`Unexpected token '<'`.
