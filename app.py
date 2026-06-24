"""Compatibility entrypoint for legacy imports.

Keep the legacy application module isolated while preserving the historical
``app.py`` import surface (e.g. ``from app import app``).
"""

from __future__ import annotations

from services.app_runtime import legacy as legacy_runtime

__all__ = tuple(name for name in dir(legacy_runtime) if not name.startswith("_"))
globals().update({name: getattr(legacy_runtime, name) for name in __all__})

