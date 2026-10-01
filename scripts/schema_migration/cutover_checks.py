"""The cutover log's numbers: the new schema against the old one it was loaded from.

Phase D step 4 (docs/modernisation/modernisation_plan.md) established these on the first
rehearsal the applications ran against; this is the same set as a script so cutover day
produces the same page. It reads ONE database holding both schemas - the rehearsal's scratch
database after ``ALTER SCHEMA pettycash_test RENAME TO pettycashv3``, or production once
``pettycashv3`` sits beside ``pettycashv2`` - and compares:

  1. report totals per entity and month over the last 3 months, submitted/published only,
     at cent precision (the old columns are double precision and carry float residue such as
     18306.250000000004; the new ones are numeric(14,2))
  2. bills: rows and amount, bill lines, the audit trail; the three biggest companies per status
  3. subscription rows on both sides (production holds none)
  4. module grants carried, and how many live companies (a report in the last 90 days) have
     Petty Cash switched off - 0 unless ``flask subscriptions revoke-ungranted --apply``
     has run (m1a01 is a no-op), 47 on the 09-16 data if it had

Counts only, by default. ``--names`` adds the company names to section 4 for support; they
are printed, never written anywhere. ``--old-uri`` reads the OLD schema from another database:
on the Supabase project the ``pettycashv2`` beside the restored ``pettycashv3`` is the discarded
test instance (decision 2), so the source to compare against is the rehearsal's scratch
database, not the project's own old schema.

    python scripts/schema_migration/cutover_checks.py --uri postgresql://.../minty_e1 [--names]
    python scripts/schema_migration/cutover_checks.py --db minty_e1        # localhost, .env user

Exit status 1 on any mismatch, so the runbook can gate on it.
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2

OLD_DEFAULT, NEW_DEFAULT = "pettycashv2", "pettycashv3"


def _uri(args) -> str:
    if args.uri:
        return args.uri
    env = Path(__file__).resolve().parents[2] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("LOCAL_DATABASE_URI="):
            return re.sub(r"/[^/]*$", "/" + args.db, line.split("=", 1)[1].strip())
    raise SystemExit("no --uri and no LOCAL_DATABASE_URI in .env")


def cents(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--uri", help="postgres URI of the database holding both schemas")
    ap.add_argument("--db", default="minty_e1", help="database on localhost, with .env's user (ignored with --uri)")
    ap.add_argument("--old-uri", help="read the OLD schema from this database instead (the rehearsal's scratch database, "
                                       "when the new schema sits in a Supabase project whose own pettycashv2 is the discarded test instance)")
    ap.add_argument("--old", default=OLD_DEFAULT)
    ap.add_argument("--new", default=NEW_DEFAULT)
    ap.add_argument("--names", action="store_true", help="print company names in section 4 (never stored)")
    args = ap.parse_args()
    OLD, NEW = args.old, args.new

    new_cur = psycopg2.connect(_uri(args)).cursor()
    old_cur = psycopg2.connect(args.old_uri).cursor() if args.old_uri else new_cur

    def q(sql, *params):
        """Old-schema queries go to the old connection, new-schema ones to the new."""
        cur = old_cur if f"{OLD}." in sql else new_cur
        cur.execute(sql, params)
        return cur.fetchall()

    problems = 0

    # ---- 1. report totals, last 3 months ----------------------------------------------------
    old = q(f"""
        select e.name, date_trunc('month', r.transaction_date)::date, count(*),
               sum(r.cash_sales), sum(r.shop_sales + coalesce(r.delivery_sales, 0) - r.cash_sales),
               sum(r.total_sales), sum(r.expenses), sum(r.bank_deposit)
          from {OLD}.report r join {OLD}.entities e on e.id::text = r.company::text
         where r.status in ('posted', 'published')
           and r.transaction_date >= (current_date - interval '3 months')::date
      group by 1, 2""")
    new = q(f"""
        select e.name, date_trunc('month', r.transaction_date)::date, count(*),
               sum(r.cashsale_total), sum(r.nocashsale_total), sum(r.total_sales), sum(r.expense_total), sum(r.bank_deposit)
          from {NEW}.report r join {NEW}.entities e on e.id = r.entity_id
         where r.status in ('submitted', 'published')
           and r.transaction_date >= (current_date - interval '3 months')::date
      group by 1, 2""")
    o = {(r[0], r[1]): r[2:] for r in old}
    n = {(r[0], r[1]): r[2:] for r in new}
    keys = sorted(set(o) | set(n))
    mism = [k for k in keys if o.get(k) is None or n.get(k) is None
            or any(cents(x) != cents(y) for x, y in zip(o[k], n[k]))]
    print(f"1. report totals, last 3 months: {len(keys)} entity-months; rows old {sum(r[2] for r in old)} new {sum(r[2] for r in new)}; "
          f"mismatching entity-months: {len(mism)}  {'OK' if not mism else '!!'}")
    for k in mism:
        print(f"   !! {k[0][:40]!r} {k[1]}: old {[str(v) for v in (o.get(k) or [])]} new {[str(v) for v in (n.get(k) or [])]}")
    problems += len(mism)

    # ---- 2. bills ------------------------------------------------------------------------------
    ob = q(f"select count(*), coalesce(sum(amount), 0) from {OLD}.bill")[0]
    nb = q(f"select count(*), coalesce(sum(amount), 0) from {NEW}.bill")[0]
    ok = ob[0] == nb[0] and cents(ob[1]) == cents(nb[1]); problems += not ok
    print(f"2. bills: old {ob[0]} rows / {cents(ob[1])}; new {nb[0]} rows / {cents(nb[1])}  {'OK' if ok else '!!'}")
    ol = q(f"select count(*), coalesce(sum(line_amount), 0) from {OLD}.bill_line_item")[0]
    nl = q(f"select count(*), coalesce(sum(line_amount), 0) from {NEW}.bill_line")[0]
    ok = ol[0] == nl[0] and cents(ol[1]) == cents(nl[1]); problems += not ok
    print(f"   bill lines: old {ol[0]} / {cents(ol[1])}; new {nl[0]} / {cents(nl[1])}  {'OK' if ok else '!!'}")
    oa = q(f"select count(*) from {OLD}.audit")[0][0]
    na = q(f"select count(*) from {NEW}.bill_audit")[0][0]
    ok = oa == na; problems += not ok
    print(f"   bill audit trail: old {oa}, new {na}  {'OK' if ok else '!!'}")
    top = q(f"""select e.name from {NEW}.entities e
                 where exists (select 1 from {NEW}.bill b where b.entity_id = e.id)
              order by (select count(*) from {NEW}.bill b where b.entity_id = e.id) desc limit 3""")
    status_map = {"voided": "void"}  # the enum word changed (01 item 18)
    for (name,) in top:
        o2 = {status_map.get(s_, s_): (c, cents(a)) for s_, c, a in q(
            f"select b.status, count(*), sum(b.amount) from {OLD}.bill b join {OLD}.entities e on e.id::text = b.entity_id::text where e.name = %s group by 1", name)}
        n2 = {s_: (c, cents(a)) for s_, c, a in q(
            f"select b.status, count(*), sum(b.amount) from {NEW}.bill b join {NEW}.entities e on e.id = b.entity_id where e.name = %s group by 1", name)}
        ok = o2 == n2; problems += not ok
        label = name if args.names else f"company #{top.index((name,)) + 1}"
        print(f"   {label}: {sum(c for c, _ in n2.values())} bills, per status {'identical' if ok else 'DIFFER ' + str((o2, n2))}  {'OK' if ok else '!!'}")

    # ---- 3. subscriptions ------------------------------------------------------------------
    oi = q(f"select count(*) from {OLD}.subscription_invoice")[0][0]
    ni = q(f"select count(*) from {NEW}.subscription_invoice")[0][0]
    os_ = q(f"select count(*) from {OLD}.entity_module_subscription")[0][0]
    ns_ = q(f"select count(*) from {NEW}.entity_module_subscription")[0][0]
    ok = oi == ni and os_ == ns_; problems += not ok
    print(f"3. subscription invoices old {oi} new {ni}; module subscriptions old {os_} new {ns_}  {'OK' if ok else '!!'}")

    # ---- 4. grants -------------------------------------------------------------------------
    en, tot = q(f"select count(*) filter (where is_enabled), count(*) from {NEW}.entity_function_map")[0]
    rows = q(f"""
        select e.name, e.id, max(r.transaction_date)
          from {NEW}.entities e
          join {NEW}.entity_function f on f.function_code = 'PETTY_CASH'
          join {NEW}.entity_function_map m on m.entity_id = e.id and m.entity_function_id = f.id and not m.is_enabled
          join {NEW}.report r on r.entity_id = e.id and r.transaction_date >= (current_date - interval '90 days')::date
      group by 1, 2 order by 3 desc""")
    print(f"4. module grants carried: {en}/{tot} enabled; live companies (a report in 90 days) with Petty Cash OFF: {len(rows)}")
    if args.names:
        for name, eid, last in rows:
            print(f"   {name[:40]:40} {eid}  last report {last}")

    print("RESULT:", "OK" if problems == 0 else f"{problems} problem(s)")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
