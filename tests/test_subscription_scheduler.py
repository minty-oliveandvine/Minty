"""The daily subscription pass, and the timer that calls it.

Five jobs whose ORDER is load-bearing, run unattended, against real money. These tests
pin the four properties that make that safe:

  the order          — close-trials first, then renewals, then dunning, and sweep-access
                       LAST. Documented in three places and enforced in one.
  failure isolation  — a broken job must not be the reason the other four do not run
  the skip rule      — EXCEPT sweep-access, which is skipped when close-trials or
                       run-renewals failed, because entitlement they would have granted is
                       missing and the sweep would read it as lapsed
  the money switch   — ``issue`` reaches ``run_renewals`` and nothing else invents it

The jobs themselves are covered elsewhere (``test_billing_engine``, ``test_dunning_*``,
``test_access_rules``). Here they are replaced by recorders: this is a test of the pass,
and a pass that only works when Stripe answers is not one that can be tested.

EVERY TEST TAKES ``daily`` AS A FIXTURE rather than importing it at the top. The ``app``
fixture clears ``blueprints.*`` out of ``sys.modules`` before building the app, so a
module-level import here would be a DIFFERENT module object from the one the running app
holds — and monkeypatching it would patch nothing, silently, while the real jobs ran
against the test database.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc
NOW = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


@pytest.fixture
def daily(app):
    """The ``daily`` module the APP is using — see the module docstring."""
    from blueprints.subscription.services import daily as module

    return module


@pytest.fixture
def scheduler(app):
    from services.app_runtime import scheduler as module

    return module


@pytest.fixture
def recorder(daily, monkeypatch):
    """Replace the five job bodies with recorders; return the call log."""
    calls: list[str] = []

    def _make(name):
        def _run(now, *, days_before, issue):
            calls.append(name)
            return {"did": []}

        return _run

    monkeypatch.setattr(
        daily, "_RUNNERS", {name: _make(name) for name in daily.JOB_ORDER}
    )
    return calls


def _fail_with(daily, job, exc=RuntimeError("boom")):
    """Make one recorded job raise, leaving the other four recording."""

    def _raise(now, *, days_before, issue):
        raise exc

    daily._RUNNERS[job] = _raise


def test_the_jobs_run_in_the_documented_order(app, daily, recorder):
    """The order is the whole reason this module exists rather than five cron lines.

    close-trials before run-renewals bills a trial converting today by today's pass;
    repair-transfers also before it, because finishing a stranded handover writes the
    claim that keeps that entity off this run's invoice — left until afterwards, the
    renewal would bill days the new payer has already paid for; retry-dunning after
    run-renewals puts this morning's failed renewal into dunning before the retry pass
    reads it; sweep-access last — see the regression proof below.
    """
    with app.app_context():
        daily.run_daily(NOW, issue=False)

    assert recorder == [
        "notify-trial-ending",
        "close-trials",
        "repair-transfers",
        "run-renewals",
        "retry-dunning",
        "sweep-access",
    ]
    assert recorder == list(daily.JOB_ORDER)


def test_sweeping_before_renewals_would_revoke_a_payer_about_to_be_billed(app, daily):
    """Why the sweep is LAST. Regression proof for a day-long outage per renewal.

    The pass shares ONE clock. A payer whose period elapsed since yesterday's pass is still
    ``active`` with a ``paid_through`` in the past, so the predicate the sweep applies —
    ``access.grants_access``, at modules.py's revoke branch — says no. With the sweep
    running third, that revoked their modules seconds before ``run-renewals`` billed them
    for the new period, and nothing re-syncs the map on a successful renewal, so access
    came back only on the next day's pass.

    Note the second case: this was never only about converted trials. Any payer whose
    ``paid_through`` falls between two passes hits it, every cycle.
    """
    from blueprints.subscription.services import access

    for paid_through in (
        NOW - timedelta(seconds=4),      # a trial converted mid-pass a month ago
        NOW - timedelta(hours=12),       # bought at midday, any payer at all
    ):
        assert not access.grants_access(
            NOW,
            phase=access.PHASE_ACTIVE,   # healthy and paid — about to renew this pass
            period_end=paid_through,
            past_due_grace_days=15,
        ), "a payer due for renewal reads as lapsed until the renewal advances them"

    # So the renewal that fixes it must already have run.
    assert daily.JOB_ORDER.index(daily.RUN_RENEWALS) < daily.JOB_ORDER.index(
        daily.SWEEP_ACCESS
    )
    # And dunning too, so a recovery is restored by this pass rather than tomorrow's.
    assert daily.JOB_ORDER.index(daily.RETRY_DUNNING) < daily.JOB_ORDER.index(
        daily.SWEEP_ACCESS
    )


def test_one_job_failing_does_not_stop_the_others(app, daily, recorder):
    """A mail outage must not be the reason nobody is billed.

    ``notify-trial-ending`` is the one whose failure carries no consequence at all for the
    four behind it — it reconciles nothing — so every one of them must still run.
    """
    _fail_with(daily, daily.NOTIFY_TRIAL_ENDING)

    with app.app_context():
        result = daily.run_daily(NOW, issue=False)

    assert recorder == [
        daily.CLOSE_TRIALS,
        daily.REPAIR_TRANSFERS,
        daily.RUN_RENEWALS,
        daily.RETRY_DUNNING,
        daily.SWEEP_ACCESS,
    ]
    assert result["ok"] is False
    assert result["failed"] == [daily.NOTIFY_TRIAL_ENDING]
    failed = next(e for e in result["jobs"] if e["job"] == daily.NOTIFY_TRIAL_ENDING)
    assert failed["error"] == "RuntimeError: boom"


@pytest.mark.parametrize("blocker", ["close-trials", "run-renewals"])
def test_sweep_is_skipped_when_a_job_that_grants_entitlement_failed(
    app, daily, recorder, blocker
):
    """The one ordering rule with teeth.

    A trial whose conversion did not happen is still past its end date; a payer who was
    not billed still has a stale ``paid_through``. The sweep cannot tell either from a
    customer who genuinely lapsed, and would revoke both over a failure that is simply
    retried tomorrow.
    """
    _fail_with(daily, blocker)

    with app.app_context():
        result = daily.run_daily(NOW, issue=False)

    assert daily.SWEEP_ACCESS not in recorder
    # Skipped, not failed: nothing went wrong with the sweep, and the pass is still
    # reported as broken by the job that actually broke.
    skipped = next(e for e in result["jobs"] if e["job"] == daily.SWEEP_ACCESS)
    assert skipped["skipped"] is True
    assert result["failed"] == [blocker]
    # The other jobs are NOT skipped with it: a trial that failed to convert is no reason
    # to leave every other payer unbilled.
    assert daily.RETRY_DUNNING in recorder


def test_dunning_failing_does_not_block_the_sweep(app, daily, recorder):
    """Dunning is deliberately NOT a blocker.

    A recovery it missed leaves the payer ``past_due``, which the grace window covers — so
    the worst case is access restored a day late, not revoked a day early. Blocking on it
    would trade a real reconciliation for a hypothetical one.
    """
    _fail_with(daily, daily.RETRY_DUNNING)

    with app.app_context():
        daily.run_daily(NOW, issue=False)

    assert daily.SWEEP_ACCESS in recorder


def test_issue_is_required_and_reaches_only_the_renewal_step(app, daily, monkeypatch):
    """``issue`` has no default anywhere in the chain, and moves nothing but money."""
    with pytest.raises(TypeError):
        daily.run_daily(NOW)  # type: ignore[call-arg]

    seen = {}

    def _fake_run_renewals(now, *, scope, issue=False, limit=None):
        seen["scope"], seen["issue"], seen["now"] = scope, issue, now
        return {"planned": [], "issued": [], "failed": [], "skipped": []}

    from blueprints.subscription.services import renewals

    monkeypatch.setattr(renewals, "run_renewals", _fake_run_renewals)

    with app.app_context():
        daily._run_renewals(NOW, days_before=3, issue=True)

    # Billing everybody is TYPED by the pass rather than obtained by omission — the same
    # rule ``run_renewals`` enforces on its own callers.
    assert seen["scope"] is renewals.ALL_PAYERS
    assert seen["issue"] is True
    assert seen["now"] == NOW


def test_the_pass_can_be_entered_only_once_at_a_time(app, daily):
    """The lock is a context manager that always yields an answer and always cleans up.

    On SQLite there is no advisory lock and no second worker, so it yields True. The
    property under test is that the pass has ONE gate whatever the backend — a caller
    that has to know which database it is on would grow a branch on every call site.
    """
    with app.app_context():
        with daily.daily_lock() as acquired:
            assert acquired is True
        # Releasing must actually release, or the next pass — tomorrow, in the same
        # long-lived worker — would find itself locked out forever.
        with daily.daily_lock() as again:
            assert again is True


def test_the_lock_key_is_stable_across_processes(daily):
    """Derived from sha256, not ``hash()``.

    ``hash()`` on bytes is salted per process, so two gunicorn workers would compute two
    different keys, each take a lock nobody else wants, and both run the pass — a lock
    that looks present in the code and is absent in production.
    """
    assert daily._LOCK_KEY == int.from_bytes(
        hashlib.sha256(b"minty:subscriptions:run-daily").digest()[:8], "big", signed=True
    )
    assert -(2 ** 63) <= daily._LOCK_KEY < 2 ** 63


def test_backlog_is_reported_when_a_payer_is_still_due(app, daily, monkeypatch):
    """A payer more than one period behind is billed again TOMORROW, and says so today.

    ``run_renewals`` raises one period per pass. An account three months stale is caught
    up over three consecutive days, three real charges — which is correct, and is not
    something anybody should have to reconstruct from first principles when the customer
    asks.
    """

    class _Account:
        user_id = "payer-behind"

    class _Group:
        id = "g-behind"

    from blueprints.subscription.services import renewals

    # The REAL shape: one entry per card. A stub of the old ``(account, paid_through)`` pair
    # is what let the report crash on every due card unnoticed.
    monkeypatch.setattr(renewals, "due_renewals", lambda now: [(_Account(), _Group(), NOW)])

    with app.app_context():
        assert daily._log_renewal_backlog(
            NOW, {"issued": [{"user_id": "payer-behind", "billing_group_id": "g-behind"}]}
        ) == ["payer-behind"]

        # A card whose charge FAILED is still due for the obvious reason. It is already
        # reported as a failure and is dunning's problem; naming it as "behind" too would
        # make every decline look like a billing backlog.
        assert daily._log_renewal_backlog(
            NOW, {"issued": [], "failed": [{"user_id": "payer-behind",
                                            "billing_group_id": "g-behind"}]}
        ) == []


def test_the_light_pass_runs_the_two_money_jobs_and_a_scoped_sweep(app, daily, recorder):
    """The hourly pass: what a customer feels the lateness of, and nothing else.

    Notify and dunning are day-scale by nature — a warning measured in days, retry offsets
    in whole days — so they stay in the full pass. The UNSCOPED sweep stays there too, and
    that is the whole point of the split: it is the one job whose cost is the entire
    customer base rather than whatever is due.
    """
    # issue=False only to keep the backlog query (which needs the billing tables) out of
    # a test about which STEPS run. Coverage of the money switch is its own test.
    with app.app_context():
        result = daily.run_daily(NOW, issue=False, mode=daily.LIGHT)

    assert recorder == [daily.CLOSE_TRIALS, daily.REPAIR_TRANSFERS, daily.RUN_RENEWALS]
    assert daily.NOTIFY_TRIAL_ENDING not in recorder
    assert daily.RETRY_DUNNING not in recorder
    assert daily.SWEEP_ACCESS not in recorder
    # But it does sweep — narrowed. Skipping reconciliation entirely would rest the whole
    # design on "the other code paths get access right", which is the assumption
    # sweep-access exists to backstop.
    assert [entry["job"] for entry in result["jobs"]][-1] == daily.SWEEP_TOUCHED
    assert result["mode"] == daily.LIGHT


def test_the_scoped_sweep_covers_every_payer_the_pass_touched(app, daily, monkeypatch):
    """Renewals report by payer; trials report by entity. Both have to be swept.

    The entity->payer resolution is the only plumbing the scoped sweep needs, and getting
    it wrong would silently leave converted trials un-reconciled — the failure would look
    like nothing at all until someone noticed a stale access flag.
    """
    swept = []
    monkeypatch.setattr(
        "blueprints.entity.services.modules.sweep_expired_module_access",
        lambda payer_user_id=None: swept.append(payer_user_id) or {},
    )
    monkeypatch.setattr(daily, "_payers_for_entities", lambda ids: {f"payer-of-{i}" for i in ids})

    payers = daily._touched_payers({
        daily.RUN_RENEWALS: {
            "issued": [{"user_id": "billed"}],
            "failed": [{"user_id": "declined"}],
            "skipped": [{"user_id": "covered"}],
        },
        daily.CLOSE_TRIALS: {
            "converted": [{"entity_id": "e1"}],
            "expired": [{"entity_id": "e2"}],
        },
    })
    assert payers == {"billed", "declined", "covered", "payer-of-e1", "payer-of-e2"}

    with app.app_context():
        summary = daily._sweep_touched({"b", "a"})
    # Sorted, so a log line for one pass is comparable with the next.
    assert swept == ["a", "b"]
    assert summary["payers"] == ["a", "b"]


def test_a_failing_payer_does_not_stop_the_scoped_sweep(app, daily, monkeypatch):
    """One payer's reconciliation failing must not cost the others theirs."""
    def _explode(payer_user_id=None):
        if payer_user_id == "bad":
            raise RuntimeError("boom")
        return {"disabled": [{"entity_id": "e", "code": "PETTY_CASH"}], "restored": []}

    monkeypatch.setattr(
        "blueprints.entity.services.modules.sweep_expired_module_access", _explode
    )
    with app.app_context():
        summary = daily._sweep_touched({"bad", "good"})
    assert len(summary["disabled"]) == 1


