"""Blueprint registration helpers for app bootstrap."""

from __future__ import annotations

from loguru import logger


def _register_if_available(app, module_path: str, attr: str) -> None:
    try:
        __import__(f"{module_path}.routes")
    except ModuleNotFoundError:
        pass
    except Exception as exc:
        # Keep bootstrap resilient when optional route modules are unavailable.
        logger.debug(f"Skip importing routes for {module_path}: {exc}")
    try:
        module = __import__(module_path, fromlist=[attr])
        blueprint = getattr(module, attr)
        app.register_blueprint(blueprint)
    except ModuleNotFoundError:
        return
    except Exception as exc:
        # Keep bootstrap resilient when optional modules are intentionally
        # absent.
        logger.debug(f"Skip registering blueprint {module_path}.{attr}: {exc}")


def register_blueprints(app):
    for module_path, attr in (
        ("blueprints.auth", "auth_bp"),
        ("blueprints.entity", "entity_bp"),
        ("blueprints.report", "report_bp"),
        ("blueprints.user_management", "user_management_bp"),
        ("blueprints.xero", "xero_bp"),
        ("blueprints.invitation", "invitation_bp"),
        ("blueprints.consent", "consent_bp"),
        ("blueprints.admin", "admin_bp"),
        ("blueprints.file", "file_bp"),
        ("blueprints.api", "api_bp"),
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
