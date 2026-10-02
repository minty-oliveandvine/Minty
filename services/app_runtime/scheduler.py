"""In-process scheduler for the subscription passes.

Minty has no worker dyno and no cron service — the Procfile is one line, ``web: gunicorn
app:app``. So the timer lives inside the web process: an APScheduler background thread
calling :func:`blueprints.subscription.services.daily.run_daily`.

TWO JOBS, ONE FUNCTION. The FULL pass runs once a day and does everything, including the
unscoped access sweep. The LIGHT pass runs every OTHER hour and does only the two jobs a
customer feels the lateness of — closing trials and raising renewals — then sweeps just
the payers it touched. That keeps trial and renewal lag under an hour while the one
genuinely expensive job, which costs the whole customer base every time it runs, still
runs once. See ``daily``'s docstring for the full reasoning.

Everything below is about the ways an in-process timer gets this wrong.

**Two workers, one pass.** The Procfile runs ``--workers 2`` and there is no ``--preload``,
so ``create_app`` runs once per worker and each starts its own scheduler. Both fire at the
same minute. The pass takes a Postgres advisory lock and the loser skips — see
``daily.daily_lock``. The lock lives with the jobs rather than here because it is what
makes the pass safe from ANY caller, including a human running the CLI while the timer is
mid-flight.

**Off unless asked.** ``SUBSCRIPTION_SCHEDULER_ENABLED`` is unset by default, so importing
the app in a test, a shell, or ``flask db upgrade`` starts no timer and bills nobody. It
is turned on in the environment of the deployed web service and nowhere else.

**A missed run costs an hour, except for the full pass.** The job store is in memory, so a
process starting at 09:30 schedules its next run for 10:00 — an hour's slip, which the
hourly cadence makes almost free. The FULL pass is the one that can lose a day: restart
after 05:00 and its next fire is 05:00 tomorrow, so that day gets no unscoped sweep and no
dunning retries. Both are day-scale by nature (a 15-day window, retry offsets in whole
days), so a day's slip is absorbed — but if this host ever idles down overnight, nothing
runs at all and the trigger has to move to a real scheduled service. ``flask subscriptions
run-daily`` exists for exactly that move: the pass does not care who calls it.
"""
from __future__ import annotations

import os

import pytz
from loguru import logger

from services.app_runtime.env import flag, is_development

# The hour that carries the FULL pass — the unscoped access sweep, the dunning retries and
# the trial-ending warnings. 05:00 Hong Kong: the expensive sweep runs while the system is
# quiet, and the whole thing has finished by the time anyone starts work, so the summary is
# waiting to be read rather than happening while you watch. Every other hour runs the light
# pass, which is why this one being pre-dawn costs nothing in responsiveness.
DEFAULT_FULL_HOUR = 5
DEFAULT_TIMEZONE = "Asia/Hong_Kong"

FULL_JOB_ID = "subscriptions-full"
LIGHT_JOB_ID = "subscriptions-light"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "scheduler: {} is not a number ({!r}); using {}", name, raw, default
        )
        return default


def run_pass_now(app, *, mode: str) -> dict | None:
    """One pass, inside an app context, under the lock. Returns None if another holder
    was already running one.

    Both the full and the light job call this, and they share ONE lock rather than having
    one each. That is deliberate: a light pass overlapping the full pass would put a
    narrowed sweep and an unscoped sweep on two different clocks, which is the split-clock
    bug the whole ordering rule exists to prevent.

    Never raises. This is what the timer calls, and an exception escaping a scheduled job
    is how a scheduler quietly stops being one.
    """
    from blueprints.subscription.services import clock, daily

    with app.app_context():
        try:
            with daily.daily_lock() as acquired:
                if not acquired:
                    logger.info(
                        "subscriptions: another pass is already running; skipping the "
                        "{} pass", mode,
                    )
                    return None
                # Read inside the context: ``clock.now`` prefers the DATABASE's time, and
                # outside an app context it silently degrades to this host's wall clock —
                # which is the exact substitution the trusted clock exists to prevent.
                #
                # ``issue=True`` is not configurable. A scheduler that is switched on and
                # silently not charging is indistinguishable from one that is working, and
                # the flag that used to allow it could never have been the billing kill
                # switch people would reach for anyway — converting a trial charges a card
                # and dunning retries invoices already owed, both with it off. Stopping
                # every charge means SUBSCRIPTION_SCHEDULER_ENABLED off, which is
                # unambiguous. A human wanting a preview has ``flask subscriptions
                # run-renewals``, which is dry by default.
                return daily.run_daily(clock.now(), issue=True, mode=mode)
        except Exception:
            logger.exception("subscriptions: the {} pass raised", mode)
            return None


def start_scheduler(app):
    """Start the daily timer if this process is meant to have one. Returns it, or None.

    Called from ``create_app``. Returning None is the normal case: only the deployed web
    service sets ``SUBSCRIPTION_SCHEDULER_ENABLED``.
    """
    if not flag("SUBSCRIPTION_SCHEDULER_ENABLED", False):
        logger.debug("scheduler: disabled (SUBSCRIPTION_SCHEDULER_ENABLED is not set)")
        return None

    # The Flask dev reloader runs a supervisor process that imports the app and then
    # forks the real one. Without this the supervisor gets a scheduler too, and every
    # code edit leaves another one behind.
    if is_development() and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        logger.debug("scheduler: skipping the reloader's supervisor process")
        return None

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from blueprints.subscription.services.daily import FULL, LIGHT

    full_hour = _int("SUBSCRIPTION_SCHEDULER_FULL_HOUR", DEFAULT_FULL_HOUR) % 24
    light = flag("SUBSCRIPTION_SCHEDULER_LIGHT", True)
    timezone = pytz.timezone(
        os.environ.get("SUBSCRIPTION_SCHEDULER_TZ") or DEFAULT_TIMEZONE
    )

    scheduler = BackgroundScheduler(timezone=timezone, daemon=True)
    common = {
        # A pass still running when the next one is due must not start a second one. The
        # lock would refuse it anyway; this refuses it a step earlier, without a database
        # round trip.
        "max_instances": 1,
        # If the process was suspended over several fire times, run ONCE on waking rather
        # than once per missed hour. The jobs are idempotent, so the extra runs would be
        # harmless — they would just be repeated work for a state already reconciled.
        "coalesce": True,
        # Late is still worth running: a pass that starts at 05:20 because the host was
        # busy does everything an 05:00 one would. Beyond that, wait for the next slot.
        "misfire_grace_time": 1800,
    }
    scheduler.add_job(
        run_pass_now,
        trigger=CronTrigger(hour=full_hour, minute=0, timezone=timezone),
        kwargs={"app": app, "mode": FULL},
        id=FULL_JOB_ID,
        name="Full subscription pass",
        **common,
    )
    if light:
        # Every hour EXCEPT the full one, spelled out rather than expressed as "every
        # hour". Two jobs firing in the same minute would take the same lock and one would
        # simply lose — silently skipping either the full sweep or an hour of billing,
        # depending on which won the race.
        light_hours = ",".join(str(h) for h in range(24) if h != full_hour)
        scheduler.add_job(
            run_pass_now,
            trigger=CronTrigger(hour=light_hours, minute=0, timezone=timezone),
            kwargs={"app": app, "mode": LIGHT},
            id=LIGHT_JOB_ID,
            name="Light subscription pass",
            **common,
        )
    scheduler.start()
    logger.info(
        "scheduler: subscription passes {} {} - full pass at {:02d}:00, billing live",
        "hourly" if light else "daily only",
        timezone,
        full_hour,
    )
    return scheduler
