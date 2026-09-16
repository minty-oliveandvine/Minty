"""Every route whose code touches a column the schema redesign changes must be exercised.

``tests/_baseline/route_inventory.json`` lists the 213 endpoints and marks the ones whose view
(or a service it calls) references a renamed, dropped or retyped column - 132 at the time of
writing. ``tests/conftest.py`` records every endpoint the suite hits. This test, named ``zz``
so it collects last, reports the in-scope endpoints nothing reached.

It is RED until the characterisation suite covers them, on purpose: the misses are the to-do
list, written to ``tests/_baseline/route_coverage_misses.txt`` on every run so progress is a
diff. Do not xfail it and do not shrink the inventory to make it pass - regenerate the
inventory only when the routes themselves change (see docs/modernisation_plan.md, Part 1 B3).
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
INVENTORY = HERE / "_baseline" / "route_inventory.json"
MISSES = HERE / "_baseline" / "route_coverage_misses.txt"


def test_every_schema_touching_route_is_exercised(app):
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    in_scope = {r["endpoint"]: r for r in inventory["routes"] if r["in_scope"]}
    hit = set(app.extensions.get("hit_endpoints", set()))
    # Legacy aliases: the same view is registered twice on one rule (``entity_settings`` next to
    # ``entity.entity_settings``, ``delete_report`` next to ``report.delete_report``). A request
    # to the rule reaches the view whichever name Flask records, so a hit on one counts for all
    # endpoints that share the rule and methods.
    by_rule: dict[tuple, set] = {}
    for r in inventory["routes"]:
        by_rule.setdefault((r["rule"], tuple(r["methods"])), set()).add(r["endpoint"])
    for twins in by_rule.values():
        if twins & hit:
            hit |= twins
    misses = sorted(e for e in in_scope if e not in hit)
    covered = len(in_scope) - len(misses)
    lines = [f"# {covered}/{len(in_scope)} schema-touching endpoints exercised", ""]
    for e in misses:
        r = in_scope[e]
        why = ", ".join(r["touches"]) or "via " + ", ".join(sorted(r["touches_via_service"]))
        lines.append(f"{e:55} {' '.join(r['methods']):9} {r['rule']:50} {why}")
    MISSES.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not misses, (
        f"{len(misses)} of {len(in_scope)} schema-touching endpoints were never requested "
        f"(see {MISSES.relative_to(HERE.parent)})"
    )
