"""Regression: the EMPTY-state "create entity" button must start a fresh onboarding.

Bug: two paths reach the wizard. ``entity.entity_create`` (the "+" on a populated
list) passed ``fresh=True``, but the ``onboarding_launch_url`` Jinja global used by
``entity/entity_list_empty.html`` did not. Without ``?fresh=1`` the wizard rehydrates
its single global session blob from localStorage and drops the user back into the
last in-progress entity instead of creating a new one.

A user with no entities only ever sees the empty state, so for them EVERY attempt to
create an entity resumed the stale session. That is the case this locks down.

Resuming a real in-progress entity is a different path (clicking the entity row,
which passes ``entity_id``); ``fresh`` and ``entity_id`` are mutually exclusive, so
the asserts below also check that the fresh URL binds no entity.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit



class _User:
    """Minimal stand-in: the launch URL only reads id and the name fields."""

    id = "11111111-2222-3333-4444-555555555555"
    first_name = "Ang"
    last_name = "Tardaguela"
    is_authenticated = True


def _params(url: str) -> dict:
    return parse_qs(urlsplit(url).query)


# Imported inside each test on purpose: conftest clears ``blueprints.*`` from
# sys.modules, so a module-level import here would bind a stale copy.
def _launch_url():
    from blueprints.entity.routes.create import onboarding_launch_url

    return onboarding_launch_url


def test_fresh_emits_fresh_flag_and_no_entity(app):
    with app.app_context():
        url = _launch_url()(_User(), fresh=True)
    params = _params(url)
    assert params.get("fresh") == ["1"]
    assert "entity_id" not in params
    assert params.get("token")


def test_resume_binds_entity_and_never_sets_fresh(app):
    """fresh and entity_id are mutually exclusive — entity_id wins."""
    with app.app_context():
        url = _launch_url()(
            _User(), entity_name="onboarding 2", entity_id="abc-123", fresh=True
        )
    params = _params(url)
    assert params.get("entity_id") == ["abc-123"]
    assert params.get("entity_name") == ["onboarding 2"]
    assert "fresh" not in params


def test_default_launch_does_not_claim_fresh(app):
    """The bare call is the resume-ish default; only explicit fresh sets the flag."""
    with app.app_context():
        url = _launch_url()(_User())
    assert "fresh" not in _params(url)


