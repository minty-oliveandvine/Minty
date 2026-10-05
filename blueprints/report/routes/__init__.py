from importlib import import_module

from loguru import logger

_ROUTE_MODULES = (
    # Registers the PETTY_CASH before_request gate for the whole blueprint;
    # keep first so the guard is attached before any route module loads.
    "module_guard",
    # Old /report/... wizard addresses -> /entity/<shortid>/<name>/reports/...; and the company
    # in the address must own the report.
    "company_addresses",
    "api",
    "cash_count",
    "create",
    "deposit",
    "download",
    "ending",
    "expense",
    "expense_ai",
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
