"""Row-timestamp columns, declared once.

Eleven subscription models carried a byte-identical ``created_at`` and six of them a
byte-identical ``updated_at`` beside it. Identical is the point: the columns are not
interesting individually, so a copy in each model is eleven places for one of them to
quietly acquire a different ``nullable`` or lose its ``onupdate``.

TWO mixins rather than one, deliberately. Five of the eleven have ``created_at`` and no
``updated_at``, and that is a real distinction, not an oversight: an append-only record
is never updated, so a column claiming otherwise would be a lie the schema tells. Folding
them all into one mixin would ADD a column to five shipped tables -- a migration, not a
refactor, and migrations are out of scope here.

``billing_policy`` is a third shape again (``updated_at`` with no ``created_at``: a single
tunable row that is edited and never inserted) and keeps its own column.

One positional note, checked rather than assumed: every model declared these columns
last except ``subscription_transfer``, which had ``created_at`` in the middle of its
lifecycle timestamps. Taking the mixin moves it to the end of that model's column list.
Nothing reads columns by position -- the ORM maps by name and the shipped tables are
untouched -- so this is inert; it is written down because a column that moves without a
reason is exactly the kind of thing worth being able to rule out later.

The values are server-side (``server_default``/``onupdate`` = ``now()``), so the DATABASE
stamps them. That matters for the same reason ``services.clock`` exists: a wrong app-host
clock must not be able to write a wrong time into a billing row.
"""
from models.db import db


class CreatedAtMixin:
    """When the row was written. For records that are appended and never edited."""

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )


class TimestampMixin:
    """``created_at`` plus an ``updated_at`` the database moves on every write.

    Declares ``created_at`` itself rather than inheriting ``CreatedAtMixin``. Inheriting
    reads better but reverses the two columns: SQLAlchemy orders mixin columns by when
    the ``Column`` objects were constructed, so the subclass's ``updated_at`` landed
    ahead of the base's ``created_at``. One repeated declaration between two adjacent
    classes is a cheaper price than a column order that no longer matches the shipped
    tables.
    """

    created_at = db.Column(
        db.DateTime(timezone=True), server_default=db.func.now(), nullable=False
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )
