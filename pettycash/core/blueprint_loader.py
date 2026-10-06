"""Blueprint registration helpers for app bootstrap."""

from __future__ import annotations

import importlib

# Every blueprint the app is made of: (package, blueprint attribute). Its ``.routes`` package is
# imported first, for the side effect of adding the routes.
BLUEPRINTS = (
    ("blueprints.auth", "auth_bp"),
    ("blueprints.entity", "entity_bp"),
    ("blueprints.report", "report_bp"),
    ("blueprints.user_management", "user_management_bp"),
    ("blueprints.xero", "xero_bp"),
    ("blueprints.invitation", "invitation_bp"),
    ("blueprints.legal", "legal_bp"),
)


def register_blueprints(app, blueprints=BLUEPRINTS):
    """Import and register every blueprint. Nothing here is caught (2026-10-05): a routes module
    that fails to import - a missing package, a circular import - stops the app from starting
    with its traceback. Until then a failure was skipped (at DEBUG, or logged and carried on), and
    the app ran with those pages missing; a circular import once dropped ``invitation`` that way,
    seen only as ``url_for`` BuildErrors in invite emails much later.
    """
    # Fully load the model registry FIRST. ``models.db`` imports every model submodule (e.g.
    # blueprints.invitation.models.invitation), and those do ``from models.db import db``: a
    # blueprint's ``.routes`` imported before ``models.db`` has finished re-enters a
    # half-initialised module ("cannot import name ... from partially initialized module").
    import models.db  # noqa: F401

    for module_path, attr in blueprints:
        importlib.import_module(f"{module_path}.routes")
        module = importlib.import_module(module_path)
        app.register_blueprint(getattr(module, attr))


def register_compat_alias(app, endpoint_aliases):
    # Placeholder for compatibility aliases. Keep route name compatibility
    # here.
    rules_by_endpoint = {}
    for rule in app.url_map.iter_rules():
        rules_by_endpoint.setdefault(rule.endpoint, []).append(rule)

    for endpoint, aliases in endpoint_aliases.items():
        for alias in aliases:
            if endpoint not in app.view_functions or alias in app.view_functions:
                continue

            view_func = app.view_functions[endpoint]
            app.view_functions[alias] = view_func

            for rule in rules_by_endpoint.get(endpoint, []):
                app.add_url_rule(
                    rule.rule,
                    endpoint=alias,
                    view_func=view_func,
                    defaults=rule.defaults,
                    methods=rule.methods,
                    strict_slashes=rule.strict_slashes,
                    merge_slashes=rule.merge_slashes,
                    provide_automatic_options=rule.provide_automatic_options,
                    subdomain=rule.subdomain,
                )
