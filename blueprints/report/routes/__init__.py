# A module that fails to import stops the app from starting (2026-10-05): until then a loop
# skipped it at DEBUG, and its pages and guards were simply missing.

# Registers the PETTY_CASH before_request gate for the whole blueprint;
# keep first so the guard is attached before any route module loads.
from . import module_guard  # noqa: F401
# Old /report/... wizard addresses -> /entity/<shortid>/<name>/reports/...; and the company
# in the address must own the report.
from . import company_addresses  # noqa: F401
from . import api  # noqa: F401
from . import cash_count  # noqa: F401
from . import create  # noqa: F401
from . import deposit  # noqa: F401
from . import download  # noqa: F401
from . import ending  # noqa: F401
from . import expense  # noqa: F401
from . import expense_ai  # noqa: F401
from . import export_screenshot  # noqa: F401
from . import history  # noqa: F401
from . import legacy  # noqa: F401
from . import opening  # noqa: F401
from . import report_detail  # noqa: F401
from . import sales  # noqa: F401
from . import submitted  # noqa: F401
