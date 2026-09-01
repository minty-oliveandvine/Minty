"""Blueprint registration helpers for app bootstrap."""

from __future__ import annotations

from loguru import logger

# Blueprints that MUST register for the app to work. A failure to register one
# of these is a real bug (not an optional module being absent), so it is logged
# at ERROR with a traceback instead of being swallowed at DEBUG. Historically a
# circular import silently dropped ``invitation`` here, which only surfaced much
# later as ``url_for('invitation.accept_invitation_page')`` BuildErrors during
# invite-email sends (email_sent=False). Loud logging prevents a repeat.
_EXPECTED_BLUEPRINTS = frozenset(
    {
        "blueprints.auth",
        "blueprints.entity",
        "blueprints.report",
        "blueprints.user_management",
        "blueprints.xero",
        "blueprints.invitation",
        "blueprints.legal",
        # Registered without a url_prefix and carrying the 15 payer-portal API
        # routes. Left out of this set, an import failure in routes/portal.py would
        # drop every one of them at DEBUG and nothing would say so.
        "blueprints.subscription",
    }
)


def _register_if_available(app, module_path: str, attr: str) -> None:
    expected = module_path in _EXPECTED_BLUEPRINTS
    try:
        __import__(f"{module_path}.routes")
    except ModuleNotFoundError:
        pass
    except Exception as exc:
        # A route module that fails to import means its endpoints won't exist,
        # so url_for() to them raises BuildError downstream. For expected
        # blueprints this is a bug — log loudly with the traceback.
        if expected:
            logger.exception(
                f"Failed to import routes for expected blueprint "
                f"{module_path!r}: {type(exc).__name__}: {exc}"
            )
        else:
            logger.debug(f"Skip importing routes for {module_path}: {exc}")
    try:
        module = __import__(module_path, fromlist=[attr])
        blueprint = getattr(module, attr)
        app.register_blueprint(blueprint)
    except ModuleNotFoundError:
        return
    except Exception as exc:
        if expected:
            logger.exception(
                f"Failed to register expected blueprint "
                f"{module_path}.{attr}: {type(exc).__name__}: {exc}"
            )
        else:
            # Keep bootstrap resilient when optional modules are intentionally
            # absent.
            logger.debug(
                f"Skip registering blueprint {module_path}.{attr}: {exc}"
            )


def register_blueprints(app):
    # Fully load the model registry FIRST. ``models.db`` imports every model
    # submodule (e.g. blueprints.invitation.models.invitation) to register them
    # with SQLAlchemy, and those submodules do ``from models.db import db``.
    # If a blueprint's ``.routes`` is imported before ``models.db`` has finished
    # executing, that ``from models.db import db`` re-enters a half-initialized
    # ``models.db`` and raises "cannot import name ... from partially
    # initialized module" — which previously silently dropped the invitation
    # blueprint. Importing models.db to completion here makes registration
    # order-independent.
    try:
        import models.db  # noqa: F401
    except Exception:
        logger.exception("Failed to pre-load models.db before blueprint registration")

    for module_path, attr in (
        ("blueprints.auth", "auth_bp"),
        ("blueprints.entity", "entity_bp"),
        ("blueprints.report", "report_bp"),
        ("blueprints.user_management", "user_management_bp"),
        ("blueprints.xero", "xero_bp"),
        ("blueprints.invitation", "invitation_bp"),
        ("blueprints.legal", "legal_bp"),
        ("blueprints.admin", "admin_bp"),
        ("blueprints.file", "file_bp"),
        ("blueprints.api", "api_bp"),
        ("blueprints.subscription", "subscription_bp"),
    ):
        _register_if_available(app, module_path, attr)


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
