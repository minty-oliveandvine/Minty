"""Column types the rebased schema needs, shared by every model.

``MintyUuid`` is *the* uuid column type. In Postgres it is the native ``uuid``; the Python
value is always the hyphenated lowercase ``str`` (``as_uuid=False``), so every
``default=lambda: str(uuid.uuid4())``, every ``str(x)`` at a query boundary and every
interpolated idempotency key keeps producing byte-identical text.

Why not ``sqlalchemy.Uuid`` or ``postgresql.UUID`` directly: the test suite still runs
on SQLite, and the two spell a uuid differently there - ``sqlalchemy.Uuid`` stores 32 hex
characters, ``postgresql.UUID`` (a Postgres-only type) falls back to a column with NUMERIC
affinity that keeps the hyphenated text (and silently turns an all-digit uuid into a
float). During phase C the tables convert one unit at a time, so a converted ``uuid``
column is routinely joined to a not-yet-converted ``String(36)`` one; with mixed
spellings that join matches nothing on SQLite while matching everything on Postgres, and
the suite lies. Storing CHAR(36) hyphenated text everywhere but Postgres keeps SQLite
comparisons honest until phase C is over and the SQLite path is retired (C10).

A well-formed value is normalised (lower case, hyphenated). A value that is NOT a uuid is
passed through untouched rather than refused here: Postgres refuses it itself (DataError),
and on SQLite it simply matches nothing - the same "not found" a bad id got before the
column was a uuid. Raising from the bind step would turn a junk id in a URL into a
StatementError inside SQLAlchemy, which no route handles; the DB's own error is the one
place a junk id should fail, and it is for the routes to validate ids before asking.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CHAR, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import DateTime, TypeDecorator


class MintyUuid(TypeDecorator):
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        try:
            return str(uuid.UUID(str(value)))  # normalises case / hyphens
        except (ValueError, AttributeError, TypeError):
            return str(value)  # junk: let the database say so (or match nothing)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return str(value)

    @property
    def python_type(self):
        return str


def Money(precision: int = 14, scale: int = 2):
    """The schema's ``numeric(14,2)`` money column.

    ``asdecimal=False``: the Python side still computes in ``float`` in a few hundred places
    (form values via ``safe_float``, balance arithmetic, Jinja formatting), and Decimal would
    break every ``Decimal + float`` on the way. The DATABASE is exact - a float ``0.30000000000000004``
    lands as ``0.30`` and comes back as ``0.3`` - which is the guarantee the redesign asked
    for; moving the in-process arithmetic to Decimal is a later, separate pass.
    """
    return Numeric(precision, scale, asdecimal=False)


def pg_enum(enum_cls):
    """``db.Enum`` for one of ``blueprints/shared/enums``: the Postgres type is the enum's
    ``pg_name`` in the ``pettycashv3`` schema, never created by SQLAlchemy, stored by value."""
    from sqlalchemy import Enum

    return Enum(
        enum_cls, name=enum_cls.pg_name, schema="pettycashv3", native_enum=True,
        create_type=False, values_callable=lambda e: [m.value for m in e],
    )


def cents(value) -> float:
    """A money figure computed in Python, back to whole cents.

    The columns are ``numeric(14,2)`` (exact) but the application still adds floats, so a
    sum of exact cents can come out as 0.9999999999999999. Every figure that is the result
    of arithmetic and is shown or stored goes through here; a value read straight from a
    column does not need to.
    """
    return round(float(value or 0), 2)


class AwareDateTime(TypeDecorator):
    """``timestamptz`` that always comes back timezone-aware.

    Postgres returns an aware datetime for a ``timestamp with time zone`` column; SQLite
    (the test path until C10) returns it naive, and the billing layer refuses a naive
    stamp rather than guess a zone (``billing._require_aware``). The subscription services
    had grown per-caller ``_aware()`` repairs for that; the type does it once, on the way
    out. Naive values are UTC - which is what every writer in the application stores.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            from datetime import timezone

            return value.replace(tzinfo=timezone.utc)
        return value
