"""Public legacy-compatible entrypoint for `pettycash` package."""

__all__ = ["create_app", "app", "db", "login_manager", "csrf", "mail", "migrate"]

_LAZY_EXPORTS = frozenset(__all__)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        from .core.bootstrap import (app, create_app, csrf, db,
                                     login_manager, mail, migrate)
        _resolved = {
            "app": app, "create_app": create_app, "csrf": csrf, "db": db,
            "login_manager": login_manager, "mail": mail, "migrate": migrate,
        }
        globals().update(_resolved)
        return _resolved[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
