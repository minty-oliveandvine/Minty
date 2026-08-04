"""Trusted-clock tests: subscription access/grace decisions use Stripe's server
time (captured from the subscription-fetch response Date header) instead of the host
wall clock, falling back to the process clock when no Stripe response was seen."""
from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def test_parse_http_date():
    from blueprints.subscription.services import clock

    dt = clock._parse_http_date("Wed, 01 Jul 2026 12:00:00 GMT")
    assert dt == datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    assert clock._parse_http_date(None) is None
    assert clock._parse_http_date("not a date") is None


def test_now_defaults_to_host_clock_without_record(app):
    from blueprints.subscription.services import clock

    with app.app_context():
        before = datetime.now(UTC)
        val = clock.now()
    # No server time recorded → within a second of the process clock.
    assert abs((val - before).total_seconds()) < 2


def test_now_returns_recorded_server_time(app):
    from blueprints.subscription.services import clock

    with app.app_context():
        clock.record_http_date("Wed, 01 Jul 2026 12:00:00 GMT")
        val = clock.now()
    assert val == datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def test_bad_header_leaves_host_clock(app):
    from blueprints.subscription.services import clock

    with app.app_context():
        clock.record_http_date("garbage")
        val = clock.now()
    assert abs((val - datetime.now(UTC)).total_seconds()) < 2


def test_stripe_client_records_date_header(app):
    from blueprints.subscription.services import clock
    from blueprints.subscription.services import stripe_client

    class _Resp:
        headers = {"Date": "Wed, 01 Jul 2026 12:00:00 GMT"}

    class _Result:
        last_response = _Resp()

    with app.app_context():
        stripe_client._record_server_time(_Result())
        assert clock.now() == datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def test_grants_access_uses_trusted_clock(app):
    """With Stripe's server time pinned ahead of the host clock, access is decided by
    that clock, not the host clock.

    ``access.grants_access`` takes ``now`` as an argument rather than reading a clock
    itself, so what this pins is the pairing: every caller feeds it ``clock.now()``, and
    the trusted value is what decides. See ``test_the_access_sweep_reads_the_trusted_clock``
    for the caller side."""
    from datetime import timedelta

    from blueprints.subscription.services import access, clock

    now_real = datetime.now(UTC)
    paid_through = now_real + timedelta(days=5)  # host-now: grants access

    with app.app_context():
        # Pin trusted time 10 days ahead → the paid period has "ended" → no access.
        future = (now_real + timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        clock.record_http_date(future)
        assert access.grants_access(
            clock.now(),
            phase="active",
            trial_end=None,
            app_access_until=None,
            period_end=paid_through,
        ) is False
        # ...and the same row still grants against the host clock, so the assertion
        # above is about the clock and not about the dates.
        assert access.grants_access(
            now_real,
            phase="active",
            trial_end=None,
            app_access_until=None,
            period_end=paid_through,
        ) is True


# NOT covered here: that ``modules.sweep_expired_module_access`` feeds ``clock.now()``
# into ``grants_access`` rather than the host clock. It discovers its own entities from
# the database, so pinning it needs entity/module fixtures — that belongs with the
# sweep's own tests, not the clock's.
