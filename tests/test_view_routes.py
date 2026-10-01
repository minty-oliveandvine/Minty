"""Smoke tests for all application view endpoints."""

from __future__ import annotations

from typing import Any

from flask import url_for
from werkzeug.routing import (AnyConverter, FloatConverter, IntegerConverter,
                             PathConverter)
from werkzeug.routing import UUIDConverter, UnicodeConverter


def _sample_value_for_converter(converter: Any) -> str:
    if isinstance(converter, IntegerConverter):
        return "1"
    if isinstance(converter, FloatConverter):
        return "1.5"
    if isinstance(converter, UUIDConverter):
        return "00000000-0000-0000-0000-000000000001"
    if isinstance(converter, PathConverter):
        return "sample/path"
    if isinstance(converter, UnicodeConverter):
        return "sample"
    if isinstance(converter, AnyConverter):
        choices = getattr(converter, "choices", None)
        if choices:
            return next(iter(choices))
    return "sample"


def _build_url(app, rule) -> str:
    values = dict(rule.defaults or {})
    for arg in rule.arguments:
        if arg in values and values[arg] is not None:
            continue
        converter = rule._converters.get(arg)
        values[arg] = _sample_value_for_converter(converter)
    with app.test_request_context():
        return url_for(rule.endpoint, **values)


def _call_route(client, url: str):
    # OPTIONS is safe for route existence checks and avoids triggering
    # endpoint-specific business logic. Which is also why it covers nothing: Flask answers
    # it without calling the view, so the route-coverage gate does not count these
    # requests (tests/conftest.py ``_install_route_recorder``) - this is a no-500 smoke
    # test, not a test of any route.
    return client.options(url, follow_redirects=False)


def test_all_views_do_not_raise_internal_server_error(app, client):
    failures = []

    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue

        try:
            url = _build_url(app, rule)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                {
                    "endpoint": rule.endpoint,
                    "path": rule.rule,
                    "method": "OPTIONS",
                    "status": None,
                    "reason": f"urlbuild_error: {exc}",
                }
            )
            continue

        try:
            response = _call_route(client, url)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                {
                    "endpoint": rule.endpoint,
                    "path": url,
                    "method": "OPTIONS",
                    "status": None,
                    "reason": f"request_error: {exc}",
                }
            )
            continue

        status = response.status_code
        if status >= 500:
            failures.append(
                    {
                        "endpoint": rule.endpoint,
                        "path": url,
                        "method": "OPTIONS",
                        "status": status,
                        "reason": "server_error",
                    }
                )

    assert not failures, "\n".join(
        (
            f"{failure['endpoint']} {failure['method']} {failure['path']} "
            f"=> {failure['status']} {failure['reason']}"
            for failure in failures
        )
    )
