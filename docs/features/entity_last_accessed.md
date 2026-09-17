# "Last logged in" on the Select Company page

**What this document is:** a walkthrough of the entity-list feature — what it
shows, how the code produces it, and the things most likely to trip you up when
you change it.

**Assumed knowledge:** Flask routes, SQLAlchemy queries, and Jinja templates at
a basic level. Everything beyond that is explained inline.

**Ported from:** `OliveAndVineHK/Minty` PR #356 (`ui/entity-list`). That repo has
no shared git history with this one, so this was a manual port, not a
cherry-pick. Four things were changed on the way across — see
[What we did differently](#8-what-we-did-differently-from-the-original-pr).

---

## 1. What the user sees

On the **Select Company** page, each company card now shows a row of small
round badges on the right:

```
┌──────────────────────────────────────────────────────────┐
│  ⌜Setup in progress⌝                                      │  ← only while onboarding
│  Vine Consulting Lim…          [💰] [🏦] [🕐]  ›          │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  Olive and vine                     [💰] [🕐]  ›          │
└──────────────────────────────────────────────────────────┘
                                            ↑
                              greyed out — never opened
```

Three kinds of badge:

| Badge | Meaning |
|---|---|
| Orange, cash register | The **Petty Cash** module is switched on for this company |
| Blue, bank building | The **Bills** module is switched on |
| Grey clock | **Last logged in.** Hover it to see when, and who |

The clock has two states. **Dark grey** means we know when the company was last
opened — hovering shows a tooltip like `9 Jun 5:42 PM / By Jiwon KIM`. **Light
grey** means nobody has opened it since this feature shipped, so we have nothing
to show and say nothing.

"Last logged in" is **team-wide, not per-user**. It answers *"when did anyone
last touch this company?"*, not *"when was I last here?"*. Section 4 explains why
that decision drives the database design.

---

## 2. The two halves

Almost every feature like this has a **write** side and a **read** side. Keep
them separate in your head and this gets much easier.

```
   WRITE                                READ
   ─────                                ────
   User clicks a company                User opens Select Company
          │                                    │
          ▼                                    ▼
   module_selector()                     entity_list()
   (routes/modules.py)                   (routes/list.py)
          │                                    │
          │ permission check passes            │ one query, joined
          ▼                                    ▼
   record_entity_access()                rows → list of dicts
          │                                    │
          ▼                                    ▼
   UPDATE entities SET                    index.html renders
     last_accessed_at = now,              the badges
     last_accessed_by_user_id = me
```

The write happens when someone **enters** a company. The read happens when
someone **lists** companies. They never run in the same request.

---

## 3. File by file

Six files. Read them in this order the first time.

| # | File | What it does |
|---|---|---|
| 1 | [`blueprints/entity/models/entity.py`](../blueprints/entity/models/entity.py) | Declares the two new columns |
| 2 | [`migrations/versions/e1a01_add_entity_last_accessed.py`](../migrations/versions/e1a01_add_entity_last_accessed.py) | Adds those columns to a real database |
| 3 | [`migrations/e1a01_add_entity_last_accessed.sql`](../migrations/e1a01_add_entity_last_accessed.sql) | The same change as hand-written SQL — **this is the one you actually run**, see section 6 |
| 4 | [`blueprints/entity/routes/modules.py`](../blueprints/entity/routes/modules.py) | `record_entity_access()` — the write side |
| 5 | [`blueprints/entity/routes/list.py`](../blueprints/entity/routes/list.py) | `entity_list()` — the read side |
| 6 | [`templates/entity/index.html`](../templates/entity/index.html) | Draws the badges |

---

## 4. The database columns

Two new columns on the existing `entities` table:

```python
last_accessed_at = db.Column(db.TIMESTAMP, nullable=True)
last_accessed_by_user_id = db.Column(
    db.String(36),
    db.ForeignKey("pettycashv2.user.id", ondelete="SET NULL"),
    nullable=True,
)
```

Three decisions worth understanding, because each one is the kind of thing a
reviewer will ask you about.

### Why on `entities` and not on `user_entity`?

`user_entity` is the join table saying "this user belongs to this company". If
we stored the timestamp there, we'd get *per-user* history — "when did **you**
last visit" — and every user would see a different date on the same card.

We want the *team-wide* answer. There is exactly one "last opened" fact per
company, so it lives on the company row.

There's also a practical reason: a **superuser** can open a company they have no
`user_entity` row for at all. If the timestamp lived on `user_entity`, there
would be no row to write to and that visit would vanish.

### Why nullable, with no backfill?

`NULL` means *"nobody has opened this since the feature shipped."* That is a real
state and the UI shows it honestly as a greyed-out clock.

We deliberately did **not** backfill these columns with existing data. The
tempting shortcut is to copy `created_at` into `last_accessed_at` so no card
looks empty — **don't**. "When it was created" and "when it was last opened" are
different facts. Filling one with the other produces a card that confidently
displays a date that is simply wrong, which is worse than a blank, because
nobody can tell it's wrong.

### Why `ON DELETE SET NULL`?

This controls what happens to the entity row when the referenced **user** is
deleted.

- `CASCADE` would delete the company because a user was deleted. Catastrophic.
- `RESTRICT` would refuse to delete the user at all. Annoying.
- `SET NULL` blanks out `last_accessed_by_user_id` and leaves everything else
  alone — the company survives, we just forget who last opened it.

`SET NULL` is the only sane option here. As a general rule: only use `CASCADE`
when the child row is genuinely meaningless without the parent.

---

## 5. How the code works

### 5a. The write side — `record_entity_access()`

Lives in [`routes/modules.py`](../blueprints/entity/routes/modules.py). Called
from `module_selector()`, the route that runs when someone clicks a company.

```python
def record_entity_access(entity_id: str, user_id: str) -> None:
    try:
        updated = Entity.query.filter(Entity.id == entity_id).update(
            {
                "last_accessed_at": datetime.now(tz),
                "last_accessed_by_user_id": user_id,
            },
            synchronize_session=False,
        )
        if updated:
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning(...)
```

Four things to notice:

**It swallows all exceptions.** This looks like bad practice, and normally it
would be. Here it's deliberate: this function updates a *decorative timestamp*.
If it fails, the user must still get into their company. A crash here would
block someone from doing their actual work over a badge. So it rolls back, logs
a warning, and returns quietly. If you ever add something *important* to this
function, that reasoning stops holding.

**`datetime.now(tz)`, not `datetime.now()`.** `tz` is `Asia/Hong_Kong`, defined
in [`models/db.py`](../models/db.py). The column is a naive `TIMESTAMP` — it
stores no timezone — and everything else in this app stores Hong Kong wall time.
A plain `datetime.now()` returns the *server's* local time, which on a
production host is usually UTC, so every card would read 8 hours behind.

**`synchronize_session=False`** tells SQLAlchemy not to bother updating objects
already loaded in memory. We're about to redirect, so nothing will read them.
It's a small performance win and it avoids an error SQLAlchemy raises for some
update patterns.

**`if updated:`** — `.update()` returns how many rows it changed. Zero means the
entity vanished between page load and click. No point committing nothing.

### Where the call sits, and why it matters

Order inside `module_selector()`:

```
line  85:  if org.status == "onboarding":  →  redirect to the wizard   ← returns!
line 103:  if no permission:               →  redirect away            ← returns!
line 108:  record_entity_access(...)                                   ← only reached
                                                                          if both pass
```

It must come **after** the permission check. Someone who was refused entry did
not access the company, and recording them would be a lie — one that then shows
up on another user's screen.

**Known behaviour:** because the onboarding redirect at line 85 returns first,
opening a company that is still mid-onboarding never stamps the timestamp. Those
cards keep the greyed clock until setup finishes. This is fine in practice —
onboarding companies sort to the top of the list anyway — but it will look like a
bug if you don't know about it.

### 5b. The read side — `entity_list()`

Lives in [`routes/list.py`](../blueprints/entity/routes/list.py). It builds one
query, runs it, then reshapes the result for the template.

```python
accessor = aliased(User)
base_query = (
    db.session.query(
        Entity.id, Entity.name, Entity.status, Entity.last_accessed_at,
        accessor.first_name, accessor.last_name,
    )
    .outerjoin(accessor, Entity.last_accessed_by_user_id == accessor.id)
    .filter(or_(Entity.status.is_(None), Entity.status != "deleted"))
    .order_by(
        (Entity.status == "onboarding").desc(),
        Entity.last_accessed_at.desc().nulls_last(),
    )
)
```

**`aliased(User)`** gives the `user` table a temporary nickname for this query.
We need it because `User` may be joined more than once for different reasons; an
alias keeps "the user who last opened this" unambiguous. Think of it as
`JOIN "user" AS accessor` in SQL.

**`outerjoin`, not `join`.** This is the single most important line to
understand. A plain (inner) join returns only rows where the join *matches*. Most
companies have `last_accessed_by_user_id = NULL`, which matches no user — so an
inner join would **silently drop every company nobody has opened yet**. Users
would open the page and find companies missing. An outer join keeps the entity
row and fills the user columns with `NULL`.

**Rule of thumb:** whenever you join on a nullable column, you almost always want
an outer join.

**The ordering** has two levels. First `(Entity.status == "onboarding").desc()`
— that expression is a boolean, and sorting `True` before `False` floats
half-finished setups to the top. Then most-recently-opened first.
`.nulls_last()` is required because databases don't agree on where `NULL` sorts;
without it, never-opened companies could land at the very top, which is the
opposite of useful.

Then the module badges:

```python
modules_by_entity = get_enabled_modules_for_entities([r.id for r in rows])
```

This returns `{entity_id: {"PETTY_CASH", "BILL"}}`. It is **fail-closed** — if
there's no `entity_function_map` row, the module counts as OFF. That's what we
want: a badge is a claim that the module is paid for and usable, so when in doubt
we show nothing rather than promise something.

Finally the rows become dicts:

```python
organizations = [
    {
        "id": r.id,
        "name": r.name,
        "status": r.status,
        "modules": modules_by_entity.get(r.id, set()),
        "last_accessed_display": _format_last_accessed(r.last_accessed_at),
        "last_accessed_by": f"{r.first_name or ''} {r.last_name or ''}".strip() or None,
    }
    for r in rows
]
```

**This changed the shape of `organizations`** — it used to be SQLAlchemy `Row`
objects, it is now a list of plain dicts. Jinja doesn't care (`org.name` works on
both), but Python code would. [`index.html`](../templates/entity/index.html) is
the only consumer, so nothing else needed changing — worth re-checking if you add
another.

