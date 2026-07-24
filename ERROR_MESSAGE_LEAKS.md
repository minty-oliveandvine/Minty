# Remaining error-message leaks (frontend)

Places where raw error text is rendered to the user. Each shows a JS `Error.message`
straight from a `.catch()` block — so on a network failure, a parse failure, or an
HTML error page being handed to `response.json()`, the user sees things like
`Unexpected token '<' ... is not valid JSON` instead of a real message.

**The fix pattern already exists in this repo.** `templates/report/expense.html`
(around lines 2551 and 2651) tags errors the server actually authored:

```js
const serverError = new Error(errorData.message || 'Network response was not ok');
serverError.fromServer = Boolean(errorData.message);
throw serverError;
```

…and then only shows `error.message` when that flag is set:

```js
showFlashMessages(
  error && error.fromServer && error.message
    ? error.message
    : "I couldn't add that contact. Mind trying again?",
  'error'
);
```

Anything reaching `.catch()` **without** `fromServer` is a JS/parser failure and must
not be surfaced verbatim. Apply that same shape to each site below.

Status: the Python/backend leaks are fixed (commit `ad9a952c`). These frontend ones
are **not fixed**.

---

## 1. `templates/entity/settings_users_scripts.html` — 4 sites

Highest priority: this is the user-management screen, and all four are bare
`'Error: ' + err.message`.

| Line | Context | Current |
|---|---|---|
| 776 | update user | `.catch(err => showErrorToast('Error: ' + err.message))` |
| 822 | remove user | `.catch(err => showErrorToast('Error: ' + err.message))` |
| 984 | cancel invitation | `showErrorToast('Error: ' + err.message);` |
| 1020 | resend invitation | `showErrorToast('Error: ' + err.message);` |

Note lines 984 and 1020 already log to DataDog on the line above — keep that, and
replace only the user-visible toast with a generic message.

Suggested copy: *"I couldn't update that user. Mind trying again?"* /
*"I couldn't remove that user. Mind trying again?"* /
*"I couldn't cancel that invitation. Mind trying again?"* /
*"I couldn't resend that invitation. Mind trying again?"*

## 2. `templates/entity/settings.html` — 3 sites

Lines **2667**, **3505**, **4634** — all `showErrorToast('Error creating contact: ' + error.message);`

Suggested copy: *"I couldn't add that contact. Mind trying again?"*

## 3. `templates/entity/partials/xero_mapping_classic_script_fragment.html` — 3 sites

Lines **1925**, **2763**, **3892** — all `showErrorToast('Error creating contact: ' + error.message);`

Same three-times-duplicated block as above. Worth asking whether these six
create-contact handlers can be collapsed into one shared function rather than
fixed six times.

## 4. `templates/report/expense.html` — 1 site

Line **4010**: `alert('Error deleting expense: ' + error.message);`

This file already has the `fromServer` guard elsewhere, so this one was simply
missed. It also still uses a blocking `alert()` rather than the flash toast the
rest of the file was moved to.

Suggested copy: *"I couldn't delete that expense. Mind trying again?"*

## 5. `templates/download_statements.html` — 1 site

Line **157**: ``alert(`Error: ${error.message}`);``

Also a blocking `alert()`. Logs to DataDog on the line above — keep that.

Suggested copy: *"I couldn't download those statements. Mind trying again?"*

---

## Also worth doing (not a leak, but related)

`blueprints/xero/routes/settings.py:72` returns `jsonify({"status": "error",
"message": str(e)})` — this is the **same backend leak class** as the ones fixed in
`ad9a952c`, and it was deliberately left out of that commit to avoid mixing a
security fix into a copy-only change. It should be folded in with the above.

## How to verify a fix

Force a non-JSON error response (e.g. make the endpoint 500, or point it at a URL
that returns HTML) and confirm the toast shows your friendly copy rather than
`Unexpected token '<'`.
