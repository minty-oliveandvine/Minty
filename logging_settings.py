# -*- coding: utf-8 -*-
"""Shared logging format constants.

This module keeps the fixed-width Loguru format in one place so it is easy to
share between bootstrap, CLI scripts, and background jobs.
"""

LOG_LEVEL_DEFAULT = "INFO"
LOG_FORMAT_FIXED_WIDTH = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name: <26} | "
    "{module: <24}:{line: >5} | "
    "{function: <22} | "
    "{message}"
)
