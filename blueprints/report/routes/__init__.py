# A module that fails to import stops the app from starting (2026-10-05): until then a loop
# skipped it at DEBUG, and its pages and guards were simply missing.
#
# Flask's Petty Cash pages and the AJAX routes behind them went on 2026-10-20 (minty-petty-cash-web
# and minty-petty-cash-api have them). What is left: the history address's hand-off, the old share
# address's redirect, the deposit correction and the receipt reading the internal routes call.

# Registers the PETTY_CASH before_request gate for the whole blueprint;
# keep first so the guard is attached before any route module loads.
from . import module_guard  # noqa: F401
from . import expense_ai  # noqa: F401
from . import history  # noqa: F401
from . import legacy  # noqa: F401
