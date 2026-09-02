"""How a payer-facing value is printed.

Small on purpose. It exists because ``portal`` and ``payment_methods`` each carried a
byte-identical ``_fmt`` -- the same one-line date format, written twice -- and neither is
the right owner of the other's copy: ``payment_methods`` already imports ``portal``, so
the direction is settled, but reaching across a layer for a PRIVATE helper is worse than
a module that belongs to neither.

Two forms of the same date exist in this blueprint, and the difference is deliberate:

* :func:`day` -- ``15 Aug 2026``, zero-padded. What the payer portal and the card list
  print, because the design sets those in a table where a ragged left edge reads badly.
* ``notify.day`` -- ``5 Aug 2026``, unpadded. What the billing EMAILS print, because
  prose does not zero-pad a date.

Kept apart rather than unified behind a flag: they are two typographic decisions about
two different surfaces, not one rule with a parameter.
"""
from __future__ import annotations


def day(moment) -> str | None:
    """``15 Aug 2026`` -- zero-padded day, as the design prints it. None when unset."""
    return moment.strftime("%d %b %Y") if moment else None
