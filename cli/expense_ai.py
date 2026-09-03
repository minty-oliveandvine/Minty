"""``flask expense-ai`` CLI — retention purge and a spike round-trip check.

Two jobs, both from the Stage 1 plan:

    flask expense-ai purge            the 90-day retention sweep (§8.5)
    flask expense-ai check            one round trip, to prove the route works

``purge`` is DRY BY DEFAULT. It reports what it would delete and deletes
nothing until given ``--delete``, because its first production run happens
before anyone has seen the table fill up and a retention job that deletes on
its first invocation gives no chance to notice it is wrong (§10.3).

``check`` is Stage 0's "one successful round-trip call from the application's
own network path — not from a laptop". It sends a tiny generated image, not a
customer receipt, and prints the model, the region, the latency and the token
usage so the answer to "is this configured correctly" is a fact rather than a
guess.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click
from flask.cli import AppGroup

from blueprints.report.services import expense_ai
from models.db import AiExpenseSuggestion, db

expense_ai_cli = AppGroup(
    "expense-ai", help="Retention purge and connectivity check for expense AI."
)


@expense_ai_cli.command("purge", help="Delete audit rows past the retention window.")
@click.option(
    "--days",
    type=int,
    default=None,
    help="Override EXPENSE_AI_RETENTION_DAYS for this run.",
)
@click.option(
    "--delete",
    is_flag=True,
    default=False,
    help="Actually delete. Without this the command only reports.",
)
def purge_cmd(days: int | None, delete: bool) -> None:
    retention = days if days is not None else expense_ai._env_int(
        "EXPENSE_AI_RETENTION_DAYS", 90
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)

    query = AiExpenseSuggestion.query.filter(AiExpenseSuggestion.created_at < cutoff)
    count = query.count()

    click.echo(f"Retention: {retention} days (cutoff {cutoff.isoformat()})")
    click.echo(f"Rows older than the cutoff: {count}")

    if not count:
        return
    if not delete:
        click.echo("DRY RUN — nothing deleted. Re-run with --delete to purge.")
        return

    deleted = query.delete(synchronize_session=False)
    db.session.commit()
    click.echo(f"Deleted {deleted} row(s).")


@expense_ai_cli.command("check", help="One round-trip call, from where the code runs.")
def check_cmd() -> None:
    click.echo(f"enabled          : {expense_ai.is_enabled()}")
    click.echo(f"route            : {'Vertex AI' if expense_ai.uses_vertex() else 'direct Gemini API'}")
    click.echo(f"location         : {expense_ai.location()}")
    click.echo(f"model            : {expense_ai.model_id()}")
    click.echo(f"thinking_level   : {expense_ai.thinking_level()}")

    if not expense_ai.uses_vertex():
        click.secho(
            "WARNING: the direct Gemini API has no regional endpoint and no "
            "residency commitment. On the free tier Google may use submitted "
            "content to develop its products and human reviewers may read it. "
            "Use non-customer receipts only.",
            fg="yellow",
        )

    # A generated 2x2 PNG, so the check exercises the real call path without
    # sending anything belonging to anyone.
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (2, 2), (255, 255, 255)).save(buffer, format="PNG")

    context = {
        "entity": {"id": "check", "name": "Connectivity check", "country": "HK",
                   "currency": "HKD"},
        "accounts": [{"id": "acc-1", "code": "5100", "name": "Courier Expense"}],
        "contacts": [{"id": "con-1", "name": "SF Express"}],
    }

    result = expense_ai.extract(buffer.getvalue(), "image/png", context)

    click.echo(f"latency_ms       : {result.audit.get('latency_ms')}")
    click.echo(f"request id       : {result.audit.get('provider_request_id')}")
    click.echo(f"tokens in / out  : {result.audit.get('input_tokens')} / "
               f"{result.audit.get('output_tokens')}")
    # Zero across repeated same-entity calls means the prefix is under the
    # 4,096-token minimum or is not byte-stable (§7.3).
    click.echo(f"cached tokens    : {result.audit.get('cached_tokens')}")
    click.echo(f"estimated cost   : {result.audit.get('estimated_cost')}")

    if result.reason in (None, expense_ai.REASON_NO_USABLE_FIELD):
        click.secho(
            "Round trip OK — the model answered and the reply passed the "
            "schema. (A blank image yields no usable field, as expected.)",
            fg="green",
        )
    else:
        click.secho(f"FAILED: {result.reason}", fg="red")
        raise SystemExit(1)
