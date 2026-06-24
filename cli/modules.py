"""``flask modules`` CLI — manual override for entity module entitlements.

Stand-in for the eventual subscription admin UI: lets ops flip a module on
or off for a specific entity without writing SQL by hand. Uses the same
``set_entity_module`` helper as the onboarding endpoint, so audit columns
(``created_by``, ``enabled_at`` / ``disabled_at``, ``updated_at``) stay
consistent regardless of how the row was last touched.

Usage:
    flask modules set <entity_id> <module> <on|off>
    flask modules show <entity_id>

Examples:
    flask modules set 4f3a... BILL on
    flask modules set 4f3a... PETTY_CASH off
    flask modules show 4f3a...
"""

from __future__ import annotations

import click
from flask.cli import AppGroup

from blueprints.entity.services.modules import (ACTOR_CLI, MODULE_CODES,
                                                set_entity_module)
from models.db import Entity, EntityFunction, EntityFunctionMap

modules_cli = AppGroup("modules", help="Inspect / toggle entity module entitlements.")


def _normalize_code(raw: str) -> str:
    code = (raw or "").strip().upper().replace("-", "_")
    if code not in MODULE_CODES:
        raise click.BadParameter(
            f"unknown module {raw!r}; expected one of {list(MODULE_CODES)}"
        )
    return code


@modules_cli.command("set", help="Turn one module on or off for an entity.")
@click.argument("entity_id")
@click.argument("module")
@click.argument("state", type=click.Choice(["on", "off"], case_sensitive=False))
def set_cmd(entity_id: str, module: str, state: str) -> None:
    entity_id = (entity_id or "").strip()
    if not entity_id:
        raise click.BadParameter("entity_id is required")

    entity = Entity.query.filter(Entity.id == entity_id).first()
    if entity is None:
        raise click.ClickException(f"Entity {entity_id} not found.")

    code = _normalize_code(module)
    enabled = state.lower() == "on"

    data, status = set_entity_module(entity_id, code, enabled, actor=ACTOR_CLI)
    if status >= 400:
        raise click.ClickException(data.get("error") or f"Failed (status {status}).")

    click.echo(f"Entity {entity.name!r} ({entity_id}) modules:")
    for c, on in data["modules"].items():
        click.echo(f"  {c:<12} {'ON' if on else 'off'}")


@modules_cli.command("show", help="Show the current module state for an entity.")
@click.argument("entity_id")
def show_cmd(entity_id: str) -> None:
    entity_id = (entity_id or "").strip()
    if not entity_id:
        raise click.BadParameter("entity_id is required")

    entity = Entity.query.filter(Entity.id == entity_id).first()
    if entity is None:
        raise click.ClickException(f"Entity {entity_id} not found.")

    catalog = (
        EntityFunction.query.filter(EntityFunction.function_code.in_(MODULE_CODES)).all()
    )
    catalog_by_id = {fn.id: fn for fn in catalog}
    rows = EntityFunctionMap.query.filter(
        EntityFunctionMap.entity_id == entity_id,
        EntityFunctionMap.entity_function_id.in_(list(catalog_by_id)),
    ).all()
    row_by_code = {
        catalog_by_id[r.entity_function_id].function_code: r
        for r in rows
        if r.entity_function_id in catalog_by_id
    }

    click.echo(f"Entity {entity.name!r} ({entity_id}) modules:")
    for code in MODULE_CODES:
        row = row_by_code.get(code)
        if row is None:
            # No explicit row → falls back to entity_function.is_active.
            fallback = next(
                (fn.is_active for fn in catalog if fn.function_code == code), False
            )
            click.echo(
                f"  {code:<12} {'ON' if fallback else 'off'}  (catalog fallback)"
            )
        else:
            click.echo(
                f"  {code:<12} {'ON' if row.is_enabled else 'off'}"
                f"  (set by {row.created_by or '?'})"
            )