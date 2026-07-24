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

# Class 1 — Raw exception text leaking to users

## 1a. Frontend — 22 sites

### `templates/entity/settings_users_scripts.html` — 4 sites
Highest priority: user-management screen, all four bare `'Error: ' + err.message`.

| Line | Context | Suggested copy |
|---|---|---|
| 776 | update user | "I couldn't update that user. Mind trying again?" |
| 822 | remove user | "I couldn't remove that user. Mind trying again?" |
| 984 | cancel invitation | "I couldn't cancel that invitation. Mind trying again?" |
| 1020 | resend invitation | "I couldn't resend that invitation. Mind trying again?" |

Lines 984 and 1020 log to DataDog on the line above — keep that, replace only the toast.

### `templates/entity/settings.html` — 3 sites
Lines **2757**, **3595**, **4724** — all `showErrorToast('Error creating contact: ' + error.message);`

### `templates/entity/partials/xero_mapping_classic_script_fragment.html` — 3 sites
Lines **1925**, **2763**, **3892** — identical to the above.

> These six create-contact handlers are the same duplicated block. Worth
> collapsing into one shared function rather than fixing six times.

### `templates/report/expense.html` — 6 sites
| Line | Current | Note |
|---|---|---|
| 1571 | `'...unable to save your expense information: ' + error.message` | has a fallback, but still leaks when `message` exists |
| 3302 | `alert('Error updating expense: ' + (data.message \|\| 'Unknown error'))` | blocking alert |
| 3309 | `alert('Error updating expense. Please try again.')` | blocking alert; copy OK |
| 4000 | `alert('Error deleting expense: ' + (data.message \|\| 'Unknown error'))` | blocking alert |
| 4015 | `alert('Error deleting expense: ' + error.message)` | leaks raw JS errors |
| 4270 | `'...unable to save your expense information: ' + error.message` | duplicate of 1571 |

This file already has the `fromServer` guard elsewhere — these were missed.

### `templates/download_statements.html` — 1 site
Line **157**: ``alert(`Error: ${error.message}`)``. Logs to DataDog above — keep that.
Suggested: *"I couldn't download those statements. Mind trying again?"*

### `static/js/` — 3 sites
`opening.js:179`, `expense.js:398`, `scripts.js:775` — all
``alert(`Error: ${data.message || 'An unknown error occurred.'}`)``.
Server-authored `data.message`, so lower risk, but blocking `alert()` and
`'Error: '` prefix both need normalizing.

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

---

# Class 3 — Inconsistent tone & delivery

### Blocking `alert()` — ~45 sites
The app has a toast system (`templates/components/flash_messages.html`,
`showFlashMessages`), but ~45 call sites still use blocking `alert()`, including
every error path in `templates/report/` (`deposit`, `cash_count`, `sales`,
`opening`, `ending`, `expense`) and all of `static/js/`.

Worst offender — `templates/report/cash_count.html:1218`:
`alert('Saving data and proceeding to next step...')` — a blocking modal for a
*progress* message.

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
