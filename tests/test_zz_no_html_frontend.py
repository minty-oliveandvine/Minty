"""Flask is a backend only - and must not quietly grow pages again (the owner, 2026-10-16).

Every screen is a Next.js app's: minty-web (sign-in, companies, settings, profile),
minty-onboarding-web, minty-payment-request-web and minty-petty-cash-web. Flask keeps JSON APIs,
redirects and hand-offs (``/handoff/*``, ``/enter``, ``/api/*``, ``/api/internal/*``, Xero's
``/callback``) and its outgoing mail, which is inline HTML in Python, never a template. So this
guard fails the moment:

* a ``templates/`` folder comes back, or application code imports ``render_template`` /
  ``render_template_string`` (checked on the import statements, AST, as ``test_zz_no_stripe``);
* any GET route - signed in or not, and an unknown address too - answers ``text/html``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import char_factories as F
import pytest

ROOT = Path(__file__).resolve().parents[1]
DIRS = ["blueprints", "models", "services", "pettycash", "utils", "main.py", "app.py", "config.py"]
FORBIDDEN = {"render_template", "render_template_string"}


def _python_files():
    for entry in DIRS:
        path = ROOT / entry
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("*.py"))


def test_there_is_no_templates_folder():
    assert not (ROOT / "templates").exists()


def test_no_application_code_renders_a_template():
    hits = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "flask":
                hits += [f"{path.relative_to(ROOT).as_posix()}:{node.lineno}" for a in node.names if a.name in FORBIDDEN]
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert hits == []


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, name="Vine Cafe Central", currency=currency, country=country)
    return {"owner": owner, "entity": entity}


def _get_paths(app, entity_id):
    """Every GET route, its arguments filled with the shop's company (or a placeholder)."""
    paths = set()
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint == "static":
            continue
        values = {}
        for arg in rule.arguments:
            values[arg] = entity_id if "entity" in arg or arg in ("id", "org_id") else "x"
        try:
            paths.add(rule.build(values, append_unknown=False)[1])
        except Exception:  # a converter that refuses the placeholder: not reachable as a page
            continue
    return sorted(paths)


def _html(resp) -> bool:
    """A page: an HTML body that is not a redirect's (Werkzeug writes a tiny HTML body on a 3xx)."""
    return resp.mimetype == "text/html" and not 300 <= resp.status_code < 400


def test_no_get_route_answers_html(app, client, shop):
    paths = _get_paths(app, shop["entity"].id)
    assert paths, "no GET routes found"

    anonymous = [p for p in paths if _html(client.get(p))]
    F.login(client, shop["owner"])
    signed_in = [p for p in paths if _html(client.get(p))]

    assert (anonymous, signed_in) == ([], [])


def test_an_unknown_address_answers_json(client):
    resp = client.get("/no-such-page-anywhere")

    assert resp.status_code == 404
    assert resp.mimetype == "application/json"
