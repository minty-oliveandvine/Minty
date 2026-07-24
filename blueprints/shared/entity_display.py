"""Display helpers shared across blueprints."""

from __future__ import annotations

import re
from datetime import datetime


def build_entity_acronym(name: str | None, *, letters_only: bool = False) -> str:
    """Build the initials badge shown for an entity.

    Takes the first character of each whitespace-separated word, uppercased.

    ``letters_only`` controls how words starting with a non-letter are handled,
    because the codebase historically had two behaviours and both are still in
    use:

    - ``False`` (default): every word contributes its first character, so
      ``"7 Eleven Store"`` → ``"7ES"``. This matches the entity, report, auth
      and invitation pages.
    - ``True``: words whose first character isn't ``A-Za-z`` are skipped, so
      ``"7 Eleven Store"`` → ``"ES"``. This matches share links
      (``report/services/share.py``).
    """
    if not name:
        return ""
    return "".join(
        word[0].upper()
        for word in name.split()
        if word and (not letters_only or re.match(r"[A-Za-z]", word[0]))
    )


def entity_badge_date(entity):
    """The creation date shown on an entity badge, or ``None``.

    ``created_at`` is a ``datetime`` on some paths and already a ``date`` on
    others, so it is narrowed to a ``date`` only when needed.
    """
    created_at = getattr(entity, "created_at", None) if entity else None
    if not created_at:
        return None
    if isinstance(created_at, datetime):
        return created_at.date()
    return created_at


def entity_badge_data(entity, *, letters_only: bool = False):
    """Return ``(acronym, badge_date)`` for an entity badge.

    Convenience pairing of :func:`build_entity_acronym` and
    :func:`entity_badge_date`, which the report pages always use together.
    """
    name = getattr(entity, "name", None) if entity else None
    return (
        build_entity_acronym(name, letters_only=letters_only),
        entity_badge_date(entity),
    )