### Why `_format_last_accessed` looks odd

```python
return f"{dt.day} {dt.strftime('%b')} {dt.strftime('%I:%M %p').lstrip('0')}"
```

The obvious way to write `9 Jun 5:42 PM` is `strftime("%-d %b %-I:%M %p")`. The
`%-d` and `%-I` codes strip the leading zero — but they're a **glibc extension**.
They work on Linux and macOS and raise `ValueError` on Windows. Since people
develop on Windows here and deploy to Linux, that's a bug that only appears on
one of the two. Building the string by hand works everywhere.

### 5c. The template

Standard Jinja. Two structural points.

**The search filter.** The class `entity-item` and the `data-name` attribute moved
from the `<a>` onto a wrapping `<div>`:

```html
<div class="entity-item relative" data-name="{{ org.name }}">
  {% if org.status == 'onboarding' %}<span class="absolute -top-2 …">Setup in progress</span>{% endif %}
  <a class="…">…</a>
</div>
```

The `filterCompanies()` function at the bottom of the template finds
`.entity-item` and toggles Tailwind's `hidden` class on it. The "Setup in
progress" pill is positioned *outside* the `<a>` so it can float over the card's
top edge — which means it has to live inside the wrapper too, or a filtered-out
card would hide while its pill stayed on screen. **If you restructure this
markup, keep `entity-item` and `data-name` on the outermost element.**

