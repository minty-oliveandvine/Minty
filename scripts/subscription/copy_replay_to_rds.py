"""Copy one replay run's rows from the local database to RDS.

`replay_scenarios.py` writes to exactly one database — whichever `main.app` bound at
import, which is `RDS_DATABASE_URI` unless `FLASK_ENV=development`. Replaying twice to get
the data into both is the obvious way and it is slow twice over: every one of the five
daily jobs round-trips to Supabase for every simulated day, on top of the Stripe test-clock
advances the run has to pay for regardless. So: replay ONCE against local, then move the
result.

    # rehearse and seed locally
    $env:FLASK_ENV='development'
    python scripts/subscription/replay_scenarios.py --run angelika --setup --replay --report

    # then move it (FLASK_ENV is irrelevant here — this script binds both URIs itself)
    python scripts/subscription/copy_replay_to_rds.py --run angelika            # report only
    python scripts/subscription/copy_replay_to_rds.py --run angelika --copy

WHAT MAKES THIS SAFE TO DO AT ALL. Every primary key in the subscription schema is a
string uuid — there is not a sequence anywhere in the eleven tables below, so no
`setval` to get wrong afterwards. And the Stripe ids in these rows (`cus_`, `in_`,
`pm_`) stay valid on the far side, because Stripe is ONE test account regardless of
which database is reading it. The copy is genuinely just rows.

THE ONE THING THAT IS NOT JUST ROWS. `entity_function_map.entity_function_id` points at
`entity_function`, whose ids are minted with `uuid.uuid4()` inside migration
`b8f3a2c1d4e5` — at migration time, PER DATABASE. As of 2026-08-17 local and Supabase
happen to agree on both ids (they were seeded from one dump), so the remap below is
currently a no-op — but nothing holds them together, and the next database migrated from
scratch has its own pair. Copying the column verbatim then gets a foreign key violation on
a good day and the WRONG MODULE ENABLED on a bad one. It is remapped by `function_code`.
That table cannot simply be left out: it is where module ACCESS lives, so without it the
entities arrive on RDS with subscriptions and invoices attached and every module dark.

TARGETING. Entities are matched by NAME, built from the run's `tag` exactly as
`replay_scenarios._entities` does — so this reaches the run's own companies ("Ang - M44
Nexora Health Limited" and the rest) and cannot reach a real one. Everything else hangs off the payer id, which is a
constant in `RUNS`.

`--replace` clears the run's rows on the destination first, so a re-copy after a re-replay
refreshes rather than half-merges. It deletes the ENTITIES too (matched by name), because a
`--teardown --setup` locally rotates entity ids: without that, the second copy inserts a
duplicate set of companies under the same names beside the first. The payer's `user` row is
the one thing never deleted — its id is fixed in `RUNS`, so it is stable across re-seeds,
and deleting a user is where the real damage would be.

NOT COPIED, deliberately: `billing_plan`, `billing_policy`, `entity_function`,
`currency_info`. Those are reference data owned by migrations, and the destination has its
own. If RDS is behind on a migration the insert fails loudly here rather than seeding a
price row nobody meant to ship.
"""
from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent))

# `replay_scenarios` does `from main import app` at module level, which boots Flask and
# binds a database — the very thing this script exists to decide for itself. Stubbing the
# module gets the run table without any of that; nothing here calls setup or replay, so the
# `app` those functions close over is never touched.
_stub = types.ModuleType("main")
_stub.app = None
sys.modules.setdefault("main", _stub)

from replay_scenarios import RUNS, _clone_name  # noqa: E402

SCHEMA = os.environ.get("MINTY_DB_SCHEMA", "pettycashv3")  # blueprints/shared/schema.py, without importing the app

