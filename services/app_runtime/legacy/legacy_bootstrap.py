"""Compatibility shim for legacy bootstrap module path."""

from .bootstrap import create_app

__all__ = ["create_app"]

# Backward-compatible import name expected by recommended structure.