def test_an_unknown_mode_is_refused(app, daily):
    """A typo must not silently run the wrong pass — or worse, none of it."""
    with pytest.raises(ValueError):
        daily.run_daily(NOW, issue=True, mode="hourly")


def test_the_scheduler_is_off_unless_the_environment_asks_for_it(
    app, scheduler, monkeypatch
):
    """Importing the app must not start a timer.

    Every test, every shell, every ``flask db upgrade`` builds an app. If the scheduler
    defaulted on, each of those would be a process quietly waiting to bill the database it
    happens to be pointed at — and one of those databases has real payers in it.
    """
    monkeypatch.delenv("SUBSCRIPTION_SCHEDULER_ENABLED", raising=False)
    assert scheduler.start_scheduler(app) is None

    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ENABLED", "0")
    assert scheduler.start_scheduler(app) is None


def test_the_light_hours_are_every_hour_except_the_full_one(app, scheduler, monkeypatch):
    """The two jobs must never fire in the same minute.

    They share one advisory lock, so a collision does not corrupt anything — it silently
    drops one of them. Whichever lost, you would be missing either the full sweep or an
    hour of billing, with nothing in the log saying which. So the light hours EXCLUDE the
    full hour rather than being "every hour" and relying on the lock to sort it out.
    """
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_FULL_HOUR", "5")
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_TZ", "Asia/Hong_Kong")

    started = scheduler.start_scheduler(app)
    try:
        full = started.get_job(scheduler.FULL_JOB_ID)
        light = started.get_job(scheduler.LIGHT_JOB_ID)
        full_hours = {f.name: str(f) for f in full.trigger.fields}
        light_hours = {f.name: str(f) for f in light.trigger.fields}

        assert full_hours["hour"] == "5"
        assert full_hours["minute"] == "0"
        assert light_hours["minute"] == "0"
        assert "5" not in light_hours["hour"].split(",")
        assert len(light_hours["hour"].split(",")) == 23

        assert full.kwargs["mode"] == "full"
        assert light.kwargs["mode"] == "light"
        assert full.max_instances == light.max_instances == 1
        assert str(full.trigger.timezone) == "Asia/Hong_Kong"
        # It schedules; it does not run. A pass on every deploy would be safe — the jobs
        # are idempotent — but it would be a full sweep every time somebody pushes.
        assert full.next_run_time > datetime.now(full.trigger.timezone)
    finally:
        started.shutdown(wait=False)


