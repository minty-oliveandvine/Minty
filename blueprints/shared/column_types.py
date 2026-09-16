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

from sqlalchemy import CHAR
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import TypeDecorator


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
