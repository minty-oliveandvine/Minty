"""Delete what replay runs leave behind — orphaned Stripe objects, and dangling rows.

Every re-run of a replay ORPHANS a customer. A Stripe test clock cannot be rewound, so
`--setup` mints a new clock and a new customer whenever the old one is spent, and
`store.upsert_customer_mapping` re-points the payer at the new one. The previous
customer keeps its invoices, its payment methods and its clock, and nothing in Minty
references it again — but it is still there, and after a few days of iterating on a
scenario the test account is mostly wreckage.

    python scripts/subscription/prune_replay_stripe.py                 # report only
    python scripts/subscription/prune_replay_stripe.py --delete

WHAT COUNTS AS ORPHANED. A customer is IN USE if any `user_stripe_customer` row in
EITHER database names it — local and RDS are checked together, deliberately. They hold
different runs (and RDS is currently behind), so trusting one would delete the other's
live payer. A database that cannot be reached is a REFUSAL, not an empty set: "no rows
came back" and "no rows exist" must never be the same answer when the difference is
whether a customer gets deleted.

WHAT IS IN SCOPE. Only objects this harness made: a customer carrying
`metadata.purpose == "scenario-replay"`, or one attached to a test clock named
`replay-*`. The Stripe test account is shared with ordinary development, and a prune that
matched everything would take those with it.

Test clocks are deleted rather than their customers, where possible: deleting a clock
removes every object bound to it — customers, invoices, payment methods — in one call.
A clock is only deleted when NONE of its customers is in use.

SAFETY. Refuses outright unless `STRIPE_SECRET_KEY` is a test key, and skips anything
created in the last few minutes (`--min-age-minutes`), so a replay running in another
window cannot have its clock deleted out from under it between `TestClock.create` and
the mapping row that would mark it in use.

DANGLING ROWS, the database half. `--teardown` deletes a run's entities, and every table
that references them goes with them — `entity_module_subscription`, `entity_billing_consent`,
`user_entity`, `entity_function_map` all carry `ON DELETE CASCADE`. ONE table does not:
`subscription_audit_log` has no foreign keys at all, in either database, despite the model
declaring three. Its rows therefore outlive the entities they name, and the portal renders
history for companies that are not there. One payer replayed three times held sixteen audit
rows, eight of them pointing at nothing.

Scoped to the payer ids in ``replay_scenarios.RUNS`` — synthetic constants, every one — and
to rows whose `entity_id` matches no entity. That scoping is the whole safety argument, and
it is not incidental: for a REAL payer those same rows are the point of the table. An audit
row is history, and history has to survive the thing it describes being deleted. Only a
seeded fixture should lose its past when its entities are torn down.

Invoices are deliberately NOT swept, though they dangle the same way: `subscription_invoice`
has no payer FK and its lines have no entity FK, both documented as intentional — "this is
history and must survive the payer row". `reset()` removes a run's invoices by payer, which
is the right handle for them.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blueprints.shared.schema import SCHEMA  # noqa: E402


UTC = timezone.utc
CLOCK_PREFIX = "replay-"
PURPOSE = "scenario-replay"


def _stripe():
    import stripe

    from blueprints.subscription.services.stripe_client import STRIPE_API_VERSION

    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        raise SystemExit("refusing to run: STRIPE_SECRET_KEY is not a test key")
    stripe.api_key = key
    # The app's pinned version, not whatever the installed SDK defaults to (see the pin).
    stripe.api_version = STRIPE_API_VERSION
    return stripe


def _in_use() -> set[str]:
    """Every customer id named by a payer row, in BOTH databases.

    Raises rather than skipping a database it cannot read — see the module docstring.
    """
    ids: set[str] = set()
    for name in ("LOCAL_DATABASE_URI", "RDS_DATABASE_URI"):
        uri = os.environ.get(name)
        if not uri:
            raise SystemExit(f"{name} is not set; cannot tell which customers are in use")
        try:
            with create_engine(uri).connect() as conn:
                rows = conn.execute(text(
                    f"SELECT stripe_customer_id FROM {SCHEMA}.user_stripe_customer "
                    "WHERE stripe_customer_id IS NOT NULL"
                ))
                found = {r[0] for r in rows}
        except SystemExit:
            raise
        except Exception as exc:
            raise SystemExit(
                f"could not read {name} ({type(exc).__name__}: {exc}).\n"
                f"Refusing to prune: a database that cannot be read is not a database "
                f"with no payers in it."
            )
        print(f"  {name:<20} {len(found)} customer(s) in use")
        ids |= found
    return ids


def _clock_id(customer: dict) -> str | None:
    """The customer's test clock id.

    Stripe returns `test_clock` either EXPANDED (a dict) or as a bare id string,
    depending on the call — `Customer.list(test_clock=...)` gives one shape and
    `Customer.search` the other. Reading `.get("id")` on the string form raises, which
    is the sort of thing that only shows up against a populated account.
    """
    ref = customer.get("test_clock")
    return ref.get("id") if isinstance(ref, dict) else ref


def _replay_payers() -> list[str]:
    """Every payer id the harness owns. The scope of anything this script deletes.

    Imported lazily, and with `main` stubbed when it is not already loaded: `RUNS` is a
    plain dict, but `replay_scenarios` does `from main import app` at module level, which
    would boot Flask and bind a database for the sake of reading eighteen constants. When
    the caller IS replay_scenarios (the auto-prune after `--setup`), the module is already
    in `sys.modules` and both the stub and the import are no-ops.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if "replay_scenarios" not in sys.modules:
        stub = types.ModuleType("main")
        stub.app = None
        sys.modules.setdefault("main", stub)
    from replay_scenarios import RUNS

    return [run["user_id"] for run in RUNS.values()]


