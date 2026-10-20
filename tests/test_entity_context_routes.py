from __future__ import annotations

import sys
import types

from flask import Flask

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)

from blueprints.auth.routes import dashboard as dashboard_routes


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    app.add_url_rule("/entity", endpoint="entity.entity_list", view_func=lambda: "")
    return app


def test_index_redirects_to_entity_list_without_entity_context():
    app = _build_app()

    with app.test_request_context("/index"):
        response = dashboard_routes.index.__wrapped__()

    assert response.status_code == 302
    assert response.location is not None
    assert response.location.endswith("/entity")
