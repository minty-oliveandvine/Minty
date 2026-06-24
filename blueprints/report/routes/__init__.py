from importlib import import_module

from loguru import logger

_ROUTE_MODULES = (
    "api",
    "cash_count",
    "create",
    "deposit",
    "download",
    "ending",
    "expense",
    "export_screenshot",
    "history",
    "legacy",
    "opening",
    "report_detail",
    "sales",
    "submitted",
)

for _module_name in _ROUTE_MODULES:
    try:
        import_module(f"{__name__}.{_module_name}")
    except Exception as exc:
        logger.debug(f"Skip importing report route module {_module_name}: {exc}")