def prune_dangling_rows(delete: bool) -> None:
    """Audit rows naming an entity that no longer exists, for replay payers only.

    Both databases: replay data is copied between them, so a dangling row copied to RDS
    is as wrong there as it was locally. See the module docstring for why this table and
    no other, and why the payer scoping is load-bearing rather than tidy.
    """
    payers = _replay_payers()
    where = f"""
        WHERE a.payer_user_id = ANY(:payers)
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.entities e WHERE e.id = a.entity_id
          )
    """
    for name in ("LOCAL_DATABASE_URI", "RDS_DATABASE_URI"):
        uri = os.environ.get(name)
        if not uri:
            print(f"  {name:<20} not set — skipped")
            continue
        try:
            engine = create_engine(uri)
            with engine.begin() as conn:
                found = conn.execute(text(
                    f"SELECT count(*) FROM {SCHEMA}.subscription_audit_log a {where}"
                ), {"payers": payers}).scalar()
                if found and delete:
                    conn.execute(text(
                        f"DELETE FROM {SCHEMA}.subscription_audit_log a {where}"
                    ), {"payers": payers})
        except Exception as exc:
            # Warn, never raise: this is housekeeping, and the caller may be a replay
            # that has real work to do.
            print(f"  {name:<20} skipped ({type(exc).__name__}: {exc})")
            continue
        verb = "deleted" if (found and delete) else "dangling"
        print(f"  {name:<20} {found} audit row(s) {verb}")


def _ours(customer: dict, clock_ids: set[str]) -> bool:
    """Whether this customer belongs to the replay harness. See "WHAT IS IN SCOPE"."""
    if (customer.get("metadata") or {}).get("purpose") == PURPOSE:
        return True
    ref = _clock_id(customer)
    return bool(ref) and ref in clock_ids


