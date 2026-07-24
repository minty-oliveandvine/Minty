"""Display helpers shared across blueprints."""

from __future__ import annotations

import re


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