# Insert order is FK order; deletes run in reverse. `carrier=True` means "insert if
# absent, never delete" — see the module docstring on the payer row.
#
# `params` names which of the resolved ids the predicate needs, so a table whose id list
# comes back empty is skipped rather than emitting `= ANY(ARRAY[])`, which Postgres cannot
# type.
TABLES = [
    {"table": "user", "where": "id = :payer", "params": (), "carrier": True},
    {"table": "entities", "where": "name = ANY(:names)", "params": ("names",)},
    {"table": "user_entity",
     "where": "user_id = :payer AND entity_id = ANY(:eids)", "params": ("eids",)},
    {"table": "entity_function_map",
     "where": "entity_id = ANY(:eids)", "params": ("eids",), "remap_function": True},
    {"table": "user_stripe_customer", "where": "user_id = :payer", "params": ()},
    {"table": "entity_module_subscription", "where": "payer_user_id = :payer", "params": ()},
    {"table": "entity_billing_consent",
     "where": "entity_id = ANY(:eids)", "params": ("eids",)},
    {"table": "subscription_invoice", "where": "payer_user_id = :payer", "params": ()},
    {"table": "subscription_invoice_line",
     "where": "invoice_id = ANY(:invoices)", "params": ("invoices",)},
    {"table": "subscription_audit_log", "where": "payer_user_id = :payer", "params": ()},
    {"table": "subscription_email_log", "where": "user_id = :payer", "params": ()},
]


def _resolve(conn, run: dict) -> dict:
    """The id sets one side's predicates need, read from THAT side.

    Resolved per connection rather than once from the source: `--replace` has to delete
    the destination's own rows, and after a local `--teardown --setup` the two sides
    disagree about every entity id. Names and the payer are the only stable handles.
    """
    names = sorted({_clone_name(run, name) for name, _ in run["scenarios"]})
    eids = [r[0] for r in conn.execute(
        text(f'SELECT id FROM {SCHEMA}.entities WHERE name = ANY(:names)'),
        {"names": names},
    )]
    invoices = [r[0] for r in conn.execute(
        text(f'SELECT id FROM {SCHEMA}.subscription_invoice WHERE payer_user_id = :payer'),
        {"payer": run["user_id"]},
    )]
    return {"payer": run["user_id"], "names": names, "eids": eids, "invoices": invoices}


def _columns(conn, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"),
        {"s": SCHEMA, "t": table},
    )]


def _function_ids(conn) -> dict:
    return {r[1]: r[0] for r in conn.execute(
        text(f"SELECT id, function_code FROM {SCHEMA}.entity_function")
    )}


def _skip(spec: dict, ids: dict) -> bool:
    return any(not ids[name] for name in spec["params"])


def _count(conn, spec: dict, ids: dict) -> int:
    if _skip(spec, ids):
        return 0
    return conn.execute(
        text(f'SELECT count(*) FROM {SCHEMA}."{spec["table"]}" WHERE {spec["where"]}'), ids
    ).scalar()


def report(src, dst, run: dict) -> None:
    with src.connect() as s, dst.connect() as d:
        src_ids, dst_ids = _resolve(s, run), _resolve(d, run)
        print(f"{'table':<28} {'local':>8} {'rds':>8}")
        for spec in TABLES:
            print(f"  {spec['table']:<26} {_count(s, spec, src_ids):>8} "
                  f"{_count(d, spec, dst_ids):>8}")
        stale = set(dst_ids["eids"]) - set(src_ids["eids"])
        if stale:
            print(f"\n!! {len(stale)} entity row(s) on RDS carry these names under DIFFERENT "
                  f"ids — an earlier copy, or a local --teardown since. Use --replace, or "
                  f"the copy will duplicate them.")


