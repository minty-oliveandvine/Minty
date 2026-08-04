"""``flask plans`` CLI — inspect the module price catalog.

Reads ``billing_plan`` via ``subscription.services.catalog``. That table is also what
the billing engine quotes from, so what this prints and what a customer is charged
cannot drift — which they could while the catalog lived in Stripe and the arithmetic
lived here.

Usage:
    flask plans list
"""
from __future__ import annotations

import click
from flask.cli import AppGroup

from blueprints.subscription.services import catalog

plans_cli = AppGroup("plans", help="Inspect the module price catalog.")


@plans_cli.command("list", help="List the available plans.")
def list_cmd() -> None:
    plans = catalog.available_plans()
    if not plans:
        click.echo("No active plans in billing_plan.")
        return
    click.echo(f"{len(plans)} available plan(s):")
    for plan in sorted(plans, key=lambda p: p.function_code):
        click.echo(
            f"  {plan.function_code:<12} {plan.amount / 100:>10,.2f} {plan.currency_code}"
            f" / {plan.billing_interval_count} {plan.billing_interval}"
            f"   {plan.display_name}"
        )