def test_the_light_passes_can_be_turned_off(app, scheduler, monkeypatch):
    """The way back to one pass a day, without a code change.

    This is new behaviour going straight into production billing; being able to fall back
    to the cadence that was reasoned about first is worth one environment variable.
    """
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_LIGHT", "0")

    started = scheduler.start_scheduler(app)
    try:
        assert started.get_job(scheduler.FULL_JOB_ID) is not None
        assert started.get_job(scheduler.LIGHT_JOB_ID) is None
    finally:
        started.shutdown(wait=False)


def test_the_scheduler_always_bills(app, daily, scheduler, monkeypatch):
    """There is no environment switch that leaves the scheduler on but not charging.

    One existed and was removed. It could never have been the billing kill switch anyone
    would reach for — converting a trial charges a card and dunning retries invoices
    already owed, both with it off — so it offered the reassurance of a brake without the
    braking. A scheduler that is enabled and silently not charging is indistinguishable
    from one that is working. The honest switch is ENABLED, and it stops everything.
    """
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ISSUE", "0")  # ignored: no longer read

    @contextmanager
    def _acquired():
        yield True

    billed = []
    monkeypatch.setattr(daily, "daily_lock", _acquired)
    monkeypatch.setattr(
        daily, "run_daily", lambda now, **kw: billed.append(kw) or {"ok": True}
    )
    scheduler.run_pass_now(app, mode=daily.FULL)
    assert billed == [{"issue": True, "mode": "full"}]