def copy(src, dst, run: dict, replace: bool) -> None:
    with src.connect() as s:
        src_ids = _resolve(s, run)
        payload = {}
        for spec in TABLES:
            if _skip(spec, src_ids):
                payload[spec["table"]] = []
                continue
            rows = s.execute(
                text(f'SELECT * FROM {SCHEMA}."{spec["table"]}" WHERE {spec["where"]}'),
                src_ids,
            ).mappings().all()
            payload[spec["table"]] = [dict(r) for r in rows]
        src_functions = _function_ids(s)

    if not payload["entities"]:
        raise SystemExit(f"nothing to copy: no entities named for tag {run['tag']!r} on the "
                         f"source. Wrong database, or the run was never seeded there.")

    # One transaction: a failure anywhere leaves the destination untouched rather than
    # holding a payer with half an invoice history.
    with dst.begin() as d:
        dst_ids = _resolve(d, run)
        dst_functions = _function_ids(d)
        by_src_id = {fid: code for code, fid in src_functions.items()}

        if replace:
            for spec in reversed(TABLES):
                if spec.get("carrier") or _skip(spec, dst_ids):
                    continue
                gone = d.execute(
                    text(f'DELETE FROM {SCHEMA}."{spec["table"]}" WHERE {spec["where"]}'),
                    dst_ids,
                ).rowcount
                if gone:
                    print(f"  cleared {gone:>5} from {spec['table']}")

        for spec in TABLES:
            rows = payload[spec["table"]]
            if not rows:
                continue
            table = spec["table"]

            if spec.get("remap_function"):
                # The whole reason this script is not a pg_dump. See the module docstring.
                for row in rows:
                    code = by_src_id.get(row["entity_function_id"])
                    if code not in dst_functions:
                        raise SystemExit(
                            f"entity_function has no {code!r} on the destination — run "
                            f"migration b8f3a2c1d4e5 there first"
                        )
                    row["entity_function_id"] = dst_functions[code]

            # Intersected, not assumed equal: if RDS is a migration behind, drop the
            # columns it does not have and say so, rather than failing on the first row.
            shared = [c for c in _columns(d, table) if c in rows[0]]
            if not shared:
                raise SystemExit(f"destination has no table {SCHEMA}.{table}")
            dropped = sorted(set(rows[0]) - set(shared))
            if dropped:
                print(f"  !! {table}: destination lacks {dropped} — copying without them")

            cols = ", ".join(f'"{c}"' for c in shared)
            binds = ", ".join(f":{c}" for c in shared)
            written = d.execute(
                text(f'INSERT INTO {SCHEMA}."{table}" ({cols}) VALUES ({binds}) '
                     f'ON CONFLICT DO NOTHING'),
                [{c: row[c] for c in shared} for row in rows],
            ).rowcount
            note = "" if written == len(rows) else f"  ({len(rows) - written} already there)"
            print(f"  {table:<28} {written:>5} inserted{note}")

    print(f"\ncopied {run['tag']} — sign in as {run['email']} against RDS to check")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", required=True, choices=sorted(RUNS))
    parser.add_argument("--copy", action="store_true", help="write; otherwise report only")
    parser.add_argument("--replace", action="store_true",
                        help="clear the run's rows on the destination first")
    parser.add_argument("--source", default=os.environ.get("LOCAL_DATABASE_URI"))
    parser.add_argument("--dest", default=os.environ.get("RDS_DATABASE_URI"))
    args = parser.parse_args()

    if not args.source or not args.dest:
        raise SystemExit("need LOCAL_DATABASE_URI and RDS_DATABASE_URI (or --source/--dest)")
    # The two URIs were identical in this repo until recently, and a copy that silently
    # runs a table onto itself is worse than one that refuses.
    if args.source == args.dest:
        raise SystemExit("source and destination are the same database — nothing to copy")

    run = RUNS[args.run]
    print(f"{run['label']}\n  from {args.source.split('@')[-1]}\n"
          f"  to   {args.dest.split('@')[-1]}\n")

    source = create_engine(args.source)
    dest = create_engine(args.dest)
    if args.copy:
        copy(source, dest, run, replace=args.replace)
    else:
        report(source, dest, run)
        print("\n(report only — add --copy to write, --replace to clear first)")