def survey(stripe, cutoff: datetime) -> tuple[list, list, list]:
    """Returns (deletable clocks, orphan customers with no deletable clock, kept)."""
    clocks = {}
    for clock in stripe.test_helpers.TestClock.list(limit=100).auto_paging_iter():
        if (clock.get("name") or "").startswith(CLOCK_PREFIX):
            clocks[clock["id"]] = clock

    used = _in_use()

    customers, seen = [], set()
    for clock_id in clocks:
        for customer in stripe.Customer.list(
            test_clock=clock_id, limit=100
        ).auto_paging_iter():
            if customer["id"] not in seen:
                seen.add(customer["id"])
                customers.append(customer)
    # Customers made by an older harness, or whose clock has already gone.
    try:
        for customer in stripe.Customer.search(
            query=f"metadata['purpose']:'{PURPOSE}'", limit=100
        ).auto_paging_iter():
            if customer["id"] not in seen:
                seen.add(customer["id"])
                customers.append(customer)
    except Exception as exc:  # search is a separate, index-backed API
        print(f"  (metadata search unavailable: {exc}; clock-attached objects only)")

    kept, orphans = [], []
    for customer in customers:
        if not _ours(customer, set(clocks)):
            continue
        created = datetime.fromtimestamp(customer["created"], UTC)
        if customer["id"] in used:
            kept.append((customer, "in use by a payer row"))
        elif created > cutoff:
            kept.append((customer, f"created {created:%H:%M}, too recent"))
        else:
            orphans.append(customer)

    orphan_ids = {c["id"] for c in orphans}
    kept_ids = {c["id"] for c, _ in kept}
    deletable_clocks = []
    for clock_id, clock in clocks.items():
        members = {c["id"] for c in customers if _clock_id(c) == clock_id}
        # `members and` matters: a clock with no customers left is not "all of its
        # customers are orphaned", it is a clock whose customers something else already
        # removed — still deletable, but say so rather than inferring it from an empty
        # intersection, which is vacuously true for every clock.
        if members and not (members & kept_ids):
            deletable_clocks.append(clock)
        elif not members:
            deletable_clocks.append(clock)
    deletable_ids = {c["id"] for c in deletable_clocks}
    clockless = [c for c in orphans if _clock_id(c) not in deletable_ids]
    return deletable_clocks, clockless, kept


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--delete", action="store_true", help="actually delete")
    parser.add_argument("--min-age-minutes", type=int, default=5,
                        help="never touch objects newer than this (default 5)")
    args = parser.parse_args()

    stripe = _stripe()
    cutoff = datetime.now(UTC) - timedelta(minutes=args.min_age_minutes)
    print(f"in use:")
    clocks, customers, kept = survey(stripe, cutoff)

    print(f"\nKEEPING {len(kept)}:")
    for customer, why in sorted(kept, key=lambda k: k[0]["created"]):
        print(f"  {customer['id']:<22} {(customer.get('email') or '-')[:44]:<46} {why}")

    print(f"\nORPHANED — {len(clocks)} test clock(s) and {len(customers)} loose customer(s):")
    for clock in sorted(clocks, key=lambda c: c["created"]):
        frozen = datetime.fromtimestamp(clock["frozen_time"], UTC)
        print(f"  clock {clock['id']:<28} {clock.get('name', '-'):<18} "
              f"frozen at {frozen:%d %b %Y}")
    for customer in sorted(customers, key=lambda c: c["created"]):
        print(f"  cust  {customer['id']:<28} {(customer.get('email') or '-')[:44]}")

    print("\nDANGLING ROWS:")
    prune_dangling_rows(args.delete)

    if not args.delete:
        print("\n(report only — add --delete to remove them)")
        raise SystemExit(0)

    # Clocks first: deleting one removes every object bound to it, so a customer covered
    # by a clock deletion must not then be deleted again by id.
    for clock in clocks:
        stripe.test_helpers.TestClock.delete(clock["id"])
        print(f"deleted clock {clock['id']} and everything on it")
    for customer in customers:
        stripe.Customer.delete(customer["id"])
        print(f"deleted customer {customer['id']}")
    print(f"\nremoved {len(clocks)} clock(s) and {len(customers)} loose customer(s)")
