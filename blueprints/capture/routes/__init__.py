from importlib import import_module

from loguru import logger

_ROUTE_MODULES = (
    # Registers the kill switch + PETTY_CASH-or-BILL before_request gate for
    # the whole blueprint. KEEP FIRST so the guard is attached before any route
    # module loads — a route registered ahead of its guard is a route with no
    # guard.
    "module_guard",
    "upload",
    "api",
    "files",
    "queue",
)

for _module_name in _ROUTE_MODULES:
    try:
        import_module(f"{__name__}.{_module_name}")
    except Exception as exc:
        # ERROR with a traceback, not DEBUG. The report blueprint logs the same
        # failure at DEBUG, and ``pettycash/core/blueprint_loader.py`` carries a
        # comment about the afternoon that cost someone: a route module that
        # fails to import means its endpoints do not exist, and the symptom
        # surfaces much later as a url_for BuildError somewhere unrelated.
        #
        # Losing ``module_guard`` would be worse than losing a route — the
        # remaining routes would then be ungated.
        logger.exception(
            f"Failed to import capture route module {_module_name!r}: "
            f"{type(exc).__name__}: {exc}"
        )


# The bubble's context processor. Registered with ``@capture_bp
# .app_context_processor`` in the services package, so it has to be IMPORTED
# before the blueprint is registered on the app — importing the routes package
# is the hook that happens at the right moment. Without this line the decorator
# never runs, the ``capture_bubble`` variable is undefined in every template,
# and the bubble simply never appears with nothing in the log to say why.
try:
    from blueprints.capture.services import context  # noqa: F401
except Exception as exc:
    logger.exception(
        f"Failed to import the capture bubble context processor: "
        f"{type(exc).__name__}: {exc}"
    )
