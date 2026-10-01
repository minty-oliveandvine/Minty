"""Every in-scope route must be exercised by a REAL request - or be listed as a known gap.

``tests/_baseline/route_inventory.json`` lists every endpoint the app serves and marks the ones
whose view (or a service it calls) touches the schema (``in_scope``). ``tests/conftest.py``
records an endpoint only when a request actually ran its view: not an OPTIONS request
(Flask answers those without calling the view - for two weeks an OPTIONS sweep alone
"covered" ~50 routes, the crashing password-reset pages among them), and not one refused
before the view did anything (a 401/403/404/405, a 5xx, a sign-in redirect, an access
decorator's refusal).

``tests/_baseline/route_coverage_misses.txt`` is the KNOWN-GAPS list (2026-10-01): in-scope
routes with no real test yet. This gate fails the run on

* an in-scope route that no test reached and that is not listed - a new or newly untested
  route;
* a listed route that IS now reached - take it off the list (``MINTY_ROUTE_BASELINE=update``),
  so the list only ever shrinks;
* a listed route that is not in scope, or not in the inventory at all;
* a live route the inventory does not list, or an inventory route the app no longer has -
  so a new route cannot slip past by never being inventoried.

It judges COMPLETE runs only (``incomplete_run``): a partial run reaches fewer routes and
would report gaps that are not there. A partial run says so and writes nothing.

The list is written only on request, and only on a complete run:
``MINTY_ROUTE_BASELINE=update`` drops entries that are now covered; ``=add`` also adds the
current misses (a deliberate act - a new route should get a test, not a line here).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).parent
INVENTORY = HERE / "_baseline" / "route_inventory.json"
MISSES = HERE / "_baseline" / "route_coverage_misses.txt"
NODE_NAME = "test_every_schema_touching_route_is_exercised"
#: Flask's own static route: never inventoried.
UNINVENTORIED = {"static"}

_HEADER = """\
# Known gaps: in-scope routes no test reaches with a real request yet (tests/test_zz_route_coverage.py).
# The gate fails on a route missing from this list AND on a listed route that a test now reaches.
# Rewrite only on a complete run: MINTY_ROUTE_BASELINE=update (drop covered) or =add (also add misses).
"""


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def coverage(hit) -> tuple[list[str], dict]:
    """(in-scope endpoints no real request reached, the in-scope inventory rows by endpoint)."""
    inventory = _inventory()
    in_scope = {r["endpoint"]: r for r in inventory["routes"] if r["in_scope"]}
    hit = set(hit)
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
    return sorted(e for e in in_scope if e not in hit), in_scope


def known_gaps() -> set[str]:
    """The endpoints listed in the known-gaps file: the first word of each entry line."""
    if not MISSES.exists():
        return set()
    return {
        line.split()[0]
        for line in MISSES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def incomplete_run(config, *, gate_ran: bool, crashed: bool = False) -> str | None:
    """Why this run cannot be judged, or None when every test the suite has was selected."""
    if not gate_ran:
        return f"{NODE_NAME} did not run"
    if crashed:
        return "an xdist worker went down"
    option = config.option
    for flag, name in (("keyword", "-k"), ("markexpr", "-m"), ("lf", "--lf"),
                       ("deselect", "--deselect"), ("stepwise", "--sw"),
                       ("stepwise_skip", "--sw-skip"), ("maxfail", "-x/--maxfail")):
        if getattr(option, flag, None):
            return f"{name} was given"
    base = Path(config.invocation_params.dir)
    for arg in config.args:
        if not (base / str(arg).split("::")[0]).is_dir():
            return f"{arg} is not a directory"
    return None


def judge(hit, live_endpoints) -> tuple[list[str], int]:
    """Every problem with this run's coverage (empty = pass), and how many routes are in scope.

    Rewrites the known-gaps list when ``MINTY_ROUTE_BASELINE`` asks; the caller has already
    checked the run is complete.
    """
    misses, in_scope = coverage(hit)
    listed = known_gaps()
    inventoried = {r["endpoint"] for r in _inventory()["routes"]}
    live = set(live_endpoints) - UNINVENTORIED
    mode = os.environ.get("MINTY_ROUTE_BASELINE", "").strip().lower()

    if mode in ("update", "add"):
        keep = listed & set(misses)
        if mode == "add":
            keep |= set(misses)
        _write(sorted(keep & set(in_scope)), in_scope)
        print(f"\nroute coverage: {MISSES.name} rewritten ({mode}): "
              f"-{sorted(listed - keep)} +{sorted(keep - listed)}")
        listed = known_gaps()

    problems = []
    for endpoint in sorted(set(misses) - listed):
        r = in_scope[endpoint]
        problems.append(f"NOT TESTED  {endpoint}  {' '.join(r['methods'])} {r['rule']}")
    for endpoint in sorted(listed - set(misses)):
        problems.append(
            f"NOW TESTED  {endpoint}: take it off {MISSES.name} (MINTY_ROUTE_BASELINE=update)"
            if endpoint in in_scope
            else f"NOT IN SCOPE  {endpoint} is listed in {MISSES.name} but is not an in-scope route"
        )
    if live:
        for endpoint in sorted(live - inventoried):
            problems.append(f"UNINVENTORIED  {endpoint}: add it to {INVENTORY.name}")
        for endpoint in sorted(inventoried - live):
            problems.append(f"GONE  {endpoint} is in {INVENTORY.name} but the app has no such route")
    return problems, len(in_scope)


def _write(endpoints: list[str], in_scope: dict) -> None:
    lines = [_HEADER.rstrip("\n"), f"# {len(endpoints)} of {len(in_scope)} in-scope routes", ""]
    for e in endpoints:
        r = in_scope[e]
        why = ", ".join(r["touches"]) or "via " + ", ".join(sorted(r["touches_via_service"]))
        lines.append(f"{e:55} {' '.join(r['methods']):9} {r['rule']:50} {why}".rstrip())
    MISSES.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def report(problems: list[str], total: int) -> str:
    return (f"route coverage: {len(problems)} problem(s) across {total} in-scope routes\n  "
            + "\n  ".join(problems))


def test_every_schema_touching_route_is_exercised(app, request):
    if os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.skip("under pytest-xdist the controller judges route coverage at session end "
                    "(tests/conftest.py pytest_sessionfinish)")
    why = incomplete_run(request.config, gate_ran=True)
    if why:
        pytest.skip(f"route coverage not judged (partial run: {why})")
    live = {rule.endpoint for rule in app.url_map.iter_rules()}
    problems, total = judge(app.extensions.get("hit_endpoints", set()), live)
    assert not problems, report(problems, total)
