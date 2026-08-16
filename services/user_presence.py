"""Who is signed in right now.

Settings > Users lists the people currently signed in to an entity rather than
everyone holding a membership row: logging out takes you off the list, logging
back in puts you back on it. `UserEntity` still decides who *may* appear — this
module only decides who does, right now.

Presence lives in two columns on `user` rather than a sessions table because
there is no single server-side session to count. Minty keeps its session in a
signed cookie and the billing module (Django) issues its own JWT; neither writes
a row anyone else can read. Two columns both sides can update is the smallest
thing that works across the pair:

  * ``signed_in_at`` — the intent. Stamped when Flask-Login emits
    ``user_logged_in`` (password, Xero, OTP, invitation accept all route through
    it) and cleared on ``user_logged_out`` or when billing's logout endpoint is
    called.
  * ``last_seen_at`` — the backstop. A browser that is simply closed sends no
    logout of any kind, and without this the person would read as signed in
    forever. Refreshed on request, throttled (see ``SEEN_REFRESH_SECONDS``) so a
    presence write does not ride along with every page load.

Presence is therefore "said they were in, and has been seen since the window
opened" — both columns, never one.

A live Flask session counts as signed in even if nothing stamped it, which is why
``refresh_presence`` can fill a blank ``signed_in_at`` rather than only bumping
``last_seen_at``. Every session open when this shipped has a NULL there and will
never see a login signal, so without that those people stayed invisible until their
cookie expired.

But a blank ``signed_in_at`` means two different things, and only the pair of
columns tells them apart: both blank is "never stamped" (adopt it), while a blank
one beside a set ``last_seen_at`` is "signed out" (leave it). That distinction is
what lets signing out of the billing module survive the redirect back into Minty
without ending the Minty session. Keep it in mind before adding any other writer of
these columns: anything that clears ``signed_in_at`` must leave ``last_seen_at``
set, or the next authenticated request will read it as never-stamped and put the
person back on the list.

Every write here swallows its own failure. Presence is decoration on a user
list; a hiccup writing it must never break a login, a logout, or a page.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app
from loguru import logger
from sqlalchemy import and_, case, func
from sqlalchemy import inspect as sa_inspect

from models.db import User, db, tz

# How stale ``last_seen_at`` may go before a user drops off the list. Matches the
# idle-logout window when one is configured, so the list and the session agree on
# what "still here" means; 30 minutes otherwise.
DEFAULT_PRESENCE_WINDOW_SECONDS = 1800

# Minimum gap between ``last_seen_at`` writes for one session. Small enough that
# the window above is never missed by more than a rounding error, large enough
# that a burst of requests costs one UPDATE rather than dozens.
SEEN_REFRESH_SECONDS = 60


def now() -> datetime:
    """Naive HK-local, the convention every TIMESTAMP on `user` already follows.

    Written naive on purpose: the columns are TIMESTAMP WITHOUT TIME ZONE, and
    handing the driver an aware value leaves the stored wall-clock at the mercy
    of the session's TimeZone setting. Dropping the offset here makes what we
    write and what we compare against provably the same clock.
    """
    return datetime.now(tz).replace(tzinfo=None)


def presence_window_seconds() -> int:
    try:
        return int(
            current_app.config.get(
                "IDLE_TIMEOUT_SECONDS", DEFAULT_PRESENCE_WINDOW_SECONDS
            )
        )
    except Exception:
        return DEFAULT_PRESENCE_WINDOW_SECONDS


def is_signed_in_clause(entity_id=None):
    """SQLAlchemy criterion for "this user is signed in to ``entity_id`` right now".

    THREE conditions, and the entity is not optional in spirit. The two stamps are
    facts about the person — they signed in, and we have seen them since — while the
    question a company's Users page asks is "who is here, in THIS company". Answering
    it from the stamps alone listed anyone signed in to Minty on every company they
    belonged to at once, which is the bug this argument exists to fix.

    ``signed_in_at`` alone would keep a closed browser on the list; ``last_seen_at``
    alone would put a logged-out user back on it the moment any lingering session
    touched the app; and without ``current_entity_id`` the answer belongs to no
    company in particular.

    Omitting ``entity_id`` asks the looser question — signed in to Minty at all,
    wherever they are. Nothing on the Users page wants that; it is here for callers
    that genuinely mean "anywhere", and it is deliberately the awkward one to reach
    for rather than the default.
    """
    cutoff = now() - timedelta(seconds=presence_window_seconds())
    conditions = [
        User.signed_in_at.isnot(None),
        User.last_seen_at.isnot(None),
        User.last_seen_at >= cutoff,
    ]
    if entity_id is not None:
        conditions.append(User.current_entity_id == str(entity_id))
    return and_(*conditions)


def _user_id(user) -> str | None:
    """The user's primary key, without needing them attached to a session.

    ``user_logged_out`` fires from ``logout_user()``, and by then the instance can
    be detached and its attributes expired — Minty's ``teardown_request`` calls
    ``db.session.remove()``. Reading a mapped attribute on one of those raises
    DetachedInstanceError, which ``getattr(user, "id", None)`` does not catch: the
    default only covers AttributeError. The identity key is already in memory and
    needs no session at all, so it is tried first.
    """
    try:
        identity = sa_inspect(user).identity
        if identity:
            return str(identity[0])
    except Exception:
        pass
    try:
        return str(user.id) if user.id else None
    except Exception:
        return None


def _stamp(user, **values) -> None:
    user_id = _user_id(user)
    if not user_id:
        return
    try:
        db.session.query(User).filter(User.id == user_id).update(
            values, synchronize_session=False
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning("user_presence: write failed user=%s: %s", user_id, exc)


def mark_signed_in(user) -> None:
    """Signed in to Minty — but not yet inside any company.

    Called from the ``user_logged_in`` signal, which knows nothing about companies:
    signing in lands you on the entity list, having chosen none. So the company is
    cleared rather than left over from last time, or the first page of a new session
    would place them wherever they were when the previous one ended.
    """
    stamp = now()
    _stamp(user, signed_in_at=stamp, last_seen_at=stamp, current_entity_id=None)


def mark_signed_out(user) -> None:
    """Take the user off the list.

    ``signed_in_at`` is cleared and ``last_seen_at`` is stamped — signing out is
    the last moment we saw them, so it is true on its own terms, and it is also
    what makes the pair unambiguous. A cleared ``signed_in_at`` beside a blank
    ``last_seen_at`` would read as never-stamped, and ``refresh_presence`` would
    adopt them straight back onto the list.
    """
    _stamp(user, signed_in_at=None, last_seen_at=now(), current_entity_id=None)


def resume_presence(user, entity_id) -> None:
    """Put the user on THIS company's list, because they just opened it.

    The counterpart to ``refresh_presence``, which deliberately refuses to revive
    a signed-out session. That refusal is right for page loads — signing out of
    the billing profile drops you on Minty's entity list, and reviving there would
    undo the sign-out before the page had finished rendering.

    But opening an entity is not a page load, it is a decision: the user picked a
    company and asked to go in. Since that sign-out leaves the Minty session alive
    on purpose, this is the only way back onto the list short of a full sign-out
    and sign-in — and without it, "log out, then go back into the company" leaves
    you invisible for as long as the session lasts, which is the bug this fixes.

    COALESCE on ``signed_in_at``, so someone already listed keeps the time they
    actually signed in rather than having it reset each time they switch company.
    ``current_entity_id`` is overwritten outright, because that is the one thing
    opening a company genuinely changes — and moving to company B necessarily means
    leaving company A's list, since a person is in one place at a time.
    """
    stamp = now()
    _stamp(
        user,
        last_seen_at=stamp,
        signed_in_at=func.coalesce(User.signed_in_at, stamp),
        current_entity_id=str(entity_id) if entity_id else None,
    )


def refresh_presence(user, entity_id=None) -> None:
    """Hold an authenticated user on the list for another window.

    ``entity_id`` is the company the CURRENT REQUEST is about, when it is about one.
    Passing it keeps presence following the person as they move — including when
    they arrive somewhere by deep link rather than through the company's front door,
    which ``resume_presence`` alone would miss.

    A request with no company (the entity list, the profile, an API with no entity in
    its path) passes None, and None LEAVES THE COMPANY ALONE rather than clearing it.
    Plenty of pages simply do not name an entity, and treating every one of them as
    "left the company" would flicker people off their colleagues' lists all day.
    Leaving is an explicit act: /leave-entity and sign-out clear it.

    ``last_seen_at`` is always bumped. ``signed_in_at`` is written only in the one
    case where its blankness means "nobody ever asked" — and the two columns
    together are what tell that case apart from the one that looks identical in
    ``signed_in_at`` alone:

      * both blank — this account has never been stamped, which is every session
        that was already open when presence shipped. No login signal will ever
        fire for it, so adopt it: the request is authenticated, and a live session
        is what being signed in means.
      * ``signed_in_at`` blank, ``last_seen_at`` set — they were signed in and
        then signed out. Leave it blank. The Flask session can legitimately
        outlive that sign-out (the billing module's Log out clears presence and
        returns the browser to Minty's entity list without ending the Minty
        session), and re-stamping here would undo the thing the user just asked
        for on their very next page.
      * ``signed_in_at`` set — keep it. It records when they signed in, not when
        they last clicked something.

    Written as one statement so the read and the write cannot disagree; the CASE
    sees the row as it was before this update.
    """
    stamp = now()
    values = {
        "last_seen_at": stamp,
        "signed_in_at": case(
            (User.signed_in_at.isnot(None), User.signed_in_at),
            (User.last_seen_at.is_(None), stamp),
            else_=None,
        ),
    }
    if entity_id:
        values["current_entity_id"] = str(entity_id)
    _stamp(user, **values)
