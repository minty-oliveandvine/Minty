"""AI Hub (Stage 2).

NAMING. On screen this feature is called **AI Hub**. In the code it is
``capture`` — this blueprint, ``/capture/*``, and the three ``capture_*``
tables. Those identifiers stay as they are: renaming a blueprint, its routes
and three tables to follow a label is churn with real risk and no user benefit.

It is the same rule as BILL / Payment: the database keeps the old name, and
every word a user can see says the new one. Do not "tidy up" ``capture``.

The hub is its OWN blueprint, not part of ``report``, and that is a decision
rather than a filing preference. Every route in the report blueprint sits
behind a ``before_request`` gate that denies access when PETTY_CASH is off for
the entity (see ``blueprints/report/routes/module_guard.py``). A customer who
bought Payment Submission but not Petty Cash would therefore be locked out of
their own capture hub.

So this blueprint carries its own gate: PETTY_CASH **or** BILL opens it.
See ``blueprints/capture/routes/module_guard.py``.
"""

from flask import Blueprint

capture_bp = Blueprint("capture", __name__)
