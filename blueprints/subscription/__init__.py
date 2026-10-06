"""Subscription tables, as SQLAlchemy models - and nothing that acts on them.

The subscription engine is minty-subscription-api (Django): it owns every write to these
tables and is the only service that talks to Stripe. Flask's copy of the engine - the
services, the payer-portal routes, the CLI and the in-process scheduler - was deleted on
2026-10-06.

What stays here:

* ``models/`` - the 13 models, for Alembic and ``models.db`` (the schema's source of
  truth is ``docs/schema/01_schema_rebased.sql``);
* ``constants.py`` - the phase and status words those rows carry;
* ``services/store_ro.py`` - the few READS the rest of Flask still makes (who pays for a
  company, whether a module is billed, the entity list's trial badge).

No blueprint: there are no routes.
"""
