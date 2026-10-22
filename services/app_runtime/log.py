"""Flask's ``logger``: loguru's call shape (``logger.info("{} issued", n)``,
``logger.exception(...)``) over the standard library's ``minty`` logger, through
``minty_shared.log.BraceLogger`` - so every call site and its text stayed as it was when loguru
was dropped (2026-10-22). The line format and the trace/user/entity/step context are
``minty_shared.logctx``; ``services/app_runtime/legacy/bootstrap.py`` configures the handlers.
"""

from minty_shared.log import BraceLogger

logger = BraceLogger("minty")
