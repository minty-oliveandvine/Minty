"""A routes module that fails to import stops the app from starting (2026-10-05).

``pettycash/core/blueprint_loader.py`` used to skip such a failure (at DEBUG, or logged and
carried on), so the app ran with those pages missing. Each case is a throwaway package on
``sys.path`` with its own name, so ``sys.modules`` caching cannot hide one.
"""

from __future__ import annotations

import pytest
from flask import Flask

from pettycash.core.blueprint_loader import register_blueprints

INIT = (
    "from flask import Blueprint\n"
    "bp = Blueprint({name!r}, __name__)\n"
)


def _package(tmp_path, monkeypatch, name: str, routes: str) -> str:
    package = tmp_path / name
    (package / "routes").mkdir(parents=True)
    (package / "__init__.py").write_text(INIT.format(name=name))
    (package / "routes" / "__init__.py").write_text(routes)
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def test_a_healthy_blueprint_registers_with_its_routes(tmp_path, monkeypatch):
    name = _package(tmp_path, monkeypatch, "loader_ok_pkg", (
        "from loader_ok_pkg import bp\n"
        "@bp.route('/loader-ok')\n"
        "def ok():\n"
        "    return 'ok'\n"
    ))
    app = Flask(__name__)

    register_blueprints(app, blueprints=((name, "bp"),))

    assert "/loader-ok" in {rule.rule for rule in app.url_map.iter_rules()}


def test_a_missing_package_in_a_routes_module_stops_the_start(tmp_path, monkeypatch):
    name = _package(tmp_path, monkeypatch, "loader_missing_pkg",
                    "import a_package_that_is_not_installed_anywhere  # noqa: F401\n")

    with pytest.raises(ModuleNotFoundError, match="a_package_that_is_not_installed_anywhere"):
        register_blueprints(Flask(__name__), blueprints=((name, "bp"),))


def test_any_other_import_failure_stops_the_start_too(tmp_path, monkeypatch):
    name = _package(tmp_path, monkeypatch, "loader_broken_pkg", "raise RuntimeError('broken routes')\n")

    with pytest.raises(RuntimeError, match="broken routes"):
        register_blueprints(Flask(__name__), blueprints=((name, "bp"),))