**The clock's two branches** are a plain `{% if org.last_accessed_display %}` /
`{% else %}`. The `if` branch adds the hover tooltip; the `else` branch renders
the same icon in grey with no tooltip.

---

## 6. Applying the migration

**Read this before running anything.** The Python migration is not the one you
run.

This repo has **six Alembic heads** — six separate chains of migrations with no
single end point. That means `alembic upgrade head` fails with a "multiple heads"
error. It is a pre-existing situation, not something this feature created.

So the actual process here uses the **hand-written `.sql` twin**. Every recent
schema change in this repo ships as a matched pair: an Alembic file for the
record, and a `.sql` file that is what actually gets run.

### Steps

1. Open [`migrations/e1a01_add_entity_last_accessed.sql`](../migrations/e1a01_add_entity_last_accessed.sql).
2. Run it as-is against the target database. **It ends in `ROLLBACK`**, so it
   changes nothing on this first run — it applies the change, prints
   verification output, then undoes it.
3. Read the verification output at the bottom. You should see both columns
   present and nullable, the foreign key with `confdeltype = 'n'` (that's
   `SET NULL`), and zero stamped rows.
4. If that all looks right, change the final `ROLLBACK;` to `COMMIT;` and run it
   again. Now it's applied.

The `ROLLBACK`-first pattern is a safety net worth understanding: it lets you see
exactly what a migration does to the real database before committing to it.