def test_a_pass_that_raises_does_not_kill_the_timer(app, daily, scheduler, monkeypatch):
    """An exception escaping a scheduled job is how a scheduler stops being one."""

    def _explode():
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(daily, "daily_lock", _explode)
    assert scheduler.run_pass_now(app, mode=daily.FULL) is None


def test_the_loser_of_the_lock_does_nothing(app, daily, scheduler, monkeypatch):
    """Two workers, one pass. The second must SKIP, not queue and run afterwards.

    Full and light share this ONE lock rather than having one each, so a light pass can
    never overlap the full pass — which would put a narrowed sweep and an unscoped sweep
    on two different clocks, the exact split the ordering rule exists to prevent.
    """

    @contextmanager
    def _no_lock():
        yield False

    ran = []
    monkeypatch.setattr(daily, "daily_lock", _no_lock)
    monkeypatch.setattr(daily, "run_daily", lambda *a, **kw: ran.append(kw) or {})

    assert scheduler.run_pass_now(app, mode=daily.LIGHT) is None
    assert ran == []


def test_env_flags_survive_nonsense(scheduler, monkeypatch):
    """A mistyped hour must not stop the pass being scheduled at all."""
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_HOUR", "not-a-number")
    assert scheduler._int("SUBSCRIPTION_SCHEDULER_HOUR", 2) == 2
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ENABLED", "yes")
    assert scheduler._flag("SUBSCRIPTION_SCHEDULER_ENABLED", False) is True
    monkeypatch.setenv("SUBSCRIPTION_SCHEDULER_ENABLED", "off")
    assert scheduler._flag("SUBSCRIPTION_SCHEDULER_ENABLED", False) is False
    monkeypatch.delenv("SUBSCRIPTION_SCHEDULER_ISSUE", raising=False)
    # The default that matters most: unset means BILL, because a scheduler that is on and
    # silently not charging looks identical to one that is working.
    assert scheduler._flag("SUBSCRIPTION_SCHEDULER_ISSUE", True) is True
