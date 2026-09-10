"""Database column types shared by the subscription tables.

Created by ``u1a01_subscription_types``, which turned the ids into ``uuid`` and
four status vocabularies into Postgres enums. The models bind to those types here
rather than each declaring its own, for two reasons:

  * ``extension_state`` and ``subscription_phase`` are each used by TWO tables.
    Spelling the label set out twice is how the two spellings drift apart, and a
    drifted enum does not fail on the write - see the note on LookupError below.
  * the label sets are a fact about the DATABASE, not about any one model, so
    they belong beside each other where a reader can see the whole vocabulary.

WHY ``as_uuid=False``

The ids round-trip as Python ``str``, not ``uuid.UUID``. That is what keeps this a
type change and not a rewrite: every ``default=lambda: str(uuid.uuid4())`` keeps
working, every ``str(x)`` coercion at a query boundary keeps matching, and every
interpolated idempotency key - ``f"transfer-{offer.id}-{n}"`` in transfers, the
dunning and renewal keys - keeps producing byte-identical text. Under
``as_uuid=True`` those strings change and a retry stops matching a key that was
already claimed, which means charging twice.

It is also the established shape in this codebase: see
``blueprints/entity/models/currency_info.py`` and ``entity.py``.

WHY ``create_type=False``

The migration owns the four types. Without this flag SQLAlchemy tries to
``CREATE TYPE`` them itself whenever a table is created, which both fights the
migration and fails on a second table using the same type.

WHY THE LABEL SETS MUST BE COMPLETE

SQLAlchemy validates on the way OUT, not only on the way in: reading a value that
is not in the list raises ``LookupError``. A missing label therefore does not
announce itself when the row is written - it detonates later, on an unrelated
read, a long way from the cause.
"""
from sqlalchemy.dialects.postgresql import ENUM, UUID

from blueprints.subscription import constants

SCHEMA = "pettycashv2"


def uuid_column():
    """The id type: a uuid in the database, a ``str`` in Python.

    A function rather than a shared instance so each column gets its own type
    object, matching how the rest of the codebase declares these.
    """
    return UUID(as_uuid=False)


PHASES = (
    constants.PHASE_TRIAL,
    constants.PHASE_ACTIVE,
    constants.PHASE_PAST_DUE,
    constants.PHASE_SCHEDULED_CANCEL,
    constants.PHASE_CANCELLED,
    constants.PHASE_EXPIRED,
)

#: The three terminal undo outcomes have no constants in ``constants.py`` - they
#: were written by the Stripe invoice-item path, which went with the in-house
#: billing cutover, and nothing produces them today. They are still in the enum
#: because rows still HOLD them, and a label the data holds but the type rejects
#: fails on the read. constants.py documents them in the comment above
#: ``EXT_PENDING``; they are spelled out here because this is the list the
#: database is built from.
EXT_TERMINAL_LEGACY = ("deleted", "credited", "refunded")

EXTENSION_STATES = (
    constants.EXT_PENDING,
    constants.EXT_INVOICED,
    *EXT_TERMINAL_LEGACY,
)

TRANSFER_STATUSES = (
    constants.TRANSFER_PENDING,
    constants.TRANSFER_CHARGING,
    constants.TRANSFER_CHARGED,
    constants.TRANSFER_ACCEPTED,
    constants.TRANSFER_DECLINED,
    constants.TRANSFER_CANCELLED,
    constants.TRANSFER_EXPIRED,
)

OUTCOMES = (constants.OUTCOME_SUCCEEDED, constants.OUTCOME_ABORTED)


def _enum(name, values):
    return ENUM(*values, name=name, schema=SCHEMA, create_type=False)


#: entity_module_subscription.phase, subscription_audit_log.phase_before/_after
SUBSCRIPTION_PHASE = _enum("subscription_phase", PHASES)

#: entity_module_subscription.extension_state, subscription_audit_log.extension_state
EXTENSION_STATE = _enum("extension_state", EXTENSION_STATES)

#: subscription_transfer.status
TRANSFER_STATUS = _enum("transfer_status", TRANSFER_STATUSES)

#: subscription_audit_log.outcome
AUDIT_OUTCOME = _enum("audit_outcome", OUTCOMES)