### Order of operations

Apply the SQL **before** deploying the code. The new `entity_list()` query
selects `last_accessed_at`, so if the code goes out first, the Select Company
page throws a database error for everybody.

Adding a nullable column with no default doesn't rewrite the table in
PostgreSQL 11+, so this is quick and doesn't lock anything meaningful. It's safe
to run on production during the day.

---

## 7. Gotchas

Things that will cost you an afternoon if you don't know them.

**Every clock is grey after deploying.** Expected. Nothing is backfilled; each
company gets its timestamp the first time someone opens it. Click into a company
and reload the list to confirm it's working.

**Onboarding companies never get a timestamp.** By design, as explained in
section 5a — the route returns before the recording call.

**One extra query per company.** `get_enabled_modules_for_entities()` loops and
queries once per entity rather than fetching everything in one go. This is the
classic **N+1 query problem**. With a handful of companies it's invisible. If
someone with 50 companies complains the page is slow, this is the first place to
look — and batching it is a contained fix.

**The tooltip is CSS-only.** It uses Tailwind's `group` / `group-hover:block`,
so there is no JavaScript to debug. If it doesn't appear, check that the parent
`<span>` still has the `group` class — that's what `group-hover` keys off.

**Don't hotlink icons.** The original PR loaded the Bills icon from
`cdn-icons-png.flaticon.com`. We replaced it with an inline SVG. An external
image on a page every user loads is a third-party dependency that can break, slow
the page down, or leak which of your users loaded it.

---

## 8. What we did differently from the original PR

Useful context if you compare this against PR #356 upstream.

| # | The PR did | We did | Why |
|---|---|---|---|
| 1 | Shipped its own permissive `get_enabled_modules_for_entities` (missing row → module ON) | Reused this repo's existing fail-closed version | Module access here is tied to subscriptions. The permissive version would show Bills badges on companies that never paid for Bills. |
| 2 | `datetime.now()` | `datetime.now(tz)` | The PR's version renders 8 hours behind on a UTC server. |
| 3 | Hotlinked the Bills icon from a CDN | Inline SVG | No third-party request on a page everyone loads. |
| 4 | `.nullslast()` | `.nulls_last()` | The old spelling is deprecated in SQLAlchemy 2.0, which this repo uses. |

One more piece of context you should have: **PR #356 was merged upstream and then
reverted**, and never re-applied. We ported it here on request. If this feature
starts misbehaving in a way that seems fundamental rather than a small bug, that
revert is worth investigating — nobody has established what prompted it.

---

## 9. Testing it locally

```bash
# 1. Apply the SQL (section 6) to your local database.

# 2. Confirm nothing is broken.
python -m pytest tests/test_entity_list_flash_drain.py \
                 tests/test_entity_selection_flow.py \
                 tests/test_entity_context_routes.py -q
# expect: 27 passed

# 3. Start the app, open Select Company.
#    - every clock grey  → correct on a fresh database
#    - click a company, go back, reload
#    - that company's clock is now dark; hover shows the time and your name
```

**A warning about the full suite.** Running `python -m pytest` on its own gives
roughly **274 failures**. Those are pre-existing and unrelated to this feature —
verified by stashing these changes and re-running to get an identical count.
Don't assume you broke something. If you need to check whether *your* change
broke anything, do the same: stash, run, compare the numbers.
